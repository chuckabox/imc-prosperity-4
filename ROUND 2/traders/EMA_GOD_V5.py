"""
trader_v4.py — "Position First, Nothing Else" rewrite
=======================================================
Deep analysis of logs revealed the actual problem is not what we thought.
 
THE REAL FINDINGS (from analysing the 7286-run):
 
1. AVERAGE PEPPER POSITION = 6.8 units (not 80!)
   - Final pos=80, entry avg≈13015, PnL=6808 → avg pos = 6808/(10000*0.1) = 6.8
   - The algo gets to 80 late in the day. Most drift is missed.
   - Stop events at t=3000, t=10800, t=14000 cause position dumps + slow rebuilds
   - Each stop costs ~150 PnL (direct loss + rebuild lag)
 
2. PEPPER FILLS ARE RARE — key constraint
   - Spread = 15 ticks. Ask at mid+7.5. Our passive bid at bb+1 is 14 ticks below ask.
   - We CAN cross: when ask ≤ mid + cross_edge. 
   - With edge=3: only 3% of ticks are crossable. 
   - With edge=8 (half-spread): 70.6% of ticks crossable!
   - By crossing at half-spread price, we fill fast at fair cost.
 
3. OSMIUM MECHANICS ARE CORRECT but quotes could be tighter
   - We quote bp=9999, ap=10001 when market is 10000/10016
   - Our ask at 10001 IS inside the spread → gets hit regularly
   - IMPROVEMENT: add flow-direction detection for size scaling
 
4. END-OF-DAY OSMIUM UNWIND is the other drag
   - OSMIUM ends at pos=-76 needing to cover
   - A gentle unwind in the last 1000 ticks prevents forced liquidation cost
 
CREATIVE SOLUTION — Three new ideas:
 
IDEA A: "Half-spread aggression" for PEPPER entry
  Standard take_edge = half of typical spread ≈ 7 ticks.
  This means we ALWAYS cross immediately (70% of ticks have ask ≤ mid+8).
  Cost: we pay 7 ticks per fill vs ~15 ticks if we waited passively.
  But drift recovers 7 ticks in just 70 run() calls (7000 timestamps).
  MASSIVE win: position goes from 6.8 average to ~80 from tick 5 onwards.
 
IDEA B: "Inertia stop" — exponential moving stop, not absolute
  Instead of dumping on a fixed price threshold, use a trailing stop
  based on the ENTRY PRICE. Only stop if price drops more than X below
  the best mid seen since entry. This prevents the noisy t=3000 stops.
 
IDEA C: "OSMIUM day-end ladder"
  Start at t=95000: reduce OSMIUM quotes on adverse side by half.
  By t=98000: go to zero size on adverse side.
  This creates a natural unwind without crossing the spread.
 
MAF bid: 4000 (unchanged)
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
 
    # ── PEPPER ───────────────────────────────────────────────────────────────
    # Key insight: take_edge = 8 ticks → crosses happen 70%+ of ticks
    # This means we fill up to cap within the first 3-4 run() calls
    # Cost per fill: 8 ticks. Payback: 8 / 0.1 = 80 ticks = 8000 timestamps
    # Remaining 92000 timestamps at full 80-unit position = massive gain
 
    PEP_TAKE_EDGE      = 8     # half-spread aggression: cross if ask ≤ mid + 8
    PEP_TAKE_STRONG    = 80    # take everything in one shot (entire cap)
    PEP_PASSIVE_BID_OFFSET = 2 # bid at bb+2 when spread wide (beat other passives)
    PEP_CAP            = 80
 
    # "Inertia stop" — only stop if price drops far below our peak since entry
    # This avoids the noise-triggered stops at t=3000, t=10800, t=14000
    PEP_STOP_DRAWDOWN  = 80    # stop if unrealized loss exceeds 80 ticks from peak
                               # (peak-based trailing stop, very hard to trigger)
    PEP_STOP_BREACH    = 3     # consecutive breaches needed
 
    # ── OSMIUM ───────────────────────────────────────────────────────────────
    OSM_ANCHOR         = 10_000
    OSM_ANCHOR_WEIGHT  = 0.85
    OSM_FAIR_EMA_ALPHA = 2.0 / 51.0
    OSM_ATR_ALPHA      = 2.0 / 21.0
    OSM_ATR_MIN        = 1.0
    OSM_ATR_MAX        = 4.0
 
    # OBI thresholds for flow detection
    OSM_OBI_STRONG     = 0.5   # strong directional flow → trade WITH it
    OSM_OBI_WEAK       = 0.3   # weak bias → just shift fair
 
    OSM_TOXICITY       = 30
    OSM_EDGE_POS_STEP  = 25
    OSM_TAKE_EDGE_MAX  = 2
 
    OSM_SKEW_SOFT      = 12
    OSM_SKEW_HARD      = 30
    OSM_FLATTEN_HARD   = 55
    OSM_FLATTEN_TARGET = 45
 
    # Quote sizes
    OSM_QUOTE_FRONT    = 45
    OSM_QUOTE_SECOND   = 35
 
    # Drift watchdog (tight — data shows max deviation = 20)
    OSM_DRIFT_THRESHOLD   = 15
    OSM_DRIFT_STREAK_TRIP = 50
    OSM_DRIFT_FLATTEN_TARGET = 30
 
    # End-of-day OSMIUM unwind (ladder down adverse-side quotes)
    OSM_UNWIND_START_TS = 95_000   # start reducing at t=95000
    OSM_UNWIND_END_TS   = 99_000   # fully wound down by t=99000
 
    def __init__(self):
        self.history: Dict = {}
 
    def bid(self) -> int:
        return 4_000
 
    # ─────────────────────────────────────────────────────────────────────────
    def _load(self, state: TradingState) -> None:
        if state.traderData:
            try:
                self.history = json.loads(state.traderData)
            except Exception:
                self.history = {}
        else:
            self.history = {}
 
        # PEPPER state
        self.history.setdefault("pp_peak_mid", None)   # highest mid seen since entry
        self.history.setdefault("pp_entry_avg", None)  # avg entry price
        self.history.setdefault("pp_breach", 0)
        self.history.setdefault("pp_stopped", False)
        self.history.setdefault("pp_stop_until", -1)   # stop cooldown
 
        # OSMIUM state
        self.history.setdefault("osm_last_mid", None)
        self.history.setdefault("osm_vwap_ema", None)
        self.history.setdefault("osm_atr_ema", 1.0)
        self.history.setdefault("osm_drift_streak", 0)
 
    def _save(self) -> str:
        return json.dumps(self.history, separators=(",", ":"))
 
    # ─────────────────────────────────────────────────────────────────────────
    @staticmethod
    def _best_bid(od: OrderDepth):
        if not od.buy_orders: return None, 0
        p = max(od.buy_orders.keys())
        return p, od.buy_orders[p]
 
    @staticmethod
    def _best_ask(od: OrderDepth):
        if not od.sell_orders: return None, 0
        p = min(od.sell_orders.keys())
        return p, -od.sell_orders[p]
 
    @staticmethod
    def _second_bid(od, best):
        ks = sorted([p for p in od.buy_orders if p != best], reverse=True)
        return (ks[0], od.buy_orders[ks[0]]) if ks else (None, 0)
 
    @staticmethod
    def _second_ask(od, best):
        ks = sorted([p for p in od.sell_orders if p != best])
        return (ks[0], -od.sell_orders[ks[0]]) if ks else (None, 0)
 
    @staticmethod
    def _ema(prev, x, alpha):
        return float(x) if prev is None else prev + alpha * (x - prev)
 
    # ─────────────────────────────────────────────────────────────────────────
    # PEPPER — "Position First" strategy
    # Goal: be at pos=80 within the first 5 run() calls, then HOLD.
    # Use half-spread aggression to cross immediately.
    # Use inertia-based trailing stop (not absolute threshold).
    # ─────────────────────────────────────────────────────────────────────────
    def _pepper(self, state: TradingState, od: OrderDepth) -> List[Order]:
        orders: List[Order] = []
        pos = state.position.get(PEPPER, 0)
        ts  = state.timestamp
 
        bb, bbv = self._best_bid(od)
        ba, bav = self._best_ask(od)
        if bb is None or ba is None:
            return orders
 
        mid    = (bb + ba) / 2.0
        spread = ba - bb
 
        # ── Inertia trailing stop ─────────────────────────────────────────────
        # Track the highest mid we've seen while long.
        # Only stop if mid drops PEP_STOP_DRAWDOWN below that peak.
        # This NEVER fires during normal +0.001/tick uptrend.
        # Only fires in a true regime reversal (price drops 80 ticks from peak).
 
        peak = self.history["pp_peak_mid"]
        entry_avg = self.history["pp_entry_avg"]
 
        if pos > 0:
            # Update peak
            if peak is None or mid > peak:
                peak = mid
                self.history["pp_peak_mid"] = peak
            # Trailing drawdown
            drawdown_from_peak = peak - mid
            if drawdown_from_peak > self.PEP_STOP_DRAWDOWN:
                self.history["pp_breach"] = self.history["pp_breach"] + 1
            else:
                self.history["pp_breach"] = 0
            if self.history["pp_breach"] >= self.PEP_STOP_BREACH:
                self.history["pp_stopped"] = True
                self.history["pp_stop_until"] = ts + 2000
                self.history["pp_breach"] = 0
                self.history["pp_peak_mid"] = None
                # Dump all at best bid
                if bb is not None and pos > 0:
                    orders.append(Order(PEPPER, int(bb), -pos))
                return orders
        else:
            # Reset peak when flat
            self.history["pp_peak_mid"] = None
 
        # Stop cooldown
        stopped = self.history["pp_stopped"]
        stop_until = self.history["pp_stop_until"]
 
        if stopped:
            if ts < stop_until:
                # Still in cooldown — wait
                return orders
            else:
                # Cooldown expired — reset
                self.history["pp_stopped"] = False
                self.history["pp_breach"] = 0
 
        # ── Position building: half-spread aggression ─────────────────────────
        # The drift is ALWAYS positive. Best action: be at cap immediately.
        # Cross if ask ≤ mid + PEP_TAKE_EDGE (8 ticks = half of typical spread).
        # This fires ~70% of ticks, so we fill within a handful of calls.
 
        room = self.PEP_CAP - pos
 
        if room > 0:
            # Aggressive cross — sweep available ask volume up to mid + edge
            remaining = min(room, self.PEP_TAKE_STRONG)
            for ask_px in sorted(od.sell_orders.keys()):
                if remaining <= 0:
                    break
                if ask_px <= mid + self.PEP_TAKE_EDGE:
                    qty = min(remaining, -od.sell_orders[ask_px])
                    if qty > 0:
                        orders.append(Order(PEPPER, ask_px, qty))
                        remaining -= qty
 
            # If still room (cross edge not met this tick), post aggressive passive
            # Bid at bb + PEP_PASSIVE_BID_OFFSET to be at top of passive queue
            if remaining > 0 and bb is not None:
                px = min(int(bb + self.PEP_PASSIVE_BID_OFFSET), int(ba - 1))
                if px > bb:
                    orders.append(Order(PEPPER, px, remaining))
                else:
                    # Fallback: just join best bid
                    orders.append(Order(PEPPER, int(bb + 1), remaining))
 
        # Update entry avg (blended, for stop reference only)
        # Simple approximation: track as mid at time of first fill
        if pos == 0 and room > 0 and len(orders) > 0:
            self.history["pp_entry_avg"] = mid
 
        return orders
 
    # ─────────────────────────────────────────────────────────────────────────
    # OSMIUM — tighter quotes + flow detection + day-end ladder
    # ─────────────────────────────────────────────────────────────────────────
    def _osmium(self, state: TradingState, od: OrderDepth) -> List[Order]:
        orders: List[Order] = []
        pos = state.position.get(OSMIUM, 0)
        ts  = state.timestamp
 
        bb, bbv = self._best_bid(od)
        ba, bav = self._best_ask(od)
        if bb is None or ba is None:
            return orders
 
        mid = (bb + ba) / 2.0
 
        # VWAP from top-2
        sb, sbv = self._second_bid(od, bb)
        sa, sav = self._second_ask(od, ba)
        num = bb * bbv + ba * bav
        den = bbv + bav
        if sb is not None: num += sb * sbv; den += sbv
        if sa is not None: num += sa * sav; den += sav
        vwap = num / den if den > 0 else mid
 
        # Update EMAs
        self.history["osm_vwap_ema"] = self._ema(
            self.history["osm_vwap_ema"], vwap, self.OSM_FAIR_EMA_ALPHA)
        last = self.history["osm_last_mid"]
        if last is not None:
            self.history["osm_atr_ema"] = self._ema(
                self.history["osm_atr_ema"], abs(mid - last), self.OSM_ATR_ALPHA)
        self.history["osm_last_mid"] = mid
 
        atr      = max(self.OSM_ATR_MIN, min(self.OSM_ATR_MAX, self.history["osm_atr_ema"]))
        vwap_ema = self.history["osm_vwap_ema"] or vwap
 
        # Drift watchdog
        drift  = vwap_ema - self.OSM_ANCHOR
        streak = self.history["osm_drift_streak"]
        if abs(drift) > self.OSM_DRIFT_THRESHOLD:
            streak = min(streak + 1, 1000)
        else:
            streak = max(streak - 2, 0)
        self.history["osm_drift_streak"] = streak
        in_drift = streak >= self.OSM_DRIFT_STREAK_TRIP
 
        # Adaptive anchor weight
        if in_drift:
            anchor_w = 0.0
        elif abs(drift) > 6.0:
            t = min(1.0, (abs(drift) - 6.0) / (self.OSM_DRIFT_THRESHOLD - 6.0))
            anchor_w = self.OSM_ANCHOR_WEIGHT * (1.0 - t) + 0.55 * t
        else:
            anchor_w = self.OSM_ANCHOR_WEIGHT
 
        fair = anchor_w * self.OSM_ANCHOR + (1.0 - anchor_w) * vwap_ema
 
        # OBI flow detection — creative enhancement
        total_vol = bbv + bav
        obi = (bbv - bav) / total_vol if total_vol > 0 else 0.0
 
        # Strong OBI: trade WITH the flow (lean quotes, add size on favoured side)
        # Weak OBI: just shift fair value
        if abs(obi) >= self.OSM_OBI_STRONG:
            # Strong flow: shift fair AND scale quotes
            fair += 0.8 * (1.0 if obi > 0 else -1.0)
            obi_strong = True
        elif abs(obi) >= self.OSM_OBI_WEAK:
            fair += 0.6 * (1.0 if obi > 0 else -1.0)
            obi_strong = False
        else:
            obi_strong = False
 
        # Toxicity
        toxic_buys  = bbv >= self.OSM_TOXICITY
        toxic_sells = bav >= self.OSM_TOXICITY
 
        # Take edge
        edge_from_pos = min(self.OSM_TAKE_EDGE_MAX, abs(pos) // self.OSM_EDGE_POS_STEP)
        take_edge = self.OSM_TAKE_EDGE_MAX - edge_from_pos
 
        rb = self.LIMIT - pos
        rs = self.LIMIT + pos
 
        # Cross-take on mispriced levels
        if not toxic_sells and ba <= fair - take_edge and rb > 0:
            q = min(rb, bav, 25)
            if q > 0:
                orders.append(Order(OSMIUM, int(ba), q))
                rb -= q; pos += q
 
        if not toxic_buys and bb >= fair + take_edge and rs > 0:
            q = min(rs, bbv, 25)
            if q > 0:
                orders.append(Order(OSMIUM, int(bb), -q))
                rs -= q; pos -= q
 
        # Hard flatten
        flatten_target = self.OSM_DRIFT_FLATTEN_TARGET if in_drift else self.OSM_FLATTEN_TARGET
        flatten_hard   = flatten_target + 15
 
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
 
        # ── Day-end unwind ladder ─────────────────────────────────────────────
        # Creative: instead of holding OSMIUM position to the end (paying forced
        # liquidation price), gradually reduce adverse-side quote size from t=95000.
        # This naturally unwinds the position while still making MM income
        # on the favoured side.
        unwind_factor = 1.0
        if ts >= self.OSM_UNWIND_START_TS:
            progress = min(1.0, (ts - self.OSM_UNWIND_START_TS) /
                          (self.OSM_UNWIND_END_TS - self.OSM_UNWIND_START_TS))
            unwind_factor = 1.0 - progress  # goes from 1.0 → 0.0
 
        # ── Adaptive quotes (ATR-scaled half-spread) ──────────────────────────
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
 
        suppress_buy  = in_drift and drift < 0
        suppress_sell = in_drift and drift > 0
 
        front  = self.OSM_QUOTE_FRONT
        second = self.OSM_QUOTE_SECOND
        if in_drift:
            front  = max(3, front  // 2)
            second = max(2, second // 2)
 
        # Apply unwind factor: if pos < 0 (short), we want to reduce sell quotes
        # to stop adding to the short. Scale down sell side.
        # If pos > 0 (long), scale down buy side.
        buy_scale  = unwind_factor if pos > 0 else 1.0
        sell_scale = unwind_factor if pos < 0 else 1.0
 
        # Strong OBI boost: add extra size on the OBI-aligned side
        if obi_strong and obi > 0:
            sell_scale = min(sell_scale * 1.5, 1.5)  # more selling when buyers are active
        elif obi_strong and obi < 0:
            buy_scale  = min(buy_scale * 1.5, 1.5)   # more buying when sellers are active
 
        if rb > 0 and not toxic_buys and not suppress_buy:
            q = min(rb, int(front * buy_scale))
            if q > 0:
                orders.append(Order(OSMIUM, bp, q))
                rb -= q
                if rb > 0:
                    q2 = min(rb, int(second * buy_scale))
                    if q2 > 0:
                        orders.append(Order(OSMIUM, bp - 1, q2))
 
        if rs > 0 and not toxic_sells and not suppress_sell:
            q = min(rs, int(front * sell_scale))
            if q > 0:
                orders.append(Order(OSMIUM, ap, -q))
                rs -= q
                if rs > 0:
                    q2 = min(rs, int(second * sell_scale))
                    if q2 > 0:
                        orders.append(Order(OSMIUM, ap + 1, -q2))
 
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