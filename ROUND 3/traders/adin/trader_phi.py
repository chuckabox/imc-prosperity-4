"""trader_phi.py — Peter-analysis purist.

Implements every alpha in ROUND 3/docs/ROUND_3_PETER_ANALYSIS.md verbatim.

  HP   — Order Book Imbalance (OBI) skew + OU mean-reversion (half-life 30k).
         Tightens hold aggression by deviation from 10k anchor.

  VFE  — Lag-1 negative autocorr scalp + asymmetric post-trade quoting.
         After a large aggressive print, raise the ask but hold the bid
         (or vice versa) to capture the predicted reversal.  Whale-trade
         detection on `state.market_trades` adds a fade-the-large-print
         signal.

  VEV  — Gamma scalping with σ_model = 0.019 / day (between IV 1.26 % and
         RV 2.15 %).  ATM-only focus on K = 5200, 5300 (peak gamma).  Buy
         when BS_fair > market_ask + edge, delta-hedge via VFE with a
         wide ±25 dead-band so spread cost doesn't eat gamma P&L.
"""
from __future__ import annotations

import json
import math
from typing import Dict, List, Optional, Tuple

from datamodel import Order, OrderDepth, TradingState

HYDROGEL = "HYDROGEL_PACK"
VFE = "VELVETFRUIT_EXTRACT"
TS_PER_DAY = 1_000_000

# Peter's ATM gamma-scalping focus.
PHI_VEV_STRIKES = [5200, 5300]
ALL_VEV_STRIKES = [5000, 5100, 5200, 5300, 5400, 5500]


# ===========================================================================
# Black-Scholes
# ===========================================================================
_SQRT_2PI_INV = 1.0 / math.sqrt(2.0 * math.pi)


def _norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _norm_pdf(x: float) -> float:
    return _SQRT_2PI_INV * math.exp(-0.5 * x * x)


def bs_call(S: float, K: float, T: float, sigma: float) -> float:
    if T <= 1e-10 or sigma <= 1e-10:
        return max(S - K, 0.0)
    sqrt_T = math.sqrt(T)
    d1 = (math.log(S / K) + 0.5 * sigma * sigma * T) / (sigma * sqrt_T)
    d2 = d1 - sigma * sqrt_T
    return S * _norm_cdf(d1) - K * _norm_cdf(d2)


def bs_delta(S: float, K: float, T: float, sigma: float) -> float:
    if T <= 1e-10 or sigma <= 1e-10:
        return 1.0 if S > K else 0.0
    sqrt_T = math.sqrt(T)
    d1 = (math.log(S / K) + 0.5 * sigma * sigma * T) / (sigma * sqrt_T)
    return _norm_cdf(d1)


def iv_solve(price: float, S: float, K: float, T: float) -> Optional[float]:
    intr = max(0.0, S - K)
    if price <= intr + 1e-6 or price >= S:
        return None
    lo, hi = 1e-4, 2.0
    for _ in range(32):
        m = 0.5 * (lo + hi)
        if bs_call(S, K, T, m) > price:
            hi = m
        else:
            lo = m
    return 0.5 * (lo + hi)


# ===========================================================================
# Trader
# ===========================================================================
class Trader:
    LIMITS = {HYDROGEL: 80, VFE: 80, **{f"VEV_{k}": 60 for k in ALL_VEV_STRIKES}}

    # ---- HP — OBI + OU ----------------------------------------------------
    HP_ANCHOR = 10_000.0
    HP_EWMA_ALPHA = 0.20
    HP_OBI_THRESHOLD = 0.7
    HP_OBI_SKEW = 1                    # XIRECs skew when |OBI| > threshold
    HP_OU_HALFLIFE_TICKS = 30_000
    HP_TAKE_EDGE = 2.0
    HP_MAKER_EDGE = 2.0
    HP_TAKER_BASE = 12

    # ---- VFE — lag-1 mean-rev + asymmetric quote -------------------------
    VFE_EWMA_ALPHA = 0.25
    VFE_BIG_MOVE = 2.0                 # ticks/move to trigger asymmetric quote
    VFE_WHALE_QTY = 30                 # market_trade size threshold = "whale"
    VFE_WHALE_FADE_SIZE = 8
    VFE_WHALE_TTL_TICKS = 5            # how many ticks the whale signal persists
    VFE_MAKER_EDGE = 2.0
    VFE_TAKER_EDGE = 4.0
    VFE_TAKER_MAX = 12
    VFE_HEDGE_BAND = 25                # wide — peter: hedge cost eats gamma if too tight

    # ---- VEV — peter gamma scalping --------------------------------------
    VEV_TTE_START = 8.0
    VEV_DAY_INIT = 0
    VEV_SIGMA_MODEL = 0.019
    VEV_ENTRY_EDGE = 5.0               # |BS_fair − market| ≥ 5 to enter
    VEV_EXIT_EDGE = 1.0
    VEV_PER_STRIKE_CAP = 12            # small — gamma P&L scales with γ × Δunderlying², not lots
    VEV_TAKER_MAX = 4
    VEV_MAKER_EDGE = 2.5

    # ----------------------------------------------------------------------
    def __init__(self) -> None:
        self.history: Dict = {}

    def _load(self, state: TradingState) -> None:
        if state.traderData:
            try:
                self.history = json.loads(state.traderData)
            except Exception:
                self.history = {}
        self.history.setdefault("hp_ewma", None)
        self.history.setdefault("vfe_ewma", None)
        self.history.setdefault("last_vfe_mid", None)
        self.history.setdefault("whale_until", -1)
        self.history.setdefault("whale_dir", 0)
        self.history.setdefault("day_index", self.VEV_DAY_INIT)
        self.history.setdefault("last_ts", -1)

    def _save(self) -> str:
        return json.dumps(self.history)

    def _update_day(self, ts: int) -> None:
        last = int(self.history.get("last_ts", -1))
        if last >= 0 and ts < last:
            self.history["day_index"] = int(self.history.get("day_index", self.VEV_DAY_INIT)) + 1
        self.history["last_ts"] = ts

    @staticmethod
    def _top(d: OrderDepth) -> Tuple[Optional[int], Optional[int], int, int]:
        bb = max(d.buy_orders) if d.buy_orders else None
        ba = min(d.sell_orders) if d.sell_orders else None
        bv = d.buy_orders[bb] if bb is not None else 0
        av = -d.sell_orders[ba] if ba is not None else 0
        return bb, ba, bv, av

    @staticmethod
    def _mid(d: OrderDepth) -> Optional[float]:
        bb = max(d.buy_orders) if d.buy_orders else None
        ba = min(d.sell_orders) if d.sell_orders else None
        return (bb + ba) / 2.0 if bb is not None and ba is not None else None

    # ---- HP — OBI + OU ----------------------------------------------------
    def _hp(self, state: TradingState) -> List[Order]:
        depth = state.order_depths.get(HYDROGEL)
        if depth is None:
            return []
        bb, ba, bv, av = self._top(depth)
        if bb is None or ba is None:
            return []
        mid = (bb + ba) / 2.0
        prev = self.history.get("hp_ewma")
        ewma = mid if prev is None else (1 - self.HP_EWMA_ALPHA) * prev + self.HP_EWMA_ALPHA * mid
        self.history["hp_ewma"] = ewma

        # OBI signal — peter's #1 HP alpha.
        total_v = bv + av
        obi = (bv - av) / total_v if total_v > 0 else 0.0
        obi_skew = 0
        if obi > self.HP_OBI_THRESHOLD:
            obi_skew = self.HP_OBI_SKEW       # buyers dominate → fair drifts up
        elif obi < -self.HP_OBI_THRESHOLD:
            obi_skew = -self.HP_OBI_SKEW

        # OU mean-reversion: scale aggression by deviation from anchor.
        # Half-life 30k ticks → expected revert per tick ≈ ln(2)/30000.
        deviation = mid - self.HP_ANCHOR
        ou_aggression = min(1.0, abs(deviation) / 30.0)

        fair = 0.65 * ewma + 0.35 * self.HP_ANCHOR + obi_skew

        pos = state.position.get(HYDROGEL, 0)
        lim = self.LIMITS[HYDROGEL]
        orders: List[Order] = []
        taker_max = max(4, int(self.HP_TAKER_BASE * (0.5 + 0.5 * ou_aggression)))

        if ba <= fair - self.HP_TAKE_EDGE and pos < lim:
            sz = min(taker_max, lim - pos, -depth.sell_orders[ba])
            if sz > 0:
                orders.append(Order(HYDROGEL, ba, sz))
                pos += sz
        if bb >= fair + self.HP_TAKE_EDGE and pos > -lim:
            sz = min(taker_max, lim + pos, depth.buy_orders[bb])
            if sz > 0:
                orders.append(Order(HYDROGEL, bb, -sz))
                pos -= sz

        qbid = int(round(fair - self.HP_MAKER_EDGE))
        qask = int(round(fair + self.HP_MAKER_EDGE))
        if qbid >= ba:
            qbid = ba - 1
        if qask <= bb:
            qask = bb + 1
        if qbid >= qask:
            qbid = qask - 1
        per_side = 14
        if lim - pos > 0:
            orders.append(Order(HYDROGEL, qbid, min(per_side, lim - pos)))
        if lim + pos > 0:
            orders.append(Order(HYDROGEL, qask, -min(per_side, lim + pos)))
        return orders

    # ---- VFE — lag-1 + asymmetric + whale --------------------------------
    def _detect_whale(self, state: TradingState, ts: int) -> int:
        """Returns +1 (whale buy), -1 (whale sell), 0 (none).
        Detection: any market_trade on VFE with |qty| ≥ VFE_WHALE_QTY in
        the current tick.  Sign tracks the implied book pressure (large
        buy → expect short-term reversion, return -1 to fade).
        """
        whale_until = int(self.history.get("whale_until", -1))
        whale_dir = int(self.history.get("whale_dir", 0))
        if ts >= whale_until:
            whale_dir = 0

        trades = state.market_trades.get(VFE, []) if state.market_trades else []
        for t in trades:
            if abs(t.quantity) >= self.VFE_WHALE_QTY:
                # Trade is a buy (price taker hit ask) when seller is the
                # passive side.  Without reliable buyer/seller fields we
                # use a price-vs-mid heuristic.
                last_mid = self.history.get("last_vfe_mid")
                if last_mid is not None:
                    if t.price >= last_mid:
                        whale_dir = -1   # whale lifted offer → reversion = short
                    else:
                        whale_dir = +1   # whale hit bid → reversion = long
                    whale_until = ts + self.VFE_WHALE_TTL_TICKS * 100
                    break

        self.history["whale_until"] = whale_until
        self.history["whale_dir"] = whale_dir
        return whale_dir

    def _vfe(self, state: TradingState, target_pos: int) -> List[Order]:
        depth = state.order_depths.get(VFE)
        if depth is None:
            return []
        bb, ba, bv, av = self._top(depth)
        if bb is None or ba is None:
            return []
        mid = (bb + ba) / 2.0
        prev = self.history.get("vfe_ewma")
        ewma = mid if prev is None else (1 - self.VFE_EWMA_ALPHA) * prev + self.VFE_EWMA_ALPHA * mid
        self.history["vfe_ewma"] = ewma

        # Lag-1 mean-reversion: detect aggressive move.
        last_mid = self.history.get("last_vfe_mid")
        big_move = 0
        if last_mid is not None:
            d = mid - float(last_mid)
            if d >= self.VFE_BIG_MOVE:
                big_move = +1   # price jumped up → expect reversal down
            elif d <= -self.VFE_BIG_MOVE:
                big_move = -1   # price jumped down → expect reversal up

        whale = self._detect_whale(state, int(state.timestamp))
        # Combined directional bias — sum of both fade signals.
        bias = -big_move + whale  # negative = expect down, positive = expect up

        fair = ewma
        pos = state.position.get(VFE, 0)
        lim = self.LIMITS[VFE]
        orders: List[Order] = []

        # Delta-hedge first (peter's #1 priority for VEV gamma scalping).
        residual = target_pos - pos
        if abs(residual) >= self.VFE_HEDGE_BAND:
            if residual > 0 and pos < lim:
                hq = min(self.VFE_HEDGE_BAND, residual, lim - pos, -depth.sell_orders[ba])
                if hq > 0:
                    orders.append(Order(VFE, ba, hq))
                    pos += hq
            elif residual < 0 and pos > -lim:
                hq = min(self.VFE_HEDGE_BAND, -residual, lim + pos, depth.buy_orders[bb])
                if hq > 0:
                    orders.append(Order(VFE, bb, -hq))
                    pos -= hq

        # Whale-fade taker (small size, respects position cap).
        if whale != 0:
            if whale > 0 and pos < lim:
                sz = min(self.VFE_WHALE_FADE_SIZE, lim - pos, -depth.sell_orders[ba])
                if sz > 0:
                    orders.append(Order(VFE, ba, sz))
                    pos += sz
            elif whale < 0 and pos > -lim:
                sz = min(self.VFE_WHALE_FADE_SIZE, lim + pos, depth.buy_orders[bb])
                if sz > 0:
                    orders.append(Order(VFE, bb, -sz))
                    pos -= sz

        # Asymmetric maker quote: hold the side that's about to revert TO
        # us, widen the side that's about to revert AWAY from us.
        bid_widen = 0
        ask_widen = 0
        if bias < 0:
            # Expect price down → keep ask tight, widen bid (don't lift here).
            bid_widen = 1
        elif bias > 0:
            ask_widen = 1
        qbid = int(round(fair - self.VFE_MAKER_EDGE - bid_widen))
        qask = int(round(fair + self.VFE_MAKER_EDGE + ask_widen))
        if qbid >= ba:
            qbid = ba - 1
        if qask <= bb:
            qask = bb + 1
        if qbid >= qask:
            qbid = qask - 1
        per_side = 16
        if lim - pos > 0:
            orders.append(Order(VFE, qbid, min(per_side, lim - pos)))
        if lim + pos > 0:
            orders.append(Order(VFE, qask, -min(per_side, lim + pos)))

        self.history["last_vfe_mid"] = mid
        return orders

    # ---- VEV — peter gamma scalping (ATM only) ---------------------------
    def _vev(self, state: TradingState, S: float, T: float) -> Tuple[List[Order], int]:
        orders: List[Order] = []
        target_vfe_delta = 0.0

        for K in PHI_VEV_STRIKES:
            sym = f"VEV_{K}"
            depth = state.order_depths.get(sym)
            if depth is None:
                continue
            bb, ba, _, _ = self._top(depth)
            if bb is None or ba is None:
                continue
            mid = (bb + ba) / 2.0
            fair = bs_call(S, K, T, self.VEV_SIGMA_MODEL)
            delta = bs_delta(S, K, T, self.VEV_SIGMA_MODEL)

            pos = state.position.get(sym, 0)
            cap = self.VEV_PER_STRIKE_CAP

            # Long undervalued: BS fair > market ask + edge.
            if ba <= fair - self.VEV_ENTRY_EDGE and pos < cap:
                sz = min(self.VEV_TAKER_MAX, cap - pos, -depth.sell_orders[ba])
                if sz > 0:
                    orders.append(Order(sym, ba, sz))
                    pos += sz
            # Symmetric short side (rare; peter says "options underpriced").
            if bb >= fair + self.VEV_ENTRY_EDGE and pos > -cap:
                sz = min(self.VEV_TAKER_MAX, cap + pos, depth.buy_orders[bb])
                if sz > 0:
                    orders.append(Order(sym, bb, -sz))
                    pos -= sz

            # Convergence exit.
            if pos > 0 and bb is not None and bb >= fair - self.VEV_EXIT_EDGE:
                sz = min(pos, depth.buy_orders[bb], 4)
                if sz > 0:
                    orders.append(Order(sym, bb, -sz))
                    pos -= sz
            elif pos < 0 and ba is not None and ba <= fair + self.VEV_EXIT_EDGE:
                sz = min(-pos, -depth.sell_orders[ba], 4)
                if sz > 0:
                    orders.append(Order(sym, ba, sz))
                    pos += sz

            # Passive maker on the same fair.
            qbid = int(round(fair - self.VEV_MAKER_EDGE))
            qask = int(round(fair + self.VEV_MAKER_EDGE))
            if qbid >= ba:
                qbid = ba - 1
            if qask <= bb:
                qask = bb + 1
            if qbid >= qask:
                qbid = qask - 1
            per_side = 4
            if cap - pos > 0 and qbid > 0:
                orders.append(Order(sym, qbid, min(per_side, cap - pos)))
            if cap + pos > 0 and qask > 0:
                orders.append(Order(sym, qask, -min(per_side, cap + pos)))

            target_vfe_delta += pos * delta

        target_vfe = max(-self.LIMITS[VFE],
                         min(self.LIMITS[VFE], int(round(-target_vfe_delta))))
        return orders, target_vfe

    # ---- main entrypoint --------------------------------------------------
    def run(self, state: TradingState) -> Tuple[Dict[str, List[Order]], int, str]:
        self._load(state)
        ts = int(state.timestamp)
        self._update_day(ts)
        result: Dict[str, List[Order]] = {}

        for o in self._hp(state):
            result.setdefault(o.symbol, []).append(o)

        S = self._mid(state.order_depths.get(VFE)) if VFE in state.order_depths else None
        target_vfe = 0
        if S is not None:
            day = int(self.history.get("day_index", self.VEV_DAY_INIT))
            T = max(0.5, (self.VEV_TTE_START - day) - ts / TS_PER_DAY)
            vev_orders, target_vfe = self._vev(state, S, T)
            for o in vev_orders:
                result.setdefault(o.symbol, []).append(o)

        for o in self._vfe(state, target_vfe):
            result.setdefault(o.symbol, []).append(o)

        return result, 0, self._save()
