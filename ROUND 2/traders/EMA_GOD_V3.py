"""
trader_ema_v3.py — EMA hybrid (best of v8 + EMA-v2)
=====================================================
Root-cause fixes from log analysis:
 
PEPPER problems in v2:
  • EMA-of-returns slow alpha (2/501) takes ~500 ticks to converge.
    By then the market has already drifted. Threshold 0.0008 combined with
    slow convergence meant regime almost never fired "strong_up".
  • Result: PEPPER P&L = 0 for the entire run.
  Fix: Revert PEPPER to v8's proven median-drift regime detector (fast,
  reliable by tick 200) with all the v8 aggressive sizing numbers.
 
OSMIUM problems in v2:
  • Drift watchdog: streak of 200 ticks ABOVE 15-unit drift before tripping.
    In all four bad episodes the drift built over 100+ ticks before being
    caught. Reducing to 120 ticks catches it sooner.
  • The watchdog FLATTEN_TARGET is 25 — too small. When the algo is at +58
    and the drift trips, flattening to 25 takes many ticks at the capped
    quote size. Increase to 35 so the flatten happens faster.
  • OSM_ANCHOR_WEIGHT = 0.70 fights strong drift for too long. When drift
    watchdog IS NOT tripped, the anchor keeps quoting against the move.
    Add a "soft drift" adjustment: if |vwap_ema - anchor| > 8 ticks (but
    below watchdog threshold), tilt the anchor weight toward vwap_ema.
  • ATR-adaptive half-spread is good — keep it.
  • OBI bias: proven alpha — keep it.
  • Quote sizes (FRONT=38, SECOND=28) from v8 — keep them.
 
MAF bid: 4,000 — unchanged.
"""
 
import json
from typing import Dict, List
 
from datamodel import Order, OrderDepth, TradingState, Symbol
 
 
PEPPER = "INTARIAN_PEPPER_ROOT"
OSMIUM = "ASH_COATED_OSMIUM"
 
 
def _median(vals: list) -> float:
    n = len(vals)
    if n == 0:
        return 0.0
    s = sorted(vals)
    mid = n // 2
    return float(s[mid]) if n % 2 == 1 else (s[mid - 1] + s[mid]) / 2.0
 
 
class Trader:
    LIMIT = 80
 
    # ── PEPPER (v8 regime detector — proven, fast) ───────────────────────────
    PEP_WARMUP_TICKS     = 1200
    PEP_FAST_TRACK_TICKS = 200
 
    # Slope thresholds (median-drift over elapsed ticks * 100)
    PEP_SLOPE_STRONG_FAST = 0.05
    PEP_SLOPE_STRONG      = 0.04
    PEP_SLOPE_MODERATE    = 0.01
    PEP_SLOPE_WEAK        = -0.01
 
    # Position caps
    PEP_CAP_STRONG    = 80
    PEP_CAP_MODERATE  = 60
    PEP_CAP_WEAK      = 30
    PEP_CAP_NEGATIVE  =  0
    PEP_CAP_TENTATIVE = 25
 
    # Sizing (v8 — proven on historical data)
    PEP_TAKE_STRONG  = 32
    PEP_TAKE_NORMAL  = 18
    PEP_PASSIVE_MAX  = 65
 
    # Stop-loss
    PEP_STOP_BREACH_COUNT = 3
    PEP_STOP_STRONG    = -20
    PEP_STOP_MODERATE  = -10
    PEP_STOP_WEAK      =  -7
    PEP_RESUME_STRONG  =   5
    PEP_RESUME_MODERATE=   5
    PEP_RESUME_WEAK    =   4
 
    PEP_SPREAD_PASSIVE_SCALE = 0.75
    PEP_TAKE_CROSS_EDGE      = 2.0
 
    # ── OSMIUM (EMA-v2 core + tighter watchdog + soft-drift tilt) ────────────
    OSM_ANCHOR         = 10_000
    OSM_ANCHOR_WEIGHT  = 0.70       # base weight; softened when drift detected
    OSM_FAIR_EMA_ALPHA = 2.0 / 101.0
    OSM_ATR_ALPHA      = 2.0 / 31.0
    OSM_ATR_MIN        = 1.0
    OSM_ATR_MAX        = 5.0
 
    # Soft drift: |vwap_ema - anchor| > this → tilt anchor weight down
    OSM_SOFT_DRIFT_THRESHOLD = 8.0
    OSM_SOFT_DRIFT_MIN_WEIGHT = 0.45  # floor for anchor weight in soft-drift
 
    # Watchdog thresholds (tightened from v2: 200 → 120)
    OSM_DRIFT_THRESHOLD   = 15
    OSM_DRIFT_STREAK_TRIP = 120      # v2 was 200 — catches drift 40% sooner
    OSM_DRIFT_FLATTEN_TARGET = 35    # v2 was 25 — faster de-risk
 
    OSM_TOXICITY       = 35
    OSM_EDGE_POS_STEP  = 30
    OSM_TAKE_EDGE_MAX  = 3
 
    OSM_SKEW_SOFT      = 15
    OSM_SKEW_HARD      = 35
    OSM_FLATTEN_HARD   = 58
    OSM_FLATTEN_TARGET = 50
 
    OSM_QUOTE_FRONT    = 38
    OSM_QUOTE_SECOND   = 28
 
    def __init__(self):
        self.history: Dict = {}
 
    # ─────────────────────────────────────────────────────────────────────────
    def bid(self) -> int:
        return 4_000
 
    # ─────────────────────────────────────────────────────────────────────────
    # Persistence
    # ─────────────────────────────────────────────────────────────────────────
    def _load(self, state: TradingState) -> None:
        if state.traderData:
            try:
                self.history = json.loads(state.traderData)
            except Exception:
                self.history = {}
        else:
            self.history = {}
 
        # PEPPER state (v8 style)
        self.history.setdefault("pp", [])
        self.history.setdefault("pp_base", [])
        self.history.setdefault("pp_t0", None)
        self.history.setdefault("pp_cap", None)
        self.history.setdefault("pp_breach", 0)
        self.history.setdefault("pp_stopped", False)
        self.history.setdefault("pp_prev_spread", None)
 
        # OSMIUM state (EMA-v2 style)
        self.history.setdefault("osm_last_mid", None)
        self.history.setdefault("osm_vwap_ema", None)
        self.history.setdefault("osm_atr_ema", 1.0)
        self.history.setdefault("osm_drift_streak", 0)
 
    def _save(self) -> str:
        return json.dumps(self.history, separators=(",", ":"))
 
    # ─────────────────────────────────────────────────────────────────────────
    # Book helpers
    # ─────────────────────────────────────────────────────────────────────────
    @staticmethod
    def _best_bid(od: OrderDepth):
        if not od.buy_orders:
            return None, 0
        bp = max(od.buy_orders.keys())
        return bp, od.buy_orders[bp]
 
    @staticmethod
    def _best_ask(od: OrderDepth):
        if not od.sell_orders:
            return None, 0
        ap = min(od.sell_orders.keys())
        return ap, -od.sell_orders[ap]
 
    @staticmethod
    def _second_bid(od: OrderDepth, best):
        ks = sorted([p for p in od.buy_orders.keys() if p != best], reverse=True)
        if not ks:
            return None, 0
        return ks[0], od.buy_orders[ks[0]]
 
    @staticmethod
    def _second_ask(od: OrderDepth, best):
        ks = sorted([p for p in od.sell_orders.keys() if p != best])
        if not ks:
            return None, 0
        return ks[0], -od.sell_orders[ks[0]]
 
    @staticmethod
    def _ema(prev, x, alpha):
        if prev is None:
            return float(x)
        return prev + alpha * (x - prev)
 
    # ─────────────────────────────────────────────────────────────────────────
    # PEPPER — v8 median-drift regime (the one that actually works)
    # ─────────────────────────────────────────────────────────────────────────
    def _pepper(self, state: TradingState, od: OrderDepth) -> List[Order]:
        orders: List[Order] = []
        pos = state.position.get(PEPPER, 0)
 
        bb, bbv = self._best_bid(od)
        ba, bav = self._best_ask(od)
        if bb is None or ba is None:
            return orders
 
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
            self.history["pp_base"] = base_samples
 
        if self.history["pp_t0"] is None:
            self.history["pp_t0"] = ts
        start_ts = self.history["pp_t0"]
 
        # ── Spread momentum ───────────────────────────────────────────────────
        prev_spread = self.history["pp_prev_spread"]
        if prev_spread is None:
            prev_spread = spread
        spread_widening = spread > prev_spread
        self.history["pp_prev_spread"] = spread
 
        # ── Regime detection (v8 median-drift) ───────────────────────────────
        elapsed   = ts - start_ts
        warmed_up = elapsed >= self.PEP_WARMUP_TICKS
        fast_track = elapsed >= self.PEP_FAST_TRACK_TICKS
 
        cap = self.history["pp_cap"]
 
        if len(base_samples) >= 15 and len(hist) >= 15:
            base_mean    = _median(base_samples)
            current_mean = _median(hist[-15:])
            dt    = max(1, elapsed)
            drift = (current_mean - base_mean) / dt * 100.0
 
            if fast_track and drift >= self.PEP_SLOPE_STRONG_FAST:
                new_cap = self.PEP_CAP_STRONG
            elif warmed_up:
                if drift > self.PEP_SLOPE_STRONG:
                    new_cap = self.PEP_CAP_STRONG
                elif drift > self.PEP_SLOPE_MODERATE:
                    new_cap = self.PEP_CAP_MODERATE
                elif drift > self.PEP_SLOPE_WEAK:
                    new_cap = self.PEP_CAP_WEAK
                else:
                    new_cap = self.PEP_CAP_NEGATIVE
            else:
                new_cap = cap
 
            if cap is None:
                cap = new_cap if new_cap is not None else self.PEP_CAP_TENTATIVE
            elif new_cap is not None and new_cap > cap:
                cap = new_cap
            elif warmed_up and new_cap is not None and new_cap < cap:
                cap = new_cap
 
            self.history["pp_cap"] = cap
 
        effective_cap = cap if cap is not None else self.PEP_CAP_TENTATIVE
 
        # ── Stop logic ────────────────────────────────────────────────────────
        if effective_cap == self.PEP_CAP_STRONG:
            stop_th, resume_th = self.PEP_STOP_STRONG, self.PEP_RESUME_STRONG
        elif effective_cap == self.PEP_CAP_WEAK:
            stop_th, resume_th = self.PEP_STOP_WEAK, self.PEP_RESUME_WEAK
        else:
            stop_th, resume_th = self.PEP_STOP_MODERATE, self.PEP_RESUME_MODERATE
 
        breach_count  = int(self.history["pp_breach"])
        drift_stopped = bool(self.history["pp_stopped"])
 
        if len(hist) >= 20:
            local_slope = hist[-1] - hist[-20]
            if local_slope < stop_th:
                breach_count += 1
            else:
                breach_count = 0
            if breach_count >= self.PEP_STOP_BREACH_COUNT:
                drift_stopped = True
            elif drift_stopped and local_slope > resume_th:
                drift_stopped = False
 
        self.history["pp_breach"]  = breach_count
        self.history["pp_stopped"] = drift_stopped
 
        # ── Stopped: orderly exit ─────────────────────────────────────────────
        if drift_stopped or effective_cap == 0:
            if pos > 0:
                dump_qty = min(pos, 20)
                qty = min(dump_qty, bbv)
                if qty > 0:
                    orders.append(Order(PEPPER, int(bb), -qty))
            elif pos < 0:
                dump_qty = min(-pos, 20)
                qty = min(dump_qty, bav)
                if qty > 0:
                    orders.append(Order(PEPPER, int(ba), qty))
            return orders
 
        # ── Active: buy into trend ────────────────────────────────────────────
        rem_cap    = effective_cap - pos
        take_limit = (self.PEP_TAKE_STRONG if effective_cap == self.PEP_CAP_STRONG
                      else self.PEP_TAKE_NORMAL)
 
        if rem_cap > 0:
            budget = min(rem_cap, take_limit)
            for ask in sorted(od.sell_orders.keys()):
                if budget <= 0:
                    break
                if ask <= mid + self.PEP_TAKE_CROSS_EDGE:
                    qty = min(budget, -od.sell_orders[ask])
                    if qty > 0:
                        orders.append(Order(PEPPER, ask, qty))
                        budget  -= qty
                        rem_cap -= qty
 
            if rem_cap > 0:
                passive_qty = min(rem_cap, self.PEP_PASSIVE_MAX)
                if spread_widening:
                    passive_qty = int(passive_qty * self.PEP_SPREAD_PASSIVE_SCALE)
                if passive_qty > 0:
                    orders.append(Order(PEPPER, int(bb + 1), passive_qty))
 
        # Light de-risk on spread widening when heavily loaded
        if spread_widening and pos > effective_cap * 0.6:
            sell_qty = min(pos, 8)
            if bav > 0:
                orders.append(Order(PEPPER, int(ba - 1), -sell_qty))
 
        return orders
 
    # ─────────────────────────────────────────────────────────────────────────
    # OSMIUM — EMA fair + tighter watchdog + soft-drift anchor tilt
    # ─────────────────────────────────────────────────────────────────────────
    def _osmium(self, state: TradingState, od: OrderDepth) -> List[Order]:
        orders: List[Order] = []
        pos = state.position.get(OSMIUM, 0)
 
        bb, bbv = self._best_bid(od)
        ba, bav = self._best_ask(od)
        if bb is None or ba is None:
            return orders
 
        mid = (bb + ba) / 2.0
 
        # VWAP from top-2 levels
        sb, sbv = self._second_bid(od, bb)
        sa, sav = self._second_ask(od, ba)
        num = bb * bbv + ba * bav
        den = bbv + bav
        if sb is not None:
            num += sb * sbv; den += sbv
        if sa is not None:
            num += sa * sav; den += sav
        vwap = num / den if den > 0 else mid
 
        # Update EMAs
        self.history["osm_vwap_ema"] = self._ema(
            self.history["osm_vwap_ema"], vwap, self.OSM_FAIR_EMA_ALPHA)
        last = self.history["osm_last_mid"]
        if last is not None:
            self.history["osm_atr_ema"] = self._ema(
                self.history["osm_atr_ema"], abs(mid - last), self.OSM_ATR_ALPHA)
        self.history["osm_last_mid"] = mid
 
        atr = max(self.OSM_ATR_MIN, min(self.OSM_ATR_MAX, self.history["osm_atr_ema"]))
        vwap_ema = self.history["osm_vwap_ema"] or vwap
 
        # ── Drift watchdog (tightened: trip at 120 ticks, not 200) ───────────
        drift     = vwap_ema - self.OSM_ANCHOR
        streak    = self.history["osm_drift_streak"]
        if abs(drift) > self.OSM_DRIFT_THRESHOLD:
            streak = min(streak + 1, 1000)
        else:
            streak = max(streak - 2, 0)
        self.history["osm_drift_streak"] = streak
        in_drift = streak >= self.OSM_DRIFT_STREAK_TRIP
 
        # ── Fair value with adaptive anchor weight ────────────────────────────
        if in_drift:
            # Full abandon — track the move, don't fight it
            anchor_w = 0.0
        elif abs(drift) > self.OSM_SOFT_DRIFT_THRESHOLD:
            # Soft drift: linearly reduce anchor weight from 0.70 toward floor
            # as drift moves from soft threshold toward hard threshold
            t = min(1.0, (abs(drift) - self.OSM_SOFT_DRIFT_THRESHOLD) /
                    (self.OSM_DRIFT_THRESHOLD - self.OSM_SOFT_DRIFT_THRESHOLD))
            anchor_w = self.OSM_ANCHOR_WEIGHT * (1.0 - t) + self.OSM_SOFT_DRIFT_MIN_WEIGHT * t
        else:
            anchor_w = self.OSM_ANCHOR_WEIGHT
 
        fair = anchor_w * self.OSM_ANCHOR + (1.0 - anchor_w) * vwap_ema
 
        # OBI micro-bias (proven alpha)
        total_vol = bbv + bav
        obi = (bbv - bav) / total_vol if total_vol > 0 else 0.0
        if abs(obi) >= 0.3:
            fair += 0.6 * (1.0 if obi > 0 else -1.0)
 
        # Toxicity filter
        toxic_buys  = bbv >= self.OSM_TOXICITY
        toxic_sells = bav >= self.OSM_TOXICITY
 
        # Position-indexed take edge
        edge_from_pos = min(self.OSM_TAKE_EDGE_MAX,
                            abs(pos) // self.OSM_EDGE_POS_STEP)
        take_edge = self.OSM_TAKE_EDGE_MAX - edge_from_pos
 
        rb = self.LIMIT - pos
        rs = self.LIMIT + pos
 
        # ── Cross-take on mispriced levels ────────────────────────────────────
        if not toxic_sells and ba <= fair - take_edge and rb > 0:
            q = min(rb, bav, 30)
            if q > 0:
                orders.append(Order(OSMIUM, int(ba), q))
                rb -= q; pos += q
 
        if not toxic_buys and bb >= fair + take_edge and rs > 0:
            q = min(rs, bbv, 30)
            if q > 0:
                orders.append(Order(OSMIUM, int(bb), -q))
                rs -= q; pos -= q
 
        # ── Hard flatten ──────────────────────────────────────────────────────
        # In drift mode, use a tighter flatten target so we de-risk faster
        flatten_target = self.OSM_DRIFT_FLATTEN_TARGET if in_drift else self.OSM_FLATTEN_TARGET
        flatten_hard   = flatten_target + 20  # keep hard threshold 20 above target
 
        if pos > flatten_hard and rs > 0:
            exit_px = bb if in_drift else int(round(fair))
            qty = min(pos - flatten_target + 5, rs)
            if qty > 0:
                orders.append(Order(OSMIUM, exit_px, -qty))
                rs -= qty; pos -= qty
        elif pos < -flatten_hard and rb > 0:
            exit_px = ba if in_drift else int(round(fair))
            qty = min(-pos - flatten_target + 5, rb)
            if qty > 0:
                orders.append(Order(OSMIUM, exit_px, qty))
                rb += qty; pos += qty
 
        # ── Adaptive quoting (ATR-scaled spread) ─────────────────────────────
        half_spread = max(1, int(round(0.4 * atr)))
        bp = int(round(fair - half_spread))
        ap = int(round(fair + half_spread))
 
        if bp >= ba: bp = ba - 1
        if ap <= bb: ap = bb + 1
 
        # Inventory skew
        if pos > self.OSM_SKEW_HARD:
            bp -= 1; ap -= 1
        elif pos > self.OSM_SKEW_SOFT:
            ap = max(bb + 1, ap - 1)
        elif pos < -self.OSM_SKEW_HARD:
            bp += 1; ap += 1
        elif pos < -self.OSM_SKEW_SOFT:
            bp = min(ba - 1, bp + 1)
 
        # In drift mode: suppress the side that goes against us, halve sizes
        suppress_buy  = in_drift and drift < 0
        suppress_sell = in_drift and drift > 0
 
        front  = self.OSM_QUOTE_FRONT
        second = self.OSM_QUOTE_SECOND
        if in_drift:
            front  = max(3, front  // 2)
            second = max(2, second // 2)
 
        if rb > 0 and not toxic_buys and not suppress_buy:
            q = min(rb, front)
            orders.append(Order(OSMIUM, bp, q))
            rb -= q
            if rb > 0:
                orders.append(Order(OSMIUM, bp - 1, min(rb, second)))
 
        if rs > 0 and not toxic_sells and not suppress_sell:
            q = min(rs, front)
            orders.append(Order(OSMIUM, ap, -q))
            rs -= q
            if rs > 0:
                orders.append(Order(OSMIUM, ap + 1, -min(rs, second)))
 
        return orders
 
    # ─────────────────────────────────────────────────────────────────────────
    def run(self, state: TradingState):
        self._load(state)
 
        result: Dict[Symbol, List[Order]] = {}
        for sym, od in state.order_depths.items():
            if sym == PEPPER:
                result[sym] = self._pepper(state, od)
            elif sym == OSMIUM:
                result[sym] = self._osmium(state, od)
 
        return result, 0, self._save()
 