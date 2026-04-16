import json
import math
from typing import Any, Dict, List

from datamodel import Order, Symbol, TradingState


class Logger:
    def __init__(self) -> None:
        self.logs = ""

    def print(self, *objects: Any, sep: str = " ", end: str = "\n") -> None:
        self.logs += sep.join(map(str, objects)) + end

    def flush(
        self,
        state: TradingState,
        orders: Dict[Symbol, List["Order"]],
        conversions: int,
        trader_data: str,
    ) -> None:
        pass


logger = Logger()


class Trader:
    """
    ken_pepper_innov_v1
    - Osmium: v6.6 baseline
    - Pepper: adaptive signal stack
      * trend signal (short-long drift)
      * residual reversion signal (mid - fair)
      * volatility-adaptive execution edges
      * dynamic inventory target by signal confidence
    """

    def __init__(self):
        self.limits = {"ASH_COATED_OSMIUM": 80, "INTARIAN_PEPPER_ROOT": 80}
        self.sf_weights = [0.34296, 0.32058, 0.33645]
        self.sf_intercept = 0.2535
        self.history: Dict[str, Any] = {}

    def update_history(self, trader_data: str):
        if trader_data:
            try:
                self.history = json.loads(trader_data)
            except Exception:
                self.history = {}

    def get_osmium_fair(self, state: TradingState) -> float:
        product = "ASH_COATED_OSMIUM"
        depth = state.order_depths[product]
        best_bid = max(depth.buy_orders.keys()) if depth.buy_orders else 10000
        best_ask = min(depth.sell_orders.keys()) if depth.sell_orders else 10000

        tape_volume = 0.0
        if product in state.market_trades:
            for trade in state.market_trades[product]:
                if trade.price >= 10000:
                    tape_volume += trade.quantity
                else:
                    tape_volume -= trade.quantity

        tape_adj = math.copysign(min(abs(tape_volume) * 0.17, 2.8), tape_volume)
        top_bid_vol = depth.buy_orders.get(best_bid, 0)
        top_ask_vol = -depth.sell_orders.get(best_ask, 0)
        denom = top_bid_vol + top_ask_vol
        imbalance = (top_bid_vol - top_ask_vol) / denom if denom > 0 else 0.0
        imbalance_adj = max(-0.7, min(0.7, imbalance * 0.9))
        return 10000.0 + tape_adj + imbalance_adj

    def _update_pepper_hist(self, mid: float):
        short_hist = self.history.get("pepper_short_hist", [])
        if not isinstance(short_hist, list):
            short_hist = []
        short_hist.append(mid)
        short_hist = short_hist[-3:]
        self.history["pepper_short_hist"] = short_hist

        long_hist = self.history.get("pepper_long_hist", [])
        if not isinstance(long_hist, list):
            long_hist = []
        long_hist.append(mid)
        long_hist = long_hist[-20:]
        self.history["pepper_long_hist"] = long_hist

    def _pepper_vol(self) -> float:
        hist = self.history.get("pepper_long_hist", [])
        if len(hist) < 8:
            return 1.6
        recent = hist[-8:]
        avg = sum(recent) / len(recent)
        var = sum((x - avg) ** 2 for x in recent) / len(recent)
        return max(0.6, min(4.0, math.sqrt(var)))

    def get_pepper_fair(self, state: TradingState) -> float:
        product = "INTARIAN_PEPPER_ROOT"
        depth = state.order_depths[product]
        best_bid = max(depth.buy_orders.keys()) if depth.buy_orders else None
        best_ask = min(depth.sell_orders.keys()) if depth.sell_orders else None
        if best_bid is None and best_ask is None:
            return self.history.get("_pepper_last", 0.0)

        mid = ((best_bid or best_ask) + (best_ask or best_bid)) / 2.0
        self.history["_pepper_last"] = mid
        self._update_pepper_hist(mid)

        short_hist = self.history.get("pepper_short_hist", [])
        if len(short_hist) < 3:
            return mid

        # Base AR(3) predictor.
        fair = self.sf_intercept
        for i in range(3):
            fair += self.sf_weights[i] * short_hist[-(i + 1)]

        # Add smooth trend component from longer history.
        long_hist = self.history.get("pepper_long_hist", [])
        trend = 0.0
        if len(long_hist) >= 10:
            trend = (long_hist[-1] - long_hist[-10]) / 9.0
        fair += max(-1.6, min(1.6, trend * 1.5))

        # Tape confluence.
        momentum = 0
        if product in state.market_trades and state.market_trades[product]:
            for trade in state.market_trades[product]:
                if trade.price >= mid:
                    momentum += trade.quantity
                else:
                    momentum -= trade.quantity
        if momentum != 0:
            direction = 1 if momentum > 0 else -1
            pred_dir = 1 if fair > mid else -1
            if direction == pred_dir:
                fair += direction * 0.8

        return fair

    def run(self, state: TradingState):
        self.update_history(state.traderData)
        result = {}

        # OSMIUM baseline unchanged.
        product = "ASH_COATED_OSMIUM"
        if product in state.order_depths:
            depth = state.order_depths[product]
            position = state.position.get(product, 0)
            limit = self.limits[product]
            best_bid = max(depth.buy_orders.keys()) if depth.buy_orders else 10000
            best_ask = min(depth.sell_orders.keys()) if depth.sell_orders else 10000
            spread = max(1, best_ask - best_bid)
            fair = self.get_osmium_fair(state)
            orders: List["Order"] = []

            rem_buy = limit - position
            rem_sell = limit + position
            base_take = 2.2 if spread <= 2 else 2.65
            inventory_penalty = 0.2 if abs(position) >= 55 else 0.0
            take_margin = base_take + inventory_penalty

            for ask, vol in sorted(depth.sell_orders.items()):
                if ask <= fair - take_margin and rem_buy > 0:
                    qty = min(rem_buy, -vol)
                    orders.append(Order(product, ask, qty))
                    rem_buy -= qty
                    position += qty

            for bid, vol in sorted(depth.buy_orders.items(), reverse=True):
                if bid >= fair + take_margin and rem_sell > 0:
                    qty = min(rem_sell, vol)
                    orders.append(Order(product, bid, -qty))
                    rem_sell -= qty
                    position -= qty

            spread_bias = 0.06 if spread <= 2 else 0.08
            skew_factor = spread_bias if abs(position) < 45 else spread_bias + 0.03
            width = 0.45 if spread <= 2 else 0.6
            bid_price = math.floor(fair - width - (position * skew_factor))
            ask_price = math.ceil(fair + width - (position * skew_factor))
            final_bid = min(best_bid + 1, bid_price)
            final_ask = max(best_ask - 1, ask_price)
            final_bid = min(final_bid, math.floor(fair - 0.5))
            final_ask = max(final_ask, math.ceil(fair + 0.5))

            if rem_buy > 0:
                top_buy = min(rem_buy, math.ceil(rem_buy * 0.68))
                deep_buy = rem_buy - top_buy
                orders.append(Order(product, int(final_bid), top_buy))
                if deep_buy > 0:
                    orders.append(Order(product, int(final_bid - 1), deep_buy))

            if rem_sell > 0:
                top_sell = min(rem_sell, math.ceil(rem_sell * 0.68))
                deep_sell = rem_sell - top_sell
                orders.append(Order(product, int(final_ask), -top_sell))
                if deep_sell > 0:
                    orders.append(Order(product, int(final_ask + 1), -deep_sell))

            result[product] = orders

        # PEPPER innovative logic.
        product = "INTARIAN_PEPPER_ROOT"
        if product in state.order_depths:
            depth = state.order_depths[product]
            pos = state.position.get(product, 0)
            limit = self.limits[product]
            fair = self.get_pepper_fair(state)
            best_bid = max(depth.buy_orders.keys()) if depth.buy_orders else int(fair - 1)
            best_ask = min(depth.sell_orders.keys()) if depth.sell_orders else int(fair + 1)
            mid = (best_bid + best_ask) / 2.0 if best_bid and best_ask else fair
            vol = self._pepper_vol()
            spread = max(1, best_ask - best_bid)
            orders: List["Order"] = []

            # Signal stack.
            trend_sig = 0.0
            long_hist = self.history.get("pepper_long_hist", [])
            if len(long_hist) >= 8:
                trend_sig = (long_hist[-1] - long_hist[-8]) / 7.0
            residual = mid - fair

            # Confidence score combines trend and residual mismatch.
            score = (trend_sig / max(0.8, vol)) - (residual / max(1.0, vol * 1.2))
            score = max(-2.0, min(2.0, score))
            target = int(max(-32, min(32, score * 16)))

            buy_cap = limit - pos
            sell_cap = limit + pos

            # Volatility-adaptive edges.
            base_edge = 0.9 + min(1.5, vol * 0.28)
            buy_edge = base_edge
            sell_edge = base_edge
            if target > 8:
                buy_edge -= 0.25
                sell_edge += 0.45
            elif target < -8:
                buy_edge += 0.45
                sell_edge -= 0.25

            # Hard safety rails.
            if pos >= 68:
                buy_cap = 0
                sell_edge = min(sell_edge, 0.9)
            if pos <= -68:
                sell_cap = 0
                buy_edge = min(buy_edge, 0.9)

            # Taker logic.
            for ask, vol_at_ask in sorted(depth.sell_orders.items()):
                if buy_cap <= 0:
                    break
                if ask <= fair - buy_edge and pos < target + 20:
                    qty = min(abs(vol_at_ask), buy_cap, 18)
                    orders.append(Order(product, ask, qty))
                    buy_cap -= qty
                    pos += qty
                else:
                    break

            for bid, vol_at_bid in sorted(depth.buy_orders.items(), reverse=True):
                if sell_cap <= 0:
                    break
                if bid >= fair + sell_edge and pos > target - 20:
                    qty = min(abs(vol_at_bid), sell_cap, 18)
                    orders.append(Order(product, bid, -qty))
                    sell_cap -= qty
                    pos -= qty
                else:
                    break

            # Passive logic with dynamic bias and size.
            gap = target - pos
            bias = max(-2.0, min(2.0, gap / 14.0))
            quote_w = 1.1 + min(0.6, vol * 0.15) + (0.2 if spread >= 15 else 0.0)
            passive_bid = min(best_bid + 1, int(math.floor(fair - quote_w + bias)))
            passive_ask = max(best_ask - 1, int(math.ceil(fair + quote_w + bias)))

            if buy_cap > 0:
                buy_qty = min(buy_cap, 24 if gap > 0 else 10)
                if pos >= 58:
                    buy_qty = min(buy_qty, 5)
                if buy_qty > 0:
                    orders.append(Order(product, passive_bid, buy_qty))

            if sell_cap > 0:
                sell_qty = min(sell_cap, 24 if gap < 0 else 10)
                if pos <= -58:
                    sell_qty = min(sell_qty, 5)
                if sell_qty > 0:
                    orders.append(Order(product, passive_ask, -sell_qty))

            self.history["pepper_target"] = target
            self.history["pepper_score"] = round(score, 4)
            result[product] = orders

        trader_data = json.dumps(self.history)
        logger.flush(state, result, 0, trader_data)
        return result, 0, trader_data
