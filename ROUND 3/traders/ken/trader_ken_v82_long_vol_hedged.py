"""trader_ken_v82_long_vol_hedged.py

Key change from v81: options module rebuilt around the IV/RV gap.
- v77-v81 all used parabolic smile-fit (relative pricing); flat ~1.26% IV
  across all strikes means no smile exists to trade — the fit was pure noise.
- Realized vol is ~2.15%/day, so every call is ~40 XIRECs cheap at fair value.
- v82: price options with σ_model = 0.018/day (20% haircut on realized),
  buy when BS_fair − ask > MIN_EDGE, scale size by edge. Delta-hedge with VFE.
- HYDROGEL module unchanged from v81 (it works).
- VFE trimmed to pure delta-hedger; EWMA/microprice/speed-limit layers removed.

Tunable knobs (all in Trader class header):
  VEV_SIGMA_MODEL    : vol assumption (0.018 conservative, 0.020 aggressive)
  VEV_MIN_EDGE_ENTER : min BS_fair - ask to trigger a buy
  VEV_K_SCALE        : target_qty = edge * K_SCALE (before soft-cap)
  VEV_SOFT_CAP       : per-strike cap (80 = 80% of 100 limit)
  VEV_DAY_INIT       : set to 2 when running the IMC sim (day-2 only);
                       leave at 0 for full 3-day backtests
"""
from __future__ import annotations

import json
import math
from typing import Dict, List, Optional, Tuple

from datamodel import Order, OrderDepth, TradingState


# ── Math helpers ─────────────────────────────────────────────────────────────

def _norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def bs_call_and_delta(S: float, K: float, T: float, sigma: float) -> Tuple[float, float]:
    """Return (call_price, delta=Phi(d1)) in one pass."""
    if T <= 1e-10 or sigma <= 1e-10:
        return max(S - K, 0.0), (1.0 if S > K else 0.0)
    sqrt_T = math.sqrt(T)
    d1 = (math.log(S / K) + 0.5 * sigma * sigma * T) / (sigma * sqrt_T)
    d2 = d1 - sigma * sqrt_T
    price = S * _norm_cdf(d1) - K * _norm_cdf(d2)
    return price, _norm_cdf(d1)


# ── Constants ─────────────────────────────────────────────────────────────────

HYDROGEL = "HYDROGEL_PACK"
VFE = "VELVETFRUIT_EXTRACT"
VEV_STRIKES = [4000, 4500, 5000, 5100, 5200, 5300, 5400, 5500, 6000, 6500]
VEV_SYMBOLS = [f"VEV_{k}" for k in VEV_STRIKES]
TS_PER_DAY = 1_000_000


# ── Trader ────────────────────────────────────────────────────────────────────

class Trader:
    LIMITS = {HYDROGEL: 200, VFE: 200, **{s: 100 for s in VEV_SYMBOLS}}

    # ── Module 1: HYDROGEL (Peter v100, unchanged from v81) ──────────────────
    HP_ANCHOR = 9991.0
    HP_BLEND = 0.65
    HP_EWMA_ALPHA = 0.20
    HP_VOL_ALPHA = 0.10
    HP_TAKE_EDGE = 2
    HP_QUOTE_SIZE = 45

    # ── Module 3: VEV options engine ─────────────────────────────────────────
    VEV_SIGMA_MODEL = 0.018       # day-vol; 20% haircut on ~2.15% realized
    VEV_TTE_DAY0 = 8.0            # TTE (days) at start of day 0
    VEV_DAY_INIT = 2              # IMC upload replays the start of day 2
    VEV_MIN_EDGE_ENTER = 4.0      # min (BS_fair - ask) XIRECs to buy
    VEV_MIN_EDGE_EXIT = 1.5       # trim longs when market >= model by this edge
    VEV_K_SCALE = 3               # target_qty = int(edge * K_SCALE)
    VEV_SOFT_CAP = 80             # per-strike position cap (80% of 100)
    VEV_GLOBAL_ABS_CAP = 520      # portfolio soft cap across active VEV strikes
    VEV_LATE_TTE_EXIT = 1.2       # de-risk options inventory near expiry
    VEV_SIGNAL_TIGHT_SPREAD = 2   # "tight regime" from 5200/5300 spread intel
    VEV_5200_CAP = 45             # keep 5200 tighter; this strike leaked most PnL

    # Strike tiers: primary (highest edge), secondary, tertiary (half-size)
    VEV_PRIMARY   = frozenset([5200, 5300])
    VEV_SECONDARY = frozenset([5100, 5400])
    VEV_TERTIARY  = frozenset([5000, 5500])
    VEV_ACTIVE    = VEV_PRIMARY | VEV_SECONDARY | VEV_TERTIARY
    # 4000/4500 = delta-1 proxies (no vol edge); 6000/6500 = illiquid (0/1 bid/ask)

    # ── Module 2: VFE delta-hedge ─────────────────────────────────────────────
    VFE_LIMIT = 200
    VFE_HEDGE_BAND = 10           # ±units dead-band before re-hedging
    VFE_HEDGE_MAX = 30            # max VFE qty per tick

    def __init__(self) -> None:
        self.history: Dict = {}

    def _load(self, state: TradingState) -> None:
        if state.traderData:
            try:
                self.history = json.loads(state.traderData)
            except Exception:
                self.history = {}
        self.history.setdefault("hp_ewma", None)
        self.history.setdefault("hp_vol", 0.0)
        self.history.setdefault("day_index", self.VEV_DAY_INIT)
        self.history.setdefault("last_ts", -1)

    def _save(self) -> str:
        return json.dumps(self.history)

    def _update_day(self, ts: int) -> None:
        last = int(self.history["last_ts"])
        if last >= 0 and ts < last:
            self.history["day_index"] += 1
        self.history["last_ts"] = ts

    def _tte(self, ts: int) -> float:
        day = int(self.history["day_index"])
        return max(0.5, (self.VEV_TTE_DAY0 - day) - ts / TS_PER_DAY)

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

    # ── Module 1: HYDROGEL ────────────────────────────────────────────────────

    def _hp(self, state: TradingState) -> List[Order]:
        if HYDROGEL not in state.order_depths:
            return []
        od = state.order_depths[HYDROGEL]
        m = self._mid(od)
        if m is None:
            return []

        prev = self.history.get("hp_ewma")
        ewma = m if prev is None else self.HP_EWMA_ALPHA * m + (1 - self.HP_EWMA_ALPHA) * prev
        self.history["hp_ewma"] = ewma

        diff = abs(m - (prev or m))
        vol = (1 - self.HP_VOL_ALPHA) * self.history["hp_vol"] + self.HP_VOL_ALPHA * diff
        self.history["hp_vol"] = vol

        fair = self.HP_BLEND * ewma + (1 - self.HP_BLEND) * self.HP_ANCHOR
        pos = state.position.get(HYDROGEL, 0)
        lim = self.LIMITS[HYDROGEL]
        bb, ba, _, _ = self._top(od)
        orders: List[Order] = []

        if ba is not None and ba <= fair - self.HP_TAKE_EDGE:
            qty = min(-od.sell_orders[ba], lim - pos)
            if qty > 0:
                orders.append(Order(HYDROGEL, ba, qty))
                pos += qty
        if bb is not None and bb >= fair + self.HP_TAKE_EDGE:
            qty = min(od.buy_orders[bb], lim + pos)
            if qty > 0:
                orders.append(Order(HYDROGEL, bb, -qty))
                pos -= qty

        spread = 1 + int(vol * 2)
        skew = int(round(3 * (pos / lim)))
        bid_px = int(round(fair - spread - skew))
        ask_px = int(round(fair + spread - skew))
        if bb is not None:
            bid_px = max(bid_px, bb + (1 if pos < lim * 0.3 else 0))
        if ba is not None:
            ask_px = min(ask_px, ba - (1 if pos > -lim * 0.3 else 0))
        if bid_px >= ask_px:
            bid_px = ask_px - 1

        if lim - pos > 0:
            orders.append(Order(HYDROGEL, bid_px, min(self.HP_QUOTE_SIZE, lim - pos)))
        if lim + pos > 0:
            orders.append(Order(HYDROGEL, ask_px, -min(self.HP_QUOTE_SIZE, lim + pos)))
        return orders

    # ── Module 3: VEV options ─────────────────────────────────────────────────

    def _vev(self, state: TradingState, S: float, T: float) -> List[Order]:
        orders: List[Order] = []
        abs_vev_pos = sum(abs(state.position.get(f"VEV_{k}", 0)) for k in self.VEV_ACTIVE)
        vfe_pos = abs(state.position.get(VFE, 0))
        vfe_pressure = vfe_pos / float(self.VFE_LIMIT) if self.VFE_LIMIT > 0 else 0.0
        # If hedge is already near limit, require more edge before adding more options.
        entry_gate = 1.0 + max(0.0, vfe_pressure - 0.75) * 2.0
        # Spread-based regime signal from community intel:
        # when both 5200 and 5300 have tight spreads, execution quality is better and
        # 5000/5100 alpha tends to be more reliable than 5200 overpay.
        spread_5200 = None
        spread_5300 = None
        od_5200 = state.order_depths.get("VEV_5200")
        if od_5200 and od_5200.buy_orders and od_5200.sell_orders:
            spread_5200 = min(od_5200.sell_orders) - max(od_5200.buy_orders)
        od_5300 = state.order_depths.get("VEV_5300")
        if od_5300 and od_5300.buy_orders and od_5300.sell_orders:
            spread_5300 = min(od_5300.sell_orders) - max(od_5300.buy_orders)
        tight_regime = (
            spread_5200 is not None
            and spread_5300 is not None
            and spread_5200 <= self.VEV_SIGNAL_TIGHT_SPREAD
            and spread_5300 <= self.VEV_SIGNAL_TIGHT_SPREAD
        )

        for K in VEV_STRIKES:
            if K not in self.VEV_ACTIVE:
                continue
            sym = f"VEV_{K}"
            od = state.order_depths.get(sym)
            if not od:
                continue

            pos = state.position.get(sym, 0)
            bb, ba, _, _ = self._top(od)
            fair, _ = bs_call_and_delta(S, K, T, self.VEV_SIGMA_MODEL)
            cap = self.VEV_5200_CAP if K == 5200 else self.VEV_SOFT_CAP
            scale = 0.5 if K in self.VEV_TERTIARY else 1.0
            if tight_regime:
                # In tight-spread windows, favor lower strikes (5000/5100) for cleaner carry.
                if K in (5000, 5100):
                    scale *= 1.20
                elif K == 5200:
                    scale *= 0.75
            elif K == 5200:
                # Outside tight windows, be more conservative on 5200.
                scale *= 0.65

            # Trim inventory if mark-to-model edge is gone, portfolio is oversized,
            # or expiry is getting close.
            if bb is not None and pos > 0:
                exit_edge = bb - fair
                must_trim = abs_vev_pos > self.VEV_GLOBAL_ABS_CAP or T <= self.VEV_LATE_TTE_EXIT
                if exit_edge > self.VEV_MIN_EDGE_EXIT or must_trim:
                    base = max(1, int(max(0.5, exit_edge + self.VEV_MIN_EDGE_EXIT) * self.VEV_K_SCALE * scale))
                    overflow = max(0, abs_vev_pos - self.VEV_GLOBAL_ABS_CAP)
                    qty = min(pos, od.buy_orders[bb], max(base, overflow))
                    if qty > 0:
                        orders.append(Order(sym, bb, -qty))
                        pos -= qty
                        abs_vev_pos -= qty

            # Buy when market underprices vs our model
            if ba is not None and pos < cap and abs_vev_pos < self.VEV_GLOBAL_ABS_CAP:
                edge = fair - ba
                strike_gate = self.VEV_MIN_EDGE_ENTER * entry_gate
                if K == 5200 and not tight_regime:
                    strike_gate *= 1.30
                elif K in (5000, 5100) and tight_regime:
                    strike_gate *= 0.90
                if edge > strike_gate:
                    target = max(1, int(edge * self.VEV_K_SCALE * scale))
                    budget = self.VEV_GLOBAL_ABS_CAP - abs_vev_pos
                    qty = min(target, cap - pos, -od.sell_orders[ba], budget)
                    if qty > 0:
                        orders.append(Order(sym, ba, qty))
                        abs_vev_pos += qty

            # Sell when market overprices vs our model (rare given IV/RV gap)
            if bb is not None and pos > -cap:
                edge = bb - fair
                if edge > self.VEV_MIN_EDGE_ENTER:
                    target = max(1, int(edge * self.VEV_K_SCALE * scale))
                    qty = min(target, cap + pos, od.buy_orders[bb])
                    if qty > 0:
                        orders.append(Order(sym, bb, -qty))

        return orders

    # ── Module 2: VFE delta-hedger ────────────────────────────────────────────

    def _vfe_hedge(self, state: TradingState, S: float, T: float) -> List[Order]:
        """Neutralize portfolio delta. No directional PnL target."""
        if VFE not in state.order_depths:
            return []
        od = state.order_depths[VFE]
        bb, ba, _, _ = self._top(od)
        if bb is None or ba is None:
            return []

        net_delta = 0.0
        for K in VEV_STRIKES:
            if K not in self.VEV_ACTIVE:
                continue
            pos = state.position.get(f"VEV_{K}", 0)
            if pos == 0:
                continue
            _, d = bs_call_and_delta(S, K, T, self.VEV_SIGMA_MODEL)
            net_delta += pos * d

        target = max(-self.VFE_LIMIT, min(self.VFE_LIMIT, round(-net_delta)))
        pos_vfe = state.position.get(VFE, 0)
        residual = target - pos_vfe

        if abs(residual) <= self.VFE_HEDGE_BAND:
            return []

        qty = min(self.VFE_HEDGE_MAX, abs(residual))
        if residual > 0:
            avail = min(-od.sell_orders[ba], self.VFE_LIMIT - pos_vfe)
            buy_qty = min(qty, avail)
            if buy_qty > 0:
                return [Order(VFE, ba, buy_qty)]
        else:
            avail = min(od.buy_orders[bb], self.VFE_LIMIT + pos_vfe)
            sell_qty = min(qty, avail)
            if sell_qty > 0:
                return [Order(VFE, bb, -sell_qty)]
        return []

    # ── Run ───────────────────────────────────────────────────────────────────

    def run(self, state: TradingState) -> Tuple[Dict[str, List[Order]], int, str]:
        self._load(state)
        ts = int(state.timestamp)
        self._update_day(ts)

        result: Dict[str, List[Order]] = {}

        h = self._hp(state)
        if h:
            result[HYDROGEL] = h

        S = self._mid(state.order_depths[VFE]) if VFE in state.order_depths else None
        if S is not None:
            T = self._tte(ts)

            vev_orders = self._vev(state, S, T)
            for o in vev_orders:
                result.setdefault(o.symbol, []).append(o)

            vfe_orders = self._vfe_hedge(state, S, T)
            if vfe_orders:
                result[VFE] = vfe_orders

        return result, 0, self._save()
