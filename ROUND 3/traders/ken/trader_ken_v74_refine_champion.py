"""Champion variant from v73 refinement sweep."""
from __future__ import annotations

from trader_ken_v73_signal_depth_champion import Trader as _Base


class Trader(_Base):
    # From sweep winner v73r_13.
    HP_OBI_ENTRY = 0.34
    VEV_Z_ENTRY = 1.20
    VEV_REL_Z_ENTRY = 0.90

