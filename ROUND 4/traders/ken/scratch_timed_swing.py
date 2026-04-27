from __future__ import annotations

from typing import Dict, List, Tuple

from datamodel import Order, TradingState


VFE = "VELVETFRUIT_EXTRACT"
HP = "HYDROGEL_PACK"
VEV_SIG = ["VEV_5000", "VEV_5200", "VEV_5300", "VEV_5400"]
ALL = [VFE, HP, *VEV_SIG]

LIMITS = {
    VFE: 200,
    HP: 200,
    "VEV_5000": 100,
    "VEV_5200": 100,
    "VEV_5300": 100,
    "VEV_5400": 100,
}


def best_bid_ask(od):
    bb = max(od.buy_orders) if od.buy_orders else None
    ba = min(od.sell_orders) if od.sell_orders else None
    return bb, ba


def mid(od):
    bb, ba = best_bid_ask(od)
    if bb is None or ba is None:
        return None
    return (bb + ba) / 2.0


class Trader:
    def __init__(self) -> None:
        self.prev_ts = -1
        self.day_index = 0
        self.ema: dict[str, float] = {}
        self.var: dict[str, float] = {}
        self.prev_mid: dict[str, float] = {}
        self.open_mid: dict[str, float] = {}
        self.low_mid: dict[str, float] = {}
        self.high_mid: dict[str, float] = {}
        self.alpha = 0.02

    def _reset_day(self) -> None:
        self.day_index += 1
        self.open_mid = {}
        self.low_mid = {}
        self.high_mid = {}

    def _update_stats(self, sym: str, m: float) -> None:
        if sym not in self.ema:
            self.ema[sym] = m
            self.var[sym] = 25.0
            self.prev_mid[sym] = m
            return
        e = self.ema[sym]
        diff = m - e
        self.ema[sym] = (1 - self.alpha) * e + self.alpha * m
        self.var[sym] = max(1.0, (1 - self.alpha) * self.var[sym] + self.alpha * diff * diff)
        self.prev_mid[sym] = m

    def _z(self, sym: str, m: float) -> float:
        std = max(1.0, self.var.get(sym, 25.0) ** 0.5)
        return (m - self.ema.get(sym, m)) / std

    def _pos(self, state: TradingState, sym: str) -> int:
        return int(state.position.get(sym, 0))

    def _cross_to_target(self, state: TradingState, sym: str, target: int) -> List[Order]:
        od = state.order_depths.get(sym)
        if not od:
            return []
        bb, ba = best_bid_ask(od)
        pos = self._pos(state, sym)
        diff = target - pos
        orders: List[Order] = []
        if diff > 0 and ba is not None:
            orders.append(Order(sym, int(ba), diff))
        elif diff < 0 and bb is not None:
            orders.append(Order(sym, int(bb), diff))
        return orders

    def _clamp(self, sym: str, target: int) -> int:
        lim = LIMITS[sym]
        return max(-lim, min(lim, target))

    def _basket_target(self, ts: int, vfe_mid: float, vfe_z: float) -> dict[str, int]:
        targets = {sym: 0 for sym in [VFE, *VEV_SIG]}
        open_vfe = self.open_mid.get(VFE, vfe_mid)
        low_vfe = self.low_mid.get(VFE, vfe_mid)
        prev_vfe = self.prev_mid.get(VFE, vfe_mid)
        rebound = vfe_mid - low_vfe

        # Opening dump pattern: strongest and most repeatable in first 10%.
        if ts <= 12000:
            if vfe_mid >= open_vfe - 6:
                targets[VFE] = -200
                targets["VEV_5000"] = -100
                targets["VEV_5200"] = -100
                targets["VEV_5300"] = -100
                targets["VEV_5400"] = -100
                return targets

        # Hold / cover opening short until washout.
        if ts <= 90000:
            if vfe_z > 1.2 and vfe_mid >= open_vfe - 10:
                targets[VFE] = -200
                targets["VEV_5000"] = -100
                targets["VEV_5200"] = -100
                targets["VEV_5300"] = -100
                targets["VEV_5400"] = -100
            elif vfe_z < -1.8 and ts >= 18000:
                # capitulation reached: flatten short
                if rebound >= 6 and vfe_mid > prev_vfe:
                    # only flip long on clear rebound; smaller size than short
                    targets[VFE] = 120
                    targets["VEV_5000"] = 70
                    targets["VEV_5200"] = 60
                    targets["VEV_5300"] = 40
                else:
                    return targets
            elif rebound >= 10 and vfe_mid > prev_vfe and ts >= 30000:
                targets[VFE] = 120
                targets["VEV_5000"] = 70
                targets["VEV_5200"] = 60
                targets["VEV_5300"] = 40
            return targets

        # Midday peak -> trough pattern (days 1-2 strongest).
        if 220000 <= ts <= 420000 and vfe_z > 2.0:
            targets[VFE] = -200
            targets["VEV_5000"] = -100
            targets["VEV_5200"] = -100
            targets["VEV_5300"] = -100
            targets["VEV_5400"] = -100
            return targets

        if 520000 <= ts <= 820000 and vfe_z < -2.0:
            targets[VFE] = 200
            targets["VEV_5000"] = 100
            targets["VEV_5200"] = 100
            targets["VEV_5300"] = 100
            targets["VEV_5400"] = 80
            return targets

        if ts >= 930000:
            return targets

        return targets

    def _hp_target(self, ts: int, hp_mid: float, hp_z: float) -> int:
        open_hp = self.open_mid.get(HP, hp_mid)
        low_hp = self.low_mid.get(HP, hp_mid)
        high_hp = self.high_mid.get(HP, hp_mid)

        # HP is reliably mean-reverting, so use symmetric z swings + some opening logic.
        if ts <= 15000:
            if hp_mid >= open_hp + 8:
                return -200
            if hp_mid <= open_hp - 8:
                return 200

        if hp_z >= 2.0:
            return -200
        if hp_z <= -2.0:
            return 200

        # Exit after reversion to center or late in day.
        if abs(hp_z) <= 0.4 or ts >= 930000:
            return 0

        # keep existing exposure otherwise
        return 10_000  # sentinel = hold

    def run(self, state: TradingState) -> Tuple[Dict[str, List[Order]], int, str]:
        if self.prev_ts >= 0 and state.timestamp < self.prev_ts:
            self._reset_day()
        self.prev_ts = state.timestamp

        result: Dict[str, List[Order]] = {}

        mids: dict[str, float] = {}
        for sym in ALL:
            od = state.order_depths.get(sym)
            if not od:
                continue
            m = mid(od)
            if m is None:
                continue
            mids[sym] = float(m)
            if sym not in self.open_mid:
                self.open_mid[sym] = float(m)
                self.low_mid[sym] = float(m)
                self.high_mid[sym] = float(m)
            self.low_mid[sym] = min(self.low_mid[sym], float(m))
            self.high_mid[sym] = max(self.high_mid[sym], float(m))
            self._update_stats(sym, float(m))

        if VFE in mids:
            vfe_tg = self._basket_target(state.timestamp, mids[VFE], self._z(VFE, mids[VFE]))
            for sym, tg in vfe_tg.items():
                tg = self._clamp(sym, tg)
                orders = self._cross_to_target(state, sym, tg)
                if orders:
                    result[sym] = orders

        if HP in mids:
            hp_tg = self._hp_target(state.timestamp, mids[HP], self._z(HP, mids[HP]))
            if hp_tg != 10_000:
                hp_tg = self._clamp(HP, hp_tg)
                orders = self._cross_to_target(state, HP, hp_tg)
                if orders:
                    result[HP] = result.get(HP, []) + orders

        return result, 0, ""

