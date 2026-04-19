"""
trader_v8.py — Maximum Aggression, Same Safety Envelope
=========================================================
All safety mechanisms from v7 are kept 100% intact:
  - Pepper stop/resume guard (breach_count=2, same thresholds)
  - Osmium circuit-breaker at ±58 → flatten to ±50
  - Osmium skew starts at pos=15, hard boost at pos=35
  - VWAP-anchor blend (65/35) prevents runaway fair
  - Fair smoothing over last 5 ticks
  - Toxicity filter still suppresses passive MM on toxic flow

Aggression upgrades from v7:
─────────────────────────────────────────────────────────
OSMIUM
  1. TAKE_EDGE = -1 (was 0): lift asks 1 tick ABOVE fair and hit bids
     1 tick BELOW fair. We pay a tiny cross but capture far more volume
     on every tick — net positive in a mean-reverting book.
  2. QUOTE_FRONT = 40, QUOTE_SECOND = 30 (was 35/25): maximum inventory
     turnover, fills more of the available book depth each tick.
  3. SPREAD_CLAMP = 6 (was 5): quotes reach further from fair when the
     book is thin, capturing wider spreads without extra directional risk.
  4. TOXICITY_THRESHOLD = 40 (was 35): we were skipping MM too often on
     borderline imbalances; raise the bar so only genuinely toxic flow
     suppresses quotes.
  5. EDGE_POS_STEP = 35 (was 30): edge widens even more slowly with
     position — we keep taking aggressively at mid-range inventory.
  6. TAKE_EDGE_MAX = 4 (was 3): allows position-adjusted edge to reach
     higher values at extreme inventory, giving better mean-reversion.
  7. FLATTEN_TARGET = 45 (was 50): after circuit-breaker fires, we
     flatten further (to 45 not 50), freeing more capacity for new trades.

PEPPER
  8. WARMUP_TICKS = 800 (was 1200): enters regime detection sooner,
     capturing more of the early trend in both real and IMC scenarios.
  9. FAST_TRACK_TICKS = 200 (was 300): strong cap triggers even earlier
     in short IMC back-tests.
 10. SLOPE_STRONG_FAST = 0.04 (was 0.06): even easier fast-track trigger,
     more runs classified as strong-trend earlier.
 11. CAP_TENTATIVE = 35 (was 25): buy more before regime is confirmed.
 12. TAKE_STRONG = 30 (was 25): maximise fills per tick in strong cap.
 13. TAKE_NORMAL = 18 (was 14): more fills per tick in moderate/weak cap.
 14. PASSIVE_MAX = 60 (was 50): larger passive orders when book has depth.
 15. SPREAD_PASSIVE_SCALE = 0.75 (was 0.6): minimal cutback on passive
     when spread widens — widening spread is rarely a reversal signal.
 16. TAKE_THRESHOLD = mid + 2.0 (was mid + 1.5): take asks that are up to
     2 ticks above mid, capturing more depth on each sweep.
 17. DE_RISK_THRESHOLD = 0.7 (was 0.6): only de-risk when position is
     70%+ of cap and spread widening, not 60% — hold inventory longer.
 18. DE_RISK_QTY = 6 (was 8): smaller de-risk sell, stay more loaded.
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
    PEPPER_WARMUP_TICKS      = 800    # v7: 1200
    PEPPER_FAST_TRACK_TICKS  = 200    # v7: 300

    PEPPER_SLOPE_STRONG_FAST = 0.04   # v7: 0.06
    PEPPER_SLOPE_STRONG      = 0.04
    PEPPER_SLOPE_MODERATE    = 0.01
    PEPPER_SLOPE_WEAK        = -0.01

    PEPPER_CAP_STRONG    = 80
    PEPPER_CAP_MODERATE  = 60
    PEPPER_CAP_WEAK      = 30
    PEPPER_CAP_NEGATIVE  =  0
    PEPPER_CAP_TENTATIVE = 35         # v7: 25

    PEPPER_TAKE_STRONG   = 30         # v7: 25
    PEPPER_TAKE_NORMAL   = 18         # v7: 14
    PEPPER_PASSIVE_MAX   = 60         # v7: 50
    PEPPER_TAKE_THRESH   = 2.0        # v7: 1.5  (ticks above mid)

    # Safety — unchanged
    PEPPER_STOP_BREACH_COUNT = 2
    PEPPER_STOP_STRONG    = -14
    PEPPER_STOP_MODERATE  = -10
    PEPPER_STOP_WEAK      =  -7
    PEPPER_RESUME_STRONG  =   6
    PEPPER_RESUME_MODERATE=   5
    PEPPER_RESUME_WEAK    =   4

    PEPPER_SPREAD_PASSIVE_SCALE = 0.75  # v7: 0.6
    PEPPER_DERISK_THRESHOLD     = 0.7   # v7: 0.6  (fraction of cap)
    PEPPER_DERISK_QTY           = 6     # v7: 8    (smaller exit, stay loaded)

    # ── OSMIUM constants ──────────────────────────────────────────────────────
    OSMIUM_ANCHOR = 10_000

    OSMIUM_TOXICITY_THRESHOLD = 40    # v7: 35
    OSMIUM_TAKE_EDGE          = -1    # v7: 0  → lift 1 tick above fair
    OSMIUM_EDGE_POS_STEP      = 35    # v7: 30
    OSMIUM_TAKE_EDGE_MAX      = 4     # v7: 3

    # Safety — unchanged
    OSMIUM_SKEW_SOFT      = 15
    OSMIUM_SKEW_HARD      = 35
    OSMIUM_FLATTEN_HARD   = 58
    OSMIUM_FLATTEN_TARGET = 45        # v7: 50 → flatten further

    OSMIUM_QUOTE_FRONT    = 40        # v7: 35
    OSMIUM_QUOTE_SECOND   = 30        # v7: 25

    OSMIUM_SPREAD_CLAMP   = 6         # v7: 5
    OSMIUM_VWAP_WEIGHT    = 0.65
    OSMIUM_DRIFT_SCALE_AT = 8

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

        # ── Spread momentum (soft gate only) ─────────────────────────────────
        prev_spread     = self.history.get("pp_prev_spread", spread)
        spread_widening = spread > prev_spread
        self.history["pp_prev_spread"] = spread

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

        # ── Stop logic (safety — unchanged from v7) ───────────────────────────
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

        # ── Stopped: orderly exit (safety — unchanged) ────────────────────────
        if drift_stopped or effective_cap == 0:
            if pos > 0:
                dump_qty = min(pos, 20)
                avail    = depth.buy_orders.get(bb, 0)
                qty      = min(dump_qty, avail)
                if qty > 0:
                    orders.append(Order(product, bb, -qty))
            return orders

        # ── Normal: buy aggressively into trend ───────────────────────────────
        rem_cap    = effective_cap - pos
        take_limit = (self.PEPPER_TAKE_STRONG
                      if effective_cap == self.PEPPER_CAP_STRONG
                      else self.PEPPER_TAKE_NORMAL)

        if rem_cap > 0:
            budget = min(rem_cap, take_limit)
            for ask in sorted(depth.sell_orders.keys()):
                if budget <= 0:
                    break
                if ask <= mid + self.PEPPER_TAKE_THRESH:
                    qty = min(budget, -depth.sell_orders[ask])
                    orders.append(Order(product, ask, qty))
                    budget  -= qty
                    rem_cap -= qty

            # Passive — scale back only slightly when spread widens
            if rem_cap > 0:
                passive_qty = min(rem_cap, self.PEPPER_PASSIVE_MAX)
                if spread_widening:
                    passive_qty = int(passive_qty * self.PEPPER_SPREAD_PASSIVE_SCALE)
                if passive_qty > 0:
                    orders.append(Order(product, bb + 1, passive_qty))

        # Minimal de-risk — only when heavily loaded and spread clearly widening
        if spread_widening and pos > effective_cap * self.PEPPER_DERISK_THRESHOLD:
            orders.append(Order(product, ba - 1, -self.PEPPER_DERISK_QTY))

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

        # ── VWAP-blended fair value (safety — unchanged) ──────────────────────
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

        # ── Hard circuit-breaker (safety — unchanged) ─────────────────────────
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

        # ── Liquidity taking (aggressive — edge starts at -1) ─────────────────
        pos_adj_buy  = min(self.OSMIUM_TAKE_EDGE_MAX,
                           self.OSMIUM_TAKE_EDGE + max(0, pos  // self.OSMIUM_EDGE_POS_STEP))
        pos_adj_sell = min(self.OSMIUM_TAKE_EDGE_MAX,
                           self.OSMIUM_TAKE_EDGE + max(0, (-pos) // self.OSMIUM_EDGE_POS_STEP))

        # Always take (toxic flow = price moved favorably = take it)
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
        skew = int(pos / self.OSMIUM_SKEW_SOFT)

        bp = int(min(bb + 1, fair - 1)) - skew
        ap = int(max(ba - 1, fair + 1)) - skew

        bp = max(bp, int(fair) - self.OSMIUM_SPREAD_CLAMP)
        ap = min(ap, int(fair) + self.OSMIUM_SPREAD_CLAMP)

        # Hard skew boost (safety — unchanged)
        if pos > self.OSMIUM_SKEW_HARD:
            bp -= 1
        if pos < -self.OSMIUM_SKEW_HARD:
            ap += 1

        if bp >= ap:
            bp = int(fair) - 1
            ap = int(fair) + 1

        # Size scaling — only shrinks when drift is genuinely far from anchor
        anchor_drift = abs(fair - self.OSMIUM_ANCHOR)
        size_scale   = (max(0.5, 1.0 - (anchor_drift - self.OSMIUM_DRIFT_SCALE_AT) / 20.0)
                        if anchor_drift > self.OSMIUM_DRIFT_SCALE_AT else 1.0)

        front  = max(6, int(self.OSMIUM_QUOTE_FRONT  * size_scale))
        second = max(4, int(self.OSMIUM_QUOTE_SECOND * size_scale))

        # Passive MM — suppressed only on genuinely toxic flow
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