"""trader_ken_v52_smile_pure.py

Pure smile-residual + VFE hedge (no hydro module).
"""
from __future__ import annotations

from trader_ken_v51_smile import Trader as _BaseTrader


class Trader(_BaseTrader):
    ENABLE_HYDRO = False
    VEV_ENTRY_Z = 1.65
    VEV_SPREAD_MAX = 6
    VEV_TAKER_MAX = 6

