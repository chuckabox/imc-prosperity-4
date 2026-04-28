"""bed.py — improved trader derived from lamp.py.

Key changes vs lamp.py (justified by Day 1-3 data analysis):

1. HYDROGEL_PACK and VELVETFRUIT_EXTRACT trade as Ornstein–Uhlenbeck
   processes (AR(1) phi = 0.998, half-life ≈ 350 ticks, lag-1 return
   autocorrelation ≈ −0.12 to −0.16). lamp.py uses POSITIVE momentum
   (`momo_k=0.20`) — wrong sign. We use a **mean-reversion pull**
   toward the rolling mean: fair = mid − alpha · (mid − mu).

2. Mark trader signals were misclassified in lamp.py. Empirical
   signed-PnL on Day 1-3:
       HYDROGEL: Mark 14 = follow (+0.88 over 50t),
                 Mark 38 = fade  (−0.74 over 50t)
       VFE:      Mark 55 = follow (+0.99 over 200t),
                 Mark 67 = follow (+1.80 over 200t),
                 Mark 14 = fade  (−1.52 over 200t),
                 Mark 49 = fade  (−2.45 over 200t)
   We re-tag accordingly per product (lamp.py used a single global tag).

3. VEV options: deep-ITM (K ≤ 4500) residual = mid − (VFE − K) is
   noisy but stationary with mean ≈ 0 and lag-1 AC ≈ −0.5 — a clean
   z-score arb. ATM/OTM strikes (5000–5500) keep the floor-table
   theo from lamp.py but with a residual mean tracker for adaptive
   threshold.

4. Inventory penalty kept; edges and clip sizes tuned slightly.
"""

import json
import statistics
from collections import defaultdict
from typing import Dict, List, Optional, Tuple

from datamodel import Order, TradingState


class Trader:
    POSITION_LIMITS = {
        "HYDROGEL_PACK": 60, "VELVETFRUIT_EXTRACT": 60,
        "VEV_4000": 25, "VEV_4500": 25, "VEV_5000": 30, "VEV_5100": 30,
        "VEV_5200": 30, "VEV_5300": 30, "VEV_5400": 25, "VEV_5500": 25,
        "VEV_6000": 20, "VEV_6500": 20,
    }

    MM_CFG = {
        "HYDROGEL_PACK": {
            "edge": 4, "clip": 10,
            "mr_alpha": 0.30,      # fraction of (mid-mu) pulled toward mu
            "mark_skew_k": 0.10,   # mark_signal → skew multiplier (price units / signal)
            "inv_k": 0.05,         # inventory penalty per unit
            "take_th": 3.0,        # take edge threshold (price units beyond fair)
            "take_size": 8,
            "z_window": 200, "z_min_obs": 60,
        },
        "VELVETFRUIT_EXTRACT": {
            "edge": 2, "clip": 10,
            "mr_alpha": 0.40,      # VFE has stronger MR
            "mark_skew_k": 0.08,
            "inv_k": 0.04,
            "take_th": 1.5,
            "take_size": 8,
            "z_window": 200, "z_min_obs": 60,
        },
    }

    # Per-product Mark trader weights. +1 = follow (their buy → bullish);
    # −1 = fade. Weights scale the per-trade signal accumulation.
    MARK_SIGNALS: Dict[str, Dict[str, float]] = {
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
        },
    }
    MARK_SIGNAL_DECAY = 0.85
    MARK_SIGNAL_CAP = 40.0

    # VEV strikes & floor table (tuned to observed residuals on day 1-3)
    VEV_FLOOR_TV = {
        4000: 0.0, 4500: 0.0, 5000: 3.5, 5100: 13.0, 5200: 41.0,
        5300: 41.0, 5400: 13.0, 5500: 5.0, 6000: 0.5, 6500: 0.5,
    }
    VEV_DEEP_ITM_STRIKES = {4000, 4500}     # arb against intrinsic
    VEV_ATM_STRIKES = {5000, 5100, 5200, 5300, 5400, 5500}
    VEV_DEEP_ITM_Z_THRESH = 1.5             # std-devs of residual
    VEV_ATM_THRESH = 5.0                    # absolute deviation from theo
    VEV_SIZE = 4
    VEV_RES_WINDOW = 150
    VEV_RES_MIN_OBS = 40

    def _load_state(self, td: str) -> Dict:
        if not td:
            return {"hist": {}, "mark": {}, "res": {}}
        try:
            s = json.loads(td)
        except Exception:
            return {"hist": {}, "mark": {}, "res": {}}
        s.setdefault("hist", {})
        s.setdefault("mark", {})
        s.setdefault("res", {})
        return s

    def _save_state(self, mem: Dict) -> str:
        for k, v in mem["hist"].items():
            cap = self.MM_CFG[k]["z_window"] if k in self.MM_CFG else self.VEV_RES_WINDOW
            if len(v) > cap:
                mem["hist"][k] = v[-cap:]
        for k, v in mem["res"].items():
            if len(v) > self.VEV_RES_WINDOW:
                mem["res"][k] = v[-self.VEV_RES_WINDOW:]
        return json.dumps(mem, separators=(",", ":"))

    @staticmethod
    def _best_bid_ask(depth) -> Tuple[Optional[int], Optional[int]]:
        if not depth or not depth.buy_orders or not depth.sell_orders:
            return None, None
        return max(depth.buy_orders.keys()), min(depth.sell_orders.keys())

    def _mid(self, state: TradingState, sym: str) -> Optional[float]:
        depth = state.order_depths.get(sym)
        if depth is None:
            return None
        b, a = self._best_bid_ask(depth)
        if b is None:
            return None
        return 0.5 * (b + a)

    @staticmethod
    def _mu_sd(values: List[float]) -> Tuple[float, float]:
        if not values:
            return 0.0, 0.0
        mu = statistics.fmean(values)
        if len(values) < 2:
            return mu, 0.0
        var = sum((x - mu) ** 2 for x in values) / (len(values) - 1)
        return mu, var ** 0.5

    def _update_mark_signals(self, state: TradingState, mem: Dict) -> None:
        marks = mem["mark"]
        for sym in list(marks):
            marks[sym] *= self.MARK_SIGNAL_DECAY
            if abs(marks[sym]) < 0.05:
                del marks[sym]
        for sym, weights in self.MARK_SIGNALS.items():
            trades = state.market_trades.get(sym, []) if state.market_trades else []
            if not trades:
                continue
            cur = marks.get(sym, 0.0)
            for t in trades:
                qty = abs(getattr(t, "quantity", 0) or 0)
                if qty == 0:
                    continue
                buyer = getattr(t, "buyer", "") or ""
                seller = getattr(t, "seller", "") or ""
                if buyer in weights:
                    cur += weights[buyer] * 0.10 * qty
                if seller in weights:
                    cur -= weights[seller] * 0.10 * qty
            cap = self.MARK_SIGNAL_CAP
            cur = max(-cap, min(cap, cur))
            if abs(cur) > 0.01:
                marks[sym] = cur

    def _mr_orders(self, sym: str, state: TradingState, mem: Dict) -> List[Order]:
        cfg = self.MM_CFG[sym]
        cur = self._mid(state, sym)
        if cur is None:
            return []

        hist = mem["hist"].setdefault(sym, [])
        hist.append(cur)
        if len(hist) > cfg["z_window"]:
            del hist[: len(hist) - cfg["z_window"]]

        if len(hist) >= cfg["z_min_obs"]:
            mu, sd = self._mu_sd(hist)
        else:
            mu, sd = cur, 0.0

        # Mean-reversion pull: skew fair toward rolling mean
        mr_skew = -cfg["mr_alpha"] * (cur - mu)
        # Mark signal pull
        mark_skew = cfg["mark_skew_k"] * mem["mark"].get(sym, 0.0)
        # Inventory penalty
        pos = state.position.get(sym, 0)
        inv_skew = -cfg["inv_k"] * pos

        fair = cur + mr_skew + mark_skew + inv_skew

        depth = state.order_depths.get(sym)
        if depth is None:
            return []
        lim = self.POSITION_LIMITS[sym]
        bid_cap = max(0, lim - pos)
        ask_cap = max(0, lim + pos)
        orders: List[Order] = []

        # Quote around skewed fair
        bid_px = int(fair - cfg["edge"])
        ask_px = int(fair + cfg["edge"])
        if bid_px >= ask_px:
            ask_px = bid_px + 1
        if bid_cap > 0:
            orders.append(Order(sym, bid_px, min(cfg["clip"], bid_cap)))
        if ask_cap > 0:
            orders.append(Order(sym, ask_px, -min(cfg["clip"], ask_cap)))

        # Take aggressively when book offers a price beyond skewed fair
        best_ask = min(depth.sell_orders.keys()) if depth.sell_orders else None
        best_bid = max(depth.buy_orders.keys()) if depth.buy_orders else None
        if best_ask is not None and best_ask <= fair - cfg["take_th"] and bid_cap > 0:
            qty = min(cfg["take_size"], bid_cap, abs(depth.sell_orders[best_ask]))
            if qty > 0:
                orders.append(Order(sym, best_ask, qty))
        if best_bid is not None and best_bid >= fair + cfg["take_th"] and ask_cap > 0:
            qty = min(cfg["take_size"], ask_cap, abs(depth.buy_orders[best_bid]))
            if qty > 0:
                orders.append(Order(sym, best_bid, -qty))

        return orders

    def _vev_orders(self, sym: str, state: TradingState, vfe_mid: float, mem: Dict) -> List[Order]:
        depth = state.order_depths.get(sym)
        if depth is None or vfe_mid is None:
            return []
        try:
            k = int(sym.split("_")[1])
        except Exception:
            return []
        if k not in self.VEV_FLOOR_TV:
            return []

        bid, ask = self._best_bid_ask(depth)
        if bid is None:
            return []
        mid = 0.5 * (bid + ask)
        intrinsic = max(vfe_mid - k, 0.0)
        theo_floor = intrinsic + self.VEV_FLOOR_TV[k]

        pos = state.position.get(sym, 0)
        lim = self.POSITION_LIMITS[sym]
        buy_cap = max(0, lim - pos)
        sell_cap = max(0, lim + pos)
        orders: List[Order] = []

        if k in self.VEV_DEEP_ITM_STRIKES:
            # Track residual mid - intrinsic (no floor; near zero) and z-score
            rkey = f"VEV_RES_{k}"
            rhist = mem["res"].setdefault(rkey, [])
            residual = mid - intrinsic
            rhist.append(residual)
            if len(rhist) > self.VEV_RES_WINDOW:
                del rhist[: len(rhist) - self.VEV_RES_WINDOW]
            if len(rhist) >= self.VEV_RES_MIN_OBS:
                rmu, rsd = self._mu_sd(rhist)
            else:
                rmu, rsd = residual, 0.0
            if rsd > 0.3:
                z = (residual - rmu) / rsd
                if z < -self.VEV_DEEP_ITM_Z_THRESH and buy_cap > 0:
                    qty = min(self.VEV_SIZE, buy_cap, abs(depth.sell_orders[ask]))
                    if qty > 0:
                        orders.append(Order(sym, ask, qty))
                elif z > self.VEV_DEEP_ITM_Z_THRESH and sell_cap > 0:
                    qty = min(self.VEV_SIZE, sell_cap, abs(depth.buy_orders[bid]))
                    if qty > 0:
                        orders.append(Order(sym, bid, -qty))
            return orders

        if k in self.VEV_ATM_STRIKES:
            mispricing = mid - theo_floor
            th = self.VEV_ATM_THRESH
            if mispricing < -th and buy_cap > 0:
                qty = min(self.VEV_SIZE, buy_cap, abs(depth.sell_orders[ask]))
                if qty > 0:
                    orders.append(Order(sym, ask, qty))
            elif mispricing > th and sell_cap > 0:
                qty = min(self.VEV_SIZE, sell_cap, abs(depth.buy_orders[bid]))
                if qty > 0:
                    orders.append(Order(sym, bid, -qty))
        return orders

    def run(self, state: TradingState):
        mem = self._load_state(state.traderData)
        self._update_mark_signals(state, mem)
        result: Dict[str, List[Order]] = defaultdict(list)

        for sym in ("HYDROGEL_PACK", "VELVETFRUIT_EXTRACT"):
            if sym in state.order_depths:
                result[sym].extend(self._mr_orders(sym, state, mem))

        vfe_mid = self._mid(state, "VELVETFRUIT_EXTRACT")
        if vfe_mid is not None:
            for sym in state.order_depths:
                if sym.startswith("VEV_") and sym in self.POSITION_LIMITS:
                    result[sym].extend(self._vev_orders(sym, state, vfe_mid, mem))

        return dict(result), 0, self._save_state(mem)
