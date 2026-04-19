"""
trader_peter_v4.py — Best-of-Both Merge
========================================
Base: trader_stable_suvin_v2 (better calibrated params on almost all axes)
Added from peter_v3 (structural improvements):

OSMIUM additions/fixes vs suvin_v2:
1. Full 3-level order book VWAP (was top-of-book only) → more accurate fair
2. Warmup 100 ticks: observe-only before quoting → kills early dip from EMA lag
3. Flow-based quote skew: imbalance 15-34 → shift quotes 1 tick into active flow
   (e.g. buyers active → lower ask by 1 → more sell fills into demand)
4. BUG FIX: flatten short branch had rb += flatten_qty (should be -=)
   suvin_v2 L337: "rb  += flatten_qty" was wrong; we BUY so rb must decrease
5. FRONT=36 SECOND=28 (suvin: 35/25) — marginal extra size

OSMIUM params kept from suvin_v2 (all better than v3):
- TAKE_EDGE=0: fill at fair, not just beyond it
- Takes always run (toxic = block MM quotes only, not takes)
- SPREAD_CLAMP=5 (v3 had 4)
- EDGE_POS_STEP=30 (v3 had 25)
- DRIFT_SCALE_AT=8 (v3 had 5)
- SKEW_SOFT=15

PEPPER additions vs suvin_v2:
1. Spread trend alpha (10-tick window):
   - spread_trending_up → 1.6x take aggression (was cutting passive by 0.6x)
   - Dynamic take threshold = mid + max(1.5, avg_spread*0.55)
   - Passive bid at bb+2 when spread trending up (deeper inside spread)
   - Removed: de-risk sell on spread widening (backwards for uptrend asset)
   - Removed: SPREAD_PASSIVE_SCALE cutback (replaced by spread boost)

PEPPER params kept from suvin_v2 (all better than v3):
- FAST_TRACK=300 (v3 had 500)
- SLOPE_STRONG_FAST=0.06, SLOPE_STRONG=0.04, SLOPE_MODERATE=0.01
- TAKE_STRONG=25, TAKE_NORMAL=14, PASSIVE_MAX=50
- CAP_TENTATIVE=25

SAFETY unchanged: pepper stop/resume guard, osmium circuit-breaker ±58→±50,
hard skew at pos=35, VWAP-anchor blend 65/35, 5-tick fair smoothing.
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
    PEPPER_WARMUP_TICKS      = 1200
    PEPPER_FAST_TRACK_TICKS  = 300    # suvin: faster strong-regime entry

    PEPPER_SLOPE_STRONG_FAST = 0.06   # fast-track trigger (suvin)
    PEPPER_SLOPE_STRONG      = 0.04   # warmed-up strong threshold
    PEPPER_SLOPE_MODERATE    = 0.01   # suvin: finer gradient
    PEPPER_SLOPE_WEAK        = -0.01

    PEPPER_CAP_STRONG    = 80
    PEPPER_CAP_MODERATE  = 60
    PEPPER_CAP_WEAK      = 30
    PEPPER_CAP_NEGATIVE  =  0
    PEPPER_CAP_TENTATIVE = 25

    PEPPER_TAKE_STRONG   = 25         # suvin
    PEPPER_TAKE_NORMAL   = 14         # suvin
    PEPPER_PASSIVE_MAX   = 50         # suvin

    PEPPER_STOP_BREACH_COUNT = 2
    PEPPER_STOP_STRONG    = -14
    PEPPER_STOP_MODERATE  = -10
    PEPPER_STOP_WEAK      =  -7
    PEPPER_RESUME_STRONG  =   6
    PEPPER_RESUME_MODERATE=   5
    PEPPER_RESUME_WEAK    =   4

    # Spread trend alpha (peter_v3): boost aggression when spread growing
    PEPPER_SPREAD_TAKE_BOOST   = 1.6
    PEPPER_SPREAD_TREND_WINDOW = 10

    # ── OSMIUM constants ──────────────────────────────────────────────────────
    OSMIUM_ANCHOR = 10_000
    OSMIUM_WARMUP_TICKS = 100         # peter_v3: no quotes until EMA stable

    OSMIUM_TOXICITY_THRESHOLD = 35
    OSMIUM_FLOW_SKEW_THRESHOLD = 15   # peter_v3: softer flow-skew gate
    OSMIUM_TAKE_EDGE      = 0         # suvin: fill at fair, not just beyond
    OSMIUM_EDGE_POS_STEP  = 30        # suvin: slower widening with position
    OSMIUM_TAKE_EDGE_MAX  = 3

    OSMIUM_SKEW_SOFT      = 15        # suvin
    OSMIUM_SKEW_HARD      = 35
    OSMIUM_FLATTEN_HARD   = 58
    OSMIUM_FLATTEN_TARGET = 50

    OSMIUM_QUOTE_FRONT    = 36        # +1 over suvin's 35
    OSMIUM_QUOTE_SECOND   = 28        # +3 over suvin's 25

    OSMIUM_SPREAD_CLAMP   = 5         # suvin: quote further from fair
    OSMIUM_VWAP_WEIGHT    = 0.65
    OSMIUM_DRIFT_SCALE_AT = 8         # suvin: tolerate more drift before shrinking

    def __init__(self):
        self.history: Dict = {}

    def bid(self) -> int:
        # Top-50% bid for 25% more order book volume
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

    @staticmethod
    def _full_book_vwap(depth: OrderDepth) -> float:
        total_val = total_vol = 0.0
        for price, vol in depth.buy_orders.items():
            total_val += price * abs(vol)
            total_vol += abs(vol)
        for price, vol in depth.sell_orders.items():
            total_val += price * abs(vol)
            total_vol += abs(vol)
        return total_val / total_vol if total_vol > 0 else 0.0

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

        # ── Spread trend alpha ────────────────────────────────────────────────
        spread_hist = self.history["pp_spread_hist"]
        spread_hist.append(spread)
        if len(spread_hist) > 20:
            spread_hist = spread_hist[-20:]
        self.history["pp_spread_hist"] = spread_hist

        w = self.PEPPER_SPREAD_TREND_WINDOW
        spread_trending_up = (
            len(spread_hist) >= w and
            spread_hist[-1] > spread_hist[-w]
        )
        avg_spread = sum(spread_hist[-w:]) / min(len(spread_hist), w)

        # ── Regime / cap detection ────────────────────────────────────────────
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

        # ── Stopped: orderly exit ─────────────────────────────────────────────
        if drift_stopped or effective_cap == 0:
            if pos > 0:
                dump_qty = min(pos, 20)
                avail    = depth.buy_orders.get(bb, 0)
                qty      = min(dump_qty, avail)
                if qty > 0:
                    orders.append(Order(product, bb, -qty))
            return orders

        # ── Normal: buy into trend ────────────────────────────────────────────
        rem_cap    = effective_cap - pos

        # Spread alpha: boost take aggression when spread is growing
        base_take = self.PEPPER_TAKE_STRONG if effective_cap == self.PEPPER_CAP_STRONG else self.PEPPER_TAKE_NORMAL
        take_limit = int(base_take * self.PEPPER_SPREAD_TAKE_BOOST) if spread_trending_up else base_take

        # Dynamic take threshold: widen with avg spread
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

            if rem_cap > 0:
                passive_qty = min(rem_cap, self.PEPPER_PASSIVE_MAX)
                # Post deeper inside spread when spread is growing (better fill)
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
        ts  = state.timestamp

        # ── Warmup: no quoting until EMA has data ────────────────────────────
        os_t0     = self.history.setdefault("os_t0", ts)
        os_warmed = (ts - os_t0) >= self.OSMIUM_WARMUP_TICKS

        # ── Full 3-level order book VWAP ─────────────────────────────────────
        full_vwap = self._full_book_vwap(depth)
        if full_vwap == 0.0:
            full_vwap = mid

        fair = self.OSMIUM_VWAP_WEIGHT * full_vwap + (1 - self.OSMIUM_VWAP_WEIGHT) * self.OSMIUM_ANCHOR

        op = self.history["op"]
        op.append(fair)
        if len(op) > 30:
            op = op[-30:]
        self.history["op"] = op

        if len(op) >= 5:
            fair = 0.6 * fair + 0.4 * (sum(op[-5:]) / 5.0)

        # ── Toxicity & flow imbalance ─────────────────────────────────────────
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

        # Flow skew: lean quotes into sub-toxic active flow
        flow_skew = 0
        if imbalance >= self.OSMIUM_FLOW_SKEW_THRESHOLD and not toxic_buys:
            flow_skew = 1    # buyers active → lower ask, sell more into demand
        elif imbalance <= -self.OSMIUM_FLOW_SKEW_THRESHOLD and not toxic_sells:
            flow_skew = -1   # sellers active → raise bid, buy more from supply

        orders: List[Order] = []

        if not os_warmed:
            return orders

        rb = self.LIMIT - pos
        rs = self.LIMIT + pos

        # ── Hard circuit-breaker ──────────────────────────────────────────────
        if pos > self.OSMIUM_FLATTEN_HARD and rs > 0:
            flatten_qty = min(pos - self.OSMIUM_FLATTEN_TARGET + 5, rs)
            orders.append(Order(product, int(fair), -flatten_qty))
            rs  -= flatten_qty
            pos -= flatten_qty
        elif pos < -self.OSMIUM_FLATTEN_HARD and rb > 0:
            flatten_qty = min(-pos - self.OSMIUM_FLATTEN_TARGET + 5, rb)
            orders.append(Order(product, int(fair), flatten_qty))
            rb  -= flatten_qty   # BUG FIX: suvin_v2 had rb += here
            pos += flatten_qty

        # ── Liquidity taking: always run (toxic = skip MM only, not takes) ───
        pos_adj_buy  = min(self.OSMIUM_TAKE_EDGE_MAX,
                           self.OSMIUM_TAKE_EDGE + max(0, pos  // self.OSMIUM_EDGE_POS_STEP))
        pos_adj_sell = min(self.OSMIUM_TAKE_EDGE_MAX,
                           self.OSMIUM_TAKE_EDGE + max(0, (-pos) // self.OSMIUM_EDGE_POS_STEP))

        for ask in sorted(depth.sell_orders.keys()):
            if ask <= fair - pos_adj_buy and rb > 0:
                q = min(rb, -depth.sell_orders[ask])
                orders.append(Order(product, ask, q))
                rb  -= q
                pos += q

        for bid in sorted(depth.buy_orders.keys(), reverse=True):
            if bid >= fair + pos_adj_sell and rs > 0:
                q = min(rs, depth.buy_orders[bid])
                orders.append(Order(product, bid, -q))
                rs  -= q
                pos -= q

        # ── Market making ─────────────────────────────────────────────────────
        total_skew = int(pos / self.OSMIUM_SKEW_SOFT) + flow_skew

        bp = int(min(bb + 1, fair - 1)) - total_skew
        ap = int(max(ba - 1, fair + 1)) - total_skew

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

        # On toxic side: skip passive MM (not takes — already ran above)
        if rb > 0 and not toxic_buys:
            q = min(rb, front)
            orders.append(Order(product, bp, q))
            rb -= q
            if rb > 0:
                orders.append(Order(product, bp - 1, min(rb, second)))

        if rs > 0 and not toxic_sells:
            q = min(rs, front)
            orders.append(Order(product, ap, -q))
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
