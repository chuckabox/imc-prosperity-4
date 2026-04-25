"""trader_ken_v37.py

Fast iteration variant on v35:
- Keep sparse VEV taker logic from v35.
- Aggressively increase HYDRO maker footprint.

Note: this file depends on trader_ken_v35.py for rapid iteration.
"""
from __future__ import annotations

from trader_ken_v35 import Trader as _BaseTrader


class Trader(_BaseTrader):
    # Hydrogel aggression sweep
    HP_MAKER_EDGE = 1.8
    HP_TAKER_EDGE = 2.1
    HP_TAKER_MAX = 24

    # Slightly looser inventory/risk before throttling
    RISK_HP_POS_TRIGGER = 70

