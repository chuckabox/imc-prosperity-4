"""
trader_ema.py — EMA-driven (v2)
===============================
Total rewrite of the original EMA algo. The first attempt lost money because:

  • Pepper used Kaufman's Efficiency Ratio, which is near-zero on a slow
    clean drift dominated by tick noise. It almost never triggered STRONG,
    so the position never loaded near cap. Result: ~zero pepper PnL.
  • Osmium used the slow EMA as fair value, but 10,000 IS the true anchor.
    Using a drifting EMA as fair turned the MM into a trend-chaser that
    bought into the selling and vice versa.
  • All proven sizing / stop numbers from v8-v11 were discarded.

This rewrite keeps EMA as the *unifying* tool (that's the whole point of this
experiment) but applies it where it actually helps:

PEPPER — trend follower, regime detected by EMA of RETURNS
----------------------------------------------------------
  • slope = EMA(mid_t - mid_{t-1}, α=2/501)  (≈500-tick memory)
    On the historical data (drift = +0.001/tick), this converges to ~+0.001
    and is *extremely* stable — far cleaner than OLS slope or ER.
  • ribbon (fast EMA, mid EMA) used only for alignment confirmation:
    we only trust the slope sign if fast > mid (up) or fast < mid (down).
  • Sizing, stops, passive quoting: **lifted verbatim from v8**, which
    achieved 8,126 / day. No reason to reinvent what works.

OSMIUM — adaptive market maker anchored at 10,000
--------------------------------------------------
  • Fair = 0.70 * 10000 + 0.30 * EMA_slow(vwap_mid).  Anchor dominates
    (the true mean) but small EMA component tracks regime.
  • ATR_ema = EMA(|mid_t - mid_{t-1}|, α=2/31). Quote width scales with it
    instead of a fixed spread-clamp constant. Automatically tightens in
    calm markets, widens in vol.
  • OBI micro-bias (proven alpha): |OBI| >= 0.3 shifts fair ±0.6 tick.
  • Drift watchdog (from v13): if |vwap - anchor| > 15 for 200+ ticks,
    fall back to vwap-fair + suppress adverse side + early flatten.
    Never fires on real IMC data (|vwap-10000| stays < 5) but caps
    worst-case loss on synthetic drift scenarios from −27k → a few k.
  • Proven v8 MM geometry otherwise: quote front=38, second=28,
    flatten_hard=58, toxicity filter, cross-take with position-indexed edge.

MAF bid: 4,000  (realistic — ~8k/day gross, ~2k extra-flow EV).
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

    # ─── Pepper: EMA-of-returns based regime detection ─────────────────────
    PEP_WARMUP_TICKS   = 600      # need enough returns for EMA to converge
    PEP_FAST_TRACK     = 150      # after this, rely on ribbon alignment only
    PEP_RET_ALPHA_SLOW = 2.0 / 501.0   # slow slope estimator (period ~500)
    PEP_RET_ALPHA_FAST = 2.0 / 101.0   # faster responsiveness check

    PEP_RET_STRONG_UP      = 0.0008    # observed drift ≈ 0.001; threshold ~0.8x
    PEP_RET_MODERATE_UP    = 0.0003
    PEP_RET_WEAK_UP        = -0.0002
    # Mirrored implicitly for negative side.

    PEP_FAST_EMA_ALPHA = 2.0 / 21.0    # ribbon fast (period ~20)
    PEP_MID_EMA_ALPHA  = 2.0 / 81.0    # ribbon mid  (period ~80)
    PEP_RIBBON_MIN_DIFF = 0.15          # |fast-mid| must exceed this in ticks

    # Position caps by regime (same shape as v8)
    PEP_CAP_STRONG     = 80
    PEP_CAP_MODERATE   = 60
    PEP_CAP_WEAK       = 30
    PEP_CAP_NEGATIVE   = 0
    PEP_CAP_TENTATIVE  = 25

    # Take sizes & passive (v8 numbers — the proven ones)
    PEP_TAKE_STRONG    = 32
    PEP_TAKE_NORMAL    = 18
    PEP_PASSIVE_MAX    = 65

    # Stop-loss (v8)
    PEP_STOP_STRONG    = -20
    PEP_STOP_MODERATE  = -10
    PEP_STOP_WEAK      = -7
    PEP_STOP_BREACH    = 3
    PEP_RESUME_STRONG  = 5
    PEP_RESUME_MODERATE= 5
    PEP_RESUME_WEAK    = 4

    PEP_SPREAD_PASSIVE_SCALE = 0.75
    PEP_CROSS_EDGE     = 2.0

    # ─── Osmium: EMA-smoothed anchor + ATR + OBI + drift watchdog ──────────
    OSM_ANCHOR         = 10_000
    OSM_ANCHOR_WEIGHT  = 0.70           # how strongly we trust the 10k anchor
    OSM_FAIR_EMA_ALPHA = 2.0 / 101.0    # ~100-tick EMA of vwap
    OSM_ATR_ALPHA      = 2.0 / 31.0     # ~30-tick EMA of |Δmid|
    OSM_ATR_MIN        = 1.0
    OSM_ATR_MAX        = 5.0

    OSM_TOXICITY       = 35
    OSM_EDGE_POS_STEP  = 30
    OSM_TAKE_EDGE_MAX  = 3

    OSM_SKEW_SOFT      = 15
    OSM_SKEW_HARD      = 35
    OSM_FLATTEN_HARD   = 58
    OSM_FLATTEN_TARGET = 50

    OSM_QUOTE_FRONT    = 38
    OSM_QUOTE_SECOND   = 28

    # Drift watchdog (from v13) — critical safety net
    OSM_DRIFT_THRESHOLD   = 15
    OSM_DRIFT_STREAK_TRIP = 200
    OSM_DRIFT_FLATTEN     = 25

    def __init__(self):
        self.history: Dict = {}

    # ─────────────────────────────────────────────────────────────────────────
    def bid(self) -> int:
        # Gross PnL ~8k/day; extra-flow EV ~2k. 15k would be net-negative.
        # 4k is low enough to stay profitable if rejected but plausibly
        # inside top-50% of a blind auction.
        return 4_000

    # ─────────────────────────────────────────────────────────────────────────
    # Persistence helpers
    # ─────────────────────────────────────────────────────────────────────────
    def _load(self, state: TradingState) -> None:
        if state.traderData:
            try:
                self.history = json.loads(state.traderData)
            except Exception:
                self.history = {}
        else:
            self.history = {}

        # Pepper EMAs
        self.history.setdefault("pep_last_mid", None)
        self.history.setdefault("pep_ret_ema_slow", 0.0)
        self.history.setdefault("pep_ret_ema_fast", 0.0)
        self.history.setdefault("pep_fast_ema", None)
        self.history.setdefault("pep_mid_ema", None)
        self.history.setdefault("pep_tick", 0)
        self.history.setdefault("pep_entry_avg", 0.0)
        self.history.setdefault("pep_stop_until", -1)
        self.history.setdefault("pep_breach_count", 0)
        self.history.setdefault("pep_last_stop_regime", "none")
        # Osmium EMAs / watchdog
        self.history.setdefault("osm_last_mid", None)
        self.history.setdefault("osm_vwap_ema", None)
        self.history.setdefault("osm_atr_ema", 1.0)
        self.history.setdefault("osm_drift_streak", 0)

    def _save(self) -> str:
        return json.dumps(self.history, separators=(",", ":"))

    # ─────────────────────────────────────────────────────────────────────────
    # Low-level book helpers
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
        return ap, -od.sell_orders[ap]  # vol positive

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
        """Standard EMA step. If prev is None, initialise with x."""
        if prev is None:
            return float(x)
        return prev + alpha * (x - prev)

    # ─────────────────────────────────────────────────────────────────────────
    # PEPPER
    # ─────────────────────────────────────────────────────────────────────────
    def _pepper(self, state: TradingState, od: OrderDepth) -> List[Order]:
        orders: List[Order] = []
        pos = state.position.get(PEPPER, 0)

        bb, bbv = self._best_bid(od)
        ba, bav = self._best_ask(od)
        if bb is None or ba is None:
            return orders
        mid = (bb + ba) / 2.0
        spread = ba - bb

        # ---- Update EMAs ----
        last = self.history["pep_last_mid"]
        if last is not None:
            ret = mid - last
            self.history["pep_ret_ema_slow"] = self._ema(
                self.history["pep_ret_ema_slow"], ret, self.PEP_RET_ALPHA_SLOW)
            self.history["pep_ret_ema_fast"] = self._ema(
                self.history["pep_ret_ema_fast"], ret, self.PEP_RET_ALPHA_FAST)
        self.history["pep_last_mid"] = mid

        self.history["pep_fast_ema"] = self._ema(
            self.history["pep_fast_ema"], mid, self.PEP_FAST_EMA_ALPHA)
        self.history["pep_mid_ema"] = self._ema(
            self.history["pep_mid_ema"], mid, self.PEP_MID_EMA_ALPHA)

        tick = self.history["pep_tick"]
        self.history["pep_tick"] = tick + 1

        # ---- Regime from EMA of returns + ribbon alignment ----
        ret_slow = self.history["pep_ret_ema_slow"]
        fast_ema = self.history["pep_fast_ema"]
        mid_ema  = self.history["pep_mid_ema"]
        ribbon   = fast_ema - mid_ema

        # Direction from slow ret-EMA; confirmed by ribbon in same direction.
        if tick < self.PEP_FAST_TRACK:
            # Not enough history — stay cautious, no sizing.
            regime = "none"
            cap    = self.PEP_CAP_TENTATIVE
            desired_sign = 0
        else:
            if ret_slow >= self.PEP_RET_STRONG_UP and ribbon >= self.PEP_RIBBON_MIN_DIFF:
                regime, cap, desired_sign = "strong_up", self.PEP_CAP_STRONG, +1
            elif ret_slow >= self.PEP_RET_MODERATE_UP and ribbon >= 0:
                regime, cap, desired_sign = "mod_up", self.PEP_CAP_MODERATE, +1
            elif ret_slow >= self.PEP_RET_WEAK_UP:
                regime, cap, desired_sign = "weak_up", self.PEP_CAP_WEAK, +1
            elif ret_slow <= -self.PEP_RET_STRONG_UP and ribbon <= -self.PEP_RIBBON_MIN_DIFF:
                regime, cap, desired_sign = "strong_dn", self.PEP_CAP_STRONG, -1
            elif ret_slow <= -self.PEP_RET_MODERATE_UP and ribbon <= 0:
                regime, cap, desired_sign = "mod_dn", self.PEP_CAP_MODERATE, -1
            elif ret_slow <= -self.PEP_RET_WEAK_UP:
                regime, cap, desired_sign = "weak_dn", self.PEP_CAP_WEAK, -1
            else:
                regime, cap, desired_sign = "neutral", self.PEP_CAP_NEGATIVE, 0

        # ---- Track entry avg for P&L-based stop ----
        # We only maintain a rough running-average entry price; reset when pos
        # crosses zero. Good enough for stop-loss decisions.
        prev_pos = self.history.get("pep_prev_pos", 0)
        entry    = self.history["pep_entry_avg"]
        if pos == 0 or (prev_pos * pos) <= 0:
            entry = mid if pos != 0 else 0.0
        elif abs(pos) > abs(prev_pos):
            # Position grew — blend new fill into avg (approximated at mid).
            diff = abs(pos) - abs(prev_pos)
            entry = (abs(prev_pos) * entry + diff * mid) / abs(pos)
        self.history["pep_entry_avg"] = entry
        self.history["pep_prev_pos"] = pos

        # Per-unit P&L (positive = winning)
        unit_pnl = 0.0
        if pos > 0 and entry:
            unit_pnl = mid - entry
        elif pos < 0 and entry:
            unit_pnl = entry - mid

        # Regime-dependent stop threshold
        if regime.startswith("strong"):
            stop_thr = self.PEP_STOP_STRONG
        elif regime.startswith("mod"):
            stop_thr = self.PEP_STOP_MODERATE
        else:
            stop_thr = self.PEP_STOP_WEAK

        # Stop-loss logic
        stop_until = self.history["pep_stop_until"]
        breach = self.history["pep_breach_count"]

        if pos != 0 and unit_pnl < stop_thr:
            breach += 1
        else:
            breach = 0
        self.history["pep_breach_count"] = breach

        if breach >= self.PEP_STOP_BREACH and pos != 0:
            # Force-flatten at best-cross; suspend new entries briefly.
            if pos > 0:
                qty = min(pos, bbv if bbv > 0 else pos)
                if qty > 0:
                    orders.append(Order(PEPPER, int(bb), -qty))
            else:
                qty = min(-pos, bav if bav > 0 else -pos)
                if qty > 0:
                    orders.append(Order(PEPPER, int(ba), qty))
            resume = self.PEP_RESUME_STRONG if regime.startswith("strong") \
                   else self.PEP_RESUME_MODERATE if regime.startswith("mod") \
                   else self.PEP_RESUME_WEAK
            self.history["pep_stop_until"] = tick + resume
            self.history["pep_breach_count"] = 0
            self.history["pep_last_stop_regime"] = regime
            return orders

        if tick < stop_until:
            return orders  # cooling off

        if desired_sign == 0:
            # Neutral regime — unwind any position passively toward 0.
            if pos > 0 and bb is not None:
                orders.append(Order(PEPPER, int(bb), -min(pos, 20)))
            elif pos < 0 and ba is not None:
                orders.append(Order(PEPPER, int(ba), min(-pos, 20)))
            return orders

        # ---- Take aggressively (cross) when appropriate ----
        take_sz = self.PEP_TAKE_STRONG if regime.startswith("strong") \
                else self.PEP_TAKE_NORMAL

        if desired_sign > 0:
            # Want long. Cross the ask if it isn't too far above fair.
            proj_fair = fast_ema + 0.5 * ribbon
            if ba is not None and ba <= proj_fair + self.PEP_CROSS_EDGE:
                room = cap - pos
                if room > 0:
                    q = min(room, take_sz, bav)
                    if q > 0:
                        orders.append(Order(PEPPER, int(ba), q))
                        pos += q
        else:
            proj_fair = fast_ema + 0.5 * ribbon
            if bb is not None and bb >= proj_fair - self.PEP_CROSS_EDGE:
                room = cap + pos  # cap is magnitude; pos is negative → room = cap-(-pos)
                if room > 0:
                    q = min(room, take_sz, bbv)
                    if q > 0:
                        orders.append(Order(PEPPER, int(bb), -q))
                        pos -= q

        # ---- Passive quoting ----
        passive_scale = 1.0
        if spread >= 3:
            passive_scale *= self.PEP_SPREAD_PASSIVE_SCALE

        if desired_sign > 0:
            room = cap - pos
            if room > 0:
                q = min(room, int(self.PEP_PASSIVE_MAX * passive_scale))
                if q > 0:
                    # Try to join best bid or improve by 1 tick if spread wide.
                    px = bb + (1 if spread >= 3 else 0)
                    orders.append(Order(PEPPER, int(px), q))
        else:
            room = cap + pos
            if room > 0:
                q = min(room, int(self.PEP_PASSIVE_MAX * passive_scale))
                if q > 0:
                    px = ba - (1 if spread >= 3 else 0)
                    orders.append(Order(PEPPER, int(px), -q))

        return orders

    # ─────────────────────────────────────────────────────────────────────────
    # OSMIUM
    # ─────────────────────────────────────────────────────────────────────────
    def _osmium(self, state: TradingState, od: OrderDepth) -> List[Order]:
        orders: List[Order] = []
        pos = state.position.get(OSMIUM, 0)

        bb, bbv = self._best_bid(od)
        ba, bav = self._best_ask(od)
        if bb is None or ba is None:
            return orders
        mid = (bb + ba) / 2.0

        # Build VWAP from top-2 on each side (filters toxic thin levels)
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

        # Fair: anchor-dominated blend with EMA(vwap)
        vwap_ema = self.history["osm_vwap_ema"] or vwap
        fair = self.OSM_ANCHOR_WEIGHT * self.OSM_ANCHOR + (1 - self.OSM_ANCHOR_WEIGHT) * vwap_ema

        # OBI micro-bias (proven alpha)
        total_vol = bbv + bav
        obi = (bbv - bav) / total_vol if total_vol > 0 else 0.0
        if abs(obi) >= 0.3:
            fair += 0.6 * (1.0 if obi > 0 else -1.0)

        # Drift watchdog
        drift = vwap_ema - self.OSM_ANCHOR
        streak = self.history["osm_drift_streak"]
        if abs(drift) > self.OSM_DRIFT_THRESHOLD:
            streak = min(streak + 1, 1000)
        else:
            streak = max(streak - 2, 0)
        self.history["osm_drift_streak"] = streak
        in_drift = streak >= self.OSM_DRIFT_STREAK_TRIP

        if in_drift:
            # Abandon anchor — track the trend, don't fade it
            fair = vwap_ema + (0.6 * (1.0 if obi > 0 else -1.0) if abs(obi) >= 0.3 else 0.0)

        # Toxicity: massive top-of-book vol => someone sweeping
        toxic_buys  = bbv >= self.OSM_TOXICITY
        toxic_sells = bav >= self.OSM_TOXICITY

        # Take-edge ramp: more willing to cross as position grows (reduce it)
        edge_from_pos = min(self.OSM_TAKE_EDGE_MAX,
                            abs(pos) // self.OSM_EDGE_POS_STEP)
        take_edge = self.OSM_TAKE_EDGE_MAX - edge_from_pos

        rb = self.LIMIT - pos  # room to buy (actual cap here is also 80 but
        rs = self.LIMIT + pos  # we throttle via OSM_FLATTEN anyway)

        # ─── Cross-take on favourable asks/bids ─────────────────────────────
        if not toxic_sells and ba <= fair - take_edge and rb > 0:
            # ask is below fair → buy
            q = min(rb, bav, 30)
            if q > 0:
                orders.append(Order(OSMIUM, int(ba), q))
                rb -= q
                pos += q
        if not toxic_buys and bb >= fair + take_edge and rs > 0:
            q = min(rs, bbv, 30)
            if q > 0:
                orders.append(Order(OSMIUM, int(bb), -q))
                rs -= q
                pos -= q

        # ─── Hard flatten if over limit ─────────────────────────────────────
        flatten_hard = self.OSM_DRIFT_FLATTEN if in_drift else self.OSM_FLATTEN_HARD
        if pos > flatten_hard and rs > 0:
            exit_px = bb if in_drift else int(round(fair))
            qty = min(pos - self.OSM_FLATTEN_TARGET + 5, rs)
            if qty > 0:
                orders.append(Order(OSMIUM, exit_px, -qty))
                rs -= qty; pos -= qty
        elif pos < -flatten_hard and rb > 0:
            exit_px = ba if in_drift else int(round(fair))
            qty = min(-pos - self.OSM_FLATTEN_TARGET + 5, rb)
            if qty > 0:
                orders.append(Order(OSMIUM, exit_px, qty))
                rb += qty; pos += qty

        # ─── Adaptive quoting ───────────────────────────────────────────────
        # Width scales with ATR.
        half_spread = max(1, int(round(0.4 * atr)))
        bp = int(round(fair - half_spread))
        ap = int(round(fair + half_spread))

        # Ensure quotes are inside the current book
        if bp >= ba: bp = ba - 1
        if ap <= bb: ap = bb + 1

        # Inventory skew: push quotes toward side that reduces inventory
        if pos > self.OSM_SKEW_HARD:
            bp -= 1; ap -= 1
        elif pos > self.OSM_SKEW_SOFT:
            ap = max(bb + 1, ap - 1)
        elif pos < -self.OSM_SKEW_HARD:
            bp += 1; ap += 1
        elif pos < -self.OSM_SKEW_SOFT:
            bp = min(ba - 1, bp + 1)

        # Drift-mode suppression of adverse side
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
    # Main entry point
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
