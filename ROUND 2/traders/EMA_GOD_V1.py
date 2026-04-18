"""
trader_ema.py — EMA Ribbon + Kaufman Efficiency Ratio
=====================================================
A completely different philosophy from v8-v13. No anchors, no linear
regression slopes, no streak counters. Every decision is derived from:

  1. Four overlapping EMAs forming a "ribbon"
        fast (8)  — instantaneous fair value
        mid  (25) — short-term momentum reference
        slow (80) — regime filter
        anchor(250) — slow drift reference
  2. Kaufman's Efficiency Ratio (ER = |net move| / sum(|bar moves|))
        ER → 1 : price is efficient / trending cleanly
        ER → 0 : price is choppy / mean-reverting
  3. Ribbon alignment and spread (fast vs slow, slow vs anchor).
  4. ATR (average absolute tick move) for adaptive band widths.
  5. Order Book Imbalance (OBI) as a micro-timing filter only.

Trading logic:

PEPPER — trend follower
-----------------------
• Fair = fast_ema + 0.5 * (fast_ema - mid_ema) (short slope projection).
• Regime from ER:
    ER >= 0.30  -> strong trend     : take hard, passive to 55
    ER >= 0.15  -> weak trend       : take moderate, passive to 30
    ER <  0.15  -> chop / no-trend  : de-risk toward 0
• Direction only taken if ribbon is aligned (fast > mid > slow or inverse).
• No anchor to fade — position sizing is purely a function of ER × direction.

OSMIUM — adaptive mean reverter
-------------------------------
• Fair = slow EMA (let the market tell us the center, don't hardcode 10000).
• OBI shifts fair by up to +/-0.6 ticks when |OBI| >= 0.3.
• ATR-adaptive quote placement: bp = round(fair - max(1, 0.4*ATR)),
  ap = round(fair + max(1, 0.4*ATR)). Adapts automatically to vol regimes.
• Inventory skew: quote prices tilt toward the side that reduces position.
• Drift guard via ER: if ER >= 0.40 and |fast-anchor| > 5, switch to
  "trend respect" mode — suppress the side that adds adverse inventory,
  halve quote sizes, actively flatten at low cross threshold.
• Mean-reversion take only when ER is low AND price is > 1 tick off fair.

MAF BID
-------
4,000 — realistic bid given ~8k gross/day and ~2k extra-flow EV.
"""

import json
from typing import Dict, List, Tuple

from datamodel import Order, OrderDepth, TradingState, Symbol


PEPPER  = "INTARIAN_PEPPER_ROOT"
OSMIUM  = "ASH_COATED_OSMIUM"


class Trader:
    # ─── Shared / framework ────────────────────────────────────────────────
    POS_CAP     = {PEPPER: 80, OSMIUM: 100}
    MAX_HIST    = 120          # rolling window cap for mids / returns

    # ─── EMA periods ───────────────────────────────────────────────────────
    EMA_FAST    = 8
    EMA_MID     = 25
    EMA_SLOW    = 80
    EMA_ANCHOR  = 250

    # ─── Efficiency Ratio / ATR ────────────────────────────────────────────
    ER_WINDOW   = 30
    ATR_WINDOW  = 30

    # ─── Pepper thresholds ─────────────────────────────────────────────────
    PEP_ER_STRONG   = 0.30
    PEP_ER_WEAK     = 0.15
    PEP_TAKE_STRONG = 28
    PEP_TAKE_WEAK   = 12
    PEP_PASSIVE_ST  = 55
    PEP_PASSIVE_WK  = 30
    PEP_RIBBON_MIN  = 0.6      # |fast-slow| must exceed this to trust ribbon
    PEP_TAKE_EDGE   = 1.5      # ask <= fair + edge to take (in ticks)

    # ─── Osmium thresholds ─────────────────────────────────────────────────
    OSM_OBI_TRIP    = 0.30
    OSM_OBI_SHIFT   = 0.6
    OSM_QUOTE_FRONT = 30
    OSM_QUOTE_SECOND= 20
    OSM_BAND_ATR_K  = 0.4
    OSM_TAKE_EDGE   = 1.0
    OSM_TAKE_SIZE   = 20
    OSM_FLATTEN_SOFT= 55
    OSM_FLATTEN_HARD= 75
    # drift guard
    OSM_ER_DRIFT    = 0.40
    OSM_DRIFT_SPREAD= 5.0      # |fast - anchor| past which drift is "real"
    OSM_DRIFT_FLAT  = 25

    # ─── Market Access Fee ─────────────────────────────────────────────────
    MAF_BID = 4_000

    # =======================================================================
    # Construction / state
    # =======================================================================
    def __init__(self):
        self.history: Dict[str, object] = {}

    def _load_state(self, state: TradingState) -> None:
        if state.traderData:
            try:
                self.history = json.loads(state.traderData)
            except Exception:
                self.history = {}
        else:
            self.history = {}

        # structured defaults — flat dict keeps JSON ser/deser trivial
        for key, default in (
            ("pep_ef", None), ("pep_em", None), ("pep_es", None), ("pep_ea", None),
            ("osm_ef", None), ("osm_em", None), ("osm_es", None), ("osm_ea", None),
            ("pep_mids", []), ("osm_mids", []),
        ):
            self.history.setdefault(key, default)

    def _save_state(self) -> str:
        return json.dumps(self.history, separators=(",", ":"))

    # =======================================================================
    # EMA / feature helpers
    # =======================================================================
    @staticmethod
    def _ema_step(prev, new, period: int) -> float:
        if prev is None:
            return float(new)
        alpha = 2.0 / (period + 1)
        return prev + alpha * (new - prev)

    def _features(self, product: str, mid: float) -> Dict[str, float]:
        """Update all EMAs, mids buffer, and compute ER/ATR for `product`."""
        prefix = "pep" if product == PEPPER else "osm"

        ef = self._ema_step(self.history[f"{prefix}_ef"], mid, self.EMA_FAST)
        em = self._ema_step(self.history[f"{prefix}_em"], mid, self.EMA_MID)
        es = self._ema_step(self.history[f"{prefix}_es"], mid, self.EMA_SLOW)
        ea = self._ema_step(self.history[f"{prefix}_ea"], mid, self.EMA_ANCHOR)

        self.history[f"{prefix}_ef"] = ef
        self.history[f"{prefix}_em"] = em
        self.history[f"{prefix}_es"] = es
        self.history[f"{prefix}_ea"] = ea

        mids: List[float] = self.history[f"{prefix}_mids"]
        mids.append(float(mid))
        if len(mids) > self.MAX_HIST:
            mids = mids[-self.MAX_HIST:]
        self.history[f"{prefix}_mids"] = mids

        # Kaufman Efficiency Ratio over last ER_WINDOW ticks
        er = 0.0
        atr = 1.0
        n = min(len(mids), self.ER_WINDOW + 1)
        if n >= 3:
            recent = mids[-n:]
            net = abs(recent[-1] - recent[0])
            path = sum(abs(recent[i] - recent[i - 1]) for i in range(1, n))
            er = (net / path) if path > 1e-9 else 0.0
            atr = path / max(1, n - 1)

        # Ribbon alignment: +1 bull, -1 bear, 0 mixed
        if ef > em > es:
            aligned = 1
        elif ef < em < es:
            aligned = -1
        else:
            aligned = 0

        return {
            "ef": ef, "em": em, "es": es, "ea": ea,
            "er": er, "atr": atr, "aligned": aligned,
            "ribbon_spread": ef - es,
            "macro_spread":  es - ea,
        }

    # =======================================================================
    # Book helpers
    # =======================================================================
    @staticmethod
    def _book(od: OrderDepth) -> Tuple[List[Tuple[int, int]], List[Tuple[int, int]]]:
        # buy_orders volumes are positive; sell_orders volumes are negative
        bids = sorted(od.buy_orders.items(), key=lambda x: -x[0])
        asks = sorted(od.sell_orders.items(), key=lambda x:  x[0])
        return bids, asks

    # =======================================================================
    # PEPPER — EMA ribbon trend follower
    # =======================================================================
    def _pepper_logic(self, state: TradingState) -> List[Order]:
        if PEPPER not in state.order_depths:
            return []
        od = state.order_depths[PEPPER]
        bids, asks = self._book(od)
        if not bids or not asks:
            return []
        bb, _  = bids[0]
        ba, _  = asks[0]
        mid    = (bb + ba) / 2.0
        pos    = state.position.get(PEPPER, 0)
        cap    = self.POS_CAP[PEPPER]
        rb     = cap - pos
        rs     = cap + pos

        f      = self._features(PEPPER, mid)
        slope  = f["ef"] - f["em"]           # recent velocity
        fair   = f["ef"] + 0.5 * slope       # one-step projection
        ribbon = abs(f["ribbon_spread"])
        er     = f["er"]
        direction = f["aligned"]

        orders: List[Order] = []

        # ── No-trend regime: mean-revert position toward zero
        if er < self.PEP_ER_WEAK or direction == 0 or ribbon < self.PEP_RIBBON_MIN:
            if pos > 5 and rs > 0:
                q = min(rs, max(1, pos // 2))
                orders.append(Order(PEPPER, max(int(round(fair)) + 1, ba), -q))
            elif pos < -5 and rb > 0:
                q = min(rb, max(1, -pos // 2))
                orders.append(Order(PEPPER, min(int(round(fair)) - 1, bb), q))
            return orders

        strong   = er >= self.PEP_ER_STRONG
        take_cap = self.PEP_TAKE_STRONG if strong else self.PEP_TAKE_WEAK
        pass_cap = self.PEP_PASSIVE_ST  if strong else self.PEP_PASSIVE_WK

        # ── Uptrend: buy
        if direction > 0:
            remaining = take_cap
            for px, vol in asks:
                if remaining <= 0 or rb <= 0:
                    break
                if px <= fair + self.PEP_TAKE_EDGE:
                    q = min(rb, -vol, remaining)
                    if q > 0:
                        orders.append(Order(PEPPER, px, q))
                        rb -= q; pos += q; remaining -= q
                else:
                    break
            # passive load toward pass_cap
            if rb > 0 and pos < pass_cap:
                q = min(rb, pass_cap - pos)
                orders.append(Order(PEPPER, bb, q))

        # ── Downtrend: sell
        else:
            remaining = take_cap
            for px, vol in bids:
                if remaining <= 0 or rs <= 0:
                    break
                if px >= fair - self.PEP_TAKE_EDGE:
                    q = min(rs, vol, remaining)
                    if q > 0:
                        orders.append(Order(PEPPER, px, -q))
                        rs -= q; pos -= q; remaining -= q
                else:
                    break
            if rs > 0 and pos > -pass_cap:
                q = min(rs, pass_cap + pos)
                orders.append(Order(PEPPER, ba, -q))

        return orders

    # =======================================================================
    # OSMIUM — adaptive EMA-centered market maker
    # =======================================================================
    def _osmium_logic(self, state: TradingState) -> List[Order]:
        if OSMIUM not in state.order_depths:
            return []
        od = state.order_depths[OSMIUM]
        bids, asks = self._book(od)
        if not bids or not asks:
            return []
        bb, bv1 = bids[0]
        ba, av1 = asks[0]
        av1     = -av1
        mid     = (bb + ba) / 2.0
        pos     = state.position.get(OSMIUM, 0)
        cap     = self.POS_CAP[OSMIUM]
        rb      = cap - pos
        rs      = cap + pos

        f       = self._features(OSMIUM, mid)
        ef, es, ea = f["ef"], f["es"], f["ea"]
        atr     = f["atr"]
        er      = f["er"]

        # ── Fair value = slow EMA + OBI bias
        total_vol = bv1 + av1
        obi = (bv1 - av1) / total_vol if total_vol > 0 else 0.0
        fair = es
        if obi >= self.OSM_OBI_TRIP:
            fair += self.OSM_OBI_SHIFT
        elif obi <= -self.OSM_OBI_TRIP:
            fair -= self.OSM_OBI_SHIFT

        # ── Drift guard: ER high + fast ema well away from anchor = trending
        drift_active = (er >= self.OSM_ER_DRIFT
                        and abs(ef - ea) >= self.OSM_DRIFT_SPREAD)
        drift_dir = 1 if ef > ea else -1 if ef < ea else 0

        orders: List[Order] = []

        # ── Hard flatten (drift or extreme inventory) ──────────────────────
        flatten_hard = self.OSM_DRIFT_FLAT if drift_active else self.OSM_FLATTEN_HARD
        if pos > flatten_hard and rs > 0:
            q = min(rs, pos - self.OSM_FLATTEN_SOFT + 5)
            exit_px = bb if drift_active else int(round(fair))
            orders.append(Order(OSMIUM, exit_px, -q))
            rs -= q; pos -= q
        elif pos < -flatten_hard and rb > 0:
            q = min(rb, -pos - self.OSM_FLATTEN_SOFT + 5)
            exit_px = ba if drift_active else int(round(fair))
            orders.append(Order(OSMIUM, exit_px, q))
            rb += q; pos += q

        # ── Mean-reversion take (only when market is choppy) ───────────────
        if not drift_active and er < 0.25:
            # buy deep asks
            if rb > 0:
                remaining = self.OSM_TAKE_SIZE
                for px, vol in asks:
                    if remaining <= 0 or rb <= 0:
                        break
                    if px <= fair - self.OSM_TAKE_EDGE:
                        q = min(rb, -vol, remaining)
                        if q > 0:
                            orders.append(Order(OSMIUM, px, q))
                            rb -= q; pos += q; remaining -= q
                    else:
                        break
            # sell lifted bids
            if rs > 0:
                remaining = self.OSM_TAKE_SIZE
                for px, vol in bids:
                    if remaining <= 0 or rs <= 0:
                        break
                    if px >= fair + self.OSM_TAKE_EDGE:
                        q = min(rs, vol, remaining)
                        if q > 0:
                            orders.append(Order(OSMIUM, px, -q))
                            rs -= q; pos -= q; remaining -= q
                    else:
                        break

        # ── Adaptive quote placement ──────────────────────────────────────
        band = max(1.0, self.OSM_BAND_ATR_K * atr)
        bp   = int(round(fair - band))
        ap   = int(round(fair + band))
        if bp >= ba: bp = ba - 1
        if ap <= bb: ap = bb + 1
        if bp >= bb: bp = bb                 # never worse than top-of-book
        if ap <= ba: ap = ba                 # never worse than top-of-book

        # Inventory skew — push quotes toward reducing position
        skew = pos / cap                      # -1 .. 1
        if skew >= 0.3:
            bp -= 1                           # less aggressive bid
        elif skew <= -0.3:
            ap += 1                           # less aggressive ask

        # Size scaling
        front  = self.OSM_QUOTE_FRONT
        second = self.OSM_QUOTE_SECOND
        if drift_active:
            front  = max(4, front  // 2)
            second = max(3, second // 2)

        # Suppress the side that would add adverse inventory in drift
        suppress_buy  = drift_active and drift_dir < 0
        suppress_sell = drift_active and drift_dir > 0

        if rb > 0 and not suppress_buy:
            q = min(rb, front)
            orders.append(Order(OSMIUM, bp, q))
            rb -= q
            if rb > 0:
                orders.append(Order(OSMIUM, bp - 1, min(rb, second)))

        if rs > 0 and not suppress_sell:
            q = min(rs, front)
            orders.append(Order(OSMIUM, ap, -q))
            rs -= q
            if rs > 0:
                orders.append(Order(OSMIUM, ap + 1, -min(rs, second)))

        return orders

    # =======================================================================
    # Framework entry points
    # =======================================================================
    def run(self, state: TradingState):
        self._load_state(state)
        result: Dict[str, List[Order]] = {}

        pep = self._pepper_logic(state)
        if pep:
            result[PEPPER] = pep

        osm = self._osmium_logic(state)
        if osm:
            result[OSMIUM] = osm

        return result, 0, self._save_state()

    # Market Access Fee bid
    def bid(self) -> int:
        return self.MAF_BID
