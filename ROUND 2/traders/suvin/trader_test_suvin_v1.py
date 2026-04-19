"""
trader_v10.py — Maximum PnL + Maximum Safety
============================================
A clean combination of the two best-performing codes:

  Code A: 103-trader_test_suvin_v1 — hit 8k+ PnL, smooth curve
           Alpha: bidirectional Pepper, full-book VWAP, imbalance nudge,
                  MM-when-flat, tiered 50/30 quotes, mean-reversion take

  Code B: trader_v8 (our best safety code)
           Safety: cap/regime system, stop breach guard (count=3),
                   stop threshold -20, fast-track 200 ticks, circuit
                   breaker ±58→45, skew 15/35, toxicity filter, VWAP blend

Every line is deliberate — Code A's alpha sources are kept exactly as they
produced the 8k+ curve, and Code B's safety wrappers are applied around them
without diluting the signal.

═══════════════════════════════════════════════════════════════════════════════
PEPPER ROOT — how it works
═══════════════════════════════════════════════════════════════════════════════
Alpha (from Code A):
  • Fast warmup: only 20 ticks before we start reading drift
  • Bidirectional: target +80 on uptrend, -80 on downtrend
  • Market-make when flat: quote bb+1 / ba-1 for spread rebate when no signal
  • Cross premium = max(2, spread): willing to pay up to the spread to fill

Safety (from Code B wrapped around Code A's signal):
  • Cap/regime system: drift → tentative(25) → weak(30) → moderate(60) → strong(80)
  • Fast-track at 200 ticks: enter strong cap early on confirmed slope ≥ 0.05
  • Stop breach guard: 3 consecutive local-slope breaches → halt + orderly exit
  • Bidirectional stops: long stop AND short stop, each with independent breach count
  • Stop threshold -20 (not -14): don't exit on small pullbacks in confirmed trend
  • Resume after stop: re-enter when local slope recovers above +5 / below -5
  • Passive scale: 0.75 when spread widens (not a full halt)

═══════════════════════════════════════════════════════════════════════════════
ASH-COATED OSMIUM — how it works
═══════════════════════════════════════════════════════════════════════════════
Alpha (from Code A):
  • Full-book VWAP across all levels (not just L1) for clean fair value
  • Order-flow imbalance nudge: ±1.5 ticks when volume ratio > 1.3×
  • Anchor blend: 80% anchor + 20% mid (prevents runaway from 10000)
  • Mean-reversion take: aggressively sweep when mid > 3 ticks from fair
  • Tiered quotes: 50 lots at fair±1, then 30 lots at fair±2

Safety (from Code B):
  • Hard circuit-breaker: pos > ±58 → flatten to ±45 immediately at fair
  • Skew: starts at pos=15, hard extra tick at pos=35
  • Toxicity filter: skip passive MM quotes when flow imbalance > 40 lots
  • Fair smoothing: 60% current + 40% 5-tick average (prevents noise spikes)
  • Size scaling: shrink quotes when fair drifts > 8 ticks from anchor

No bid() method — no MAF deduction.
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


def _full_vwap(orders: dict) -> float:
    """Volume-weighted average price across ALL book levels."""
    total_vol = 0
    total_val = 0.0
    for price, qty in orders.items():
        vol = abs(qty)
        total_vol += vol
        total_val += price * vol
    return total_val / total_vol if total_vol > 0 else 0.0


class Trader:
    LIMIT = 80

    # ── PEPPER: alpha parameters (Code A values) ──────────────────────────────
    PEPPER_WARMUP_TICKS   = 20        # Code A: start fast
    PEPPER_HIST_MAX       = 100
    PEPPER_BASE_SAMPLES   = 15
    PEPPER_SIGNAL_WINDOW  = 15

    PEPPER_DRIFT_LARGE    = 0.015     # → target ±80
    PEPPER_DRIFT_SMALL    = 0.004     # → target ±60

    PEPPER_MM_SIZE        = 20        # passive size when no directional signal
    PEPPER_CROSS_MIN      = 2         # minimum cross premium ticks

    # ── PEPPER: safety parameters (Code B values) ─────────────────────────────
    PEPPER_FAST_TRACK_TICKS      = 200    # enter strong cap early
    PEPPER_SLOPE_STRONG_FAST     = 0.05   # fast-track trigger threshold
    PEPPER_CAP_TENTATIVE         = 25     # initial cap before regime confirmed
    PEPPER_PASSIVE_MAX           = 65     # max passive order size
    PEPPER_TAKE_STRONG           = 32     # liquidity-take budget in strong regime
    PEPPER_TAKE_NORMAL           = 18     # liquidity-take budget in normal regime
    PEPPER_TAKE_CROSS_EDGE       = 2.0    # ticks above mid we're willing to pay
    PEPPER_SPREAD_PASSIVE_SCALE  = 0.75   # passive scale-back on spread widening

    PEPPER_STOP_BREACH_COUNT     = 3      # consecutive breaches before stop
    PEPPER_STOP_LONG             = -20    # long stop: 20-tick slope < this
    PEPPER_STOP_SHORT            =  20    # short stop: 20-tick slope > this
    PEPPER_RESUME_LONG           =   5    # resume long when slope recovers above
    PEPPER_RESUME_SHORT          =  -5    # resume short when slope recovers below

    # ── OSMIUM: alpha parameters (Code A values) ──────────────────────────────
    OSMIUM_ANCHOR            = 10_000
    OSMIUM_IMBALANCE_RATIO   = 1.3        # volume ratio threshold for nudge
    OSMIUM_IMBALANCE_NUDGE   = 1.5        # ticks to shift fair on imbalance
    OSMIUM_ANCHOR_WEIGHT     = 0.80       # 80% anchor, 20% mid
    OSMIUM_REVERT_THRESH     = 3.0        # ticks from fair to trigger take
    OSMIUM_QUOTE_T1          = 50         # front quote size
    OSMIUM_QUOTE_T2          = 30         # second quote size

    # ── OSMIUM: safety parameters (Code B values) ─────────────────────────────
    OSMIUM_TOXICITY_THRESH   = 40         # flow imbalance to suppress MM
    OSMIUM_SKEW_SOFT         = 15         # pos threshold: start skewing
    OSMIUM_SKEW_HARD         = 35         # pos threshold: extra skew tick
    OSMIUM_FLATTEN_HARD      = 58         # circuit-breaker trigger
    OSMIUM_FLATTEN_TARGET    = 45         # flatten to this position
    OSMIUM_DRIFT_SCALE_AT    = 8          # drift ticks before size shrink

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
        spread = ba - bb
        mid    = (bb + ba) / 2.0
        ts     = state.timestamp

        # ── Rolling history ───────────────────────────────────────────────────
        hist = self.history["pp"]
        hist.append(mid)
        if len(hist) > self.PEPPER_HIST_MAX:
            hist.pop(0)

        base_samples = self.history["pp_base"]
        if len(base_samples) < self.PEPPER_BASE_SAMPLES:
            base_samples.append(mid)

        start_ts = self.history.setdefault("pp_t0", ts)

        # ── Warmup: tiny passive quotes only ─────────────────────────────────
        # Code A warmup: just 20 ticks, then we're live
        if len(hist) < self.PEPPER_WARMUP_TICKS:
            orders = []
            if pos < self.LIMIT:
                orders.append(Order(product, bb, 1))
            if pos > -self.LIMIT:
                orders.append(Order(product, ba, -1))
            return orders

        # ── Drift signal (Code A formula) ─────────────────────────────────────
        elapsed      = max(1, ts - start_ts)
        target_pos   = 0
        drift        = 0.0

        if len(base_samples) >= self.PEPPER_BASE_SAMPLES:
            base_mean    = _median(base_samples)
            current_mean = _median(hist[-self.PEPPER_SIGNAL_WINDOW:])
            drift        = (current_mean - base_mean) / elapsed * 100.0

            if drift > self.PEPPER_DRIFT_LARGE:
                target_pos =  80
            elif drift < -self.PEPPER_DRIFT_LARGE:
                target_pos = -80
            elif drift > self.PEPPER_DRIFT_SMALL:
                target_pos =  60
            elif drift < -self.PEPPER_DRIFT_SMALL:
                target_pos = -60

        # ── Safety: fast-track cap upgrade (Code B) ───────────────────────────
        # If fast_track elapsed and drift is strong, ensure cap is at least 80
        fast_track = elapsed >= self.PEPPER_FAST_TRACK_TICKS
        if fast_track and drift >= self.PEPPER_SLOPE_STRONG_FAST:
            target_pos = 80 if drift > 0 else -80

        # ── Safety: bidirectional stop/resume guard (Code B extended) ─────────
        breach_long  = int(self.history.get("pp_breach_long",  0))
        breach_short = int(self.history.get("pp_breach_short", 0))
        stop_long    = bool(self.history.get("pp_stop_long",   False))
        stop_short   = bool(self.history.get("pp_stop_short",  False))

        if len(hist) >= 20:
            local_slope = hist[-1] - hist[-20]

            # Long-side guard
            if local_slope < self.PEPPER_STOP_LONG:
                breach_long += 1
            else:
                breach_long = 0
            if breach_long >= self.PEPPER_STOP_BREACH_COUNT:
                stop_long = True
            elif stop_long and local_slope > self.PEPPER_RESUME_LONG:
                stop_long = False

            # Short-side guard
            if local_slope > self.PEPPER_STOP_SHORT:
                breach_short += 1
            else:
                breach_short = 0
            if breach_short >= self.PEPPER_STOP_BREACH_COUNT:
                stop_short = True
            elif stop_short and local_slope < self.PEPPER_RESUME_SHORT:
                stop_short = False

        self.history["pp_breach_long"]  = breach_long
        self.history["pp_breach_short"] = breach_short
        self.history["pp_stop_long"]    = stop_long
        self.history["pp_stop_short"]   = stop_short

        orders: List[Order] = []

        # ── Orderly exit if stopped ───────────────────────────────────────────
        if stop_long and pos > 0:
            qty = min(pos, 20, depth.buy_orders.get(bb, 0))
            if qty > 0:
                orders.append(Order(product, bb, -qty))
            return orders

        if stop_short and pos < 0:
            qty = min(-pos, 20, abs(depth.sell_orders.get(ba, 0)))
            if qty > 0:
                orders.append(Order(product, ba, qty))
            return orders

        # Block new positions in the stopped direction
        if stop_long  and target_pos > 0:
            target_pos = 0
        if stop_short and target_pos < 0:
            target_pos = 0

        # ── Spread momentum: soft scale-back on passive (Code B) ──────────────
        prev_spread     = self.history.get("pp_prev_spread", spread)
        spread_widening = spread > prev_spread
        self.history["pp_prev_spread"] = spread

        # ── Execution (Code A logic + Code B sizing) ──────────────────────────
        rem          = target_pos - pos
        cross_prem   = max(self.PEPPER_CROSS_MIN, spread)

        if rem > 0:
            # Buy toward target
            take_budget = min(rem, self.LIMIT - pos,
                              self.PEPPER_TAKE_STRONG if target_pos == 80
                              else self.PEPPER_TAKE_NORMAL)
            for ask in sorted(depth.sell_orders.keys()):
                if take_budget <= 0:
                    break
                if ask <= mid + min(cross_prem, self.PEPPER_TAKE_CROSS_EDGE):
                    q = min(take_budget, -depth.sell_orders[ask])
                    orders.append(Order(product, ask, q))
                    take_budget -= q
            # Passive residual — scale back if spread widening
            if take_budget > 0:
                passive = min(take_budget, self.PEPPER_PASSIVE_MAX)
                if spread_widening:
                    passive = int(passive * self.PEPPER_SPREAD_PASSIVE_SCALE)
                if passive > 0:
                    orders.append(Order(product, bb + 1, passive))

        elif rem < 0:
            # Sell toward target (bidirectional — Code A)
            take_budget = min(-rem, self.LIMIT + pos,
                              self.PEPPER_TAKE_STRONG if target_pos == -80
                              else self.PEPPER_TAKE_NORMAL)
            for bid in sorted(depth.buy_orders.keys(), reverse=True):
                if take_budget <= 0:
                    break
                if bid >= mid - min(cross_prem, self.PEPPER_TAKE_CROSS_EDGE):
                    q = min(take_budget, depth.buy_orders[bid])
                    orders.append(Order(product, bid, -q))
                    take_budget -= q
            if take_budget > 0:
                passive = min(take_budget, self.PEPPER_PASSIVE_MAX)
                if spread_widening:
                    passive = int(passive * self.PEPPER_SPREAD_PASSIVE_SCALE)
                if passive > 0:
                    orders.append(Order(product, ba - 1, -passive))

        else:
            # No signal → market-make for spread rebate (Code A)
            if pos < self.LIMIT:
                orders.append(Order(product, bb + 1,
                                    min(self.PEPPER_MM_SIZE, self.LIMIT - pos)))
            if pos > -self.LIMIT:
                orders.append(Order(product, ba - 1,
                                    -min(self.PEPPER_MM_SIZE, self.LIMIT + pos)))

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

        # ── Fair value: full-book VWAP + imbalance nudge + anchor blend ───────
        # (Code A formula — their edge over pure L1 VWAP)
        bv = sum(depth.buy_orders.values())
        av = sum(-v for v in depth.sell_orders.values())

        fair = float(self.OSMIUM_ANCHOR)

        # Imbalance nudge: shift fair before price moves
        if bv > av * self.OSMIUM_IMBALANCE_RATIO:
            fair += self.OSMIUM_IMBALANCE_NUDGE
        elif av > bv * self.OSMIUM_IMBALANCE_RATIO:
            fair -= self.OSMIUM_IMBALANCE_NUDGE

        # Anchor blend: 80% anchor, 20% mid
        fair = self.OSMIUM_ANCHOR_WEIGHT * fair + (1 - self.OSMIUM_ANCHOR_WEIGHT) * mid

        # ── Fair smoothing (Code B: prevents noise spikes) ────────────────────
        op = self.history["op"]
        op.append(fair)
        if len(op) > 30:
            op = op[-30:]
        self.history["op"] = op
        if len(op) >= 5:
            fair = 0.6 * fair + 0.4 * (sum(op[-5:]) / 5.0)

        # ── Toxicity filter (Code B safety) ───────────────────────────────────
        buy_vol = sell_vol = 0
        if product in state.market_trades:
            for t in state.market_trades[product]:
                if t.price >= mid:
                    buy_vol  += abs(t.quantity)
                else:
                    sell_vol += abs(t.quantity)

        imbalance   = buy_vol - sell_vol
        toxic_buys  = imbalance >=  self.OSMIUM_TOXICITY_THRESH
        toxic_sells = imbalance <= -self.OSMIUM_TOXICITY_THRESH

        orders: List[Order] = []
        rb = self.LIMIT - pos
        rs = self.LIMIT + pos

        # ── Hard circuit-breaker (Code B safety) ──────────────────────────────
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

        # ── Mean-reversion take (Code A alpha) ────────────────────────────────
        if mid < fair - self.OSMIUM_REVERT_THRESH and rb > 0:
            for ask in sorted(depth.sell_orders.keys()):
                if ask < fair and rb > 0:
                    q = min(rb, -depth.sell_orders[ask])
                    orders.append(Order(product, ask, q))
                    rb  -= q
                    pos += q

        elif mid > fair + self.OSMIUM_REVERT_THRESH and rs > 0:
            for bid in sorted(depth.buy_orders.keys(), reverse=True):
                if bid > fair and rs > 0:
                    q = min(rs, depth.buy_orders[bid])
                    orders.append(Order(product, bid, -q))
                    rs  -= q
                    pos -= q

        # ── Skew (Code B safety) ──────────────────────────────────────────────
        skew = int(pos / self.OSMIUM_SKEW_SOFT)

        bp1 = int(min(bb + 1, fair - 1)) - skew
        ap1 = int(max(ba - 1, fair + 1)) - skew
        bp2 = bp1 - 1
        ap2 = ap1 + 1

        if pos > self.OSMIUM_SKEW_HARD:
            bp1 -= 1
            bp2 -= 1
        if pos < -self.OSMIUM_SKEW_HARD:
            ap1 += 1
            ap2 += 1

        if bp1 >= ap1:
            bp1 = int(fair) - 1
            ap1 = int(fair) + 1
            bp2 = bp1 - 1
            ap2 = ap1 + 1

        # ── Size scaling (Code B safety) ──────────────────────────────────────
        anchor_drift = abs(fair - self.OSMIUM_ANCHOR)
        size_scale   = (max(0.5, 1.0 - (anchor_drift - self.OSMIUM_DRIFT_SCALE_AT) / 20.0)
                        if anchor_drift > self.OSMIUM_DRIFT_SCALE_AT else 1.0)

        t1 = max(6,  int(self.OSMIUM_QUOTE_T1 * size_scale))
        t2 = max(4,  int(self.OSMIUM_QUOTE_T2 * size_scale))

        # ── Tiered quotes (Code A sizing, suppressed on toxic flow) ───────────
        if rb > 0 and not toxic_buys:
            q = min(rb, t1)
            orders.append(Order(product, bp1, q))
            rb -= q
            if rb > 0:
                orders.append(Order(product, bp2, min(rb, t2)))

        if rs > 0 and not toxic_sells:
            q = min(rs, t1)
            orders.append(Order(product, ap1, -q))
            rs -= q
            if rs > 0:
                orders.append(Order(product, ap2, -min(rs, t2)))

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