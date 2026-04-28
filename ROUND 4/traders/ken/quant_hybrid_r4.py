import json
from collections import defaultdict
from typing import Dict, List, Tuple

from datamodel import Order, TradingState


class Trader:
    CFG = {
        "hydro_edge": 7,
        "hydro_clip": 14,
        "hydro_momo_k": 0.22,
        "hydro_take_th": 3.0,
        "hydro_take_size": 8,
        "vfe_edge": 3,
        "vfe_clip": 14,
        "vfe_momo_k": 0.18,
        "vfe_take_th": 2.0,
        "vfe_take_size": 8,
        "vev_strikes": [5000, 5200, 5300, 5400, 5500],
        "vev_threshold": 7.0,
        "vev_size": 6,
        "mark_decay": 0.90,
        "mark_cap": 30.0,
    }

    POSITION_LIMITS = {
        "HYDROGEL_PACK": 140,
        "VELVETFRUIT_EXTRACT": 140,
        "VEV_5000": 70,
        "VEV_5200": 70,
        "VEV_5300": 70,
        "VEV_5400": 60,
        "VEV_5500": 50,
    }

    VEV_TIME_VALUE_FLOOR = {5000: 3.0, 5100: 12.0, 5200: 36.0, 5300: 54.0, 5400: 19.0, 5500: 7.0, 6000: 0.5, 6500: 0.5}
    MARK_BUY = {"Mark 67", "Mark 01", "Mark 38"}
    MARK_SELL = {"Mark 49", "Mark 22", "Mark 14"}

    def _load_state(self, trader_data: str) -> Dict:
        if not trader_data:
            return {"mark_signal": {}, "last_mid": {}, "open_mid": {}, "low_mid": {}, "high_mid": {}, "last_ts": -1}
        try:
            s = json.loads(trader_data)
            s.setdefault("mark_signal", {})
            s.setdefault("last_mid", {})
            s.setdefault("open_mid", {})
            s.setdefault("low_mid", {})
            s.setdefault("high_mid", {})
            s.setdefault("last_ts", -1)
            return s
        except Exception:
            return {"mark_signal": {}, "last_mid": {}, "open_mid": {}, "low_mid": {}, "high_mid": {}, "last_ts": -1}

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
        ms = mem["mark_signal"]
        decay = self.CFG["mark_decay"]
        cap = self.CFG["mark_cap"]
        for k in list(ms.keys()):
            ms[k] *= decay
            if abs(ms[k]) < 0.05:
                del ms[k]
        for symbol, trades in state.market_trades.items():
            if not trades:
                continue
            s = ms.get(symbol, 0.0)
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
                ms[symbol] = max(-cap, min(cap, s))

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

    def _session_bias(self, symbol: str, state: TradingState, mem: Dict, mid: float, momo: float) -> float:
        ts = state.timestamp
        open_mid = mem["open_mid"].get(symbol, mid)
        low_mid = mem["low_mid"].get(symbol, mid)
        high_mid = mem["high_mid"].get(symbol, mid)

        # Early-round shape from raw data:
        # - VFE + mid VEVs: usually offered early, then rebound after washout.
        # - HP: often mean reverts upward after early dip.
        if symbol == "VELVETFRUIT_EXTRACT":
            if ts <= 25000:
                return -0.35 * max(0.0, open_mid - low_mid + 2.0)
            if 25000 < ts <= 85000 and mid <= low_mid + 10 and momo > 0:
                return 5.0
            if 220000 <= ts <= 420000:
                return -2.0
            if 520000 <= ts <= 850000:
                return 2.0
            return 0.0

        if symbol == "HYDROGEL_PACK":
            if ts <= 60000 and mid <= open_mid - 10:
                return 6.0
            if ts <= 60000 and mid >= open_mid + 18:
                return -6.0
            if mid <= low_mid + 8 and momo > 0:
                return 5.0
            if mid >= high_mid - 8 and momo < 0:
                return -4.0
            return 0.0

        # VEVs amplify VFE directional bias
        if symbol.startswith("VEV_"):
            if ts <= 25000:
                return -2.0
            if 30000 < ts <= 90000 and momo > 0:
                return 1.5
            if 220000 <= ts <= 420000:
                return -1.5
            if 520000 <= ts <= 850000:
                return 1.5
        return 0.0

    def _mm_orders(self, symbol: str, state: TradingState, fair: float, edge: int, clip: int, skew: float) -> List[Order]:
        orders: List[Order] = []
        depth = state.order_depths.get(symbol)
        if not depth:
            return orders
        pos = state.position.get(symbol, 0)
        lim = self.POSITION_LIMITS.get(symbol, 20)
        bid_cap = max(0, lim - pos)
        ask_cap = max(0, lim + pos)
        if bid_cap <= 0 and ask_cap <= 0:
            return orders
        fair_adj = fair + skew - 0.04 * pos
        bid_px = int(fair_adj - edge)
        ask_px = int(fair_adj + edge)
        best_bid = max(depth.buy_orders.keys()) if depth.buy_orders else None
        best_ask = min(depth.sell_orders.keys()) if depth.sell_orders else None
        if best_bid is not None:
            bid_px = max(bid_px, best_bid + 1)
        if best_ask is not None:
            ask_px = min(ask_px, best_ask - 1)
        if best_bid is not None and best_ask is not None and bid_px >= ask_px:
            bid_px = best_bid
            ask_px = best_ask
        if bid_cap > 0 and bid_px > 0:
            orders.append(Order(symbol, bid_px, min(clip, bid_cap)))
        if ask_cap > 0 and ask_px > 0:
            orders.append(Order(symbol, ask_px, -min(clip, ask_cap)))
        return orders

    def _take_edge_orders(self, symbol: str, state: TradingState, fair: float, threshold: float, max_take: int) -> List[Order]:
        depth = state.order_depths.get(symbol)
        if not depth:
            return []
        orders: List[Order] = []
        pos = state.position.get(symbol, 0)
        lim = self.POSITION_LIMITS.get(symbol, 20)
        buy_cap = max(0, lim - pos)
        sell_cap = max(0, lim + pos)
        best_ask = min(depth.sell_orders.keys()) if depth.sell_orders else None
        best_bid = max(depth.buy_orders.keys()) if depth.buy_orders else None
        if best_ask is not None and best_ask <= fair - threshold and buy_cap > 0:
            qty = min(max_take, buy_cap, abs(depth.sell_orders[best_ask]))
            if qty > 0:
                orders.append(Order(symbol, best_ask, qty))
        if best_bid is not None and best_bid >= fair + threshold and sell_cap > 0:
            qty = min(max_take, sell_cap, abs(depth.buy_orders[best_bid]))
            if qty > 0:
                orders.append(Order(symbol, best_bid, -qty))
        return orders

    def _vev_orders(self, symbol: str, state: TradingState, vfe_mid: float, skew: float) -> List[Order]:
        depth = state.order_depths.get(symbol)
        if not depth or vfe_mid is None:
            return []
        k = int(symbol.split("_")[1])
        enabled = set(self.CFG["vev_strikes"])
        if k not in enabled:
            return []
        bid, ask = self._best_bid_ask(depth)
        if bid is None or ask is None:
            return []
        theo = max(vfe_mid - k, 0.0) + self.VEV_TIME_VALUE_FLOOR.get(k, 0.0)
        mid = 0.5 * (bid + ask)
        mispricing = mid - theo
        pos = state.position.get(symbol, 0)
        lim = self.POSITION_LIMITS[symbol]
        buy_cap = max(0, lim - pos)
        sell_cap = max(0, lim + pos)
        th = self.CFG["vev_threshold"]
        size = self.CFG["vev_size"]
        out: List[Order] = []
        fair = theo + skew
        if mispricing < -th and buy_cap > 0:
            out.append(Order(symbol, ask, min(size, buy_cap)))
        if mispricing > th and sell_cap > 0:
            out.append(Order(symbol, bid, -min(size, sell_cap)))
        # also passively lean one side
        px_bid = min(ask - 1, int(fair - 1))
        px_ask = max(bid + 1, int(fair + 1))
        if buy_cap > 0 and px_bid > 0:
            out.append(Order(symbol, px_bid, min(2, buy_cap)))
        if sell_cap > 0 and px_ask > 0:
            out.append(Order(symbol, px_ask, -min(2, sell_cap)))
        return out

    def run(self, state: TradingState):
        mem = self._load_state(state.traderData)
        self._update_mark_signal(state, mem)
        mids: Dict[str, float] = {}
        result: Dict[str, List[Order]] = defaultdict(list)
        watch = ["VELVETFRUIT_EXTRACT", "HYDROGEL_PACK", "VEV_5000", "VEV_5200", "VEV_5300", "VEV_5400", "VEV_5500"]
        for sym in watch:
            m = self._mid_price(state, sym, mids)
            if m is not None:
                mids[sym] = m
        self._update_session_extremes(state, mem, mids)

        hydro_mid = mids.get("HYDROGEL_PACK")
        vfe_mid = mids.get("VELVETFRUIT_EXTRACT")

        if hydro_mid is not None:
            last = mem["last_mid"].get("HYDROGEL_PACK", hydro_mid)
            momo = hydro_mid - last
            skew = (
                0.06 * mem["mark_signal"].get("HYDROGEL_PACK", 0.0)
                + self.CFG["hydro_momo_k"] * momo
                + self._session_bias("HYDROGEL_PACK", state, mem, hydro_mid, momo)
            )
            result["HYDROGEL_PACK"].extend(self._mm_orders("HYDROGEL_PACK", state, hydro_mid, self.CFG["hydro_edge"], self.CFG["hydro_clip"], skew))
            result["HYDROGEL_PACK"].extend(self._take_edge_orders("HYDROGEL_PACK", state, hydro_mid + skew, self.CFG["hydro_take_th"], self.CFG["hydro_take_size"]))
            mem["last_mid"]["HYDROGEL_PACK"] = hydro_mid

        if vfe_mid is not None:
            last = mem["last_mid"].get("VELVETFRUIT_EXTRACT", vfe_mid)
            momo = vfe_mid - last
            skew = (
                0.05 * mem["mark_signal"].get("VELVETFRUIT_EXTRACT", 0.0)
                + self.CFG["vfe_momo_k"] * momo
                + self._session_bias("VELVETFRUIT_EXTRACT", state, mem, vfe_mid, momo)
            )
            result["VELVETFRUIT_EXTRACT"].extend(self._mm_orders("VELVETFRUIT_EXTRACT", state, vfe_mid, self.CFG["vfe_edge"], self.CFG["vfe_clip"], skew))
            result["VELVETFRUIT_EXTRACT"].extend(self._take_edge_orders("VELVETFRUIT_EXTRACT", state, vfe_mid + skew, self.CFG["vfe_take_th"], self.CFG["vfe_take_size"]))
            mem["last_mid"]["VELVETFRUIT_EXTRACT"] = vfe_mid
            for symbol in ["VEV_5000", "VEV_5200", "VEV_5300", "VEV_5400", "VEV_5500"]:
                if symbol in state.order_depths and symbol in self.POSITION_LIMITS:
                    vmid = mids.get(symbol)
                    vmomo = 0.0 if vmid is None else vmid - mem["last_mid"].get(symbol, vmid)
                    vskew = 0.4 * skew + self._session_bias(symbol, state, mem, vmid if vmid is not None else 0.0, vmomo)
                    result[symbol].extend(self._vev_orders(symbol, state, vfe_mid, vskew))
                    if vmid is not None:
                        mem["last_mid"][symbol] = vmid
        return dict(result), 0, self._save_state(mem)

