"""trader_ken_v79b_full_send.py

Higher-aggression parameterization of v79 for portal A/B testing.
Keeps the same logic as v79, but with stronger taker/maker throughput
and looser risk throttles to chase higher PnL.
"""
from __future__ import annotations

from trader_ken_v79_portal_recovery import Trader as _Base


class Trader(_Base):
    # HYDROGEL: full-send cash-cow
    HP_TAKER_EDGE = 0.8
    HP_MAKER_EDGE = 1.0
    HP_TAKER_MAX = 72
    HP_OBI_ENTRY = 0.24
    HP_OBI_TAKER_MAX = 14

    # VFE: tighter + larger
    VFE_MAKER_EDGE = 1.0
    VFE_TAKER_EDGE = 1.8
    VFE_TAKER_MAX = 42
    VFE_MICRO_TILT = 0.24
    VFE_HEDGE_BAND = 14
    VFE_HEDGE_AGGRO_BAND = 52
    VFE_HEDGE_MAX = 38

    # VEV: enter more often, size bigger
    VEV_Z_ENTRY = 0.78
    VEV_REL_Z_ENTRY = 0.62
    VEV_REL_Z_BOOST = 1.35
    VEV_STRONG_PAIR_SIZE_MULT = 1.72
    VEV_TAKER_MAX_BY_STRIKE = {5000: 9, 5100: 11, 5200: 16, 5300: 16, 5400: 9}
    VEV_MAKER_MAX_BY_STRIKE = {5000: 7, 5100: 8, 5200: 12, 5300: 12, 5400: 7}
    VEV_MAKER_EDGE = 0.9
    VEV_STRUCT_LONG_Z = -0.40
    VEV_STRUCT_LONG_SIZE = 7

    # Risk: looser to avoid over-throttling
    RISK_NET_DELTA_TRIGGER = 130.0
    RISK_HP_POS_TRIGGER = 184
    RISK_MIN_SCALE = 0.22
    RISK_VEV_GUARD_SCALE_CUT = 0.16
    RISK_VEV_GUARD_Z_BUMP = 0.06
    RISK_VEV_GUARD_REL_BUMP = 0.06

    # Soften opening/speed brakes
    OPEN_SCALE_MULT = 0.97
    SPEED_SCALE_MULT = 0.90
    HP_SPEED_TRIGGER = 60
    VFE_SPEED_TRIGGER = 54

