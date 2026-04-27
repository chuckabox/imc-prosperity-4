import json
from collections import defaultdict
from typing import Dict, List, Tuple

from datamodel import Order, TradingState


class Trader:
    CFG = {
        "mark_decay": 0.90,
        "mark_cap": 30.0,
        "hydro_edge": 7,
        "hydro_clip": 10,
        "hydro_take_th": 2.5,
        "hydro_take_size": 5,
        "hydro_momo_k": 0.22,
        "vfe_edge": 3,
        "vfe_clip": 9,
        "vfe_take_th": 1.8,
        "vfe_take_size": 4,
        "vfe_momo_k": 0.12,
        "vev_threshold": 8.0,
        "vev_size": 3,
        "vev_strikes": [5400, 5500],
    }

    POSITION_LIMITS = {
        "HYDROGEL_PACK": 90,
        "VELVETFRUIT_EXTRACT": 70,
        "VEV_5400": 35,
        "VEV_5500": 35,
    }

    VEV_TIME_VALUE_FLOOR = {5400: 19.0, 5500: 7.0}
    MARK_BUY = {"Mark 67", "Mark 01", "Mark 38"}
    MARK_SELL = {"Mark 49", "Mark 22", "Mark 14"}

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
        depth = state.order_depths.get(symbol)
        if not depth:
            return None
        bid, ask = self._best_bid_ask(depth)
        if bid is None or ask is None:
            return None
        mid = 0.5 * (bid + ask)
        cache[symbol] = mid
        return mid

    def _update_mark_signal(self, state: TradingState, mem: Dict) -> None:
        signals = mem["mark_signal"]
        decay = self.CFG["mark_decay"]
        cap = self.CFG["mark_cap"]
        for symbol in list(signals.keys()):
            signals[symbol] *= decay
            if abs(signals[symbol]) < 0.05:
                del signals[symbol]

        for symbol, trades in state.market_trades.items():
            if not trades:
                continue
            signal = signals.get(symbol, 0.0)
            for trade in trades:
                qty = abs(getattr(trade, "quantity", 0))
                buyer = getattr(trade, "buyer", "")
                seller = getattr(trade, "seller", "")
                if buyer in self.MARK_BUY:
                    signal += 0.15 * qty
                if seller in self.MARK_SELL:
                    signal += 0.10 * qty
                if buyer in self.MARK_SELL:
                    signal -= 0.15 * qty
                if seller in self.MARK_BUY:
                    signal -= 0.10 * qty
            if abs(signal) > 0.01:
                signals[symbol] = max(-cap, min(cap, signal))

    def _mm_orders(
        self,
        symbol: str,
        state: TradingState,
        fair: float,
        edge: int,
        clip: int,
        skew: float,
    ) -> List[Order]:
        depth = state.order_depths.get(symbol)
        if not depth:
            return []

        pos = state.position.get(symbol, 0)
        limit = self.POSITION_LIMITS[symbol]
        buy_cap = max(0, limit - pos)
        sell_cap = max(0, limit + pos)
        if buy_cap <= 0 and sell_cap <= 0:
            return []

        fair_adj = fair + skew - 0.03 * pos
        bid_px = int(fair_adj - edge)
        ask_px = int(fair_adj + edge)
        if bid_px >= ask_px:
            ask_px = bid_px + 1

        orders: List[Order] = []
        if buy_cap > 0:
            orders.append(Order(symbol, bid_px, min(clip, buy_cap)))
        if sell_cap > 0:
            orders.append(Order(symbol, ask_px, -min(clip, sell_cap)))
        return orders

    def _take_edge_orders(
        self,
        symbol: str,
        state: TradingState,
        fair: float,
        threshold: float,
        max_take: int,
    ) -> List[Order]:
        depth = state.order_depths.get(symbol)
        if not depth:
            return []

        pos = state.position.get(symbol, 0)
        limit = self.POSITION_LIMITS[symbol]
        buy_cap = max(0, limit - pos)
        sell_cap = max(0, limit + pos)
        best_ask = min(depth.sell_orders.keys()) if depth.sell_orders else None
        best_bid = max(depth.buy_orders.keys()) if depth.buy_orders else None

        orders: List[Order] = []
        if best_ask is not None and best_ask <= fair - threshold and buy_cap > 0:
            qty = min(max_take, buy_cap, abs(depth.sell_orders[best_ask]))
            if qty > 0:
                orders.append(Order(symbol, best_ask, qty))
        if best_bid is not None and best_bid >= fair + threshold and sell_cap > 0:
            qty = min(max_take, sell_cap, abs(depth.buy_orders[best_bid]))
            if qty > 0:
                orders.append(Order(symbol, best_bid, -qty))
        return orders

    def _vev_orders(self, symbol: str, state: TradingState, vfe_mid: float) -> List[Order]:
        depth = state.order_depths.get(symbol)
        if not depth or vfe_mid is None:
            return []

        bid, ask = self._best_bid_ask(depth)
        if bid is None or ask is None:
            return []

        strike = int(symbol.split("_")[1])
        theo = max(vfe_mid - strike, 0.0) + self.VEV_TIME_VALUE_FLOOR.get(strike, 0.0)
        mid = 0.5 * (bid + ask)
        mispricing = mid - theo

        pos = state.position.get(symbol, 0)
        limit = self.POSITION_LIMITS[symbol]
        buy_cap = max(0, limit - pos)
        sell_cap = max(0, limit + pos)

        orders: List[Order] = []
        if mispricing < -self.CFG["vev_threshold"] and buy_cap > 0:
            orders.append(Order(symbol, ask, min(self.CFG["vev_size"], buy_cap)))
        if mispricing > self.CFG["vev_threshold"] and sell_cap > 0:
            orders.append(Order(symbol, bid, -min(self.CFG["vev_size"], sell_cap)))
        return orders

    def run(self, state: TradingState):
        mem = self._load_state(state.traderData)
        self._update_mark_signal(state, mem)

        mids: Dict[str, float] = {}
        result: Dict[str, List[Order]] = defaultdict(list)

        hydro_mid = self._mid_price(state, "HYDROGEL_PACK", mids)
        vfe_mid = self._mid_price(state, "VELVETFRUIT_EXTRACT", mids)

        if hydro_mid is not None:
            last = mem["last_mid"].get("HYDROGEL_PACK", hydro_mid)
            momo = hydro_mid - last
            skew = 0.06 * mem["mark_signal"].get("HYDROGEL_PACK", 0.0) + self.CFG["hydro_momo_k"] * momo
            result["HYDROGEL_PACK"].extend(
                self._mm_orders(
                    "HYDROGEL_PACK",
                    state,
                    hydro_mid,
                    self.CFG["hydro_edge"],
                    self.CFG["hydro_clip"],
                    skew,
                )
            )
            result["HYDROGEL_PACK"].extend(
                self._take_edge_orders(
                    "HYDROGEL_PACK",
                    state,
                    hydro_mid + skew,
                    self.CFG["hydro_take_th"],
                    self.CFG["hydro_take_size"],
                )
            )
            mem["last_mid"]["HYDROGEL_PACK"] = hydro_mid

        if vfe_mid is not None:
            last = mem["last_mid"].get("VELVETFRUIT_EXTRACT", vfe_mid)
            momo = vfe_mid - last
            skew = 0.05 * mem["mark_signal"].get("VELVETFRUIT_EXTRACT", 0.0) + self.CFG["vfe_momo_k"] * momo
            result["VELVETFRUIT_EXTRACT"].extend(
                self._mm_orders(
                    "VELVETFRUIT_EXTRACT",
                    state,
                    vfe_mid,
                    self.CFG["vfe_edge"],
                    self.CFG["vfe_clip"],
                    skew,
                )
            )
            result["VELVETFRUIT_EXTRACT"].extend(
                self._take_edge_orders(
                    "VELVETFRUIT_EXTRACT",
                    state,
                    vfe_mid + skew,
                    self.CFG["vfe_take_th"],
                    self.CFG["vfe_take_size"],
                )
            )
            mem["last_mid"]["VELVETFRUIT_EXTRACT"] = vfe_mid

            for symbol in self.CFG["vev_strikes"]:
                vev_symbol = f"VEV_{symbol}"
                if vev_symbol in state.order_depths and vev_symbol in self.POSITION_LIMITS:
                    result[vev_symbol].extend(self._vev_orders(vev_symbol, state, vfe_mid))

        return dict(result), 0, self._save_state(mem)
