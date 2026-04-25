"""Champion variant from v72 signal-depth sweep."""
from __future__ import annotations

from trader_ken_v72_stacked_alpha_champion import Trader as _Base


class Trader(_Base):
    # From sweep winner v72s_01.
    VFE_MICRO_TILT = 0.16
    HP_OBI_ENTRY = 0.30
    VEV_REL_Z_ENTRY = 0.90
    VEV_Z_ENTRY = 1.30
    HP_OBI_TAKER_MAX = 4

