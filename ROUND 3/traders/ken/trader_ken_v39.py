"""trader_ken_v39.py

Candidate: tighter sparse-options, higher-confidence entries.
Builds on v35 constants only.
"""
from __future__ import annotations

from trader_ken_v35 import Trader as _BaseTrader


class Trader(_BaseTrader):
    # More selective VEV entries
    VEV_Z_ENTRY = 1.95
    VEV_SPREAD_MAX_BY_STRIKE = {5000: 7, 5100: 5, 5200: 3}
    VEV_TAKER_MAX_BY_STRIKE = {5000: 8, 5100: 5, 5200: 3}

    # Slightly stronger hydro baseline
    HP_MAKER_EDGE = 2.1
    HP_TAKER_EDGE = 2.4

