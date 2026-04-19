"""
trader_peter_v2.py — Spread-Alpha Exploitation Build
=====================================================

Changes from v1:
- Add bid() for Market Access Fee (top-50% to get 25% more order book volume)
- PEPPER ROOT: Fix inverted spread logic. Widening spread = BUY SIGNAL, not exit.
  * Take aggression scales UP with spread trend (was scaling down passive)
  * Remove de-risk sell on spread widening (was backwards for uptrend)
  * Track 10-tick spread trend for more stable signal than tick-by-tick noise
  * Take threshold widens proportionally to spread (capture more when spread big)
- OSMIUM: unchanged (toxicity filter + circuit breaker still sound)
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


class Trader:
    LIMIT = 80

    # ── PEPPER constants ──────────────────────────────────────────────────────
    PEPPER_WARMUP_TICKS = 1200
    PEPPER_FAST_TRACK_TICKS = 500

    PEPPER_SLOPE_STRONG   =  0.08
    PEPPER_SLOPE_MODERATE =  0.04
    PEPPER_SLOPE_WEAK     = -0.01

    PEPPER_CAP_STRONG   = 80
    PEPPER_CAP_MODERATE = 60
    PEPPER_CAP_WEAK     = 30
    PEPPER_CAP_NEGATIVE =  0
    PEPPER_CAP_TENTATIVE = 20

    PEPPER_TAKE_STRONG   = 20
    PEPPER_TAKE_NORMAL   = 12
    PEPPER_PASSIVE_MAX   = 40

    PEPPER_STOP_BREACH_COUNT = 2
    PEPPER_STOP_STRONG   = -14
    PEPPER_STOP_MODERATE = -10
    PEPPER_STOP_WEAK     = -7
    PEPPER_RESUME_STRONG =  6
    PEPPER_RESUME_MODERATE = 5
    PEPPER_RESUME_WEAK   =  4

    # Spread alpha: scale factor applied to take_limit when spread is trending up
    PEPPER_SPREAD_TAKE_BOOST  = 1.6   # 60% more aggressive taking when spread grows
    PEPPER_SPREAD_TREND_WINDOW = 10   # ticks to measure spread trend

    # ── OSMIUM constants ──────────────────────────────────────────────────────
    OSMIUM_ANCHOR = 10_000

    OSMIUM_TOXICITY_THRESHOLD = 35
    OSMIUM_TAKE_EDGE = 1
    OSMIUM_EDGE_POS_STEP = 25

    OSMIUM_SKEW_SOFT  = 15
    OSMIUM_SKEW_HARD  = 35
    OSMIUM_FLATTEN_HARD = 58
    OSMIUM_FLATTEN_TARGET = 50

    OSMIUM_QUOTE_FRONT  = 28
    OSMIUM_QUOTE_SECOND = 20

    OSMIUM_VWAP_WEIGHT = 0.65

    def __init__(self):
        self.history: Dict = {}

    def bid(self) -> int:
        # Pay up to stay in top-50% of bidders: 25% more order book volume
        # worth the cost vs potential trend capture on pepper + osmium MM flow.
        return 1000

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
        self.history.setdefault("pp_spread_hist", [])

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

        bb  = max(depth.buy_orders.keys())
        ba  = min(depth.sell_orders.keys())
        mid = (bb + ba) / 2.0
        spread = ba - bb
        ts  = state.timestamp

        # ── History ──────────────────────────────────────────────────────────
        hist = self.history["pp"]
        hist.append(mid)
        if len(hist) > 120:
            hist = hist[-120:]
        self.history["pp"] = hist

        base_samples = self.history["pp_base"]
        if len(base_samples) < 15:
            base_samples.append(mid)

        start_ts = self.history.setdefault("pp_t0", ts)

        # ── Spread trend signal ───────────────────────────────────────────────
        # Widening spread on a trending asset = strong directional move incoming.
        # React by INCREASING aggression, not reducing it.
        spread_hist = self.history["pp_spread_hist"]
        spread_hist.append(spread)
        if len(spread_hist) > 20:
            spread_hist = spread_hist[-20:]
        self.history["pp_spread_hist"] = spread_hist

        # Spread trending up over window = exploit signal
        w = self.PEPPER_SPREAD_TREND_WINDOW
        spread_trending_up = (
            len(spread_hist) >= w and
            spread_hist[-1] > spread_hist[-w]
        )
        # Average recent spread for dynamic take threshold
        avg_spread = sum(spread_hist[-w:]) / min(len(spread_hist), w)

        # ── Regime / cap detection ────────────────────────────────────────────
        elapsed  = ts - start_ts
        warmed_up   = elapsed >= self.PEPPER_WARMUP_TICKS
        fast_track  = elapsed >= self.PEPPER_FAST_TRACK_TICKS

        cap = self.history.get("pp_cap", None)

        if len(base_samples) >= 15 and len(hist) >= 15:
            base_mean    = _median(base_samples)
            current_mean = _median(hist[-15:])
            dt    = max(1, elapsed)
            drift = (current_mean - base_mean) / dt * 100.0

            if fast_track and drift >= self.PEPPER_SLOPE_STRONG:
                new_cap = self.PEPPER_CAP_STRONG
            elif warmed_up:
                if drift > self.PEPPER_SLOPE_MODERATE:
                    new_cap = self.PEPPER_CAP_STRONG
                elif drift > self.PEPPER_SLOPE_WEAK:
                    new_cap = self.PEPPER_CAP_MODERATE
                elif drift > -0.02:
                    new_cap = self.PEPPER_CAP_WEAK
                else:
                    new_cap = self.PEPPER_CAP_NEGATIVE
            else:
                new_cap = cap

            if cap is None:
                cap = new_cap if new_cap is not None else self.PEPPER_CAP_TENTATIVE
            elif new_cap is not None and new_cap > cap:
                cap = new_cap
            elif warmed_up and new_cap is not None and new_cap < cap:
                cap = new_cap

            self.history["pp_cap"] = cap

        effective_cap = cap if cap is not None else self.PEPPER_CAP_TENTATIVE

        # ── Stop logic ────────────────────────────────────────────────────────
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

        # ── Stopped regime: orderly exit ──────────────────────────────────────
        if drift_stopped or effective_cap == 0:
            if pos > 0:
                dump_qty = min(pos, 20)
                avail    = depth.buy_orders.get(bb, 0)
                qty      = min(dump_qty, avail)
                if qty > 0:
                    orders.append(Order(product, bb, -qty))
            return orders

        # ── Normal regime: buy into trend ─────────────────────────────────────
        rem_cap    = effective_cap - pos

        # Spread alpha: boost take aggression when spread is growing
        base_take = self.PEPPER_TAKE_STRONG if effective_cap == self.PEPPER_CAP_STRONG else self.PEPPER_TAKE_NORMAL
        if spread_trending_up:
            take_limit = int(base_take * self.PEPPER_SPREAD_TAKE_BOOST)
        else:
            take_limit = base_take

        # Dynamic take threshold: widen when spread is large (capture more of it)
        take_threshold = mid + max(1.5, avg_spread * 0.55)

        if rem_cap > 0:
            budget = min(rem_cap, take_limit)
            for ask in sorted(depth.sell_orders.keys()):
                if budget <= 0:
                    break
                if ask <= take_threshold:
                    qty = min(budget, -depth.sell_orders[ask])
                    orders.append(Order(product, ask, qty))
                    budget  -= qty
                    rem_cap -= qty

            # Passive order: post at better price when spread is wide/growing
            if rem_cap > 0:
                passive_qty = min(rem_cap, self.PEPPER_PASSIVE_MAX)
                # When spread trending up, post deeper inside spread for better fill
                passive_price = (bb + 2) if spread_trending_up else (bb + 1)
                if passive_qty > 0:
                    orders.append(Order(product, passive_price, passive_qty))

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

        bv1 = depth.buy_orders[bb]
        av1 = -depth.sell_orders[ba]
        total_vol = bv1 + av1
        if total_vol > 0:
            vwap_mid = (bb * av1 + ba * bv1) / total_vol
        else:
            vwap_mid = mid

        fair = self.OSMIUM_VWAP_WEIGHT * vwap_mid + (1 - self.OSMIUM_VWAP_WEIGHT) * self.OSMIUM_ANCHOR

        op = self.history["op"]
        op.append(fair)
        if len(op) > 30:
            op = op[-30:]
        self.history["op"] = op

        if len(op) >= 5:
            fair = 0.6 * fair + 0.4 * (sum(op[-5:]) / 5.0)

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
            rs -= flatten_qty
            pos -= flatten_qty
        elif pos < -self.OSMIUM_FLATTEN_HARD and rb > 0:
            flatten_qty = min(-pos - self.OSMIUM_FLATTEN_TARGET + 5, rb)
            orders.append(Order(product, int(fair), flatten_qty))
            rb -= flatten_qty
            pos += flatten_qty

        buy_edge  = self.OSMIUM_TAKE_EDGE + max(0, pos // self.OSMIUM_EDGE_POS_STEP)
        sell_edge = self.OSMIUM_TAKE_EDGE + max(0, (-pos) // self.OSMIUM_EDGE_POS_STEP)

        if not toxic_buys:
            for ask in sorted(depth.sell_orders.keys()):
                if ask <= fair - buy_edge and rb > 0:
                    q = min(rb, -depth.sell_orders[ask])
                    orders.append(Order(product, ask, q))
                    rb  -= q
                    pos += q

        if not toxic_sells:
            for bid in sorted(depth.buy_orders.keys(), reverse=True):
                if bid >= fair + sell_edge and rs > 0:
                    q = min(rs, depth.buy_orders[bid])
                    orders.append(Order(product, bid, -q))
                    rs  -= q
                    pos -= q

        skew = int(pos / self.OSMIUM_SKEW_SOFT)

        bp = int(min(bb + 1, fair - 1)) - skew
        ap = int(max(ba - 1, fair + 1)) - skew

        bp = max(bp, int(fair) - 4)
        ap = min(ap, int(fair) + 4)

        if pos > self.OSMIUM_SKEW_HARD:
            bp -= 1
        if pos < -self.OSMIUM_SKEW_HARD:
            ap += 1

        if bp >= ap:
            bp = int(fair) - 1
            ap = int(fair) + 1

        anchor_drift = abs(fair - self.OSMIUM_ANCHOR)
        size_scale   = max(0.5, 1.0 - anchor_drift / 20.0) if anchor_drift > 5 else 1.0
        front  = max(6, int(self.OSMIUM_QUOTE_FRONT  * size_scale))
        second = max(4, int(self.OSMIUM_QUOTE_SECOND * size_scale))

        if rb > 0:
            q = min(rb, front)
            orders.append(Order(product, bp,     q))
            rb -= q
            if rb > 0:
                orders.append(Order(product, bp - 1, min(rb, second)))

        if rs > 0:
            q = min(rs, front)
            orders.append(Order(product, ap,     -q))
            rs -= q
            if rs > 0:
                orders.append(Order(product, ap + 1, -min(rs, second)))

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
