"""trader_ken_v80_product_pnl_boost.py

Standalone v80 focused on lifting product PnL:
- Keep strong aggression on HYDROGEL / VFE.
- Improve VEV quality: tighter spread filters, slightly stricter entry z-scores.
- Reduce hedge churn so realised product edge is kept.
"""
from __future__ import annotations

import json
from typing import Dict, List, Optional, Tuple

from datamodel import Order, OrderDepth, TradingState

HYDROGEL = "HYDROGEL_PACK"
VFE = "VELVETFRUIT_EXTRACT"
VEV_STRIKES = [5000, 5100, 5200, 5300, 5400]
CORE_LONG_STRIKES = {5200, 5300}

PREM_INIT: Dict[int, float] = {5000: 5.81, 5100: 19.09, 5200: 48.85, 5300: 47.0, 5400: 18.0}
PREM_BOUNDS: Dict[int, Tuple[float, float]] = {
    5000: (2.0, 14.0),
    5100: (10.0, 30.0),
    5200: (28.0, 76.0),
    5300: (20.0, 72.0),
    5400: (7.0, 36.0),
}
STRIKE_CAP: Dict[int, int] = {5000: 40, 5100: 44, 5200: 56, 5300: 56, 5400: 40}
VEV_DELTA_APPROX: Dict[int, float] = {5000: 0.82, 5100: 0.70, 5200: 0.57, 5300: 0.44, 5400: 0.31}


class Trader:
    ENABLE_HYDROGEL = True
    ENABLE_VFE = True
    ENABLE_VEV = True

    # HYDROGEL aggressive baseline
    HP_LIMIT = 200
    HP_ANCHOR = 9993.0
    HP_EWMA_ALPHA = 0.22
    HP_TAKER_EDGE = 0.9
    HP_MAKER_EDGE = 1.0
    HP_TAKER_MAX = 68
    HP_OBI_ENTRY = 0.25
    HP_OBI_TAKER_MAX = 12

    # VFE aggressive, but slightly cleaner to preserve product pnl
    VFE_LIMIT = 200
    VFE_EWMA_ALPHA = 0.22
    VFE_MAKER_EDGE = 1.1
    VFE_TAKER_EDGE = 2.0
    VFE_TAKER_MAX = 36
    VFE_MICRO_TILT = 0.22
    VFE_HEDGE_BAND = 18
    VFE_HEDGE_AGGRO_BAND = 58
    VFE_HEDGE_MAX = 34

    # VEV: less noisy than v79b, higher quality fills
    PREM_ALPHA = 0.06
    PREM_VAR_ALPHA = 0.08
    VEV_Z_ENTRY = 0.92
    VEV_REL_Z_ENTRY = 0.74
    VEV_REL_Z_BOOST = 1.45
    VEV_STRONG_PAIR_SIZE_MULT = 1.62
    VEV_SPREAD_MAX_BY_STRIKE: Dict[int, int] = {5000: 5, 5100: 5, 5200: 4, 5300: 4, 5400: 5}
    VEV_STRONG_SPREAD_MAX = 2
    VEV_TAKER_MAX_BY_STRIKE: Dict[int, int] = {5000: 8, 5100: 10, 5200: 14, 5300: 14, 5400: 8}
    VEV_MAKER_MAX_BY_STRIKE: Dict[int, int] = {5000: 6, 5100: 7, 5200: 10, 5300: 10, 5400: 6}
    VEV_MAKER_EDGE = 1.05
    VEV_STRUCT_LONG_Z = -0.48
    VEV_STRUCT_LONG_SIZE = 5
    VEV_STRUCT_LONG_SPREAD_MAX = 2

    # Risk (slightly tighter than v79b for better realised edge retention)
    RISK_NET_DELTA_TRIGGER = 120.0
    RISK_HP_POS_TRIGGER = 176
    RISK_ADVERSE_MOVE = 2.6
    RISK_MIN_SCALE = 0.24
    RISK_VEV_GUARD_TS = 0
    RISK_VEV_GUARD_DECAY = 0.978
    RISK_VEV_GUARD_SCALE_CUT = 0.18
    RISK_VEV_GUARD_Z_BUMP = 0.08
    RISK_VEV_GUARD_REL_BUMP = 0.08

    # soft brakes
    OPEN_PHASE_TS = 120_000
    HP_SPEED_TRIGGER = 60
    VFE_SPEED_TRIGGER = 54
    SPEED_COOLDOWN_TS = 40_000
    OPEN_SCALE_MULT = 0.96
    SPEED_SCALE_MULT = 0.90

    def __init__(self):
        self.history: Dict = {}

    def _load_state(self, state: TradingState) -> None:
        if state.traderData:
            try:
                self.history = json.loads(state.traderData)
            except Exception:
                self.history = {}
        self.history.setdefault("hp_ewma", None)
        self.history.setdefault("vfe_ewma", None)
        self.history.setdefault("prem", {})
        self.history.setdefault("prem_var", {})
        self.history.setdefault("last_hp_mid", None)
        self.history.setdefault("last_vfe_mid", None)
        self.history.setdefault("last_hp_pos", 0)
        self.history.setdefault("last_vfe_pos", 0)
        self.history.setdefault("hp_speed_cooldown_until", -1)
        self.history.setdefault("vfe_speed_cooldown_until", -1)
        self.history.setdefault("vev_guard_until", -1)
        self.history.setdefault("vev_guard_level", 0.0)
        self.history.setdefault("vev_fair", {})
        self.history.setdefault("vev_z", {})
        for k in VEV_STRIKES:
            self.history["prem"].setdefault(str(k), PREM_INIT[k])
            self.history["prem_var"].setdefault(str(k), 9.0)

    def _save_state(self) -> str:
        return json.dumps(self.history)

    @staticmethod
    def _top(depth: OrderDepth) -> Tuple[Optional[int], Optional[int]]:
        bb = max(depth.buy_orders.keys()) if depth.buy_orders else None
        ba = min(depth.sell_orders.keys()) if depth.sell_orders else None
        return bb, ba

    def _guarded_maker(
        self,
        symbol: str,
        depth: OrderDepth,
        pos: int,
        fair: float,
        limit: int,
        edge: float,
        max_qty: Optional[int] = None,
    ) -> List[Order]:
        orders = []
        bb, ba = self._top(depth)
        if bb is None or ba is None:
            return []
        qbid = int(round(fair - edge))
        qask = int(round(fair + edge))
        if qbid >= ba:
            qbid = ba - 1
        if qask <= bb:
            qask = bb + 1
        if qbid >= qask:
            qbid = qask - 1
        room_long = limit - pos
        room_short = limit + pos
        if max_qty is not None:
            room_long = min(room_long, max_qty)
            room_short = min(room_short, max_qty)
        if room_long > 0:
            orders.append(Order(symbol, qbid, room_long))
        if room_short > 0:
            orders.append(Order(symbol, qask, -room_short))
        return orders

    def _deep_take(
        self,
        symbol: str,
        depth: OrderDepth,
        fair: float,
        pos: int,
        limit: int,
        edge: float,
        max_qty: int,
    ) -> Tuple[List[Order], int]:
        orders: List[Order] = []
        curr = pos
        rem_buy = max_qty
        for ask in sorted(depth.sell_orders.keys()):
            if ask > fair - edge or curr >= limit or rem_buy <= 0:
                break
            avail = -depth.sell_orders[ask]
            qty = min(avail, limit - curr, rem_buy)
            if qty > 0:
                orders.append(Order(symbol, ask, qty))
                curr += qty
                rem_buy -= qty
        rem_sell = max_qty
        for bid in sorted(depth.buy_orders.keys(), reverse=True):
            if bid < fair + edge or curr <= -limit or rem_sell <= 0:
                break
            avail = depth.buy_orders[bid]
            qty = min(avail, limit + curr, rem_sell)
            if qty > 0:
                orders.append(Order(symbol, bid, -qty))
                curr -= qty
                rem_sell -= qty
        return orders, curr

    def _portfolio_net_delta(self, state: TradingState) -> float:
        net = float(state.position.get(VFE, 0))
        for k in VEV_STRIKES:
            net += state.position.get(f"VEV_{k}", 0) * VEV_DELTA_APPROX[k]
        return net

    def _risk_state(self, state: TradingState, hp_mid: Optional[float], vfe_mid: Optional[float]) -> Tuple[float, bool]:
        now = int(state.timestamp)
        hp_pos = abs(state.position.get(HYDROGEL, 0))
        net_delta = abs(self._portfolio_net_delta(state))
        score = 0.0
        score += 0.45 * min(1.0, hp_pos / float(self.HP_LIMIT))
        score += 0.55 * min(1.0, net_delta / float(self.VFE_LIMIT))
        last_vfe = self.history.get("last_vfe_mid")
        if vfe_mid is not None and last_vfe is not None:
            dv = float(vfe_mid) - float(last_vfe)
            signed = self._portfolio_net_delta(state)
            if (signed > 0 and dv < -self.RISK_ADVERSE_MOVE) or (signed < 0 and dv > self.RISK_ADVERSE_MOVE):
                score += 0.25
                self.history["vev_guard_until"] = max(
                    int(self.history.get("vev_guard_until", -1)),
                    now + self.RISK_VEV_GUARD_TS,
                )
                self.history["vev_guard_level"] = min(1.0, float(self.history.get("vev_guard_level", 0.0)) + 0.30)
            else:
                self.history["vev_guard_level"] = max(
                    0.0,
                    float(self.history.get("vev_guard_level", 0.0)) * self.RISK_VEV_GUARD_DECAY,
                )
        else:
            self.history["vev_guard_level"] = max(
                0.0,
                float(self.history.get("vev_guard_level", 0.0)) * self.RISK_VEV_GUARD_DECAY,
            )
        risk_off = hp_pos >= self.RISK_HP_POS_TRIGGER or net_delta >= self.RISK_NET_DELTA_TRIGGER or score >= 0.98
        scale = max(self.RISK_MIN_SCALE, 1.0 - min(1.0, score))
        return scale, risk_off

    def _in_open_phase(self, state: TradingState) -> bool:
        return int(state.timestamp) <= self.OPEN_PHASE_TS

    def _speed_limited(self, state: TradingState, symbol: str, trigger: int, cd_key: str, last_pos_key: str) -> bool:
        now = int(state.timestamp)
        pos = int(state.position.get(symbol, 0))
        last_pos = int(self.history.get(last_pos_key, 0))
        if abs(pos - last_pos) >= trigger:
            self.history[cd_key] = now + self.SPEED_COOLDOWN_TS
        self.history[last_pos_key] = pos
        return now < int(self.history.get(cd_key, -1))

    def _hydrogel_logic(self, state: TradingState, scale: float, risk_off: bool) -> Tuple[List[Order], Optional[float]]:
        depth = state.order_depths.get(HYDROGEL)
        if depth is None:
            return [], None
        bb, ba = self._top(depth)
        if bb is None or ba is None:
            return [], None
        mid = (bb + ba) / 2.0
        prev = self.history.get("hp_ewma")
        ewma = mid if prev is None else (1 - self.HP_EWMA_ALPHA) * prev + self.HP_EWMA_ALPHA * mid
        self.history["hp_ewma"] = ewma
        fair = 0.56 * ewma + 0.44 * self.HP_ANCHOR
        speed_limited = self._speed_limited(state, HYDROGEL, self.HP_SPEED_TRIGGER, "hp_speed_cooldown_until", "last_hp_pos")
        local_scale = scale
        if self._in_open_phase(state):
            local_scale *= self.OPEN_SCALE_MULT
        if speed_limited:
            local_scale *= self.SPEED_SCALE_MULT
        pos = state.position.get(HYDROGEL, 0)
        lim = self.HP_LIMIT
        orders: List[Order] = []
        taker_max = max(14, int(self.HP_TAKER_MAX * local_scale))
        maker_max = max(42, int(148 * local_scale))
        if not risk_off:
            tk, pos = self._deep_take(HYDROGEL, depth, fair, pos, lim, self.HP_TAKER_EDGE, taker_max)
            orders.extend(tk)
        bvol = float(depth.buy_orders.get(bb, 0))
        avol = float(-depth.sell_orders.get(ba, 0))
        if (not risk_off) and (bvol + avol) > 0:
            obi = (bvol - avol) / (bvol + avol)
            obi_mx = max(2, int(self.HP_OBI_TAKER_MAX * local_scale))
            if obi >= self.HP_OBI_ENTRY and pos < lim:
                sz = min(obi_mx, lim - pos, -depth.sell_orders[ba])
                if sz > 0:
                    orders.append(Order(HYDROGEL, ba, sz))
                    pos += sz
            elif obi <= -self.HP_OBI_ENTRY and pos > -lim:
                sz = min(obi_mx, lim + pos, depth.buy_orders[bb])
                if sz > 0:
                    orders.append(Order(HYDROGEL, bb, -sz))
                    pos -= sz
        maker_edge = self.HP_MAKER_EDGE + (0.8 if risk_off else 0.0)
        orders.extend(self._guarded_maker(HYDROGEL, depth, pos, fair, lim, maker_edge, max_qty=maker_max))
        return orders, mid

    def _vfe_logic(self, state: TradingState, scale: float, risk_off: bool, target_pos: Optional[int] = None) -> Tuple[List[Order], Optional[float]]:
        depth = state.order_depths.get(VFE)
        if depth is None:
            return [], None
        bb, ba = self._top(depth)
        if bb is None or ba is None:
            return [], None
        mid = (bb + ba) / 2.0
        prev = self.history.get("vfe_ewma")
        ewma = mid if prev is None else (1 - self.VFE_EWMA_ALPHA) * prev + self.VFE_EWMA_ALPHA * mid
        self.history["vfe_ewma"] = ewma
        bid_vol = float(depth.buy_orders.get(bb, 0))
        ask_vol = float(-depth.sell_orders.get(ba, 0))
        if (bid_vol + ask_vol) > 0:
            micro = (bb * ask_vol + ba * bid_vol) / (bid_vol + ask_vol)
        else:
            micro = mid
        fair = (1.0 - self.VFE_MICRO_TILT) * ewma + self.VFE_MICRO_TILT * micro
        speed_limited = self._speed_limited(state, VFE, self.VFE_SPEED_TRIGGER, "vfe_speed_cooldown_until", "last_vfe_pos")
        local_scale = scale
        if self._in_open_phase(state):
            local_scale *= self.OPEN_SCALE_MULT
        if speed_limited:
            local_scale *= self.SPEED_SCALE_MULT
        pos = state.position.get(VFE, 0)
        lim = self.VFE_LIMIT
        orders: List[Order] = []
        if target_pos is not None:
            residual = target_pos - pos
            if abs(residual) >= self.VFE_HEDGE_BAND:
                hmx = max(7, int(self.VFE_HEDGE_MAX * local_scale))
                if residual > 0 and pos < lim:
                    hq = min(hmx, residual, lim - pos, -depth.sell_orders[ba])
                    if hq > 0:
                        orders.append(Order(VFE, ba, hq))
                        pos += hq
                elif residual < 0 and pos > -lim:
                    hq = min(hmx, -residual, lim + pos, depth.buy_orders[bb])
                    if hq > 0:
                        orders.append(Order(VFE, bb, -hq))
                        pos -= hq
        taker_max = max(9, int(self.VFE_TAKER_MAX * local_scale))
        maker_max = max(28, int(120 * local_scale))
        hedge_residual_after = 0 if target_pos is None else abs(target_pos - pos)
        allow_alpha_take = (not risk_off) and (hedge_residual_after <= self.VFE_HEDGE_AGGRO_BAND)
        if allow_alpha_take:
            tk, pos = self._deep_take(VFE, depth, fair, pos, lim, self.VFE_TAKER_EDGE, taker_max)
            orders.extend(tk)
        maker_edge = self.VFE_MAKER_EDGE + (0.8 if risk_off else 0.0)
        orders.extend(self._guarded_maker(VFE, depth, pos, fair, lim, maker_edge, max_qty=maker_max))
        return orders, mid

    def _vev_logic(self, state: TradingState, vfe_mid: float, scale: float, risk_off: bool) -> List[Order]:
        if risk_off:
            return []
        now = int(state.timestamp)
        guard_level = float(self.history.get("vev_guard_level", 0.0))
        guard_active = now < int(self.history.get("vev_guard_until", -1))
        local_scale = scale * (1.0 - self.RISK_VEV_GUARD_SCALE_CUT * guard_level) if guard_active else scale
        local_scale = max(0.26, local_scale)
        rel_entry = self.VEV_REL_Z_ENTRY + (self.RISK_VEV_GUARD_REL_BUMP * guard_level if guard_active else 0.0)
        z_entry = self.VEV_Z_ENTRY + (self.RISK_VEV_GUARD_Z_BUMP * guard_level if guard_active else 0.0)
        cands: List[Tuple[float, int, int, int, float, float, int]] = []
        per_strike: Dict[int, Tuple[int, int, float, float, int]] = {}
        for strike in VEV_STRIKES:
            sym = f"VEV_{strike}"
            depth = state.order_depths.get(sym)
            if depth is None:
                continue
            bb, ba = self._top(depth)
            if bb is None or ba is None:
                continue
            spread = ba - bb
            if spread <= 0 or spread > self.VEV_SPREAD_MAX_BY_STRIKE[strike]:
                continue
            obs_mid = (bb + ba) / 2.0
            intrinsic = max(vfe_mid - strike, 0.0)
            obs_prem = obs_mid - intrinsic
            prem_key = str(strike)
            prev_prem = float(self.history["prem"][prem_key])
            prem = (1 - self.PREM_ALPHA) * prev_prem + self.PREM_ALPHA * obs_prem
            lo, hi = PREM_BOUNDS[strike]
            prem = max(lo, min(hi, prem))
            self.history["prem"][prem_key] = prem
            dev = obs_prem - prem
            prev_var = float(self.history["prem_var"][prem_key])
            var = (1 - self.PREM_VAR_ALPHA) * prev_var + self.PREM_VAR_ALPHA * (dev * dev)
            var = max(1.0, var)
            self.history["prem_var"][prem_key] = var
            sigma = var ** 0.5
            z = dev / sigma
            fair = intrinsic + prem
            mny_penalty = abs(strike - vfe_mid) / 200.0
            cands.append((abs(z) - 0.08 * mny_penalty, strike, bb, ba, z, fair, spread))
            per_strike[strike] = (bb, ba, z, fair, spread)
            self.history["vev_fair"][str(strike)] = fair
            self.history["vev_z"][str(strike)] = z
        if not cands:
            return []
        raw = [(strike, bb, ba, z, fair, spread) for _, strike, bb, ba, z, fair, spread in cands]
        rich = [x for x in raw if x[3] >= rel_entry]
        cheap = [x for x in raw if x[3] <= -rel_entry]
        rich.sort(key=lambda x: x[3], reverse=True)
        cheap.sort(key=lambda x: x[3])
        orders: List[Order] = []
        if rich and cheap:
            sell_k, sell_bb, _, _, _, sell_spread = rich[0]
            buy_k, _, buy_ba, _, _, buy_spread = cheap[0]
            if sell_k != buy_k:
                sell_sym = f"VEV_{sell_k}"
                buy_sym = f"VEV_{buy_k}"
                sell_d = state.order_depths[sell_sym]
                buy_d = state.order_depths[buy_sym]
                sell_pos = state.position.get(sell_sym, 0)
                buy_pos = state.position.get(buy_sym, 0)
                sell_lim = STRIKE_CAP[sell_k]
                buy_lim = STRIKE_CAP[buy_k]
                strong_pair = (
                    (not guard_active)
                    and abs(rich[0][3]) >= self.VEV_REL_Z_BOOST
                    and abs(cheap[0][3]) >= self.VEV_REL_Z_BOOST
                    and sell_spread <= self.VEV_STRONG_SPREAD_MAX
                    and buy_spread <= self.VEV_STRONG_SPREAD_MAX
                )
                pair_scale = local_scale * (self.VEV_STRONG_PAIR_SIZE_MULT if strong_pair else 1.0)
                sell_mx = max(1, int(self.VEV_TAKER_MAX_BY_STRIKE[sell_k] * pair_scale))
                buy_mx = max(1, int(self.VEV_TAKER_MAX_BY_STRIKE[buy_k] * pair_scale))
                q_sell = min(sell_mx, sell_lim + sell_pos, sell_d.buy_orders.get(sell_bb, 0))
                q_buy = min(buy_mx, buy_lim - buy_pos, -buy_d.sell_orders.get(buy_ba, 0))
                q = min(q_sell, q_buy)
                if q > 0:
                    orders.append(Order(sell_sym, sell_bb, -q))
                    orders.append(Order(buy_sym, buy_ba, q))
        cands.sort(reverse=True, key=lambda x: x[0])
        _, strike, bb, ba, z, fair, _ = cands[0]
        sym = f"VEV_{strike}"
        depth = state.order_depths[sym]
        pos = state.position.get(sym, 0)
        lim = STRIKE_CAP[strike]
        taker_max = max(1, int(self.VEV_TAKER_MAX_BY_STRIKE[strike] * local_scale))
        if abs(z) >= z_entry:
            if z <= -z_entry and ba <= fair and pos < lim:
                sz = min(taker_max, lim - pos, -depth.sell_orders[ba])
                if sz > 0:
                    orders.append(Order(sym, ba, sz))
            elif z >= z_entry and bb >= fair and pos > -lim:
                sz = min(taker_max, lim + pos, depth.buy_orders[bb])
                if sz > 0:
                    orders.append(Order(sym, bb, -sz))
        for k, (kbb, kba, kz, kfair, kspread) in per_strike.items():
            ksym = f"VEV_{k}"
            kdepth = state.order_depths[ksym]
            kpos = state.position.get(ksym, 0)
            klim = STRIKE_CAP[k]
            kmx = max(1, int(self.VEV_MAKER_MAX_BY_STRIKE[k] * local_scale))
            orders.extend(self._guarded_maker(ksym, kdepth, kpos, kfair, klim, self.VEV_MAKER_EDGE, max_qty=kmx))
            if (
                k in CORE_LONG_STRIKES
                and kz <= self.VEV_STRUCT_LONG_Z
                and kpos < klim
                and kspread <= self.VEV_STRUCT_LONG_SPREAD_MAX
            ):
                bq = min(self.VEV_STRUCT_LONG_SIZE, kmx, klim - kpos)
                if bq > 0:
                    px = min(int(round(kfair - 1.0)), kba - 1)
                    if px > kbb:
                        orders.append(Order(ksym, px, bq))
        return orders

    def run(self, state: TradingState):
        self._load_state(state)
        result: Dict[str, List[Order]] = {}
        hp_mid = None
        vfe_mid_for_risk = None
        if HYDROGEL in state.order_depths:
            bb, ba = self._top(state.order_depths[HYDROGEL])
            if bb is not None and ba is not None:
                hp_mid = (bb + ba) / 2.0
        if VFE in state.order_depths:
            bb, ba = self._top(state.order_depths[VFE])
            if bb is not None and ba is not None:
                vfe_mid_for_risk = (bb + ba) / 2.0
        scale, risk_off = self._risk_state(state, hp_mid, vfe_mid_for_risk)
        if self.ENABLE_VEV and vfe_mid_for_risk is not None:
            for o in self._vev_logic(state, vfe_mid_for_risk, scale, risk_off):
                result.setdefault(o.symbol, []).append(o)
        target_vfe = int(round(-sum(state.position.get(f"VEV_{k}", 0) * VEV_DELTA_APPROX[k] for k in VEV_STRIKES)))
        target_vfe = max(-self.VFE_LIMIT, min(self.VFE_LIMIT, target_vfe))
        if self.ENABLE_HYDROGEL:
            hp_orders, hp_mid_exec = self._hydrogel_logic(state, scale, risk_off)
            for o in hp_orders:
                result.setdefault(o.symbol, []).append(o)
            if hp_mid_exec is not None:
                self.history["last_hp_mid"] = hp_mid_exec
        if self.ENABLE_VFE:
            vfe_orders, vfe_mid_exec = self._vfe_logic(state, scale, risk_off, target_pos=target_vfe)
            for o in vfe_orders:
                result.setdefault(o.symbol, []).append(o)
            if vfe_mid_exec is not None:
                self.history["last_vfe_mid"] = vfe_mid_exec
        return result, 0, self._save_state()