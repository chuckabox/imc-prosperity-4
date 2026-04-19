"""
trader_peter_v10.py  —  Round 2, original clean rewrite
=========================================================

PEPPER ROOT
-----------
Straight-line (linear-trending) asset around 11 000.

Data shows 3 gap events where mid spikes to near 0 (empty-book artifacts).
These must be excluded from all slope / stop calculations.

Strategy:
  1. Gap filter  : skip the tick if mid < 9 000 or spread > 100 (artifact).
  2. Slope       : v5-calibrated formula  (median-of-15 windows, 85-tick dt).
                   Slope thresholds match v5's normalised units.
  3. Target cap  : slope → 0 / 30 / 60 / 80 long.  Never short pepper.
  4. Stop guard  : local 20-tick move < threshold → dump longs, pause buys.
  5. Spread alpha: rising spread predicts −15.8 avg move in next 5 ticks.
                   Gate: when spread > prev_spread, skip buying, sell up to 20
                   of existing long into best bid.  Do NOT open new shorts.
  6. Buys        : aggressive take ≤ mid+1; passive passive bid at bb+1.

OSMIUM
------
Drifting mean-reverting asset.  VWAP mid (level-1, cross-weighted) leads
the raw mid with 0.7 correlation — use it as fair value.

Strategy:
  1. VWAP mid    : (best_bid * ask_vol + best_ask * bid_vol) / (bid_vol + ask_vol).
                   Forward-fill on gap ticks.
  2. Smooth fair : 70 % VWAP + 30 % 50-tick rolling average.
  3. Takes       : hit sell-side when ask ≤ fair − edge; hit buy-side when
                   bid ≥ fair + edge.  Edge widens with inventory size.
  4. MM quotes   : bid at int(fair)−1, ask at int(fair)+1.
                   Shift both quotes 1 tick per skew threshold crossed.
  5. Flatten     : if |pos| > 55, market-take toward 40 before quoting.

MAF
---
bid() returns 0.  We opt out — guaranteed zero fee drag.
"""

import json
from typing import Dict, List, Optional

from datamodel import Order, OrderDepth, TradingState

# ─── constants ────────────────────────────────────────────────────────────────
_PEPPER = "INTARIAN_PEPPER_ROOT"
_OSMIUM = "ASH_COATED_OSMIUM"
_LIMIT  = 80

# Pepper slope thresholds — calibrated to v5 normalised formula
_PP_SLOPE_STRONG   =  0.06
_PP_SLOPE_MODERATE =  0.02
_PP_SLOPE_WEAK     = -0.02

# Pepper stop / resume thresholds (20-tick local move)
_PP_STOP   = {80: -16, 60: -12, 30: -8,  0: -8}
_PP_RESUME = {80:   7, 60:   5, 30:  4,  0:  4}


def _median(vals: list) -> float:
    n = len(vals)
    if n == 0:
        return 0.0
    s = sorted(vals)
    m = n // 2
    return float(s[m]) if n % 2 == 1 else (s[m - 1] + s[m]) / 2.0


def _pp_slope(hist: list) -> float:
    """
    v5-compatible slope: median of last 15 vs median of 15 starting 100 ago,
    over a dt=85 window, normalised × 10.
    Requires len(hist) >= 100.
    """
    s_now   = _median(hist[-15:])
    s_start = _median(hist[-100:-85])
    return (s_now - s_start) / 85.0 * 10.0


def _pp_cap_from_slope(slope: float) -> int:
    if slope > _PP_SLOPE_STRONG:
        return 80
    if slope > _PP_SLOPE_MODERATE:
        return 60
    if slope > _PP_SLOPE_WEAK:
        return 30
    return 0


# ─── trader ────────────────────────────────────────────────────────────────────
class Trader:

    # ── MAF: opt out ──────────────────────────────────────────────────────────
    def bid(self) -> int:
        return 0

    # ── state helpers ─────────────────────────────────────────────────────────
    @staticmethod
    def _load(raw: str) -> dict:
        try:
            h = json.loads(raw) if raw else {}
        except Exception:
            h = {}
        h.setdefault("pp_mids",      [])
        h.setdefault("pp_spreads",   [])
        h.setdefault("pp_cap",       None)
        h.setdefault("pp_stopped",   False)
        h.setdefault("pp_start_ts",  None)
        h.setdefault("op_fairs",     [])
        h.setdefault("op_last_fair", None)
        return h

    # ── pepper ────────────────────────────────────────────────────────────────
    @staticmethod
    def _pepper(state: TradingState, h: dict) -> List[Order]:
        if _PEPPER not in state.order_depths:
            return []

        depth = state.order_depths[_PEPPER]
        pos   = int(state.position.get(_PEPPER, 0))
        ts    = state.timestamp

        bb = max(depth.buy_orders)  if depth.buy_orders  else None
        ba = min(depth.sell_orders) if depth.sell_orders else None
        if bb is None or ba is None:
            return []

        mid    = (bb + ba) / 2.0
        spread = ba - bb

        # ── gap filter ────────────────────────────────────────────────────────
        # Book artifact: mid spikes to near 0 on empty-side ticks.
        if mid < 9_000 or spread > 100:
            # Still dump inventory if we're stopped — don't freeze.
            if h["pp_stopped"] and pos > 0:
                return [Order(_PEPPER, bb, -pos)]
            return []

        # ── record ────────────────────────────────────────────────────────────
        if h["pp_start_ts"] is None:
            h["pp_start_ts"] = ts

        mids: list = h["pp_mids"]
        mids.append(mid)
        if len(mids) > 300:
            del mids[:-300]

        spreads: list = h["pp_spreads"]
        spreads.append(spread)
        if len(spreads) > 10:
            del spreads[:-10]

        # ── spread alpha ──────────────────────────────────────────────────────
        prev_spread    = spreads[-2] if len(spreads) >= 2 else spread
        spread_rising  = spread > prev_spread

        # ── slope / cap ───────────────────────────────────────────────────────
        warmed_up = (ts - h["pp_start_ts"]) >= 1_500
        cap: Optional[int] = h["pp_cap"]

        if len(mids) >= 100 and (warmed_up or cap is None):
            new_cap = _pp_cap_from_slope(_pp_slope(mids))
            # Monotone upgrade — never downgrade cap mid-trend
            if cap is None or new_cap > cap:
                cap = new_cap
                h["pp_cap"] = cap

        effective_cap = cap if cap is not None else 20  # tentative

        # ── stop guard ────────────────────────────────────────────────────────
        stopped: bool = h["pp_stopped"]
        if len(mids) >= 20:
            move       = mids[-1] - mids[-20]
            stop_th    = _PP_STOP.get(effective_cap,   -12)
            resume_th  = _PP_RESUME.get(effective_cap,   5)
            if move < stop_th:
                stopped = True
            elif stopped and move > resume_th:
                stopped = False
        h["pp_stopped"] = stopped

        orders: List[Order] = []

        # ── stopped or cap=0: dump longs ──────────────────────────────────────
        if stopped or effective_cap == 0:
            if pos > 0:
                orders.append(Order(_PEPPER, bb, -pos))
            return orders

        # ── spread rising: sell partial, skip buys ────────────────────────────
        if spread_rising:
            if pos > 0:
                sell_qty = min(pos, 20)
                orders.append(Order(_PEPPER, bb, -sell_qty))
            return orders  # no buys when spread widening

        # ── buy toward cap ────────────────────────────────────────────────────
        rem = max(0, effective_cap - pos)
        if rem <= 0:
            return orders

        take_budget = min(rem, 15 if effective_cap >= 60 else 10)

        for ask in sorted(depth.sell_orders):
            if take_budget <= 0 or rem <= 0:
                break
            if ask <= mid + 1:
                avail = max(0, -depth.sell_orders[ask])  # sell_orders values < 0
                qty   = min(take_budget, avail, rem)
                if qty > 0:
                    orders.append(Order(_PEPPER, ask, qty))
                    take_budget -= qty
                    rem         -= qty

        # passive bid — capped so we don't over-commit
        passive = max(0, min(rem, 40))
        if passive > 0:
            orders.append(Order(_PEPPER, bb + 1, passive))

        return orders

    # ── osmium ────────────────────────────────────────────────────────────────
    @staticmethod
    def _osmium(state: TradingState, h: dict) -> List[Order]:
        if _OSMIUM not in state.order_depths:
            return []

        depth = state.order_depths[_OSMIUM]
        pos   = int(state.position.get(_OSMIUM, 0))

        # ── VWAP mid (level-1 cross-weight, matches analyze_spread.py) ────────
        bb = max(depth.buy_orders)  if depth.buy_orders  else None
        ba = min(depth.sell_orders) if depth.sell_orders else None

        if bb is not None and ba is not None:
            bv = depth.buy_orders[bb]        # positive
            av = -depth.sell_orders[ba]      # negate: sell_orders values < 0
            if bv > 0 and av > 0:
                vwap = (bb * av + ba * bv) / (bv + av)
                h["op_last_fair"] = vwap
            else:
                vwap = h["op_last_fair"]
        else:
            vwap = h["op_last_fair"]

        if vwap is None:
            return []  # no known fair yet — skip

        # ── smooth fair ───────────────────────────────────────────────────────
        fairs: list = h["op_fairs"]
        fairs.append(vwap)
        if len(fairs) > 50:
            del fairs[:-50]

        avg_fair = sum(fairs) / len(fairs)
        fair     = 0.7 * vwap + 0.3 * avg_fair

        # ── capacity ──────────────────────────────────────────────────────────
        rem_buy  = max(0, _LIMIT - pos)
        rem_sell = max(0, _LIMIT + pos)

        # Position-aware take edge (widens as we accumulate inventory)
        buy_edge  = 1 + max(0, pos   // 30)
        sell_edge = 1 + max(0, (-pos) // 30)

        orders: List[Order] = []

        # ── mean-reversion takes ──────────────────────────────────────────────
        if depth.sell_orders and rem_buy > 0:
            for ask in sorted(depth.sell_orders):
                if rem_buy <= 0:
                    break
                if ask <= fair - buy_edge:
                    qty = max(0, min(rem_buy, -depth.sell_orders[ask]))
                    if qty > 0:
                        orders.append(Order(_OSMIUM, ask, qty))
                        rem_buy -= qty
                        pos     += qty

        if depth.buy_orders and rem_sell > 0:
            for bid_px in sorted(depth.buy_orders, reverse=True):
                if rem_sell <= 0:
                    break
                if bid_px >= fair + sell_edge:
                    qty = max(0, min(rem_sell, depth.buy_orders[bid_px]))
                    if qty > 0:
                        orders.append(Order(_OSMIUM, bid_px, -qty))
                        rem_sell -= qty
                        pos      -= qty

        # ── hard flatten (market-take into best) ──────────────────────────────
        if pos > 55 and depth.buy_orders and rem_sell > 0:
            best_bid    = max(depth.buy_orders)
            flatten_qty = max(0, min(pos - 40, rem_sell))
            if flatten_qty > 0:
                orders.append(Order(_OSMIUM, best_bid, -flatten_qty))
                rem_sell -= flatten_qty
                pos      -= flatten_qty

        elif pos < -55 and depth.sell_orders and rem_buy > 0:
            best_ask    = min(depth.sell_orders)
            flatten_qty = max(0, min(-pos - 40, rem_buy))
            if flatten_qty > 0:
                orders.append(Order(_OSMIUM, best_ask, flatten_qty))
                rem_buy -= flatten_qty
                pos     += flatten_qty

        # ── MM quotes ─────────────────────────────────────────────────────────
        bid_q = int(fair) - 1
        ask_q = int(fair) + 1

        # Inventory skew: push quotes away from over-exposed side
        if pos >  22: bid_q -= 1
        if pos >  45: bid_q -= 1
        if pos < -22: ask_q += 1
        if pos < -45: ask_q += 1

        # Guarantee non-crossing spread
        if bid_q >= ask_q:
            ask_q = bid_q + 1

        if rem_buy > 0:
            orders.append(Order(_OSMIUM, bid_q, min(rem_buy, 25)))
        if rem_sell > 0:
            orders.append(Order(_OSMIUM, ask_q, -min(rem_sell, 25)))

        return orders

    # ── entry point ───────────────────────────────────────────────────────────
    def run(self, state: TradingState):
        h      = self._load(state.traderData)
        result: Dict[str, List[Order]] = {}

        try:
            pp = self._pepper(state, h)
            if pp:
                result[_PEPPER] = pp
        except Exception:
            pass

        try:
            op = self._osmium(state, h)
            if op:
                result[_OSMIUM] = op
        except Exception:
            pass

        return result, 0, json.dumps(h)
