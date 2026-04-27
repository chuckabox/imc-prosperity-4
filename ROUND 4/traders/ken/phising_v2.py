import json
from collections import defaultdict
from typing import Dict, List, Optional, Tuple

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

    CFG = {
        "hydro_edge": 6,
        "hydro_clip": 8,
        "hydro_momo_k": 0.22,
        "hydro_take_th": 2.0,
        "hydro_take_size": 6,
        "vfe_edge": 2,
        "vfe_clip": 8,
        "vfe_momo_k": 0.22,
        "vfe_take_th": 1.4,
        "vfe_take_size": 6,
        "vev_strikes": [4000, 4500, 5000, 5400, 5500],
        "vev_threshold_base": 6.8,
        "vev_size_base": 3,
        "vev_mtm_brake": -1200.0,
    }

    MARK_BUY = {"Mark 67", "Mark 01", "Mark 38"}
    MARK_SELL = {"Mark 49", "Mark 22", "Mark 14"}

    @staticmethod
    def _clamp(x: float, lo: float, hi: float) -> float:
        return max(lo, min(hi, x))

    def _default_mem(self) -> Dict:
        return {
            "mark_signal": {},
            "last_mid": {},
            "last_ts": None,
            "day_idx": 0,
            "vev_day_mtm_pnl": 0.0,
            "vev_prev_value": 0.0,
            "vev_disabled": False,
        }

    def _load_state(self, trader_data: str) -> Dict:
        d = self._default_mem()
        if not trader_data:
            return d
        try:
            parsed = json.loads(trader_data)
            for k, v in d.items():
                parsed.setdefault(k, v)
            return parsed
        except Exception:
            return d

    def _save_state(self, state: Dict) -> str:
        return json.dumps(state, separators=(",", ":"))

    @staticmethod
    def _best_bid_ask(order_depth) -> Tuple[Optional[int], Optional[int]]:
        if not order_depth or not order_depth.buy_orders or not order_depth.sell_orders:
            return None, None
        return max(order_depth.buy_orders.keys()), min(order_depth.sell_orders.keys())

    def _mid_price(self, state: TradingState, symbol: str, cache: Dict[str, float]) -> Optional[float]:
        if symbol in cache:
            return cache[symbol]
        depth = state.order_depths.get(symbol)
        bid, ask = self._best_bid_ask(depth)
        if bid is None or ask is None:
            return None
        mid = 0.5 * (bid + ask)
        cache[symbol] = mid
        return mid

    def _roll_day_if_needed(self, state: TradingState, mem: Dict) -> None:
        last_ts = mem.get("last_ts")
        ts = state.timestamp
        if last_ts is not None and ts < last_ts:
            mem["day_idx"] += 1
            mem["vev_day_mtm_pnl"] = 0.0
            mem["vev_prev_value"] = 0.0
            mem["vev_disabled"] = False
        mem["last_ts"] = ts

    def _update_mark_signal(self, state: TradingState, mem: Dict) -> None:
        ms = mem["mark_signal"]
        for k in list(ms.keys()):
            ms[k] *= 0.86
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
                ms[symbol] = self._clamp(s, -40.0, 40.0)

    def _mm_orders(
        self,
        symbol: str,
        state: TradingState,
        fair: float,
        edge: int,
        clip: int,
        signal_skew: float,
    ) -> List[Order]:
        depth = state.order_depths.get(symbol)
        if not depth:
            return []

        pos = state.position.get(symbol, 0)
        lim = self.POSITION_LIMITS.get(symbol, 20)
        buy_cap = max(0, lim - pos)
        sell_cap = max(0, lim + pos)
        if buy_cap <= 0 and sell_cap <= 0:
            return []

        fair_adj = fair + signal_skew - 0.03 * pos
        bid_px = int(fair_adj - edge)
        ask_px = int(fair_adj + edge)
        if bid_px >= ask_px:
            ask_px = bid_px + 1

        out: List[Order] = []
        if buy_cap > 0:
            out.append(Order(symbol, bid_px, min(clip, buy_cap)))
        if sell_cap > 0:
            out.append(Order(symbol, ask_px, -min(clip, sell_cap)))
        return out

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
        lim = self.POSITION_LIMITS.get(symbol, 20)
        buy_cap = max(0, lim - pos)
        sell_cap = max(0, lim + pos)
        best_ask = min(depth.sell_orders.keys()) if depth.sell_orders else None
        best_bid = max(depth.buy_orders.keys()) if depth.buy_orders else None

        out: List[Order] = []
        if best_ask is not None and best_ask <= fair - threshold and buy_cap > 0:
            qty = min(max_take, buy_cap, abs(depth.sell_orders[best_ask]))
            if qty > 0:
                out.append(Order(symbol, best_ask, qty))
        if best_bid is not None and best_bid >= fair + threshold and sell_cap > 0:
            qty = min(max_take, sell_cap, abs(depth.buy_orders[best_bid]))
            if qty > 0:
                out.append(Order(symbol, best_bid, -qty))
        return out

    def _update_vev_mtm_brake(self, state: TradingState, mem: Dict, mids: Dict[str, float]) -> None:
        vev_value = 0.0
        for sym in state.order_depths.keys():
            if not sym.startswith("VEV_"):
                continue
            mid = self._mid_price(state, sym, mids)
            if mid is None:
                continue
            pos = state.position.get(sym, 0)
            vev_value += pos * mid

        prev = float(mem.get("vev_prev_value", 0.0))
        delta = vev_value - prev
        mem["vev_day_mtm_pnl"] = float(mem.get("vev_day_mtm_pnl", 0.0)) + delta
        mem["vev_prev_value"] = vev_value

        if mem["vev_day_mtm_pnl"] <= self.CFG["vev_mtm_brake"]:
            mem["vev_disabled"] = True

    def _vev_orders(
        self,
        symbol: str,
        state: TradingState,
        vfe_mid: float,
        sigma_score: float,
    ) -> List[Order]:
        if symbol not in state.order_depths or vfe_mid is None:
            return []

        k = int(symbol.split("_")[1])
        if k not in set(self.CFG["vev_strikes"]):
            return []

        depth = state.order_depths[symbol]
        bid, ask = self._best_bid_ask(depth)
        if bid is None or ask is None:
            return []

        theo = max(vfe_mid - k, 0.0) + self.VEV_TIME_VALUE_FLOOR.get(k, 0.0)
        mid = 0.5 * (bid + ask)
        mispricing = mid - theo

        # Higher Hydrogel volatility regime -> demand larger VEV edge and cut size.
        dynamic_threshold = self.CFG["vev_threshold_base"] + 1.2 * abs(sigma_score)
        dynamic_size = max(1, self.CFG["vev_size_base"] - (1 if abs(sigma_score) > 0.9 else 0))

        pos = state.position.get(symbol, 0)
        lim = self.POSITION_LIMITS[symbol]
        buy_cap = max(0, lim - pos)
        sell_cap = max(0, lim + pos)

        if mispricing < -dynamic_threshold and buy_cap > 0:
            return [Order(symbol, ask, min(dynamic_size, buy_cap))]
        if mispricing > dynamic_threshold and sell_cap > 0:
            return [Order(symbol, bid, -min(dynamic_size, sell_cap))]
        return []

    def run(self, state: TradingState):
        mem = self._load_state(state.traderData)
        self._roll_day_if_needed(state, mem)
        self._update_mark_signal(state, mem)

        result: Dict[str, List[Order]] = defaultdict(list)
        mids: Dict[str, float] = {}

        hydro_mid = self._mid_price(state, "HYDROGEL_PACK", mids)
        vfe_mid = self._mid_price(state, "VELVETFRUIT_EXTRACT", mids)

        # Hydrogel-centered regime score, clipped to avoid unstable scaling.
        sigma_score = 0.0
        if hydro_mid is not None:
            sigma_score = self._clamp((hydro_mid - 9995.0) / 50.0, -2.0, 2.0)

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

        # VEV MTM brake is evaluated every tick; once tripped for the day, only core legs trade.
        self._update_vev_mtm_brake(state, mem, mids)
        if not mem.get("vev_disabled", False) and vfe_mid is not None:
            for symbol in state.order_depths.keys():
                if symbol.startswith("VEV_") and symbol in self.POSITION_LIMITS:
                    result[symbol].extend(self._vev_orders(symbol, state, vfe_mid, sigma_score))

        return dict(result), 0, self._save_state(mem)
