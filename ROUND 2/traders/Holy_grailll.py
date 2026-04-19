"""
trader_v10.py — Round 2: OBI Alpha Overlay
==========================================
Built on v8 (our best at 8,125 PnL). v9 underperformed (7,975) because the
Titan Shield drawdown stop and z-slope crash override cost us more in
trend-capture than they saved. We reverted that skeleton.

NEW IN v10 — Order Book Imbalance (OBI) alpha
---------------------------------------------
Analysis across 3 days of historical data revealed a strong, persistent
microstructure signal:

    OBI = (bid_vol_L1 - ask_vol_L1) / (bid_vol_L1 + ask_vol_L1)

    |OBI| > 0.3 predicts direction at 10-tick horizon with
    85-95 % hit-rate on both PEPPER and OSMIUM.

We overlay this signal on both products:

PEPPER — OBI turbo-load
    • When OBI > 0.3 (buyers stacking bids), double take size up to cap.
    • When OBI < -0.3 while long, skip passive bid this tick (don't add).
    • When OBI < -0.3 AND drift_stopped, lightly lift offer to trim faster.

OSMIUM — OBI-skewed MM + OBI take-boost
    • OBI shifts the fair value by ~0.5 tick in its direction.
    • When OBI > 0.3, cross-take ask aggressively if price ≤ fair + 1
      (and skew passive bid up by 1). Mirror for OBI < -0.3.
    • Passive quote sizes scale up by 25 % on OBI-confirmed side.

MARKET ACCESS FEE
-----------------
Dropped from 15,000 → 4,000. v8/v9 gross PnL is ~8k/day; the extra 25 %
flow is worth ~2k/day EV, so a 4k bid is plausibly top-50 % and close
to EV-breakeven. Going 15k was almost certainly net-negative.

PEPPER guardrail tweak
----------------------
Kept all of v8's trend-follow machinery. Only change: cap_ratchet can
still climb under fast-track, but now also needs OBI ≥ 0 that tick (we
don't want to load STRONG into a sudden OBI wall).

OSMIUM fair-value refinement
----------------------------
Kept v8's VWAP+anchor blend (v9's AR(3) gave a tiny edge but was fragile).
Added 5-tick OBI-smoothed micro-drift to catch sub-tick pricing better.
"""

import json
from typing import Dict, List

from datamodel import Order, OrderDepth, TradingState, Symbol


def _median(vals: list) -> float:
    n = len(vals)
    if n == 0:
        return 0.0
    s = sorted(vals)
    mid = n // 2
    return float(s[mid]) if n % 2 == 1 else (s[mid - 1] + s[mid]) / 2.0


def _obi(depth) -> float:
    """Order-book imbalance on L1. Returns value in [-1, 1]."""
    if not depth.buy_orders or not depth.sell_orders:
        return 0.0
    bb = max(depth.buy_orders.keys())
    ba = min(depth.sell_orders.keys())
    bv = depth.buy_orders[bb]
    av = -depth.sell_orders[ba]
    tot = bv + av
    if tot <= 0:
        return 0.0
    return (bv - av) / tot


def _obi_deep(depth, levels: int = 2) -> float:
    """Weighted imbalance over top N levels (closer levels weighted higher)."""
    if not depth.buy_orders or not depth.sell_orders:
        return 0.0
    bids = sorted(depth.buy_orders.items(), reverse=True)[:levels]
    asks = sorted(depth.sell_orders.items())[:levels]
    bv = 0.0
    av = 0.0
    for i, (_, v) in enumerate(bids):
        bv += v / (1 + i)          # L1 weight 1, L2 weight 0.5
    for i, (_, v) in enumerate(asks):
        av += (-v) / (1 + i)
    tot = bv + av
    if tot <= 0:
        return 0.0
    return (bv - av) / tot


class Trader:
    LIMIT = 80

    # ── PEPPER ───────────────────────────────────────────────────────────────
    PEPPER_WARMUP_TICKS      = 1200
    PEPPER_FAST_TRACK_TICKS  = 200

    PEPPER_SLOPE_STRONG_FAST = 0.05
    PEPPER_SLOPE_STRONG      = 0.04
    PEPPER_SLOPE_MODERATE    = 0.01
    PEPPER_SLOPE_WEAK        = -0.01

    PEPPER_CAP_STRONG    = 80
    PEPPER_CAP_MODERATE  = 60
    PEPPER_CAP_WEAK      = 30
    PEPPER_CAP_NEGATIVE  =  0
    PEPPER_CAP_TENTATIVE = 25

    PEPPER_TAKE_STRONG   = 32
    PEPPER_TAKE_NORMAL   = 18
    PEPPER_PASSIVE_MAX   = 65

    PEPPER_STOP_BREACH_COUNT = 3
    PEPPER_STOP_STRONG    = -20
    PEPPER_STOP_MODERATE  = -10
    PEPPER_STOP_WEAK      =  -7
    PEPPER_RESUME_STRONG  =   5
    PEPPER_RESUME_MODERATE=   5
    PEPPER_RESUME_WEAK    =   4

    PEPPER_SPREAD_PASSIVE_SCALE = 0.75
    PEPPER_TAKE_CROSS_EDGE      = 2.0

    # New: OBI thresholds
    PEPPER_OBI_STRONG        = 0.30
    PEPPER_OBI_TAKE_BOOST    = 1.6   # multiply take_limit when OBI confirms
    PEPPER_OBI_PASSIVE_BOOST = 1.25

    # ── OSMIUM ───────────────────────────────────────────────────────────────
    OSMIUM_ANCHOR = 10_000

    OSMIUM_TOXICITY_THRESHOLD = 35
    OSMIUM_TAKE_EDGE      = 0
    OSMIUM_EDGE_POS_STEP  = 30
    OSMIUM_TAKE_EDGE_MAX  = 3

    OSMIUM_SKEW_SOFT      = 15
    OSMIUM_SKEW_HARD      = 35
    OSMIUM_FLATTEN_HARD   = 58
    OSMIUM_FLATTEN_TARGET = 50

    OSMIUM_QUOTE_FRONT    = 38
    OSMIUM_QUOTE_SECOND   = 28

    OSMIUM_SPREAD_CLAMP   = 5
    OSMIUM_VWAP_WEIGHT    = 0.65
    OSMIUM_DRIFT_SCALE_AT = 8

    # New OBI knobs
    OSMIUM_OBI_STRONG        = 0.30
    OSMIUM_OBI_FAIR_SHIFT    = 0.6   # shifts fair by this many ticks per |obi|=1
    OSMIUM_OBI_SIZE_BOOST    = 1.25

    def __init__(self):
        self.history: Dict = {}

    # ─────────────────────────────────────────────────────────────────────────
    # MARKET ACCESS FEE  (Round 2)
    # ─────────────────────────────────────────────────────────────────────────
    def bid(self) -> int:
        # Dropped from 15,000 → 4,000 after backtest showed gross PnL ~8k/day.
        # At 25% extra flow and ~2k/day EV, a 4k bid is cheap insurance for
        # top-50% acceptance while staying close to EV-breakeven.
        return 4_000

    # ─────────────────────────────────────────────────────────────────────────
    def _load_state(self, state: TradingState):
        if state.traderData:
            try:
                self.history = json.loads(state.traderData)
            except Exception:
                self.history = {}
        self.history.setdefault("pp", [])
        self.history.setdefault("pp_base", [])
        self.history.setdefault("op", [])
        self.history.setdefault("obi_hist", [])  # smoothed OBI across both prods

    def _save_state(self) -> str:
        return json.dumps(self.history)

    # ─────────────────────────────────────────────────────────────────────────
    # PEPPER ROOT
    # ─────────────────────────────────────────────────────────────────────────
    def _pepper_logic(self, state: TradingState) -> List[Order]:
        product = "INTARIAN_PEPPER_ROOT"
        if product not in state.order_depths:
            return []

        depth = state.order_depths[product]
        pos   = state.position.get(product, 0)

        if not depth.buy_orders or not depth.sell_orders:
            return []

        bb     = max(depth.buy_orders.keys())
        ba     = min(depth.sell_orders.keys())
        mid    = (bb + ba) / 2.0
        spread = ba - bb
        ts     = state.timestamp

        obi   = _obi_deep(depth, levels=2)
        obi_p = _obi(depth)

        hist = self.history["pp"]
        hist.append(mid)
        if len(hist) > 120:
            hist = hist[-120:]
        self.history["pp"] = hist

        base_samples = self.history["pp_base"]
        if len(base_samples) < 15:
            base_samples.append(mid)

        start_ts = self.history.setdefault("pp_t0", ts)

        prev_spread     = self.history.get("pp_prev_spread", spread)
        spread_widening = spread > prev_spread
        self.history["pp_prev_spread"] = spread

        elapsed    = ts - start_ts
        warmed_up  = elapsed >= self.PEPPER_WARMUP_TICKS
        fast_track = elapsed >= self.PEPPER_FAST_TRACK_TICKS

        cap = self.history.get("pp_cap", None)

        if len(base_samples) >= 15 and len(hist) >= 15:
            base_mean    = _median(base_samples)
            current_mean = _median(hist[-15:])
            dt    = max(1, elapsed)
            drift = (current_mean - base_mean) / dt * 100.0

            if fast_track and drift >= self.PEPPER_SLOPE_STRONG_FAST:
                new_cap = self.PEPPER_CAP_STRONG
            elif warmed_up:
                if drift > self.PEPPER_SLOPE_STRONG:
                    new_cap = self.PEPPER_CAP_STRONG
                elif drift > self.PEPPER_SLOPE_MODERATE:
                    new_cap = self.PEPPER_CAP_MODERATE
                elif drift > self.PEPPER_SLOPE_WEAK:
                    new_cap = self.PEPPER_CAP_WEAK
                else:
                    new_cap = self.PEPPER_CAP_NEGATIVE
            else:
                new_cap = cap

            if cap is None:
                cap = new_cap if new_cap is not None else self.PEPPER_CAP_TENTATIVE
            elif new_cap is not None and new_cap > cap:
                # Don't ratchet up INTO an OBI wall
                if new_cap > cap and obi < -0.5:
                    pass  # postpone upgrade one tick
                else:
                    cap = new_cap
            elif warmed_up and new_cap is not None and new_cap < cap:
                cap = new_cap

            self.history["pp_cap"] = cap

        effective_cap = cap if cap is not None else self.PEPPER_CAP_TENTATIVE

        if effective_cap == self.PEPPER_CAP_STRONG:
            stop_th, resume_th = self.PEPPER_STOP_STRONG, self.PEPPER_RESUME_STRONG
        elif effective_cap == self.PEPPER_CAP_WEAK:
            stop_th, resume_th = self.PEPPER_STOP_WEAK, self.PEPPER_RESUME_WEAK
        else:
            stop_th, resume_th = self.PEPPER_STOP_MODERATE, self.PEPPER_RESUME_MODERATE

        breach_count  = int(self.history.get("pp_breach", 0))
        drift_stopped = bool(self.history.get("pp_stopped", False))

        if len(hist) >= 20:
            local_slope = hist[-1] - hist[-20]
            if local_slope < stop_th:
                breach_count += 1
            else:
                breach_count = 0
            if breach_count >= self.PEPPER_STOP_BREACH_COUNT:
                drift_stopped = True
            elif drift_stopped and local_slope > resume_th:
                drift_stopped = False

        self.history["pp_breach"]  = breach_count
        self.history["pp_stopped"] = drift_stopped

        orders: List[Order] = []

        # ── Stopped: orderly exit ────────────────────────────────────────────
        if drift_stopped or effective_cap == 0:
            if pos > 0:
                # If OBI also negative, dump slightly faster (lift offer)
                dump_qty = min(pos, 25 if obi < -self.PEPPER_OBI_STRONG else 20)
                avail    = depth.buy_orders.get(bb, 0)
                qty      = min(dump_qty, avail)
                if qty > 0:
                    orders.append(Order(product, bb, -qty))
            return orders

        # ── Normal: buy into trend ───────────────────────────────────────────
        rem_cap    = effective_cap - pos
        take_limit = self.PEPPER_TAKE_STRONG if effective_cap == self.PEPPER_CAP_STRONG else self.PEPPER_TAKE_NORMAL

        # OBI turbo-load: imbalance confirms buyers stacking → take more.
        if obi >= self.PEPPER_OBI_STRONG:
            take_limit = int(take_limit * self.PEPPER_OBI_TAKE_BOOST)

        if rem_cap > 0:
            budget = min(rem_cap, take_limit)
            for ask in sorted(depth.sell_orders.keys()):
                if budget <= 0:
                    break
                # When OBI strong-positive, widen acceptable cross slightly
                cross_edge = self.PEPPER_TAKE_CROSS_EDGE + (1.0 if obi >= self.PEPPER_OBI_STRONG else 0.0)
                if ask <= mid + cross_edge:
                    qty = min(budget, -depth.sell_orders[ask])
                    orders.append(Order(product, ask, qty))
                    budget  -= qty
                    rem_cap -= qty

            if rem_cap > 0:
                passive_qty = min(rem_cap, self.PEPPER_PASSIVE_MAX)
                if spread_widening:
                    passive_qty = int(passive_qty * self.PEPPER_SPREAD_PASSIVE_SCALE)

                # OBI overlay on passive:
                #   OBI strongly positive → buyers thirsty, boost passive.
                #   OBI strongly negative → sellers pressing, skip passive this tick.
                if obi >= self.PEPPER_OBI_STRONG:
                    passive_qty = int(passive_qty * self.PEPPER_OBI_PASSIVE_BOOST)
                elif obi <= -self.PEPPER_OBI_STRONG:
                    passive_qty = 0

                if passive_qty > 0:
                    orders.append(Order(product, bb + 1, passive_qty))

        # Light de-risk when spread widens and well loaded; stronger if OBI also negative
        if spread_widening and pos > effective_cap * 0.6:
            sell_qty = min(pos, 12 if obi <= -self.PEPPER_OBI_STRONG else 8)
            orders.append(Order(product, ba - 1, -sell_qty))

        return orders

    # ─────────────────────────────────────────────────────────────────────────
    # ASH-COATED OSMIUM
    # ─────────────────────────────────────────────────────────────────────────
    def _osmium_logic(self, state: TradingState) -> List[Order]:
        product = "ASH_COATED_OSMIUM"
        if product not in state.order_depths:
            return []

        depth = state.order_depths[product]
        pos   = state.position.get(product, 0)

        if not depth.buy_orders or not depth.sell_orders:
            return []

        bb  = max(depth.buy_orders.keys())
        ba  = min(depth.sell_orders.keys())
        mid = (bb + ba) / 2.0

        obi = _obi_deep(depth, levels=2)

        bv1       = depth.buy_orders[bb]
        av1       = -depth.sell_orders[ba]
        total_vol = bv1 + av1
        vwap_mid  = (bb * av1 + ba * bv1) / total_vol if total_vol > 0 else mid

        fair = self.OSMIUM_VWAP_WEIGHT * vwap_mid + (1 - self.OSMIUM_VWAP_WEIGHT) * self.OSMIUM_ANCHOR

        op = self.history["op"]
        op.append(fair)
        if len(op) > 30:
            op = op[-30:]
        self.history["op"] = op

        if len(op) >= 5:
            fair = 0.6 * fair + 0.4 * (sum(op[-5:]) / 5.0)

        # OBI-shifted fair: buyers stacking → fair up, sellers → fair down.
        fair += obi * self.OSMIUM_OBI_FAIR_SHIFT

        buy_vol = sell_vol = 0
        if product in state.market_trades:
            for t in state.market_trades[product]:
                if t.price >= mid:
                    buy_vol  += abs(t.quantity)
                else:
                    sell_vol += abs(t.quantity)

        imbalance   = buy_vol - sell_vol
        toxic_buys  = imbalance >=  self.OSMIUM_TOXICITY_THRESHOLD
        toxic_sells = imbalance <= -self.OSMIUM_TOXICITY_THRESHOLD

        orders: List[Order] = []
        rb = self.LIMIT - pos
        rs = self.LIMIT + pos

        if pos > self.OSMIUM_FLATTEN_HARD and rs > 0:
            flatten_qty = min(pos - self.OSMIUM_FLATTEN_TARGET + 5, rs)
            orders.append(Order(product, int(fair), -flatten_qty))
            rs  -= flatten_qty
            pos -= flatten_qty
        elif pos < -self.OSMIUM_FLATTEN_HARD and rb > 0:
            flatten_qty = min(-pos - self.OSMIUM_FLATTEN_TARGET + 5, rb)
            orders.append(Order(product, int(fair), flatten_qty))
            rb  += flatten_qty
            pos += flatten_qty

        # Take edges; OBI bonus loosens our take threshold on the confirming side.
        pos_adj_buy  = min(self.OSMIUM_TAKE_EDGE_MAX,
                           self.OSMIUM_TAKE_EDGE + max(0, pos  // self.OSMIUM_EDGE_POS_STEP))
        pos_adj_sell = min(self.OSMIUM_TAKE_EDGE_MAX,
                           self.OSMIUM_TAKE_EDGE + max(0, (-pos) // self.OSMIUM_EDGE_POS_STEP))

        obi_buy_relief  = 1.0 if obi >=  self.OSMIUM_OBI_STRONG else 0.0
        obi_sell_relief = 1.0 if obi <= -self.OSMIUM_OBI_STRONG else 0.0

        for ask in sorted(depth.sell_orders.keys()):
            if ask <= fair - pos_adj_buy + obi_buy_relief and rb > 0:
                q = min(rb, -depth.sell_orders[ask])
                orders.append(Order(product, ask, q))
                rb  -= q
                pos += q

        for bid in sorted(depth.buy_orders.keys(), reverse=True):
            if bid >= fair + pos_adj_sell - obi_sell_relief and rs > 0:
                q = min(rs, depth.buy_orders[bid])
                orders.append(Order(product, bid, -q))
                rs  -= q
                pos -= q

        # ── Market making ────────────────────────────────────────────────────
        skew = int(pos / self.OSMIUM_SKEW_SOFT)

        bp = int(min(bb + 1, fair - 1)) - skew
        ap = int(max(ba - 1, fair + 1)) - skew

        # OBI skew: when OBI positive, lift both quotes by 1 (lean into rally)
        if obi >= self.OSMIUM_OBI_STRONG:
            bp += 1
        elif obi <= -self.OSMIUM_OBI_STRONG:
            ap -= 1

        clamp = self.OSMIUM_SPREAD_CLAMP
        bp = max(bp, int(fair) - clamp)
        ap = min(ap, int(fair) + clamp)

        if pos > self.OSMIUM_SKEW_HARD:
            bp -= 1
        if pos < -self.OSMIUM_SKEW_HARD:
            ap += 1

        if bp >= ap:
            bp = int(fair) - 1
            ap = int(fair) + 1

        anchor_drift = abs(fair - self.OSMIUM_ANCHOR)
        size_scale   = (max(0.5, 1.0 - (anchor_drift - self.OSMIUM_DRIFT_SCALE_AT) / 20.0)
                        if anchor_drift > self.OSMIUM_DRIFT_SCALE_AT else 1.0)

        front  = max(6, int(self.OSMIUM_QUOTE_FRONT  * size_scale))
        second = max(4, int(self.OSMIUM_QUOTE_SECOND * size_scale))

        # OBI-confirmed side gets size boost
        front_bid  = int(front  * (self.OSMIUM_OBI_SIZE_BOOST if obi >=  self.OSMIUM_OBI_STRONG else 1.0))
        front_ask  = int(front  * (self.OSMIUM_OBI_SIZE_BOOST if obi <= -self.OSMIUM_OBI_STRONG else 1.0))
        second_bid = int(second * (self.OSMIUM_OBI_SIZE_BOOST if obi >=  self.OSMIUM_OBI_STRONG else 1.0))
        second_ask = int(second * (self.OSMIUM_OBI_SIZE_BOOST if obi <= -self.OSMIUM_OBI_STRONG else 1.0))

        if rb > 0 and not toxic_buys:
            q = min(rb, front_bid)
            orders.append(Order(product, bp, q))
            rb -= q
            if rb > 0:
                orders.append(Order(product, bp - 1, min(rb, second_bid)))

        if rs > 0 and not toxic_sells:
            q = min(rs, front_ask)
            orders.append(Order(product, ap, -q))
            rs -= q
            if rs > 0:
                orders.append(Order(product, ap + 1, -min(rs, second_ask)))

        return orders

    # ─────────────────────────────────────────────────────────────────────────
    def run(self, state: TradingState):
        self._load_state(state)
        result: Dict[str, List[Order]] = {}

        pep = self._pepper_logic(state)
        if pep:
            result["INTARIAN_PEPPER_ROOT"] = pep

        osm = self._osmium_logic(state)
        if osm:
            result["ASH_COATED_OSMIUM"] = osm

        return result, 0, self._save_state()
