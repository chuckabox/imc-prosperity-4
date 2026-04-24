"""trader_ken_v28.py — empirical tune of v22 for better total PnL.

This version intentionally keeps v22 architecture (no over-engineering) and only
applies the highest-performing parameter set from a Round 3 capsule sweep.
"""
from __future__ import annotations

from trader_ken_v22 import Trader as TraderV22


class Trader(TraderV22):
    # Best-performing sweep settings vs v22 baseline on local Round 3 capsule.
    HP_TAKER_EDGE = 2.5
    HP_MAKER_EDGE = 2.5
    RISK_HP_POS_TRIGGER = 66

