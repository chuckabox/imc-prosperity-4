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
        "spread_mean": 4750.0,
        "spread_std": 35.0,
        "spread_z": 1.10,
        "spread_size": 16,
        "spread_passive_size": 16,
        "vev_itm_mm_edge": 14,
        "vev_itm_mm_size": 6,
        "vev_strikes": [5400, 5500],
        "vev_threshold": 7.0,
        "vev_size": 2,
        # Opening-session directional alpha from raw scan.
        "open_short_until": 100000,
        "open_short_start": 5000,
        "open_vfe_trigger": 6.0,
        "open_vfe_size": 18,
        "open_vev_trigger": 8.0,
        "open_vev_size": 6,
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
    PRODUCT_MARK_WEIGHTS: Dict[str, Dict[str, float]] = {
        "HYDROGEL_PACK": {
            "Mark 14": +1.0,
            "Mark 38": -1.0,
        },
        "VELVETFRUIT_EXTRACT": {
            "Mark 55": +1.0,
            "Mark 67": +1.0,
            "Mark 14": -1.0,
            "Mark 49": -1.5,
            "Mark 01": -0.5,
            "Mark 22": -1.0,
        },
    }
    ENABLED_VEV_STRIKES = set(CFG["vev_strikes"])

    def _load_state(self, trader_data: str) -> Dict:
        if not trader_data:
            return {"mark_signal": {}, "last_mid": {}, "open_mid": {}}
        try:
            state = json.loads(trader_data)
            state.setdefault("mark_signal", {})
            state.setdefault("last_mid", {})
            state.setdefault("open_mid", {})
            return state
        except Exception:
            return {"mark_signal": {}, "last_mid": {}, "open_mid": {}}

    def _save_state(self, state: Dict) -> str:
        return json.dumps(state, separators=(",", ":"))

    @staticmethod
    def _best_bid_ask(order_depth) -> Tuple[Optional[int], Optional[int]]:
        if not order_depth.buy_orders or not order_depth.sell_orders:
            return None, None
        return max(order_depth.buy_orders.keys()), min(order_depth.sell_orders.keys())

    def _mid_price(self, state: TradingState, symbol: str, cache: Dict[str, float]) -> Optional[float]:
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
            weights = self.PRODUCT_MARK_WEIGHTS.get(symbol)
            for trade in trades:
                qty = abs(getattr(trade, "quantity", 0))
                buyer = getattr(trade, "buyer", "")
                seller = getattr(trade, "seller", "")
                if weights is not None:
                    if buyer in weights:
                        signal += weights[buyer] * 0.10 * qty
                    if seller in weights:
                        signal -= weights[seller] * 0.10 * qty
                else:
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

    def _mm_orders(self, symbol: str, state: TradingState, fair: float, edge: int, clip: int, signal_skew: float) -> List[Order]:
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

        if self.CFG["mm_join_best"]:
            best_bid, best_ask = self._best_bid_ask(order_depth)
            if best_bid is not None and bid_limit > 0:
                bid_px = max(bid_px, best_bid + self.CFG["mm_improve_ticks"] - 1)
            if best_ask is not None and ask_limit > 0:
                ask_px = min(ask_px, best_ask - self.CFG["mm_improve_ticks"] + 1)
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
            qty = min(max_take, buy_cap, abs(depth.sell_orders[best_ask]))
            if qty > 0:
                orders.append(Order(symbol, best_ask, qty))
        if best_bid is not None and best_bid >= fair + take_threshold and sell_cap > 0:
            qty = min(max_take, sell_cap, abs(depth.buy_orders[best_bid]))
            if qty > 0:
                orders.append(Order(symbol, best_bid, -qty))
        return orders

    def _remaining_side_capacity(self, symbol: str, state: TradingState, planned_orders: List[Order]) -> Tuple[int, int]:
        position = state.position.get(symbol, 0)
        limit = self.POSITION_LIMITS[symbol]
        planned_buy = sum(max(order.quantity, 0) for order in planned_orders)
        planned_sell = sum(max(-order.quantity, 0) for order in planned_orders)
        buy_cap = max(0, limit - position - planned_buy)
        sell_cap = max(0, limit + position - planned_sell)
        return buy_cap, sell_cap

    def _passive_pair_orders(
        self,
        hydro_depth,
        vfe_depth,
        hydro_buy_cap: int,
        hydro_sell_cap: int,
        vfe_buy_cap: int,
        vfe_sell_cap: int,
        direction: str,
        size: int,
    ) -> Tuple[List[Order], List[Order]]:
        hydro_orders: List[Order] = []
        vfe_orders: List[Order] = []
        if size <= 0:
            return hydro_orders, vfe_orders
        h_bid, h_ask = self._best_bid_ask(hydro_depth)
        v_bid, v_ask = self._best_bid_ask(vfe_depth)
        if h_bid is None or h_ask is None or v_bid is None or v_ask is None:
            return hydro_orders, vfe_orders

        if direction == "short_spread":
            qty = min(size, hydro_sell_cap, vfe_buy_cap)
            if qty > 0:
                hydro_px = max(h_bid + 1, h_ask - 1)
                vfe_px = min(v_ask - 1, v_bid + 1)
                if hydro_px > h_bid:
                    hydro_orders.append(Order("HYDROGEL_PACK", hydro_px, -qty))
                if vfe_px < v_ask:
                    vfe_orders.append(Order("VELVETFRUIT_EXTRACT", vfe_px, qty))
        elif direction == "long_spread":
            qty = min(size, hydro_buy_cap, vfe_sell_cap)
            if qty > 0:
                hydro_px = min(h_ask - 1, h_bid + 1)
                vfe_px = max(v_bid + 1, v_ask - 1)
                if hydro_px < h_ask:
                    hydro_orders.append(Order("HYDROGEL_PACK", hydro_px, qty))
                if vfe_px > v_bid:
                    vfe_orders.append(Order("VELVETFRUIT_EXTRACT", vfe_px, -qty))
        return hydro_orders, vfe_orders

    def _vev_itm_mm_orders(self, symbol: str, state: TradingState, vfe_mid: float) -> List[Order]:
        depth = state.order_depths.get(symbol)
        if not depth or vfe_mid is None:
            return []
        bid, ask = self._best_bid_ask(depth)
        if bid is None or ask is None:
            return []
        strike = int(symbol.split("_")[1])
        if strike not in {4000, 4500}:
            return []
        intrinsic = max(vfe_mid - strike, 0.0)
        pos = state.position.get(symbol, 0)
        lim = self.POSITION_LIMITS[symbol]
        buy_cap = max(0, lim - pos)
        sell_cap = max(0, lim + pos)
        edge = self.CFG["vev_itm_mm_edge"]
        size = self.CFG["vev_itm_mm_size"]
        fair = intrinsic - 0.02 * pos
        bid_px = min(ask - 1, max(bid, int(fair - edge)))
        ask_px = max(bid + 1, min(ask, int(fair + edge)))
        orders: List[Order] = []
        if bid_px < ask and buy_cap > 0:
            orders.append(Order(symbol, bid_px, min(size, buy_cap)))
        if ask_px > bid and sell_cap > 0:
            orders.append(Order(symbol, ask_px, -min(size, sell_cap)))
        return orders

    def _vev_orders(self, symbol: str, state: TradingState, vfe_mid: float) -> List[Order]:
        depth = state.order_depths.get(symbol)
        if not depth or vfe_mid is None:
            return []
        bid, ask = self._best_bid_ask(depth)
        if bid is None or ask is None:
            return []
        strike = int(symbol.split("_")[1])
        if strike not in self.ENABLED_VEV_STRIKES:
            return []
        theo = max(vfe_mid - strike, 0.0) + self.VEV_TIME_VALUE_FLOOR.get(strike, 0.0)
        mid = 0.5 * (bid + ask)
        mispricing = mid - theo
        pos = state.position.get(symbol, 0)
        lim = self.POSITION_LIMITS[symbol]
        buy_cap = max(0, lim - pos)
        sell_cap = max(0, lim + pos)
        orders: List[Order] = []
        if mispricing < -self.CFG["vev_threshold"] and buy_cap > 0:
            orders.append(Order(symbol, ask, min(self.CFG["vev_size"], buy_cap)))
        elif mispricing > self.CFG["vev_threshold"] and sell_cap > 0:
            orders.append(Order(symbol, bid, -min(self.CFG["vev_size"], sell_cap)))
        return orders

    def _opening_short_bias(self, state: TradingState, mem: Dict, symbol: str, mid: float) -> float:
        if state.timestamp < self.CFG["open_short_start"] or state.timestamp > self.CFG["open_short_until"]:
            return 0.0
        open_mid = mem["open_mid"].setdefault(symbol, mid)
        return mid - open_mid

    def run(self, state: TradingState):
        mem = self._load_state(state.traderData)
        self._update_mark_signal(state, mem)
        mids: Dict[str, float] = {}
        result: Dict[str, List[Order]] = defaultdict(list)

        hydro_mid = self._mid_price(state, "HYDROGEL_PACK", mids)
        if hydro_mid is not None:
            mem["open_mid"].setdefault("HYDROGEL_PACK", hydro_mid)
            last_hydro = mem["last_mid"].get("HYDROGEL_PACK", hydro_mid)
            hydro_momo = hydro_mid - last_hydro
            hydro_skew = 0.06 * mem["mark_signal"].get("HYDROGEL_PACK", 0.0) + self.CFG["hydro_momo_k"] * hydro_momo
            hydro_orders = self._mm_orders("HYDROGEL_PACK", state, hydro_mid, self.CFG["hydro_edge"], self.CFG["hydro_clip"], hydro_skew)
            result["HYDROGEL_PACK"].extend(hydro_orders)
            if self.CFG["enable_take"]:
                buy_cap, sell_cap = self._remaining_side_capacity("HYDROGEL_PACK", state, hydro_orders)
                result["HYDROGEL_PACK"].extend(
                    self._take_edge_orders("HYDROGEL_PACK", state, hydro_mid + hydro_skew, self.CFG["hydro_take_th"], self.CFG["hydro_take_size"], buy_cap, sell_cap)
                )
            mem["last_mid"]["HYDROGEL_PACK"] = hydro_mid

        vfe_mid = self._mid_price(state, "VELVETFRUIT_EXTRACT", mids)
        if vfe_mid is not None:
            mem["open_mid"].setdefault("VELVETFRUIT_EXTRACT", vfe_mid)
            last_vfe = mem["last_mid"].get("VELVETFRUIT_EXTRACT", vfe_mid)
            vfe_momo = vfe_mid - last_vfe
            vfe_skew = 0.05 * mem["mark_signal"].get("VELVETFRUIT_EXTRACT", 0.0) + self.CFG["vfe_momo_k"] * vfe_momo
            # Early session often sells off from opening highs; lean quotes downward.
            open_gap = self._opening_short_bias(state, mem, "VELVETFRUIT_EXTRACT", vfe_mid)
            if open_gap > self.CFG["open_vfe_trigger"]:
                vfe_skew -= 4.0 + 0.25 * open_gap

            vfe_orders = self._mm_orders("VELVETFRUIT_EXTRACT", state, vfe_mid, self.CFG["vfe_edge"], self.CFG["vfe_clip"], vfe_skew)
            result["VELVETFRUIT_EXTRACT"].extend(vfe_orders)
            if self.CFG["enable_take"]:
                buy_cap, sell_cap = self._remaining_side_capacity("VELVETFRUIT_EXTRACT", state, vfe_orders)
                result["VELVETFRUIT_EXTRACT"].extend(
                    self._take_edge_orders("VELVETFRUIT_EXTRACT", state, vfe_mid + vfe_skew, self.CFG["vfe_take_th"], self.CFG["vfe_take_size"], buy_cap, sell_cap)
                )
                # Explicit early-session directional short when VFE opens rich.
                if open_gap > self.CFG["open_vfe_trigger"]:
                    depth = state.order_depths.get("VELVETFRUIT_EXTRACT")
                    if depth and depth.buy_orders:
                        _, sell_cap = self._remaining_side_capacity("VELVETFRUIT_EXTRACT", state, result["VELVETFRUIT_EXTRACT"])
                        best_bid = max(depth.buy_orders.keys())
                        qty = min(self.CFG["open_vfe_size"], sell_cap, abs(depth.buy_orders[best_bid]))
                        if qty > 0:
                            result["VELVETFRUIT_EXTRACT"].append(Order("VELVETFRUIT_EXTRACT", best_bid, -qty))
            mem["last_mid"]["VELVETFRUIT_EXTRACT"] = vfe_mid

            if hydro_mid is not None:
                spread = hydro_mid - vfe_mid
                z = (spread - self.CFG["spread_mean"]) / max(1.0, self.CFG["spread_std"])
                size = self.CFG["spread_size"]
                passive_size = self.CFG["spread_passive_size"]
                hydro_depth = state.order_depths.get("HYDROGEL_PACK")
                vfe_depth = state.order_depths.get("VELVETFRUIT_EXTRACT")
                if hydro_depth and vfe_depth:
                    h_bid, h_ask = self._best_bid_ask(hydro_depth)
                    v_bid, v_ask = self._best_bid_ask(vfe_depth)
                    if h_bid is not None and h_ask is not None and v_bid is not None and v_ask is not None:
                        h_buy_cap, h_sell_cap = self._remaining_side_capacity("HYDROGEL_PACK", state, result["HYDROGEL_PACK"])
                        v_buy_cap, v_sell_cap = self._remaining_side_capacity("VELVETFRUIT_EXTRACT", state, result["VELVETFRUIT_EXTRACT"])
                        if z > self.CFG["spread_z"]:
                            qty = min(size, h_sell_cap, v_buy_cap)
                            if qty > 0:
                                result["HYDROGEL_PACK"].append(Order("HYDROGEL_PACK", h_bid, -qty))
                                result["VELVETFRUIT_EXTRACT"].append(Order("VELVETFRUIT_EXTRACT", v_ask, qty))
                            p_h, p_v = self._passive_pair_orders(hydro_depth, vfe_depth, h_buy_cap, h_sell_cap - qty, v_buy_cap - qty, v_sell_cap, "short_spread", passive_size)
                            result["HYDROGEL_PACK"].extend(p_h)
                            result["VELVETFRUIT_EXTRACT"].extend(p_v)
                        elif z < -self.CFG["spread_z"]:
                            qty = min(size, h_buy_cap, v_sell_cap)
                            if qty > 0:
                                result["HYDROGEL_PACK"].append(Order("HYDROGEL_PACK", h_ask, qty))
                                result["VELVETFRUIT_EXTRACT"].append(Order("VELVETFRUIT_EXTRACT", v_bid, -qty))
                            p_h, p_v = self._passive_pair_orders(hydro_depth, vfe_depth, h_buy_cap - qty, h_sell_cap, v_buy_cap, v_sell_cap - qty, "long_spread", passive_size)
                            result["HYDROGEL_PACK"].extend(p_h)
                            result["VELVETFRUIT_EXTRACT"].extend(p_v)

            # Deep ITM maker overlay
            for sym in ("VEV_4000", "VEV_4500"):
                if sym in state.order_depths:
                    result[sym].extend(self._vev_itm_mm_orders(sym, state, vfe_mid))

            # Early-session VFE weakness can compress wings too, but keep it tiny.
            open_gap = self._opening_short_bias(state, mem, "VELVETFRUIT_EXTRACT", vfe_mid)
            for strike in self.CFG["vev_strikes"]:
                sym = f"VEV_{strike}"
                if sym in state.order_depths:
                    result[sym].extend(self._vev_orders(sym, state, vfe_mid))
                    if open_gap > self.CFG["open_vev_trigger"] and state.timestamp <= self.CFG["open_short_until"]:
                        depth = state.order_depths[sym]
                        if depth.buy_orders:
                            pos = state.position.get(sym, 0)
                            sell_cap = max(0, self.POSITION_LIMITS[sym] + pos)
                            best_bid = max(depth.buy_orders.keys())
                            qty = min(self.CFG["open_vev_size"], sell_cap, abs(depth.buy_orders[best_bid]))
                            if qty > 0:
                                result[sym].append(Order(sym, best_bid, -qty))

        return dict(result), 0, self._save_state(mem)
