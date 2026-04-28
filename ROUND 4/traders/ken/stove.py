import json
from collections import defaultdict
from typing import Dict, List, Optional, Tuple

from datamodel import Order, TradingState


class Trader:
    CFG = {
        "mm_join_best": True,
        "mm_improve_ticks": 1,
        "hydro_edge": 4,
        "hydro_clip": 18,
        "hydro_take_th": 1.7,
        "hydro_take_size": 16,
        "hydro_momo_k": 0.20,
        "vfe_edge": 2,
        "vfe_clip": 10,
        "vfe_take_th": 1.6,
        "vfe_take_size": 6,
        "vfe_momo_k": 0.10,
        "spread_mean": 4750.0,
        "spread_std": 35.0,
        "spread_z": 1.10,
        "spread_size": 16,
        "spread_passive_size": 16,
        "open_short_start": 5000,
        "open_short_until": 90000,
        "open_vfe_trigger": 4.0,
        "open_vfe_size": 24,
        "late_rebound_start": 600000,
        "late_vfe_trigger": 8.0,
        "late_vfe_size": 18,
        "vev_strikes": [5400, 5500],
        "vev_threshold": 7.0,
        "vev_size": 2,
    }

    POSITION_LIMITS = {
        "HYDROGEL_PACK": 60,
        "VELVETFRUIT_EXTRACT": 60,
        "VEV_5400": 25,
        "VEV_5500": 25,
    }

    VEV_TIME_VALUE_FLOOR = {5400: 19.0, 5500: 7.0}

    MARK_BUY = {"Mark 67", "Mark 01", "Mark 38"}
    MARK_SELL = {"Mark 49", "Mark 22", "Mark 14"}

    def _load_state(self, trader_data: str) -> Dict:
        if not trader_data:
            return {"mark_signal": {}, "last_mid": {}, "open_mid": {}, "low_mid": {}, "high_mid": {}, "last_ts": -1}
        try:
            state = json.loads(trader_data)
            state.setdefault("mark_signal", {})
            state.setdefault("last_mid", {})
            state.setdefault("open_mid", {})
            state.setdefault("low_mid", {})
            state.setdefault("high_mid", {})
            state.setdefault("last_ts", -1)
            return state
        except Exception:
            return {"mark_signal": {}, "last_mid": {}, "open_mid": {}, "low_mid": {}, "high_mid": {}, "last_ts": -1}

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
        depth = state.order_depths.get(symbol)
        if not depth:
            return None
        bid, ask = self._best_bid_ask(depth)
        if bid is None or ask is None:
            return None
        mid = 0.5 * (bid + ask)
        cache[symbol] = mid
        return mid

    def _update_session_extremes(self, state: TradingState, mem: Dict, mids: Dict[str, float]) -> None:
        if mem.get("last_ts", -1) >= 0 and state.timestamp < mem["last_ts"]:
            mem["open_mid"] = {}
            mem["low_mid"] = {}
            mem["high_mid"] = {}
        mem["last_ts"] = state.timestamp
        for sym, mid in mids.items():
            if sym not in mem["open_mid"]:
                mem["open_mid"][sym] = mid
                mem["low_mid"][sym] = mid
                mem["high_mid"][sym] = mid
            mem["low_mid"][sym] = min(mem["low_mid"][sym], mid)
            mem["high_mid"][sym] = max(mem["high_mid"][sym], mid)

    def _update_mark_signal(self, state: TradingState, mem: Dict) -> None:
        ms = mem["mark_signal"]
        for sym in list(ms.keys()):
            ms[sym] *= 0.85
            if abs(ms[sym]) < 0.05:
                del ms[sym]
        for sym, trades in state.market_trades.items():
            if not trades:
                continue
            signal = ms.get(sym, 0.0)
            for t in trades:
                qty = abs(getattr(t, "quantity", 0))
                buyer = getattr(t, "buyer", "")
                seller = getattr(t, "seller", "")
                if buyer in self.MARK_BUY:
                    signal += 0.15 * qty
                if seller in self.MARK_SELL:
                    signal += 0.10 * qty
                if buyer in self.MARK_SELL:
                    signal -= 0.15 * qty
                if seller in self.MARK_BUY:
                    signal -= 0.10 * qty
            if abs(signal) > 0.01:
                ms[sym] = max(-40.0, min(40.0, signal))

    def _mm_orders(self, symbol: str, state: TradingState, fair: float, edge: int, clip: int, skew: float) -> List[Order]:
        depth = state.order_depths.get(symbol)
        if not depth:
            return []
        pos = state.position.get(symbol, 0)
        lim = self.POSITION_LIMITS[symbol]
        buy_cap = max(0, lim - pos)
        sell_cap = max(0, lim + pos)
        if buy_cap <= 0 and sell_cap <= 0:
            return []
        fair_adj = fair + skew - 0.02 * pos
        bid_px = int(fair_adj - edge)
        ask_px = int(fair_adj + edge)
        if bid_px >= ask_px:
            ask_px = bid_px + 1
        if self.CFG["mm_join_best"]:
            best_bid, best_ask = self._best_bid_ask(depth)
            if best_bid is not None and buy_cap > 0:
                bid_px = max(bid_px, best_bid + self.CFG["mm_improve_ticks"] - 1)
            if best_ask is not None and sell_cap > 0:
                ask_px = min(ask_px, best_ask - self.CFG["mm_improve_ticks"] + 1)
            if bid_px >= ask_px:
                ask_px = bid_px + 1
        orders: List[Order] = []
        if buy_cap > 0:
            orders.append(Order(symbol, bid_px, min(clip, buy_cap)))
        if sell_cap > 0:
            orders.append(Order(symbol, ask_px, -min(clip, sell_cap)))
        return orders

    def _remaining_side_capacity(self, symbol: str, state: TradingState, planned_orders: List[Order]) -> Tuple[int, int]:
        pos = state.position.get(symbol, 0)
        lim = self.POSITION_LIMITS[symbol]
        planned_buy = sum(max(o.quantity, 0) for o in planned_orders)
        planned_sell = sum(max(-o.quantity, 0) for o in planned_orders)
        return max(0, lim - pos - planned_buy), max(0, lim + pos - planned_sell)

    def _take_edge_orders(
        self,
        symbol: str,
        state: TradingState,
        fair: float,
        threshold: float,
        max_take: int,
        buy_cap: Optional[int] = None,
        sell_cap: Optional[int] = None,
    ) -> List[Order]:
        depth = state.order_depths.get(symbol)
        if not depth:
            return []
        pos = state.position.get(symbol, 0)
        lim = self.POSITION_LIMITS[symbol]
        if buy_cap is None:
            buy_cap = max(0, lim - pos)
        if sell_cap is None:
            sell_cap = max(0, lim + pos)
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
        h_orders: List[Order] = []
        v_orders: List[Order] = []
        if size <= 0:
            return h_orders, v_orders
        h_bid, h_ask = self._best_bid_ask(hydro_depth)
        v_bid, v_ask = self._best_bid_ask(vfe_depth)
        if h_bid is None or h_ask is None or v_bid is None or v_ask is None:
            return h_orders, v_orders
        if direction == "short_spread":
            qty = min(size, hydro_sell_cap, vfe_buy_cap)
            if qty > 0:
                h_px = max(h_bid + 1, h_ask - 1)
                v_px = min(v_ask - 1, v_bid + 1)
                if h_px > h_bid:
                    h_orders.append(Order("HYDROGEL_PACK", h_px, -qty))
                if v_px < v_ask:
                    v_orders.append(Order("VELVETFRUIT_EXTRACT", v_px, qty))
        else:
            qty = min(size, hydro_buy_cap, vfe_sell_cap)
            if qty > 0:
                h_px = min(h_ask - 1, h_bid + 1)
                v_px = max(v_bid + 1, v_ask - 1)
                if h_px < h_ask:
                    h_orders.append(Order("HYDROGEL_PACK", h_px, qty))
                if v_px > v_bid:
                    v_orders.append(Order("VELVETFRUIT_EXTRACT", v_px, -qty))
        return h_orders, v_orders

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
        mis = mid - theo
        pos = state.position.get(symbol, 0)
        lim = self.POSITION_LIMITS[symbol]
        buy_cap = max(0, lim - pos)
        sell_cap = max(0, lim + pos)
        orders: List[Order] = []
        if mis < -self.CFG["vev_threshold"] and buy_cap > 0:
            orders.append(Order(symbol, ask, min(self.CFG["vev_size"], buy_cap)))
        elif mis > self.CFG["vev_threshold"] and sell_cap > 0:
            orders.append(Order(symbol, bid, -min(self.CFG["vev_size"], sell_cap)))
        return orders

    def run(self, state: TradingState):
        mem = self._load_state(state.traderData)
        self._update_mark_signal(state, mem)
        result: Dict[str, List[Order]] = defaultdict(list)
        mids: Dict[str, float] = {}

        hydro_mid = self._mid_price(state, "HYDROGEL_PACK", mids)
        vfe_mid = self._mid_price(state, "VELVETFRUIT_EXTRACT", mids)
        if hydro_mid is not None:
            mids["HYDROGEL_PACK"] = hydro_mid
        if vfe_mid is not None:
            mids["VELVETFRUIT_EXTRACT"] = vfe_mid
        self._update_session_extremes(state, mem, mids)

        if hydro_mid is not None:
            mem["open_mid"].setdefault("HYDROGEL_PACK", hydro_mid)
            mem["low_mid"].setdefault("HYDROGEL_PACK", hydro_mid)
            mem["high_mid"].setdefault("HYDROGEL_PACK", hydro_mid)
            mem["low_mid"]["HYDROGEL_PACK"] = min(mem["low_mid"]["HYDROGEL_PACK"], hydro_mid)
            mem["high_mid"]["HYDROGEL_PACK"] = max(mem["high_mid"]["HYDROGEL_PACK"], hydro_mid)
            last = mem["last_mid"].get("HYDROGEL_PACK", hydro_mid)
            momo = hydro_mid - last
            skew = 0.04 * mem["mark_signal"].get("HYDROGEL_PACK", 0.0) + self.CFG["hydro_momo_k"] * momo
            # Early weakness in Hydrogel tends to mean-revert upward.
            if state.timestamp <= 60000 and hydro_mid <= mem["open_mid"]["HYDROGEL_PACK"] - 10:
                skew += 4.0
            h_orders = self._mm_orders("HYDROGEL_PACK", state, hydro_mid, self.CFG["hydro_edge"], self.CFG["hydro_clip"], skew)
            result["HYDROGEL_PACK"].extend(h_orders)
            buy_cap, sell_cap = self._remaining_side_capacity("HYDROGEL_PACK", state, h_orders)
            result["HYDROGEL_PACK"].extend(
                self._take_edge_orders("HYDROGEL_PACK", state, hydro_mid + skew, self.CFG["hydro_take_th"], self.CFG["hydro_take_size"], buy_cap, sell_cap)
            )
            mem["last_mid"]["HYDROGEL_PACK"] = hydro_mid

        if vfe_mid is not None:
            mem["open_mid"].setdefault("VELVETFRUIT_EXTRACT", vfe_mid)
            mem["low_mid"].setdefault("VELVETFRUIT_EXTRACT", vfe_mid)
            mem["high_mid"].setdefault("VELVETFRUIT_EXTRACT", vfe_mid)
            mem["low_mid"]["VELVETFRUIT_EXTRACT"] = min(mem["low_mid"]["VELVETFRUIT_EXTRACT"], vfe_mid)
            mem["high_mid"]["VELVETFRUIT_EXTRACT"] = max(mem["high_mid"]["VELVETFRUIT_EXTRACT"], vfe_mid)
            last = mem["last_mid"].get("VELVETFRUIT_EXTRACT", vfe_mid)
            momo = vfe_mid - last
            skew = 0.06 * mem["mark_signal"].get("VELVETFRUIT_EXTRACT", 0.0) + self.CFG["vfe_momo_k"] * momo
            # New alpha family: explicit regime switch.
            if self.CFG["open_short_start"] <= state.timestamp <= self.CFG["open_short_until"]:
                open_gap = vfe_mid - mem["open_mid"]["VELVETFRUIT_EXTRACT"]
                if open_gap > self.CFG["open_vfe_trigger"]:
                    skew -= 5.0 + 0.25 * open_gap
            elif state.timestamp >= self.CFG["late_rebound_start"]:
                rebound = mem["low_mid"]["VELVETFRUIT_EXTRACT"] + self.CFG["late_vfe_trigger"] - vfe_mid
                if rebound > 0:
                    skew += 2.0 + 0.15 * rebound

            v_orders = self._mm_orders("VELVETFRUIT_EXTRACT", state, vfe_mid, self.CFG["vfe_edge"], self.CFG["vfe_clip"], skew)
            result["VELVETFRUIT_EXTRACT"].extend(v_orders)
            buy_cap, sell_cap = self._remaining_side_capacity("VELVETFRUIT_EXTRACT", state, v_orders)
            result["VELVETFRUIT_EXTRACT"].extend(
                self._take_edge_orders("VELVETFRUIT_EXTRACT", state, vfe_mid + skew, self.CFG["vfe_take_th"], self.CFG["vfe_take_size"], buy_cap, sell_cap)
            )
            if self.CFG["open_short_start"] <= state.timestamp <= self.CFG["open_short_until"]:
                open_gap = vfe_mid - mem["open_mid"]["VELVETFRUIT_EXTRACT"]
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
                hydro_depth = state.order_depths.get("HYDROGEL_PACK")
                vfe_depth = state.order_depths.get("VELVETFRUIT_EXTRACT")
                if hydro_depth and vfe_depth:
                    h_bid, h_ask = self._best_bid_ask(hydro_depth)
                    v_bid, v_ask = self._best_bid_ask(vfe_depth)
                    if h_bid is not None and h_ask is not None and v_bid is not None and v_ask is not None:
                        h_buy_cap, h_sell_cap = self._remaining_side_capacity("HYDROGEL_PACK", state, result["HYDROGEL_PACK"])
                        v_buy_cap, v_sell_cap = self._remaining_side_capacity("VELVETFRUIT_EXTRACT", state, result["VELVETFRUIT_EXTRACT"])
                        if z > self.CFG["spread_z"]:
                            qty = min(self.CFG["spread_size"], h_sell_cap, v_buy_cap)
                            if qty > 0:
                                result["HYDROGEL_PACK"].append(Order("HYDROGEL_PACK", h_bid, -qty))
                                result["VELVETFRUIT_EXTRACT"].append(Order("VELVETFRUIT_EXTRACT", v_ask, qty))
                            p_h, p_v = self._passive_pair_orders(hydro_depth, vfe_depth, h_buy_cap, h_sell_cap - qty, v_buy_cap - qty, v_sell_cap, "short_spread", self.CFG["spread_passive_size"])
                            result["HYDROGEL_PACK"].extend(p_h)
                            result["VELVETFRUIT_EXTRACT"].extend(p_v)
                        elif z < -self.CFG["spread_z"]:
                            qty = min(self.CFG["spread_size"], h_buy_cap, v_sell_cap)
                            if qty > 0:
                                result["HYDROGEL_PACK"].append(Order("HYDROGEL_PACK", h_ask, qty))
                                result["VELVETFRUIT_EXTRACT"].append(Order("VELVETFRUIT_EXTRACT", v_bid, -qty))
                            p_h, p_v = self._passive_pair_orders(hydro_depth, vfe_depth, h_buy_cap - qty, h_sell_cap, v_buy_cap, v_sell_cap - qty, "long_spread", self.CFG["spread_passive_size"])
                            result["HYDROGEL_PACK"].extend(p_h)
                            result["VELVETFRUIT_EXTRACT"].extend(p_v)

            for strike in self.CFG["vev_strikes"]:
                sym = f"VEV_{strike}"
                if sym in state.order_depths:
                    result[sym].extend(self._vev_orders(sym, state, vfe_mid))

        return dict(result), 0, self._save_state(mem)
