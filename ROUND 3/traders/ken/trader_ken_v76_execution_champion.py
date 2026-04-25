"""Champion variant from v74 execution-quality sweep."""
from __future__ import annotations

from trader_ken_v74_refine_champion import Trader as _Base


class Trader(_Base):
    # From sweep winner v74e_00.
    VEV_TAKER_MAX_BY_STRIKE = {5000: 4, 5100: 5, 5200: 6, 5300: 6, 5400: 4}
    VEV_SPREAD_MAX_BY_STRIKE = {5000: 6, 5100: 6, 5200: 6, 5300: 6, 5400: 6}

