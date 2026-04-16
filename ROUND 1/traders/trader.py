"""
Dashboard compatibility module.

`ROUND 1/tools/dashboard.py` expects `from trader import Trader, logger`.
This repo stores strategies as `trader_*.py`, so we re-export the robust
strategy as a default "template" implementation.
"""

from trader_robust import Trader, logger

