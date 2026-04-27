import json
from collections import defaultdict
from typing import Dict, List, Tuple

from datamodel import Order, TradingState


class Trader:
    AGGRO_CFG = {
        "enable_take": True,
        "hydro_edge": 7,
        "hydro_clip": 22,
        "hydro_momo_k": 0.20,
        "hydro_take_th": 2.5,
        "hydro_take_size": 12,
        "vfe_edge": 3,
        "vfe_clip": 18,
        "vfe_momo_k": 0.15,
        "vfe_take_th": 1.8,
        "vfe_take_size": 10,
        "vev_strikes": [5400, 5500],
        "vev_threshold": 8.0,
        "vev_size": 5,
        "mark_decay": 0.90,
        "mark_cap": 30.0,
    }
    SAFE_CFG = {
        "enable_take": True,
        "hydro_edge": 7,
        "hydro_clip": 7,
        "hydro_momo_k": 0.20,
        "hydro_take_th": 2.5,
        "hydro_take_size": 4,
        "vfe_edge": 3,
        "vfe_clip": 7,
        "vfe_momo_k": 0.15,
        "vfe_take_th": 1.8,
        "vfe_take_size": 4,
        "vev_strikes": [5400, 5500],
        "vev_threshold": 8.0,
        "vev_size": 2,
        "mark_decay": 0.90,
        "mark_cap": 30.0,
    }
    AGGRO_LIMITS = {
        "HYDROGEL_PACK": 160, "VELVETFRUIT_EXTRACT": 160,
        "VEV_5400": 80, "VEV_5500": 80,
    }
    SAFE_LIMITS = {
        "HYDROGEL_PACK": 60, "VELVETFRUIT_EXTRACT": 60,
        "VEV_5400": 25, "VEV_5500": 25,
    }
    VEV_TIME_VALUE_FLOOR = {5400: 19.0, 5500: 7.0}
    MARK_BUY = {"Mark 67", "Mark 01", "Mark 38"}
    MARK_SELL = {"Mark 49", "Mark 22", "Mark 14"}

    def _load_state(self, trader_data: str) -> Dict:
        if not trader_data:
            return {"mark_signal": {}, "last_mid": {}, "last_ts": -1, "day_index": 0}
        try:
            s = json.loads(trader_data)
            s.setdefault("mark_signal", {})
            s.setdefault("last_mid", {})
            s.setdefault("last_ts", -1)
            s.setdefault("day_index", 0)
            return s
        except Exception:
            return {"mark_signal": {}, "last_mid": {}, "last_ts": -1, "day_index": 0}

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

    def _current_profile(self, mem: Dict) -> tuple[Dict, Dict]:
        # Be more aggressive on sessions 1-2, then revert to the safer shelf sizing on session 3.
        if mem.get("day_index", 0) >= 2:
            return self.SAFE_CFG, self.SAFE_LIMITS
        return self.AGGRO_CFG, self.AGGRO_LIMITS

    def _update_mark_signal(self, state: TradingState, mem: Dict, cfg: Dict) -> None:
        ms = mem["mark_signal"]; decay = cfg.get("mark_decay", 0.85); cap = cfg.get("mark_cap", 40.0)
        for k in list(ms.keys()):
            ms[k] *= decay
            if abs(ms[k]) < 0.05: del ms[k]
        for symbol, trades in state.market_trades.items():
            if not trades: continue
            s = ms.get(symbol, 0.0)
            for t in trades:
                qty = abs(getattr(t, "quantity", 0)); buyer = getattr(t, "buyer", ""); seller = getattr(t, "seller", "")
                if buyer in self.MARK_BUY: s += 0.15 * qty
                if seller in self.MARK_SELL: s += 0.10 * qty
                if buyer in self.MARK_SELL: s -= 0.15 * qty
                if seller in self.MARK_BUY: s -= 0.10 * qty
            if abs(s) > 0.01: ms[symbol] = max(-cap, min(cap, s))

    def _mm_orders(self, symbol: str, state: TradingState, fair: float, edge: int, clip: int, skew: float, limits: Dict[str, int]) -> List[Order]:
        orders: List[Order] = []; depth = state.order_depths.get(symbol)
        if not depth: return orders
        pos = state.position.get(symbol, 0); lim = limits.get(symbol, 20)
        bid_cap = max(0, lim - pos); ask_cap = max(0, lim + pos)
        if bid_cap <= 0 and ask_cap <= 0: return orders
        fair_adj = fair + skew - 0.03 * pos
        bid_px = int(fair_adj - edge); ask_px = int(fair_adj + edge)
        if bid_px >= ask_px: ask_px = bid_px + 1
        if bid_cap > 0: orders.append(Order(symbol, bid_px, min(clip, bid_cap)))
        if ask_cap > 0: orders.append(Order(symbol, ask_px, -min(clip, ask_cap)))
        return orders

    def _take_edge_orders(self, symbol: str, state: TradingState, fair: float, threshold: float, max_take: int, limits: Dict[str, int]) -> List[Order]:
        depth = state.order_depths.get(symbol)
        if not depth: return []
        orders: List[Order] = []
        pos = state.position.get(symbol, 0); lim = limits.get(symbol, 20)
        buy_cap = max(0, lim - pos); sell_cap = max(0, lim + pos)
        best_ask = min(depth.sell_orders.keys()) if depth.sell_orders else None
        best_bid = max(depth.buy_orders.keys()) if depth.buy_orders else None
        if best_ask is not None and best_ask <= fair - threshold and buy_cap > 0:
            qty = min(max_take, buy_cap, abs(depth.sell_orders[best_ask]))
            if qty > 0: orders.append(Order(symbol, best_ask, qty))
        if best_bid is not None and best_bid >= fair + threshold and sell_cap > 0:
            qty = min(max_take, sell_cap, abs(depth.buy_orders[best_bid]))
            if qty > 0: orders.append(Order(symbol, best_bid, -qty))
        return orders

    def _vev_orders(self, symbol: str, state: TradingState, vfe_mid: float, cfg: Dict, limits: Dict[str, int]) -> List[Order]:
        depth = state.order_depths.get(symbol)
        if not depth or vfe_mid is None: return []
        k = int(symbol.split("_")[1]); enabled = set(cfg.get("vev_strikes", [5400, 5500]))
        if k not in enabled: return []
        bid, ask = self._best_bid_ask(depth)
        if bid is None or ask is None: return []
        theo = max(vfe_mid - k, 0.0) + self.VEV_TIME_VALUE_FLOOR.get(k, 0.0)
        mid = 0.5 * (bid + ask); mispricing = mid - theo
        pos = state.position.get(symbol, 0); lim = limits[symbol]
        buy_cap = max(0, lim - pos); sell_cap = max(0, lim + pos)
        th = cfg.get("vev_threshold", 8.0); size = cfg.get("vev_size", 2)
        if mispricing < -th and buy_cap > 0: return [Order(symbol, ask, min(size, buy_cap))]
        if mispricing > th and sell_cap > 0: return [Order(symbol, bid, -min(size, sell_cap))]
        return []

    def run(self, state: TradingState):
        mem = self._load_state(state.traderData)
        if mem["last_ts"] >= 0 and state.timestamp < mem["last_ts"]:
            mem["day_index"] += 1
        mem["last_ts"] = state.timestamp
        cfg, limits = self._current_profile(mem)
        self._update_mark_signal(state, mem, cfg)
        mids: Dict[str, float] = {}; result: Dict[str, List[Order]] = defaultdict(list)
        vfe_mid = self._mid_price(state, "VELVETFRUIT_EXTRACT", mids); hydro_mid = self._mid_price(state, "HYDROGEL_PACK", mids)
        if hydro_mid is not None:
            last = mem["last_mid"].get("HYDROGEL_PACK", hydro_mid); momo = hydro_mid - last
            skew = 0.06 * mem["mark_signal"].get("HYDROGEL_PACK", 0.0) + cfg.get("hydro_momo_k", 0.2) * momo
            result["HYDROGEL_PACK"].extend(self._mm_orders("HYDROGEL_PACK", state, hydro_mid, cfg.get("hydro_edge", 7), cfg.get("hydro_clip", 7), skew, limits))
            result["HYDROGEL_PACK"].extend(self._take_edge_orders("HYDROGEL_PACK", state, hydro_mid + skew, cfg.get("hydro_take_th", 2.5), cfg.get("hydro_take_size", 4), limits))
            mem["last_mid"]["HYDROGEL_PACK"] = hydro_mid
        if vfe_mid is not None:
            last = mem["last_mid"].get("VELVETFRUIT_EXTRACT", vfe_mid); momo = vfe_mid - last
            skew = 0.05 * mem["mark_signal"].get("VELVETFRUIT_EXTRACT", 0.0) + cfg.get("vfe_momo_k", 0.15) * momo
            result["VELVETFRUIT_EXTRACT"].extend(self._mm_orders("VELVETFRUIT_EXTRACT", state, vfe_mid, cfg.get("vfe_edge", 3), cfg.get("vfe_clip", 7), skew, limits))
            result["VELVETFRUIT_EXTRACT"].extend(self._take_edge_orders("VELVETFRUIT_EXTRACT", state, vfe_mid + skew, cfg.get("vfe_take_th", 1.8), cfg.get("vfe_take_size", 4), limits))
            mem["last_mid"]["VELVETFRUIT_EXTRACT"] = vfe_mid
            for symbol in ["VEV_5400", "VEV_5500"]:
                if symbol in state.order_depths and symbol in limits:
                    result[symbol].extend(self._vev_orders(symbol, state, vfe_mid, cfg, limits))
        return dict(result), 0, self._save_state(mem)

