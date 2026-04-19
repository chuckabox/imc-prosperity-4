"""
trader_v11.py — v8 champion + 3 surgical upgrades
==================================================
v8 scored 8,126 (best), v9 = 7,975, v10 = 7,923.  v10's OBI added
+140 on osmium but slowed pepper's cap load (6,725 vs v8's 7,066).

Diagnosis from logs:
  • v8 pepper loads to cap 80 only around t=45k → first half captures
    ~2,750 of possible 4,000. Theoretical ceiling ~8,000.
  • v8 osmium peaks at 1,189 (t=99,400) then bleeds to 1,060 in the
    final 500 ticks — classic MM terminal adverse selection.
  • MAF=15,000 is EV-negative: extra 25% flow buys <2k incremental PnL.

v11 = v8 with three targeted fixes:

1. PEPPER FAST-LOADER
   When regime is STRONG and position < 60, unlock a turbo mode:
     TAKE_STRONG 32 → 50, cross-edge 2.0 → 3.0, passive 65 → 80 (no
     spread-scale cut).  Once pos ≥ 60, revert to v8 settings so we
     don't oversize once we're near cap.

2. OSMIUM OBI BIAS  (from v10; the proven +140 bit)
   Compute OBI = (bv1 - av1)/(bv1 + av1) on the *top* level.
   • OBI ≥ +0.30 ⇒ fair += 0.6, front_buy ×1.25, front_sell ×0.80
   • OBI ≤ -0.30 ⇒ fair -= 0.6, front_sell ×1.25, front_buy ×0.80
   Nothing else changes — no OBI on pepper (it hurt there).

3. OSMIUM END-GAME FLATTEN
   • After t ≥ 95,000, shrink quote sizes to 70%.
   • After t ≥ 98,000, actively skew toward flat inventory and
     cross aggressively to close out.  Prevents the -130 terminal
     bleed observed in v8.

4. MAF lowered 15,000 → 4,000 (still plausibly top-50% at realistic
   competitor distribution; net EV ~+11k).
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

    # ── PEPPER ────────────────────────────────────────────────────────────────
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

    # NEW: turbo loader (only when regime=STRONG and pos<60)
    PEPPER_LOAD_THRESHOLD  = 60
    PEPPER_TAKE_TURBO      = 50
    PEPPER_PASSIVE_TURBO   = 80
    PEPPER_TAKE_EDGE_TURBO = 3.0

    PEPPER_STOP_BREACH_COUNT = 3
    PEPPER_STOP_STRONG    = -20
    PEPPER_STOP_MODERATE  = -10
    PEPPER_STOP_WEAK      =  -7
    PEPPER_RESUME_STRONG  =   5
    PEPPER_RESUME_MODERATE=   5
    PEPPER_RESUME_WEAK    =   4

    PEPPER_SPREAD_PASSIVE_SCALE = 0.75
    PEPPER_TAKE_CROSS_EDGE      = 2.0

    # ── OSMIUM ────────────────────────────────────────────────────────────────
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

    # NEW: OBI bias
    OSMIUM_OBI_THRESHOLD  = 0.30
    OSMIUM_OBI_FAIR_SHIFT = 0.6
    OSMIUM_OBI_BOOST      = 1.25
    OSMIUM_OBI_DAMP       = 0.80

    # NEW: end-game flattening
    OSMIUM_ENDGAME_TICK       = 95_000
    OSMIUM_FORCE_FLATTEN_TICK = 98_000
    OSMIUM_ENDGAME_SIZE_SCALE = 0.70

    def __init__(self):
        self.history: Dict = {}

    # ── MAF ───────────────────────────────────────────────────────────────────
    def bid(self) -> int:
        # Was 15_000. Log analysis: extra 25% flow ≈ +2k PnL, not +15k.
        # 4,000 stays plausibly top-50% without eroding net.
        return 4_000

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
        rem_cap = effective_cap - pos

        # NEW: turbo fast-load mode (strong regime + under-loaded)
        turbo = (effective_cap == self.PEPPER_CAP_STRONG
                 and pos < self.PEPPER_LOAD_THRESHOLD
                 and not drift_stopped)

        if turbo:
            take_limit = self.PEPPER_TAKE_TURBO
            passive_max = self.PEPPER_PASSIVE_TURBO
            cross_edge  = self.PEPPER_TAKE_EDGE_TURBO
        else:
            take_limit = (self.PEPPER_TAKE_STRONG
                          if effective_cap == self.PEPPER_CAP_STRONG
                          else self.PEPPER_TAKE_NORMAL)
            passive_max = self.PEPPER_PASSIVE_MAX
            cross_edge  = self.PEPPER_TAKE_CROSS_EDGE

        if rem_cap > 0:
            budget = min(rem_cap, take_limit)
            for ask in sorted(depth.sell_orders.keys()):
                if budget <= 0:
                    break
                if ask <= mid + cross_edge:
                    qty = min(budget, -depth.sell_orders[ask])
                    orders.append(Order(product, ask, qty))
                    budget  -= qty
                    rem_cap -= qty

            if rem_cap > 0:
                passive_qty = min(rem_cap, passive_max)
                # In turbo mode, don't scale passive down on widening spread —
                # we need to load fast; drift dominates.
                if spread_widening and not turbo:
                    passive_qty = int(passive_qty * self.PEPPER_SPREAD_PASSIVE_SCALE)
                if passive_qty > 0:
                    orders.append(Order(product, bb + 1, passive_qty))

        # Light de-risk when spread widens and well loaded (disabled in turbo)
        if spread_widening and pos > effective_cap * 0.6 and not turbo:
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
        ts  = state.timestamp

        # ── VWAP-blended fair value ──────────────────────────────────────────
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

        # ── NEW: Order-book imbalance bias ────────────────────────────────────
        obi = 0.0
        if total_vol > 0:
            obi = (bv1 - av1) / total_vol

        obi_buy_boost  = 1.0
        obi_sell_boost = 1.0
        if obi >= self.OSMIUM_OBI_THRESHOLD:
            fair += self.OSMIUM_OBI_FAIR_SHIFT
            obi_buy_boost  = self.OSMIUM_OBI_BOOST
            obi_sell_boost = self.OSMIUM_OBI_DAMP
        elif obi <= -self.OSMIUM_OBI_THRESHOLD:
            fair -= self.OSMIUM_OBI_FAIR_SHIFT
            obi_sell_boost = self.OSMIUM_OBI_BOOST
            obi_buy_boost  = self.OSMIUM_OBI_DAMP

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

        # ── NEW: end-game force flatten ───────────────────────────────────────
        if ts >= self.OSMIUM_FORCE_FLATTEN_TICK and pos != 0:
            if pos > 0:
                # sell to bid to close
                q = min(pos, depth.buy_orders.get(bb, 0), rs)
                if q > 0:
                    orders.append(Order(product, bb, -q))
                    rs  -= q
                    pos -= q
            else:
                q = min(-pos, -depth.sell_orders.get(ba, 0), rb)
                if q > 0:
                    orders.append(Order(product, ba, q))
                    rb  -= q
                    pos += q

        # ── Hard circuit-breaker ──────────────────────────────────────────────
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

        # ── Market making ─────────────────────────────────────────────────────
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

        # Size scaling — shrink when drift is really far from anchor
        anchor_drift = abs(fair - self.OSMIUM_ANCHOR)
        size_scale   = (max(0.5, 1.0 - (anchor_drift - self.OSMIUM_DRIFT_SCALE_AT) / 20.0)
                        if anchor_drift > self.OSMIUM_DRIFT_SCALE_AT else 1.0)

        # NEW: end-game size tapering
        if ts >= self.OSMIUM_ENDGAME_TICK:
            size_scale *= self.OSMIUM_ENDGAME_SIZE_SCALE

        front_buy  = max(4, int(self.OSMIUM_QUOTE_FRONT  * size_scale * obi_buy_boost))
        front_sell = max(4, int(self.OSMIUM_QUOTE_FRONT  * size_scale * obi_sell_boost))
        second     = max(3, int(self.OSMIUM_QUOTE_SECOND * size_scale))

        # NEW: in force-flatten window, stop posting the side we don't need
        in_force_flatten = ts >= self.OSMIUM_FORCE_FLATTEN_TICK

        if rb > 0 and not toxic_buys and not (in_force_flatten and pos > 0):
            q = min(rb, front_buy)
            orders.append(Order(product, bp, q))
            rb -= q
            if rb > 0:
                orders.append(Order(product, bp - 1, min(rb, second)))

        if rs > 0 and not toxic_sells and not (in_force_flatten and pos < 0):
            q = min(rs, front_sell)
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
