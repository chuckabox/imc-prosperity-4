import json
from collections import defaultdict
from typing import Dict, List, Tuple

from datamodel import Order, TradingState


class Trader:
    POSITION_LIMITS = {
        "HYDROGEL_PACK": 60,
        "VELVETFRUIT_EXTRACT": 60,
        "VEV_4000": 25,
        "VEV_4500": 25,
        "VEV_5000": 30,
        "VEV_5100": 30,
        "VEV_5200": 30,
        "VEV_5300": 30,
        "VEV_5400": 25,
        "VEV_5500": 25,
        "VEV_6000": 20,
        "VEV_6500": 20,
    }

    VEV_TIME_VALUE_FLOOR = {
        4000: 0.0,
        4500: 0.0,
        5000: 3.0,
        5100: 12.0,
        5200: 36.0,
        5300: 54.0,
        5400: 19.0,
        5500: 7.0,
        6000: 0.5,
        6500: 0.5,
    }

    MARK_BUY = {"Mark 67", "Mark 01", "Mark 38"}
    MARK_SELL = {"Mark 49", "Mark 22", "Mark 14"}
    ENABLED_VEV_STRIKES = {4000, 4500, 5400, 5500}

    def _load_state(self, trader_data: str) -> Dict:
        if not trader_data:
            return {"mark_signal": {}, "last_mid": {}}
        try:
            state = json.loads(trader_data)
            state.setdefault("mark_signal", {})
            state.setdefault("last_mid", {})
            return state
        except Exception:
            return {"mark_signal": {}, "last_mid": {}}

    def _save_state(self, state: Dict) -> str:
        return json.dumps(state, separators=(",", ":"))

    @staticmethod
    def _best_bid_ask(order_depth) -> Tuple[int, int]:
        if not order_depth.buy_orders or not order_depth.sell_orders:
            return None, None
        return max(order_depth.buy_orders.keys()), min(order_depth.sell_orders.keys())

    def _mid_price(self, state: TradingState, symbol: str, cache: Dict[str, float]) -> float:
        if symbol in cache:
            return cache[symbol]
        order_depth = state.order_depths.get(symbol)
        if not order_depth:
            return None
        bid, ask = self._best_bid_ask(order_depth)
        if bid is None or ask is None:
            return None
        mid = 0.5 * (bid + ask)
        cache[symbol] = mid
        return mid

    def _update_mark_signal(self, state: TradingState, mem: Dict) -> None:
        mark_signal = mem["mark_signal"]
        # Exponential decay to prevent stale overfitting.
        for k in list(mark_signal.keys()):
            mark_signal[k] *= 0.85
            if abs(mark_signal[k]) < 0.05:
                del mark_signal[k]

        for symbol, trades in state.market_trades.items():
            if not trades:
                continue
            s = mark_signal.get(symbol, 0.0)
            for t in trades:
                qty = abs(getattr(t, "quantity", 0))
                buyer = getattr(t, "buyer", "")
                seller = getattr(t, "seller", "")
                if buyer in self.MARK_BUY:
                    s += 0.15 * qty
                if seller in self.MARK_SELL:
                    s += 0.10 * qty
                if buyer in self.MARK_SELL:
                    s -= 0.15 * qty
                if seller in self.MARK_BUY:
                    s -= 0.10 * qty
            if abs(s) > 0.01:
                mark_signal[symbol] = max(-40.0, min(40.0, s))

    def _mm_orders(
        self,
        symbol: str,
        state: TradingState,
        fair: float,
        edge: int,
        clip: int,
        signal_skew: float,
    ) -> List[Order]:
        orders: List[Order] = []
        order_depth = state.order_depths.get(symbol)
        if not order_depth:
            return orders

        position = state.position.get(symbol, 0)
        limit = self.POSITION_LIMITS.get(symbol, 20)
        bid_limit = max(0, limit - position)
        ask_limit = max(0, limit + position)
        if bid_limit <= 0 and ask_limit <= 0:
            return orders

        inv_skew = -0.03 * position
        fair_adj = fair + signal_skew + inv_skew

        bid_px = int(fair_adj - edge)
        ask_px = int(fair_adj + edge)
        if bid_px >= ask_px:
            ask_px = bid_px + 1

        if bid_limit > 0:
            orders.append(Order(symbol, bid_px, min(clip, bid_limit)))
        if ask_limit > 0:
            orders.append(Order(symbol, ask_px, -min(clip, ask_limit)))

        return orders

    def _vev_orders(self, symbol: str, state: TradingState, vfe_mid: float) -> List[Order]:
        orders: List[Order] = []
        if symbol not in state.order_depths or vfe_mid is None:
            return orders
        order_depth = state.order_depths[symbol]
        bid, ask = self._best_bid_ask(order_depth)
        if bid is None or ask is None:
            return orders

        k = int(symbol.split("_")[1])
        if k not in self.ENABLED_VEV_STRIKES:
            return orders
        theo = max(vfe_mid - k, 0.0) + self.VEV_TIME_VALUE_FLOOR.get(k, 0.0)
        mid = 0.5 * (bid + ask)
        mispricing = mid - theo

        pos = state.position.get(symbol, 0)
        limit = self.POSITION_LIMITS[symbol]
        buy_cap = max(0, limit - pos)
        sell_cap = max(0, limit + pos)

        # Mean-revert around theo with small threshold to avoid overtrading.
        threshold = 6.0
        size = 3
        if mispricing < -threshold and buy_cap > 0:
            orders.append(Order(symbol, ask, min(size, buy_cap)))
        elif mispricing > threshold and sell_cap > 0:
            orders.append(Order(symbol, bid, -min(size, sell_cap)))

        return orders

    def run(self, state: TradingState):
        mem = self._load_state(state.traderData)
        self._update_mark_signal(state, mem)
        mids: Dict[str, float] = {}
        result: Dict[str, List[Order]] = defaultdict(list)

        vfe_mid = self._mid_price(state, "VELVETFRUIT_EXTRACT", mids)
        hydro_mid = self._mid_price(state, "HYDROGEL_PACK", mids)

        if hydro_mid is not None:
            skew = 0.06 * mem["mark_signal"].get("HYDROGEL_PACK", 0.0)
            result["HYDROGEL_PACK"].extend(
                self._mm_orders("HYDROGEL_PACK", state, hydro_mid, edge=5, clip=10, signal_skew=skew)
            )

        if vfe_mid is not None:
            skew = 0.05 * mem["mark_signal"].get("VELVETFRUIT_EXTRACT", 0.0)
            result["VELVETFRUIT_EXTRACT"].extend(
                self._mm_orders("VELVETFRUIT_EXTRACT", state, vfe_mid, edge=3, clip=12, signal_skew=skew)
            )

        if vfe_mid is not None:
            for symbol in state.order_depths.keys():
                if symbol.startswith("VEV_") and symbol in self.POSITION_LIMITS:
                    result[symbol].extend(self._vev_orders(symbol, state, vfe_mid))

        return dict(result), 0, self._save_state(mem)

