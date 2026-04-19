"""
trader_peter_v2000.py — Holy_grailll + docs-aligned refinements (NO MAF)
=========================================================================
Base: Holy_grailll.py (v10 — OBI alpha overlay on Pepper + Osmium).
This version strips the Market Access Fee entirely and layers in five
refinements explicitly called out in the Round 2 algorithm wiki.

Changes from Holy_grailll.py:

NO MAF
------
• `bid()` removed. No fee paid, no assumption of 125 % flow.

OSMIUM — richer fair value (wiki §4)
------------------------------------
1. MULTI-LEVEL VWAP: top 3 levels per side, not just L1. Wiki: "Utilizing
   depth across the full order book rather than just the first level."
2. SMOOTHER FAIR: 5-tick rolling average extended to 10 ticks; `op` cap
   lifted 30 → 50 so the longer window stays full. Calmer quotes, fewer
   quote-churn cycles.

PEPPER — sturdier stop detection (wiki §6 — Time-Series Memory)
----------------------------------------------------------------
3. LINREG STOP SLOPE: local-slope check uses OLS×19 over hist[-20:] rather
   than raw hist[-1]−hist[-20]. Same thresholds and units, but filters
   single-tick noise spikes that would otherwise count toward a stop.

BOTH — significant imbalance *periods*, not ticks (wiki §4)
-----------------------------------------------------------
4. OBI PERSISTENCE: categorical OBI gates (turbo-load, size boost, passive
   skip, quote skew, take relief) require a 3-tick rolling-average OBI
   to exceed threshold, not just one tick. Raw OBI still drives the
   continuous Osmium fair-shift so responsiveness is preserved there.
   Wiki specifically says "significant imbalance periods", not moments.

BOTH — gap handling (wiki §6 pillar 1)
--------------------------------------
5. MID-PRICE BACKFILL: when either side of the book is empty, hist / op /
   obi_hist carry forward their last value so time-series state (slopes,
   smoothers, regime elapsed counters) stays coherent instead of freezing
   mid-computation.

All caps, limits, take/passive sizes, circuit-breakers, skew, and OBI
thresholds preserved from Holy_grailll.
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


def _linreg_slope(vals: list) -> float:
    """OLS slope in price-per-sample over the given window."""
    n = len(vals)
    if n < 2:
        return 0.0
    xm = (n - 1) / 2.0
    ym = sum(vals) / n
    num = sum((i - xm) * (v - ym) for i, v in enumerate(vals))
    den = sum((i - xm) ** 2 for i in range(n))
    return num / den if den else 0.0


def _obi(depth) -> float:
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
    if not depth.buy_orders or not depth.sell_orders:
        return 0.0
    bids = sorted(depth.buy_orders.items(), reverse=True)[:levels]
    asks = sorted(depth.sell_orders.items())[:levels]
    bv = 0.0
    av = 0.0
    for i, (_, v) in enumerate(bids):
        bv += v / (1 + i)
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

    PEPPER_OBI_STRONG        = 0.30
    PEPPER_OBI_TAKE_BOOST    = 1.6
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

    OSMIUM_OBI_STRONG        = 0.30
    OSMIUM_OBI_FAIR_SHIFT    = 0.6
    OSMIUM_OBI_SIZE_BOOST    = 1.25

    # ── v2000 constants ──────────────────────────────────────────────────────
    OSMIUM_VWAP_LEVELS  = 3
    OSMIUM_FAIR_MA_WIN  = 10     # was 5
    OSMIUM_OP_CAP       = 50     # was 30
    OBI_SMOOTH_WINDOW   = 3      # require OBI persistence over 3 ticks

    def __init__(self):
        self.history: Dict = {}

    def _load_state(self, state: TradingState):
        if state.traderData:
            try:
                self.history = json.loads(state.traderData)
            except Exception:
                self.history = {}
        self.history.setdefault("pp", [])
        self.history.setdefault("pp_base", [])
        self.history.setdefault("op", [])
        self.history.setdefault("pp_obi_hist", [])
        self.history.setdefault("op_obi_hist", [])

    def _save_state(self) -> str:
        return json.dumps(self.history)

    @staticmethod
    def _push_smooth(hist_list: list, val: float, window: int) -> float:
        hist_list.append(val)
        if len(hist_list) > window:
            del hist_list[:len(hist_list) - window]
        return sum(hist_list) / len(hist_list)

    # ─────────────────────────────────────────────────────────────────────────
    # PEPPER ROOT
    # ─────────────────────────────────────────────────────────────────────────
    def _pepper_logic(self, state: TradingState) -> List[Order]:
        product = "INTARIAN_PEPPER_ROOT"
        if product not in state.order_depths:
            return []

        depth = state.order_depths[product]
        pos   = state.position.get(product, 0)

        # Gap handling: backfill hist so time-series state stays coherent
        if not depth.buy_orders or not depth.sell_orders:
            hist = self.history["pp"]
            if hist:
                hist.append(hist[-1])
                if len(hist) > 120:
                    hist = hist[-120:]
                self.history["pp"] = hist
            return []

        bb     = max(depth.buy_orders.keys())
        ba     = min(depth.sell_orders.keys())
        mid    = (bb + ba) / 2.0
        spread = ba - bb
        ts     = state.timestamp

        obi_raw    = _obi_deep(depth, levels=2)
        obi_smooth = self._push_smooth(self.history["pp_obi_hist"],
                                       obi_raw, self.OBI_SMOOTH_WINDOW)
        # categorical overlays use the smoothed value (imbalance "periods")
        obi = obi_smooth

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
                # Don't ratchet up INTO an OBI wall (use smoothed OBI)
                if obi < -0.5:
                    pass
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
            # v2000: linreg × 19 ≈ hist[-1]−hist[-20] but smoother
            local_slope = _linreg_slope(hist[-20:]) * 19
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

        if drift_stopped or effective_cap == 0:
            if pos > 0:
                dump_qty = min(pos, 25 if obi < -self.PEPPER_OBI_STRONG else 20)
                avail    = depth.buy_orders.get(bb, 0)
                qty      = min(dump_qty, avail)
                if qty > 0:
                    orders.append(Order(product, bb, -qty))
            return orders

        rem_cap    = effective_cap - pos
        take_limit = self.PEPPER_TAKE_STRONG if effective_cap == self.PEPPER_CAP_STRONG else self.PEPPER_TAKE_NORMAL

        if obi >= self.PEPPER_OBI_STRONG:
            take_limit = int(take_limit * self.PEPPER_OBI_TAKE_BOOST)

        if rem_cap > 0:
            budget = min(rem_cap, take_limit)
            for ask in sorted(depth.sell_orders.keys()):
                if budget <= 0:
                    break
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

                if obi >= self.PEPPER_OBI_STRONG:
                    passive_qty = int(passive_qty * self.PEPPER_OBI_PASSIVE_BOOST)
                elif obi <= -self.PEPPER_OBI_STRONG:
                    passive_qty = 0

                if passive_qty > 0:
                    orders.append(Order(product, bb + 1, passive_qty))

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
            op = self.history["op"]
            if op:
                op.append(op[-1])
                if len(op) > self.OSMIUM_OP_CAP:
                    op = op[-self.OSMIUM_OP_CAP:]
                self.history["op"] = op
            return []

        bb  = max(depth.buy_orders.keys())
        ba  = min(depth.sell_orders.keys())
        mid = (bb + ba) / 2.0

        obi_raw    = _obi_deep(depth, levels=2)
        obi_smooth = self._push_smooth(self.history["op_obi_hist"],
                                       obi_raw, self.OBI_SMOOTH_WINDOW)
        # categorical gates use smoothed; continuous fair shift uses raw
        obi_cat = obi_smooth

        # ── v2000: multi-level VWAP (top 3 per side) ─────────────────────────
        bid_items = sorted(depth.buy_orders.items(), reverse=True)[:self.OSMIUM_VWAP_LEVELS]
        ask_items = sorted(depth.sell_orders.items())[:self.OSMIUM_VWAP_LEVELS]
        bid_vol = sum(v for _, v in bid_items)
        ask_vol = sum(-v for _, v in ask_items)
        if bid_vol > 0 and ask_vol > 0:
            vwap_bid = sum(p * v for p, v in bid_items) / bid_vol
            vwap_ask = sum(p * (-v) for p, v in ask_items) / ask_vol
            vwap_mid = (vwap_bid + vwap_ask) / 2.0
        else:
            vwap_mid = mid

        fair = self.OSMIUM_VWAP_WEIGHT * vwap_mid + (1 - self.OSMIUM_VWAP_WEIGHT) * self.OSMIUM_ANCHOR

        op = self.history["op"]
        op.append(fair)
        if len(op) > self.OSMIUM_OP_CAP:
            op = op[-self.OSMIUM_OP_CAP:]
        self.history["op"] = op

        # v2000: longer MA window for calmer MM quotes
        w = self.OSMIUM_FAIR_MA_WIN
        if len(op) >= w:
            fair = 0.6 * fair + 0.4 * (sum(op[-w:]) / w)
        elif len(op) >= 5:
            fair = 0.6 * fair + 0.4 * (sum(op[-5:]) / 5.0)

        # OBI-shifted fair uses RAW OBI — want responsiveness on sub-tick pricing
        fair += obi_raw * self.OSMIUM_OBI_FAIR_SHIFT

        buy_vol_t = sell_vol_t = 0
        if product in state.market_trades:
            for t in state.market_trades[product]:
                if t.price >= mid:
                    buy_vol_t  += abs(t.quantity)
                else:
                    sell_vol_t += abs(t.quantity)

        imbalance   = buy_vol_t - sell_vol_t
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

        pos_adj_buy  = min(self.OSMIUM_TAKE_EDGE_MAX,
                           self.OSMIUM_TAKE_EDGE + max(0, pos  // self.OSMIUM_EDGE_POS_STEP))
        pos_adj_sell = min(self.OSMIUM_TAKE_EDGE_MAX,
                           self.OSMIUM_TAKE_EDGE + max(0, (-pos) // self.OSMIUM_EDGE_POS_STEP))

        # OBI take relief uses smoothed (avoid chasing spikes)
        obi_buy_relief  = 1.0 if obi_cat >=  self.OSMIUM_OBI_STRONG else 0.0
        obi_sell_relief = 1.0 if obi_cat <= -self.OSMIUM_OBI_STRONG else 0.0

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

        skew = int(pos / self.OSMIUM_SKEW_SOFT)

        bp = int(min(bb + 1, fair - 1)) - skew
        ap = int(max(ba - 1, fair + 1)) - skew

        # OBI quote skew uses smoothed (persistent imbalance required)
        if obi_cat >= self.OSMIUM_OBI_STRONG:
            bp += 1
        elif obi_cat <= -self.OSMIUM_OBI_STRONG:
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

        # Size boost gate uses smoothed
        front_bid  = int(front  * (self.OSMIUM_OBI_SIZE_BOOST if obi_cat >=  self.OSMIUM_OBI_STRONG else 1.0))
        front_ask  = int(front  * (self.OSMIUM_OBI_SIZE_BOOST if obi_cat <= -self.OSMIUM_OBI_STRONG else 1.0))
        second_bid = int(second * (self.OSMIUM_OBI_SIZE_BOOST if obi_cat >=  self.OSMIUM_OBI_STRONG else 1.0))
        second_ask = int(second * (self.OSMIUM_OBI_SIZE_BOOST if obi_cat <= -self.OSMIUM_OBI_STRONG else 1.0))

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
