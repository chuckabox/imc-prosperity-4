"""Champion variant from focused v71 sweep."""
from __future__ import annotations

from trader_ken_v71_crossstrike_blend import Trader as _Base


class Trader(_Base):
    # From sweep winner v71m_08.
    VFE_MICRO_TILT = 0.16
    HP_OBI_ENTRY = 0.34
    VEV_REL_Z_ENTRY = 0.9

