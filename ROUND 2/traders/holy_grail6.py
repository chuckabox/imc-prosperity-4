"""
holy_grail6.py — Round 2: EMA-driven trend detection, NO MAF bid
================================================================
Builds on Holy_grailllll.py (v8) but replaces the median-window SMA
regime detection with an Exponential Moving Average (EMA) crossover
signal. EMAs weight recent mids more heavily and react faster to
regime changes without the aliasing artefacts of a fixed 15-tick
median window.

Key changes vs v8:

MARKET ACCESS FEE
-----------------
• bid() returns 0. We do NOT bid for extra market access, so we also
  roll back every constant that was tuned to exploit the extra 25%
  quote flow (PEPPER_PASSIVE_MAX, OSMIUM_QUOTE_FRONT/SECOND).

PEPPER — EMA crossover drift signal
-----------------------------------
• Maintain a fast EMA (alpha=0.10, tau~10 ticks) and a slow EMA
  (alpha=0.02, tau~50 ticks) of the mid.
• drift_signal = (fast_ema - slow_ema). Under a steady drift d/tick,
  fast_ema - slow_ema -> d * (1/a_slow - 1/a_fast) = 40*d. So a
  measured PEPPER drift of +0.1/tick produces ~+4.0 in the signal.
• Thresholds are scaled accordingly:
    STRONG_FAST=2.0, STRONG=1.5, MODERATE=0.4, WEAK=-0.4
• Warmup is shortened: EMAs stabilise far faster than a 15-sample
  median base, so PEPPER_WARMUP_TICKS: 1200 -> 800.
• Local stop uses EMA slope (fast_ema change over last 20 ticks)
  rather than raw mid delta — smoother, fewer false breaches.
• PEPPER_PASSIVE_MAX: 65 -> 50 (no MAF bonus flow to amplify).

OSMIUM — EMA-smoothed fair value
--------------------------------
• Replace the 5-period simple average blend with an EMA (alpha=0.25,
  tau~4 ticks). Same smoothing character, but continuously updated
  and not sensitive to the exact window boundary.
• OSMIUM_QUOTE_FRONT:  38 -> 35 (no MAF bonus flow).
• OSMIUM_QUOTE_SECOND: 28 -> 25.
"""

import json
from typing import Dict, List

from datamodel import Order, OrderDepth, TradingState, Symbol


class Trader:
    LIMIT = 80

    # ── PEPPER constants ──────────────────────────────────────────────────────
    PEPPER_WARMUP_TICKS      = 800   # v8: 1200 — EMA stabilises faster
    PEPPER_FAST_TRACK_TICKS  = 200

    # EMA smoothing factors
    PEPPER_EMA_FAST_ALPHA    = 0.10  # tau ~10 ticks
    PEPPER_EMA_SLOW_ALPHA    = 0.02  # tau ~50 ticks

    # Drift thresholds on (fast_ema - slow_ema). Under d/tick drift,
    # signal converges to ~40*d.
    PEPPER_DRIFT_STRONG_FAST = 2.0   # ~ +0.05/tick
    PEPPER_DRIFT_STRONG      = 1.5   # ~ +0.04/tick
    PEPPER_DRIFT_MODERATE    = 0.4   # ~ +0.01/tick
    PEPPER_DRIFT_WEAK        = -0.4  # ~ -0.01/tick

    PEPPER_CAP_STRONG    = 80
    PEPPER_CAP_MODERATE  = 60
    PEPPER_CAP_WEAK      = 30
    PEPPER_CAP_NEGATIVE  =  0
    PEPPER_CAP_TENTATIVE = 25

    PEPPER_TAKE_STRONG   = 32
    PEPPER_TAKE_NORMAL   = 18
    PEPPER_PASSIVE_MAX   = 50        # v8: 65 — no MAF bonus flow

    PEPPER_STOP_BREACH_COUNT = 3
    PEPPER_STOP_STRONG    = -20
    PEPPER_STOP_MODERATE  = -10
    PEPPER_STOP_WEAK      =  -7
    PEPPER_RESUME_STRONG  =   5
    PEPPER_RESUME_MODERATE=   5
    PEPPER_RESUME_WEAK    =   4

    PEPPER_SPREAD_PASSIVE_SCALE = 0.75
    PEPPER_TAKE_CROSS_EDGE      = 2.0

    # ── OSMIUM constants ──────────────────────────────────────────────────────
    OSMIUM_ANCHOR = 10_000

    OSMIUM_TOXICITY_THRESHOLD = 35
    OSMIUM_TAKE_EDGE      = 0
    OSMIUM_EDGE_POS_STEP  = 30
    OSMIUM_TAKE_EDGE_MAX  = 3

    OSMIUM_SKEW_SOFT      = 15
    OSMIUM_SKEW_HARD      = 35
    OSMIUM_FLATTEN_HARD   = 58
    OSMIUM_FLATTEN_TARGET = 50

    OSMIUM_QUOTE_FRONT    = 35       # v8: 38 — no MAF bonus flow
    OSMIUM_QUOTE_SECOND   = 25       # v8: 28

    OSMIUM_SPREAD_CLAMP   = 5
    OSMIUM_VWAP_WEIGHT    = 0.65
    OSMIUM_DRIFT_SCALE_AT = 8

    OSMIUM_EMA_ALPHA      = 0.25     # replaces v8 5-period SMA blend

    def __init__(self):
        self.history: Dict = {}

    # ─────────────────────────────────────────────────────────────────────────
    # MARKET ACCESS FEE  (Round 2 only; ignored in other rounds)
    # ─────────────────────────────────────────────────────────────────────────
    def bid(self) -> int:
        # No bid: we don't want extra market access in this variant.
        return 0

    # ─────────────────────────────────────────────────────────────────────────
    def _load_state(self, state: TradingState):
        if state.traderData:
            try:
                self.history = json.loads(state.traderData)
            except Exception:
                self.history = {}
        self.history.setdefault("op_ema", None)

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

        # ── EMA update ───────────────────────────────────────────────────────
        fast_ema = self.history.get("pp_ema_fast")
        slow_ema = self.history.get("pp_ema_slow")
        if fast_ema is None:
            fast_ema = mid
        if slow_ema is None:
            slow_ema = mid
        a_fast = self.PEPPER_EMA_FAST_ALPHA
        a_slow = self.PEPPER_EMA_SLOW_ALPHA
        fast_ema = a_fast * mid + (1.0 - a_fast) * fast_ema
        slow_ema = a_slow * mid + (1.0 - a_slow) * slow_ema
        self.history["pp_ema_fast"] = fast_ema
        self.history["pp_ema_slow"] = slow_ema

        # Lagged fast EMA, 20 ticks back, for local stop logic
        lag_buf = self.history.get("pp_ema_lag", [])
        lag_buf.append(fast_ema)
        if len(lag_buf) > 21:
            lag_buf = lag_buf[-21:]
        self.history["pp_ema_lag"] = lag_buf

        # ── Spread momentum (soft gate only) ─────────────────────────────────
        prev_spread     = self.history.get("pp_prev_spread", spread)
        spread_widening = spread > prev_spread
        self.history["pp_prev_spread"] = spread

        # ── Regime / cap detection ───────────────────────────────────────────
        start_ts   = self.history.setdefault("pp_t0", ts)
        elapsed    = ts - start_ts
        warmed_up  = elapsed >= self.PEPPER_WARMUP_TICKS
        fast_track = elapsed >= self.PEPPER_FAST_TRACK_TICKS

        cap = self.history.get("pp_cap", None)

        drift = fast_ema - slow_ema  # EMA crossover signal, ~ 40 * drift_per_tick

        if fast_track and drift >= self.PEPPER_DRIFT_STRONG_FAST:
            new_cap = self.PEPPER_CAP_STRONG
        elif warmed_up:
            if drift > self.PEPPER_DRIFT_STRONG:
                new_cap = self.PEPPER_CAP_STRONG
            elif drift > self.PEPPER_DRIFT_MODERATE:
                new_cap = self.PEPPER_CAP_MODERATE
            elif drift > self.PEPPER_DRIFT_WEAK:
                new_cap = self.PEPPER_CAP_WEAK
            else:
                new_cap = self.PEPPER_CAP_NEGATIVE
        else:
            new_cap = None

        if cap is None:
            cap = new_cap if new_cap is not None else self.PEPPER_CAP_TENTATIVE
        elif new_cap is not None and new_cap > cap:
            cap = new_cap
        elif warmed_up and new_cap is not None and new_cap < cap:
            cap = new_cap

        self.history["pp_cap"] = cap
        effective_cap = cap if cap is not None else self.PEPPER_CAP_TENTATIVE

        # ── Stop logic (EMA slope over last 20 ticks) ────────────────────────
        if effective_cap == self.PEPPER_CAP_STRONG:
            stop_th, resume_th = self.PEPPER_STOP_STRONG, self.PEPPER_RESUME_STRONG
        elif effective_cap == self.PEPPER_CAP_WEAK:
            stop_th, resume_th = self.PEPPER_STOP_WEAK, self.PEPPER_RESUME_WEAK
        else:
            stop_th, resume_th = self.PEPPER_STOP_MODERATE, self.PEPPER_RESUME_MODERATE

        breach_count  = int(self.history.get("pp_breach", 0))
        drift_stopped = bool(self.history.get("pp_stopped", False))

        if len(lag_buf) >= 21:
            local_slope = lag_buf[-1] - lag_buf[0]  # fast_ema 20 ticks ago
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
                dump_qty = min(pos, 20)
                avail    = depth.buy_orders.get(bb, 0)
                qty      = min(dump_qty, avail)
                if qty > 0:
                    orders.append(Order(product, bb, -qty))
            return orders

        # ── Normal: buy into trend ───────────────────────────────────────────
        rem_cap    = effective_cap - pos
        take_limit = self.PEPPER_TAKE_STRONG if effective_cap == self.PEPPER_CAP_STRONG else self.PEPPER_TAKE_NORMAL

        if rem_cap > 0:
            budget = min(rem_cap, take_limit)
            for ask in sorted(depth.sell_orders.keys()):
                if budget <= 0:
                    break
                if ask <= mid + self.PEPPER_TAKE_CROSS_EDGE:
                    qty = min(budget, -depth.sell_orders[ask])
                    orders.append(Order(product, ask, qty))
                    budget  -= qty
                    rem_cap -= qty

            if rem_cap > 0:
                passive_qty = min(rem_cap, self.PEPPER_PASSIVE_MAX)
                if spread_widening:
                    passive_qty = int(passive_qty * self.PEPPER_SPREAD_PASSIVE_SCALE)
                if passive_qty > 0:
                    orders.append(Order(product, bb + 1, passive_qty))

        # Light de-risk when spread widens and well loaded
        if spread_widening and pos > effective_cap * 0.6:
            sell_qty = min(pos, 8)
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

        # ── VWAP-blended fair value ──────────────────────────────────────────
        bv1       = depth.buy_orders[bb]
        av1       = -depth.sell_orders[ba]
        total_vol = bv1 + av1
        vwap_mid  = (bb * av1 + ba * bv1) / total_vol if total_vol > 0 else mid

        fair = self.OSMIUM_VWAP_WEIGHT * vwap_mid + (1 - self.OSMIUM_VWAP_WEIGHT) * self.OSMIUM_ANCHOR

        # ── EMA smoothing of fair value (replaces v8's 5-period SMA blend) ───
        op_ema = self.history.get("op_ema")
        if op_ema is None:
            op_ema = fair
        op_ema = self.OSMIUM_EMA_ALPHA * fair + (1.0 - self.OSMIUM_EMA_ALPHA) * op_ema
        self.history["op_ema"] = op_ema
        fair = 0.6 * fair + 0.4 * op_ema

        # ── OBI micro-bias ───────────────────────────────────────────────────
        if total_vol > 0:
            obi = (bv1 - av1) / total_vol
            if obi >= 0.3 or obi <= -0.3:
                fair += 0.6 * (1.0 if obi > 0 else -1.0)

        # ── Toxicity filter ──────────────────────────────────────────────────
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

        # ── Hard circuit-breaker ─────────────────────────────────────────────
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

        # ── Liquidity taking ─────────────────────────────────────────────────
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

        # ── Market making ────────────────────────────────────────────────────
        skew = int(pos / self.OSMIUM_SKEW_SOFT)

        bp = int(min(bb + 1, fair - 1)) - skew
        ap = int(max(ba - 1, fair + 1)) - skew

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
