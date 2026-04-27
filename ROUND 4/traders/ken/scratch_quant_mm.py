from __future__ import annotations

import math
from typing import Dict, List, Tuple

from datamodel import Order, TradingState


VFE = "VELVETFRUIT_EXTRACT"
HP = "HYDROGEL_PACK"
VEV_STRIKES = [4000, 4500, 5000, 5100, 5200, 5300, 5400, 5500, 6000, 6500]
VEV = [f"VEV_{k}" for k in VEV_STRIKES]


LIMITS: dict[str, int] = {
    HP: 200,
    VFE: 200,
    # IMC/Prosperity limits: vouchers are 100 each in the official python engine.
    **{sym: 100 for sym in VEV},
}


def norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def bs_call(S: float, K: float, T: float, sigma: float) -> float:
    if T <= 1e-12:
        return max(S - K, 0.0)
    if sigma <= 1e-12:
        return max(S - K, 0.0)
    sqrtT = math.sqrt(T)
    d1 = (math.log(S / K) + 0.5 * sigma * sigma * T) / (sigma * sqrtT)
    d2 = d1 - sigma * sqrtT
    return S * norm_cdf(d1) - K * norm_cdf(d2)


def bs_delta(S: float, K: float, T: float, sigma: float) -> float:
    if T <= 1e-12:
        return 1.0 if S > K else 0.0
    if sigma <= 1e-12:
        return 1.0 if S > K else 0.0
    d1 = (math.log(S / K) + 0.5 * sigma * sigma * T) / (sigma * math.sqrt(T))
    return norm_cdf(d1)


def implied_vol_call(C: float, S: float, K: float, T: float) -> float:
    intrinsic = max(S - K, 0.0)
    C = max(C, intrinsic)
    lo, hi = 1e-6, 2.5
    for _ in range(60):
        mid = 0.5 * (lo + hi)
        px = bs_call(S, K, T, mid)
        if px > C:
            hi = mid
        else:
            lo = mid
    return 0.5 * (lo + hi)


def best_bid_ask(od) -> tuple[int | None, int | None]:
    bb = max(od.buy_orders) if od.buy_orders else None
    ba = min(od.sell_orders) if od.sell_orders else None
    return bb, ba


def mid_from_book(od) -> float | None:
    bb, ba = best_bid_ask(od)
    if bb is None or ba is None:
        return None
    return (bb + ba) / 2.0


class MMConfig:
    def __init__(self, take_edge: float, make_edge: float, size: int, soft_frac: float) -> None:
        self.take_edge = float(take_edge)
        self.make_edge = float(make_edge)
        self.size = int(size)
        self.soft_frac = float(soft_frac)


CFG_BY_SYMBOL: dict[str, MMConfig] = {
    HP: MMConfig(take_edge=2.0, make_edge=4.0, size=35, soft_frac=0.75),
    VFE: MMConfig(take_edge=1.0, make_edge=2.0, size=25, soft_frac=0.75),
    # deep ITM vouchers: huge spread, pure microstructure MM
    "VEV_4000": MMConfig(take_edge=0.0, make_edge=6.0, size=60, soft_frac=0.85),
    "VEV_4500": MMConfig(take_edge=0.0, make_edge=5.0, size=60, soft_frac=0.85),
}


class Trader:
    def __init__(self) -> None:
        self.fair: dict[str, float] = {HP: 9990.0, VFE: 5250.0}
        self.ema_alpha = 0.02
        self.last_sigma = 0.03

    def _pos(self, state: TradingState, sym: str) -> int:
        return int(state.position.get(sym, 0))

    def _cap_size(self, sym: str, state: TradingState, desired: int) -> int:
        lim = LIMITS.get(sym, 0)
        pos = self._pos(state, sym)
        if desired > 0:
            return max(0, min(desired, lim - pos))
        if desired < 0:
            return min(0, max(desired, -lim - pos))
        return 0

    def _update_ema(self, sym: str, mid: float) -> None:
        prev = self.fair.get(sym, mid)
        self.fair[sym] = (1 - self.ema_alpha) * prev + self.ema_alpha * mid

    def _mm_linear(
        self,
        sym: str,
        state: TradingState,
        od,
        fair: float,
        cfg: MMConfig,
    ) -> List[Order]:
        orders: List[Order] = []
        bb, ba = best_bid_ask(od)
        if bb is None or ba is None:
            return orders

        pos = self._pos(state, sym)
        lim = LIMITS[sym]
        soft = int(cfg.soft_frac * lim)

        inv_skew = 0.0
        if soft > 0:
            inv_skew = (pos / soft) * cfg.make_edge
            inv_skew = max(-cfg.make_edge, min(cfg.make_edge, inv_skew))

        # 1) Take obvious gifts (bounded by caps)
        if ba <= fair - cfg.take_edge:
            qty = self._cap_size(sym, state, cfg.size)
            if qty > 0:
                orders.append(Order(sym, int(ba), qty))
        if bb >= fair + cfg.take_edge:
            qty = self._cap_size(sym, state, -cfg.size)
            if qty < 0:
                orders.append(Order(sym, int(bb), qty))

        # 2) Make inside the spread, inventory-skewed
        bid_px = int(math.floor(fair - cfg.make_edge - inv_skew))
        ask_px = int(math.ceil(fair + cfg.make_edge - inv_skew))
        bid_px = min(bid_px, ba - 1)
        ask_px = max(ask_px, bb + 1)

        bid_qty = self._cap_size(sym, state, cfg.size)
        ask_qty = self._cap_size(sym, state, -cfg.size)
        if bid_qty > 0 and bid_px > 0:
            orders.append(Order(sym, bid_px, bid_qty))
        if ask_qty < 0 and ask_px > 0:
            orders.append(Order(sym, ask_px, ask_qty))
        return orders

    def _vev_fair_and_delta(self, state: TradingState) -> tuple[dict[str, float], dict[str, float], float] | None:
        if VFE not in state.order_depths:
            return None
        vfe_mid = mid_from_book(state.order_depths[VFE])
        if vfe_mid is None or vfe_mid <= 0:
            return None

        ref = "VEV_5200"
        if ref not in state.order_depths:
            return None
        ref_mid = mid_from_book(state.order_depths[ref])
        if ref_mid is None:
            return None

        # Time scaling doesn't matter much as long as it's consistent; we calibrate sigma each tick.
        T = 1.0
        sigma = implied_vol_call(float(ref_mid), float(vfe_mid), 5200.0, T)
        self.last_sigma = 0.9 * self.last_sigma + 0.1 * sigma
        sigma = self.last_sigma

        vev_fair: dict[str, float] = {}
        vev_delta: dict[str, float] = {}
        for k in VEV_STRIKES:
            sym = f"VEV_{k}"
            vev_fair[sym] = bs_call(float(vfe_mid), float(k), T, sigma)
            vev_delta[sym] = bs_delta(float(vfe_mid), float(k), T, sigma)
        return vev_fair, vev_delta, float(vfe_mid)

    def run(self, state: TradingState) -> Tuple[Dict[str, List[Order]], int, str]:
        result: Dict[str, List[Order]] = {}

        # Update EMA fairs for the two underlying-ish products (purely from live book)
        for sym in [HP, VFE]:
            od = state.order_depths.get(sym)
            if not od:
                continue
            mid = mid_from_book(od)
            if mid is None:
                continue
            self._update_ema(sym, float(mid))

        # Market-make HP + VFE around EMA fair
        for sym in [HP, VFE]:
            od = state.order_depths.get(sym)
            if not od:
                continue
            cfg = CFG_BY_SYMBOL[sym]
            orders = self._mm_linear(sym, state, od, self.fair[sym], cfg)
            if orders:
                result[sym] = orders

        # VEV: deep ITM (4000/4500) is best treated as wide-spread MM; mid strikes use BS fair
        vev_pack = self._vev_fair_and_delta(state)
        if vev_pack is not None:
            vev_fair, vev_delta, vfe_mid = vev_pack

            # 1) Wide-spread MM on deep ITM
            for sym in ["VEV_4000", "VEV_4500"]:
                if sym not in state.order_depths:
                    continue
                od = state.order_depths[sym]
                mid = mid_from_book(od)
                if mid is None:
                    continue
                # anchor fair to (VFE_ema - strike) + small premium from BS to prevent drifting too cheap
                k = int(sym.split("_")[1])
                fair = max(self.fair[VFE] - k, 0.0) + 0.3 * vev_fair[sym]
                orders = self._mm_linear(sym, state, od, fair, CFG_BY_SYMBOL[sym])
                if orders:
                    result[sym] = orders

            # 2) BS-based tight MM on mid strikes (skip 6000/6500: effectively worthless)
            for k in [5000, 5100, 5200, 5300, 5400, 5500]:
                sym = f"VEV_{k}"
                od = state.order_depths.get(sym)
                if not od:
                    continue
                bb, ba = best_bid_ask(od)
                if bb is None or ba is None:
                    continue

                fair = vev_fair[sym]
                pos = self._pos(state, sym)
                lim = LIMITS[sym]
                soft = int(0.8 * lim)
                inv_skew = 0.0
                if soft > 0:
                    inv_skew = (pos / soft) * 1.5
                    inv_skew = max(-2.0, min(2.0, inv_skew))

                # take if very mispriced vs BS fair (avoid overtrading)
                take_th = 2.5
                if ba <= fair - take_th:
                    qty = self._cap_size(sym, state, 40)
                    if qty > 0:
                        result.setdefault(sym, []).append(Order(sym, int(ba), qty))
                if bb >= fair + take_th:
                    qty = self._cap_size(sym, state, -40)
                    if qty < 0:
                        result.setdefault(sym, []).append(Order(sym, int(bb), qty))

                # make one tick inside when possible
                bid_px = min(int(math.floor(fair - 1.0 - inv_skew)), ba - 1)
                ask_px = max(int(math.ceil(fair + 1.0 - inv_skew)), bb + 1)
                bid_px = max(bid_px, bb + 1)
                ask_px = min(ask_px, ba - 1)
                if bid_px < ask_px:
                    bid_qty = self._cap_size(sym, state, 35)
                    ask_qty = self._cap_size(sym, state, -35)
                    if bid_qty > 0:
                        result.setdefault(sym, []).append(Order(sym, bid_px, bid_qty))
                    if ask_qty < 0:
                        result.setdefault(sym, []).append(Order(sym, ask_px, ask_qty))

            # 3) Delta control: if voucher delta exposure is big, lean VFE quotes to mean-revert it.
            vfe_od = state.order_depths.get(VFE)
            if vfe_od and vfe_od.buy_orders and vfe_od.sell_orders:
                bb, ba = best_bid_ask(vfe_od)
                vfe_pos = self._pos(state, VFE)

                total_delta = 0.0
                for sym, d in vev_delta.items():
                    total_delta += d * self._pos(state, sym)

                target_vfe = int(round(-total_delta))
                drift = target_vfe - vfe_pos
                if abs(drift) >= 25:
                    # Cross a little to reduce delta quickly (especially helps early day3)
                    step = int(max(15, min(40, abs(drift))))
                    if drift > 0:
                        qty = self._cap_size(VFE, state, step)
                        if qty > 0:
                            result.setdefault(VFE, []).append(Order(VFE, int(ba), qty))
                    else:
                        qty = self._cap_size(VFE, state, -step)
                        if qty < 0:
                            result.setdefault(VFE, []).append(Order(VFE, int(bb), qty))

        return result, 0, ""

