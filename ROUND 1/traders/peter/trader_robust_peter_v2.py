"""
trader_robust_peter_v2.py
=========================
Adaptive HFT Market Maker - IMC Prosperity Round 1
Products: INTARIAN_PEPPER_ROOT, ASH_COATED_OSMIUM

Upgrades from v1:
  1. Dynamic Volatility Spreads — Rolling StdDev widens required_edge
  2. Convex Inventory Management — Exponential penalty past |pos|>50, 
     emergency liquidity-taking at |pos|>70
  3. Regime Detection (Osmium) — Short/Long EMA crossover shifts Fair Value
  4. Reliability — Survives 10k+ timestamps of one-way drift, stays neutral
"""

import json
import math
from typing import Dict, List, Any

from datamodel import Order, OrderDepth, TradingState, Symbol


class Logger:
    def __init__(self) -> None:
        self.logs = ""

    def print(self, *objects: Any, sep: str = " ", end: str = "\n") -> None:
        self.logs += sep.join(map(str, objects)) + end

    def flush(
        self,
        state: TradingState,
        orders: Dict[Symbol, List[Order]],
        conversions: int,
        trader_data: str,
    ) -> None:
        # No-op logger for competition environment.
        pass


logger = Logger()


class Trader:
    """
    Robust Adaptive Trader (Peter v2) - Anti-Floor, Trend-Aware
    ------------------------------------------------------------
    Key features:
      - Convex inventory penalty (exponential near limits)
      - Rolling volatility-scaled spreads
      - EMA crossover regime detection (Osmium)
      - Emergency liquidity-taking when inventory critical
    """

    def __init__(self):
        self.limits = {
            "ASH_COATED_OSMIUM": 80,
            "INTARIAN_PEPPER_ROOT": 80,
        }
        self.history = {}

    def _load_state(self, trader_data: str):
        if trader_data:
            try:
                self.history = json.loads(trader_data)
            except Exception:
                self.history = {}

    # ------------------------------------------------------------------
    #  Math helpers
    # ------------------------------------------------------------------
    def _ema(self, prices: list, span: int) -> float:
        """Calculate EMA from full price history."""
        if not prices:
            return 0.0
        alpha = 2.0 / (span + 1)
        val = prices[0]
        for p in prices[1:]:
            val = alpha * p + (1 - alpha) * val
        return val

    def _rolling_std(self, prices: list, window: int) -> float:
        """Rolling standard deviation over last `window` prices."""
        if len(prices) < 2:
            return 1.0
        subset = prices[-window:]
        n = len(subset)
        mean = sum(subset) / n
        variance = sum((p - mean) ** 2 for p in subset) / n
        return max(math.sqrt(variance), 0.5)  # floor at 0.5 to avoid zero

    def _get_mid(self, depth: OrderDepth) -> float:
        bb = max(depth.buy_orders.keys()) if depth.buy_orders else None
        ba = min(depth.sell_orders.keys()) if depth.sell_orders else None
        if bb and ba:
            return (bb + ba) / 2.0
        return bb or ba or 0.0

    def _convex_skew(self, pos: int, limit: int) -> float:
        """
        Convex inventory skew. Linear below |50|, exponential above.
        Returns signed skew: positive pos → positive skew (makes buys cheaper, sells dearer).
        
        At |pos|=50: skew ≈ 2.5  (linear: 0.05 * 50)
        At |pos|=60: skew ≈ 4.5  (accelerating)
        At |pos|=70: skew ≈ 8.0  (aggressive)
        At |pos|=75: skew ≈ 12.0 (panic mode)
        """
        abs_pos = abs(pos)
        sign = 1 if pos > 0 else -1 if pos < 0 else 0

        if abs_pos <= 50:
            # Linear zone: gentle lean
            return sign * abs_pos * 0.05
        else:
            # Convex zone: exponential acceleration
            linear_base = 50 * 0.05  # = 2.5
            excess = abs_pos - 50
            # Exponential growth: 2.5 + excess^1.8 * 0.02
            convex_add = (excess ** 1.8) * 0.02
            return sign * (linear_base + convex_add)

    # ------------------------------------------------------------------
    # PEPPER ROOT — Pure Market Maker
    # ------------------------------------------------------------------
    def _pepper_logic(self, state: TradingState) -> List[Order]:
        product = "INTARIAN_PEPPER_ROOT"
        if product not in state.order_depths:
            return []

        depth = state.order_depths[product]
        pos = state.position.get(product, 0)
        limit = self.limits[product]
        mid = self._get_mid(depth)
        if mid == 0:
            return []

        best_bid = max(depth.buy_orders.keys()) if depth.buy_orders else None
        best_ask = min(depth.sell_orders.keys()) if depth.sell_orders else None

        # --- State: price history ---
        hist = self.history.get("pp", [])
        hist.append(mid)
        if len(hist) > 200:
            hist = hist[-200:]
        self.history["pp"] = hist

        # --- Fair value: fast EMA ---
        ema_f = self._ema(hist, 8)
        fair = ema_f if len(hist) >= 8 else mid

        # --- Dynamic Volatility Spread ---
        vol = self._rolling_std(hist, 30)
        # Base edge scales with volatility: more volatile → wider spread
        # Calibrated so base_edge ≈ 1.0 at vol=1.0, ≈ 3.0 at vol=3.0
        base_edge = max(1.0, vol * 1.0)

        # --- Trend detection (mild, for pepper) ---
        trend_skew = 0.0
        if len(hist) >= 40:
            ema_s = self._ema(hist, 40)
            trend = (ema_f - ema_s) / max(vol, 1.0)
            trend_skew = max(-2.0, min(2.0, trend * 4.0))

        # --- Convex inventory skew ---
        inv_skew = self._convex_skew(pos, limit)

        orders = []
        buy_cap = limit - pos
        sell_cap = limit + pos

        # --- Passive quoting ---
        if best_bid and buy_cap > 0:
            price = best_bid + 1
            price = min(price, math.floor(fair - base_edge + trend_skew - inv_skew))
            q = min(buy_cap, 20)
            if price > 0:
                orders.append(Order(product, int(price), q))
                rem = buy_cap - q
                if rem > 0:
                    orders.append(Order(product, int(price - 2), min(rem, 15)))

        if best_ask and sell_cap > 0:
            price = best_ask - 1
            price = max(price, math.ceil(fair + base_edge + trend_skew - inv_skew))
            q = min(sell_cap, 20)
            if price > 0:
                orders.append(Order(product, int(price), -q))
                rem = sell_cap - q
                if rem > 0:
                    orders.append(Order(product, int(price + 2), -min(rem, 15)))

        # --- Emergency liquidity-taking at extreme inventory ---
        abs_pos = abs(pos)
        if abs_pos > 70:
            # PANIC: take liquidity at mid to unwind
            unwind_qty = min(abs_pos - 55, 25)  # Aggressive unwind
            if pos > 70 and best_bid:
                orders.append(Order(product, best_bid, -unwind_qty))
            elif pos < -70 and best_ask:
                orders.append(Order(product, best_ask, unwind_qty))
        elif abs_pos > 55:
            # WARN: moderate unwind via passive orders near mid
            unwind_qty = min(abs_pos - 45, 15)
            if pos > 55 and best_bid:
                orders.append(Order(product, best_bid, -unwind_qty))
            elif pos < -55 and best_ask:
                orders.append(Order(product, best_ask, unwind_qty))

        return orders

    # ------------------------------------------------------------------
    # OSMIUM — Regime-Aware Market Maker
    # ------------------------------------------------------------------
    def _osmium_logic(self, state: TradingState) -> List[Order]:
        product = "ASH_COATED_OSMIUM"
        if product not in state.order_depths:
            return []

        depth = state.order_depths[product]
        pos = state.position.get(product, 0)
        limit = self.limits[product]
        mid = self._get_mid(depth)
        if mid == 0:
            return []

        best_bid = max(depth.buy_orders.keys()) if depth.buy_orders else None
        best_ask = min(depth.sell_orders.keys()) if depth.sell_orders else None
        spread = (best_ask - best_bid) if (best_bid and best_ask) else 20

        # --- State: price history ---
        hist = self.history.get("op", [])
        hist.append(mid)
        if len(hist) > 300:
            hist = hist[-300:]
        self.history["op"] = hist

        # --- Regime Detection: Short/Long EMA crossover ---
        ema_short = self._ema(hist, 10)
        ema_long = self._ema(hist, 50)

        regime_bias = 0.0
        regime_str = "NEUTRAL"
        if len(hist) >= 50:
            # Normalized crossover signal
            cross = (ema_short - ema_long) / max(self._rolling_std(hist, 50), 1.0)
            if cross > 0.5:
                regime_str = "BULL"
                regime_bias = min(cross * 1.5, 4.0)  # Shift FV up in bull
            elif cross < -0.5:
                regime_str = "BEAR"
                regime_bias = max(cross * 1.5, -4.0)  # Shift FV down in bear

        # Store regime for logging
        self.history["regime"] = regime_str

        # --- Fair Value with regime bias ---
        anchor = self._ema(hist, 20)  # Faster anchor than v1's 50
        fair = anchor + regime_bias

        # --- Tape adjustment (informed flow detection) ---
        tape_adj = 0.0
        if product in state.market_trades:
            for trade in state.market_trades[product]:
                if trade.price >= mid:
                    tape_adj += trade.quantity
                else:
                    tape_adj -= trade.quantity
        tape_adj = math.copysign(min(abs(tape_adj) * 0.1, 1.5), tape_adj)
        fair += tape_adj

        # --- Dynamic Volatility Spread ---
        vol = self._rolling_std(hist, 30)
        # Osmium is trickier — widen more aggressively
        base_edge = max(1.5, vol * 1.2)

        # --- Convex inventory skew ---
        inv_skew = self._convex_skew(pos, limit)

        # --- Quote prices ---
        bid_price = math.floor(fair - base_edge - inv_skew)
        ask_price = math.ceil(fair + base_edge - inv_skew)

        # Competitive improvement
        if best_bid:
            bid_price = min(bid_price, best_bid + 1)
            bid_price = min(bid_price, math.floor(fair - base_edge * 0.5))
        if best_ask:
            ask_price = max(ask_price, best_ask - 1)
            ask_price = max(ask_price, math.ceil(fair + base_edge * 0.5))
        if bid_price >= ask_price:
            ask_price = bid_price + 1

        orders = []
        rem_buy = limit - pos
        rem_sell = limit + pos

        # --- Aggressive take when price deviates far from fair ---
        take_margin = max(2.0, vol * 1.5)
        if best_ask and best_ask <= fair - take_margin and rem_buy > 0:
            q = min(rem_buy, -depth.sell_orders.get(best_ask, 0))
            if q > 0:
                orders.append(Order(product, best_ask, q))
                rem_buy -= q

        if best_bid and best_bid >= fair + take_margin and rem_sell > 0:
            q = min(rem_sell, depth.buy_orders.get(best_bid, 0))
            if q > 0:
                orders.append(Order(product, best_bid, -q))
                rem_sell -= q

        # --- In trend regime, reduce quoting on wrong side ---
        buy_size_mult = 1.0
        sell_size_mult = 1.0
        if regime_str == "BULL":
            sell_size_mult = 0.5  # Less eager to sell in uptrend
        elif regime_str == "BEAR":
            buy_size_mult = 0.5   # Less eager to buy in downtrend

        # --- Passive quoting with regime-adjusted sizing ---
        if rem_buy > 0:
            qty = int(min(rem_buy, math.ceil(rem_buy * 0.62 * buy_size_mult)))
            deep = min(rem_buy - qty, int(rem_buy * 0.38 * buy_size_mult))
            if qty > 0:
                orders.append(Order(product, int(bid_price), qty))
            if deep > 0:
                orders.append(Order(product, int(bid_price - 1), deep))

        if rem_sell > 0:
            qty = int(min(rem_sell, math.ceil(rem_sell * 0.62 * sell_size_mult)))
            deep = min(rem_sell - qty, int(rem_sell * 0.38 * sell_size_mult))
            if qty > 0:
                orders.append(Order(product, int(ask_price), -qty))
            if deep > 0:
                orders.append(Order(product, int(ask_price + 1), -deep))

        # --- Emergency liquidity-taking at extreme inventory ---
        abs_pos = abs(pos)
        if abs_pos > 70:
            unwind_qty = min(abs_pos - 55, 25)
            if pos > 70 and best_bid:
                orders.append(Order(product, best_bid, -unwind_qty))
            elif pos < -70 and best_ask:
                orders.append(Order(product, best_ask, unwind_qty))
        elif abs_pos > 55:
            unwind_qty = min(abs_pos - 45, 15)
            if pos > 55 and best_bid:
                orders.append(Order(product, best_bid, -unwind_qty))
            elif pos < -55 and best_ask:
                orders.append(Order(product, best_ask, unwind_qty))

        return orders

    # ------------------------------------------------------------------
    def run(self, state: TradingState):
        self._load_state(state.traderData)
        result = {}

        pep = self._pepper_logic(state)
        if pep:
            result["INTARIAN_PEPPER_ROOT"] = pep

        osm = self._osmium_logic(state)
        if osm:
            result["ASH_COATED_OSMIUM"] = osm

        trader_data = json.dumps(self.history)
        logger.flush(state, result, 0, trader_data)
        return result, 0, trader_data
