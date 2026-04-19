"""
trader_v6.py — Hybrid Dominant Trader
======================================
Design goals (rank #1 across Balanced / IMC-focused / Safety-first):

PEPPER ROOT strategy (from peter_v5, improved)
----------------------------------------------
- Keep v5's strong trend-following with stop/resume guards (best Worst Day)
- FIX: Remove aggressive spread-momentum gating that was suppressing IMC Mean
  → Spread-increasing now only reduces passive sizing (not a full halt)
  → IMC-facing buy logic is always allowed at fair value
- FIX: Drift detection uses absolute base anchor, not rolling window, for
  faster regime classification in short IMC back-tests
- Keep dual-speed slope detection (fast_track at 500 ticks)

OSMIUM strategy (from robust_suvin_v1, improved)
-------------------------------------------------
- Keep suvin's toxicity filter (the edge over v5's pure VWAP approach)
- Keep suvin's tight market-making with two-level quotes
- FIX: Add hard position circuit-breaker at ±60 (flatten aggressively)
  → This kills the tail-risk Worst Day issue in suvin
- FIX: Tighten MM skew earlier (starts at pos=15 not 22)
- FIX: Increase toxicity threshold sensitivity (35 vs 45) for faster reaction
- Add: VWAP-blend fair value (from v5) as a secondary signal for take logic
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

    # Slope thresholds (normalised per 10 ticks)
    PEPPER_SLOPE_STRONG   =  0.08   # v5 had 0.06, raise bar slightly
    PEPPER_SLOPE_MODERATE =  0.04
    PEPPER_SLOPE_WEAK     = -0.01

    PEPPER_CAP_STRONG   = 80
    PEPPER_CAP_MODERATE = 60
    PEPPER_CAP_WEAK     = 30
    PEPPER_CAP_NEGATIVE =  0
    PEPPER_CAP_TENTATIVE = 20

    PEPPER_TAKE_STRONG   = 20   # max liquidity-take per tick at strong cap
    PEPPER_TAKE_NORMAL   = 12
    PEPPER_PASSIVE_MAX   = 40

    # Stop / resume thresholds (local 20-tick slope)
    PEPPER_STOP_BREACH_COUNT = 2   # consecutive ticks below threshold
    PEPPER_STOP_STRONG   = -14
    PEPPER_STOP_MODERATE = -10
    PEPPER_STOP_WEAK     = -7
    PEPPER_RESUME_STRONG =  6
    PEPPER_RESUME_MODERATE = 5
    PEPPER_RESUME_WEAK   =  4

    # Spread momentum → only reduce passive size, never block buys entirely
    PEPPER_SPREAD_PASSIVE_SCALE = 0.4   # scale down passive qty when spread widening

    # ── OSMIUM constants ──────────────────────────────────────────────────────
    OSMIUM_ANCHOR = 10_000

    OSMIUM_TOXICITY_THRESHOLD = 35   # suvin had 45 — more sensitive
    OSMIUM_TAKE_EDGE = 1             # min edge to lift/hit
    OSMIUM_EDGE_POS_STEP = 25        # widen edge per 25-lot position

    OSMIUM_SKEW_SOFT  = 15           # suvin had 22 — skew earlier
    OSMIUM_SKEW_HARD  = 35
    OSMIUM_FLATTEN_HARD = 58         # circuit-breaker: flatten towards this
    OSMIUM_FLATTEN_TARGET = 50       # target after circuit-breaker triggers

    OSMIUM_QUOTE_FRONT  = 28
    OSMIUM_QUOTE_SECOND = 20

    # VWAP blend weight for fair value
    OSMIUM_VWAP_WEIGHT = 0.65        # 65% live VWAP, 35% anchor

    def __init__(self):
        self.history: Dict = {}

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

        # ── Spread momentum (soft gate only) ─────────────────────────────────
        prev_spread = self.history.get("pp_prev_spread", spread)
        spread_widening = spread > prev_spread
        self.history["pp_prev_spread"] = spread

        # ── Regime / cap detection ────────────────────────────────────────────
        elapsed  = ts - start_ts
        warmed_up   = elapsed >= self.PEPPER_WARMUP_TICKS
        fast_track  = elapsed >= self.PEPPER_FAST_TRACK_TICKS

        cap = self.history.get("pp_cap", None)

        if len(base_samples) >= 15 and len(hist) >= 15:
            base_mean    = _median(base_samples)
            current_mean = _median(hist[-15:])
            # Drift per 100 ticks (normalised)
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
                new_cap = cap  # hold current until warmed up

            # Upgrade freely, downgrade only at full warmup (avoid whipsawing)
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
        take_limit = self.PEPPER_TAKE_STRONG if effective_cap == self.PEPPER_CAP_STRONG else self.PEPPER_TAKE_NORMAL

        if rem_cap > 0:
            budget = min(rem_cap, take_limit)
            for ask in sorted(depth.sell_orders.keys()):
                if budget <= 0:
                    break
                if ask <= mid + 1.5:   # slightly wider take threshold vs v5
                    qty = min(budget, -depth.sell_orders[ask])
                    orders.append(Order(product, ask, qty))
                    budget    -= qty
                    rem_cap   -= qty

            # Passive order — scale down when spread is widening (soft gate)
            if rem_cap > 0:
                passive_qty = min(rem_cap, self.PEPPER_PASSIVE_MAX)
                if spread_widening:
                    passive_qty = int(passive_qty * self.PEPPER_SPREAD_PASSIVE_SCALE)
                if passive_qty > 0:
                    orders.append(Order(product, bb + 1, passive_qty))

        # Light de-risk sell when spread is widening and we're well-loaded
        if spread_widening and pos > effective_cap * 0.5:
            sell_qty = min(pos, 10)
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

        # ── VWAP-blended fair value ───────────────────────────────────────────
        bv1 = depth.buy_orders[bb]
        av1 = -depth.sell_orders[ba]
        total_vol = bv1 + av1
        if total_vol > 0:
            vwap_mid = (bb * av1 + ba * bv1) / total_vol
        else:
            vwap_mid = mid

        # Blend VWAP toward anchor (prevents runaway fair during gaps)
        fair = self.OSMIUM_VWAP_WEIGHT * vwap_mid + (1 - self.OSMIUM_VWAP_WEIGHT) * self.OSMIUM_ANCHOR

        op = self.history["op"]
        op.append(fair)
        if len(op) > 30:
            op = op[-30:]
        self.history["op"] = op

        # Smooth fair with recent history for stability
        if len(op) >= 5:
            fair = 0.6 * fair + 0.4 * (sum(op[-5:]) / 5.0)

        # ── Toxicity filter ───────────────────────────────────────────────────
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

        # ── Hard circuit-breaker: flatten first ───────────────────────────────
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

        # ── Liquidity taking (mean reversion) ────────────────────────────────
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

        # ── Market making (quote around fair) ────────────────────────────────
        skew = int(pos / self.OSMIUM_SKEW_SOFT)   # earlier skew onset

        bp = int(min(bb + 1, fair - 1)) - skew
        ap = int(max(ba - 1, fair + 1)) - skew

        # Clamp to reasonable spread around fair
        bp = max(bp, int(fair) - 4)
        ap = min(ap, int(fair) + 4)

        # Extra skew at hard threshold
        if pos > self.OSMIUM_SKEW_HARD:
            bp -= 1
        if pos < -self.OSMIUM_SKEW_HARD:
            ap += 1

        if bp >= ap:
            bp = int(fair) - 1
            ap = int(fair) + 1

        # Size scaling — reduce when far from anchor (drift-risk discount)
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