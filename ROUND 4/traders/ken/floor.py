import json
from collections import defaultdict
from typing import Dict, List, Optional, Tuple

from datamodel import Order, TradingState


class Trader:
    CFG = {
        "enable_take": True,
        "mm_join_best": True,
        "mm_improve_ticks": 1,
        "hydro_edge": 4,
        "hydro_clip": 18,
        "hydro_take_th": 1.7,
        "hydro_take_size": 16,
        "hydro_momo_k": 0.35,
        "vfe_edge": 2,
        "vfe_clip": 10,
        "vfe_take_th": 1.6,
        "vfe_take_size": 6,
        "vfe_momo_k": 0.15,
        # Spread overlay (manual: Hydrogel - VFE is stationary)
        "spread_mean": 4750.0,
        "spread_std": 35.0,
        "spread_z": 1.10,
        "spread_size": 16,
        # Keep VEV very selective (wings only); mid strikes were loss-making.
        "vev_strikes": [5400, 5500],
        "vev_threshold": 7.0,
        "vev_size": 2,
    }

    POSITION_LIMITS = {
        "HYDROGEL_PACK": 60,
        "VELVETFRUIT_EXTRACT": 60,
        "VEV_4000": 25,
        "VEV_4500": 25,
        "VEV_5400": 25,
        "VEV_5500": 25,
    }

    VEV_TIME_VALUE_FLOOR = {
        4000: 0.0,
        4500: 0.0,
        5400: 19.0,
        5500: 7.0,
    }

    MARK_BUY = {"Mark 67", "Mark 01", "Mark 38"}
    MARK_SELL = {"Mark 49", "Mark 22", "Mark 14"}
    ENABLED_VEV_STRIKES = set(CFG["vev_strikes"])

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
    def _best_bid_ask(order_depth) -> Tuple[Optional[int], Optional[int]]:
        if not order_depth.buy_orders or not order_depth.sell_orders:
            return None, None
        return max(order_depth.buy_orders.keys()), min(order_depth.sell_orders.keys())

    def _mid_price(
        self, state: TradingState, symbol: str, cache: Dict[str, float]
    ) -> Optional[float]:
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
        for symbol in list(mark_signal.keys()):
            mark_signal[symbol] *= 0.85
            if abs(mark_signal[symbol]) < 0.05:
                del mark_signal[symbol]

        for symbol, trades in state.market_trades.items():
            if not trades:
                continue

            signal = mark_signal.get(symbol, 0.0)
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
                mark_signal[symbol] = max(-40.0, min(40.0, signal))

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
        limit = self.POSITION_LIMITS[symbol]
        bid_limit = max(0, limit - position)
        ask_limit = max(0, limit + position)
        if bid_limit <= 0 and ask_limit <= 0:
            return orders

        fair_adj = fair + signal_skew - 0.02 * position
        bid_px = int(fair_adj - edge)
        ask_px = int(fair_adj + edge)
        if bid_px >= ask_px:
            ask_px = bid_px + 1

        if self.CFG.get("mm_join_best", True):
            best_bid, best_ask = self._best_bid_ask(order_depth)
            if best_bid is not None and bid_limit > 0:
                bid_px = max(bid_px, best_bid + self.CFG.get("mm_improve_ticks", 1) - 1)
            if best_ask is not None and ask_limit > 0:
                ask_px = min(ask_px, best_ask - self.CFG.get("mm_improve_ticks", 1) + 1)
            if bid_px >= ask_px:
                ask_px = bid_px + 1

        if bid_limit > 0:
            orders.append(Order(symbol, bid_px, min(clip, bid_limit)))
        if ask_limit > 0:
            orders.append(Order(symbol, ask_px, -min(clip, ask_limit)))

        return orders

    def _take_edge_orders(
        self,
        symbol: str,
        state: TradingState,
        fair: float,
        take_threshold: float,
        max_take: int,
        buy_cap: Optional[int] = None,
        sell_cap: Optional[int] = None,
    ) -> List[Order]:
        orders: List[Order] = []
        depth = state.order_depths.get(symbol)
        if not depth:
            return orders

        position = state.position.get(symbol, 0)
        limit = self.POSITION_LIMITS[symbol]
        if buy_cap is None:
            buy_cap = max(0, limit - position)
        if sell_cap is None:
            sell_cap = max(0, limit + position)

        best_ask = min(depth.sell_orders.keys()) if depth.sell_orders else None
        best_bid = max(depth.buy_orders.keys()) if depth.buy_orders else None

        if best_ask is not None and best_ask <= fair - take_threshold and buy_cap > 0:
            ask_size = abs(depth.sell_orders[best_ask])
            qty = min(max_take, buy_cap, ask_size)
            if qty > 0:
                orders.append(Order(symbol, best_ask, qty))

        if best_bid is not None and best_bid >= fair + take_threshold and sell_cap > 0:
            bid_size = abs(depth.buy_orders[best_bid])
            qty = min(max_take, sell_cap, bid_size)
            if qty > 0:
                orders.append(Order(symbol, best_bid, -qty))

        return orders

    def _remaining_side_capacity(
        self, symbol: str, state: TradingState, planned_orders: List[Order]
    ) -> Tuple[int, int]:
        position = state.position.get(symbol, 0)
        limit = self.POSITION_LIMITS[symbol]
        planned_buy = sum(max(order.quantity, 0) for order in planned_orders)
        planned_sell = sum(max(-order.quantity, 0) for order in planned_orders)
        buy_cap = max(0, limit - position - planned_buy)
        sell_cap = max(0, limit + position - planned_sell)
        return buy_cap, sell_cap

    def _vev_orders(
        self,
        symbol: str,
        state: TradingState,
        vfe_mid: float,
    ) -> List[Order]:
        orders: List[Order] = []
        order_depth = state.order_depths.get(symbol)
        if not order_depth or vfe_mid is None:
            return orders

        bid, ask = self._best_bid_ask(order_depth)
        if bid is None or ask is None:
            return orders

        strike = int(symbol.split("_")[1])
        if strike not in self.ENABLED_VEV_STRIKES:
            return orders

        theo = max(vfe_mid - strike, 0.0) + self.VEV_TIME_VALUE_FLOOR.get(strike, 0.0)
        mid = 0.5 * (bid + ask)
        mispricing = mid - theo

        position = state.position.get(symbol, 0)
        limit = self.POSITION_LIMITS[symbol]
        buy_cap = max(0, limit - position)
        sell_cap = max(0, limit + position)

        threshold = self.CFG["vev_threshold"]
        size = self.CFG["vev_size"]
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

        hydro_mid = self._mid_price(state, "HYDROGEL_PACK", mids)
        if hydro_mid is not None:
            last_hydro = mem["last_mid"].get("HYDROGEL_PACK", hydro_mid)
            hydro_momo = hydro_mid - last_hydro
            hydro_skew = 0.06 * mem["mark_signal"].get("HYDROGEL_PACK", 0.0)
            hydro_skew += self.CFG["hydro_momo_k"] * hydro_momo

            hydro_orders = self._mm_orders(
                "HYDROGEL_PACK",
                state,
                hydro_mid,
                edge=self.CFG["hydro_edge"],
                clip=self.CFG["hydro_clip"],
                signal_skew=hydro_skew,
            )
            result["HYDROGEL_PACK"].extend(hydro_orders)
            if self.CFG["enable_take"]:
                buy_cap, sell_cap = self._remaining_side_capacity(
                    "HYDROGEL_PACK", state, hydro_orders
                )
                result["HYDROGEL_PACK"].extend(
                    self._take_edge_orders(
                        "HYDROGEL_PACK",
                        state,
                        hydro_mid + hydro_skew,
                        take_threshold=self.CFG["hydro_take_th"],
                        max_take=self.CFG["hydro_take_size"],
                        buy_cap=buy_cap,
                        sell_cap=sell_cap,
                    )
                )
            mem["last_mid"]["HYDROGEL_PACK"] = hydro_mid

        vfe_mid = self._mid_price(state, "VELVETFRUIT_EXTRACT", mids)
        if vfe_mid is not None:
            last_vfe = mem["last_mid"].get("VELVETFRUIT_EXTRACT", vfe_mid)
            vfe_momo = vfe_mid - last_vfe
            vfe_skew = 0.05 * mem["mark_signal"].get("VELVETFRUIT_EXTRACT", 0.0)
            vfe_skew += self.CFG["vfe_momo_k"] * vfe_momo

            vfe_orders = self._mm_orders(
                "VELVETFRUIT_EXTRACT",
                state,
                vfe_mid,
                edge=self.CFG["vfe_edge"],
                clip=self.CFG["vfe_clip"],
                signal_skew=vfe_skew,
            )
            result["VELVETFRUIT_EXTRACT"].extend(vfe_orders)
            if self.CFG["enable_take"]:
                buy_cap, sell_cap = self._remaining_side_capacity(
                    "VELVETFRUIT_EXTRACT", state, vfe_orders
                )
                result["VELVETFRUIT_EXTRACT"].extend(
                    self._take_edge_orders(
                        "VELVETFRUIT_EXTRACT",
                        state,
                        vfe_mid + vfe_skew,
                        take_threshold=self.CFG["vfe_take_th"],
                        max_take=self.CFG["vfe_take_size"],
                        buy_cap=buy_cap,
                        sell_cap=sell_cap,
                    )
                )
            mem["last_mid"]["VELVETFRUIT_EXTRACT"] = vfe_mid

            # Spread overlay: trade Hydrogel - VFE mean reversion using top-of-book.
            if hydro_mid is not None:
                spread = hydro_mid - vfe_mid
                spread_mean = self.CFG["spread_mean"]
                spread_std = max(1.0, self.CFG["spread_std"])
                z = (spread - spread_mean) / spread_std
                k = self.CFG["spread_z"]
                size = self.CFG["spread_size"]

                hydro_depth = state.order_depths.get("HYDROGEL_PACK")
                vfe_depth = state.order_depths.get("VELVETFRUIT_EXTRACT")
                if hydro_depth and vfe_depth:
                    h_bid, h_ask = self._best_bid_ask(hydro_depth)
                    v_bid, v_ask = self._best_bid_ask(vfe_depth)
                    if h_bid is not None and h_ask is not None and v_bid is not None and v_ask is not None:
                        # Use remaining capacity after already planned MM/taker orders.
                        h_buy_cap, h_sell_cap = self._remaining_side_capacity(
                            "HYDROGEL_PACK", state, result["HYDROGEL_PACK"]
                        )
                        v_buy_cap, v_sell_cap = self._remaining_side_capacity(
                            "VELVETFRUIT_EXTRACT", state, result["VELVETFRUIT_EXTRACT"]
                        )
                        if z > k:
                            # Spread too wide: sell Hydro (hit bid), buy VFE (lift ask)
                            sell_qty = min(size, h_sell_cap)
                            buy_qty = min(size, v_buy_cap)
                            qty = min(sell_qty, buy_qty)
                            if qty > 0:
                                result["HYDROGEL_PACK"].append(Order("HYDROGEL_PACK", h_bid, -qty))
                                result["VELVETFRUIT_EXTRACT"].append(Order("VELVETFRUIT_EXTRACT", v_ask, qty))
                        elif z < -k:
                            # Spread too tight: buy Hydro (lift ask), sell VFE (hit bid)
                            buy_qty = min(size, h_buy_cap)
                            sell_qty = min(size, v_sell_cap)
                            qty = min(buy_qty, sell_qty)
                            if qty > 0:
                                result["HYDROGEL_PACK"].append(Order("HYDROGEL_PACK", h_ask, qty))
                                result["VELVETFRUIT_EXTRACT"].append(Order("VELVETFRUIT_EXTRACT", v_bid, -qty))

            for strike in self.CFG["vev_strikes"]:
                symbol = f"VEV_{strike}"
                if symbol in state.order_depths:
                    result[symbol].extend(self._vev_orders(symbol, state, vfe_mid))

        return dict(result), 0, self._save_state(mem)
