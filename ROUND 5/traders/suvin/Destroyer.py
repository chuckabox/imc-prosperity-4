import json
from collections import defaultdict
from typing import Dict, List, Tuple

from datamodel import Order, TradingState


class Trader:
    """
    DESTROYER: The Ultimate Round 5 Strategy.
    Combines aggressive multi-family shock reversion with safe PNL guards.
    Optimized for high-volatility pairs (PEBBLES, MICROCHIP) with dynamic 
    spread-gating and inventory-aware execution.
    """

    FAMILY_PREFIXES = [
        "PEBBLES", "MICROCHIP", "ROBOT", "OXYGEN_SHAKE", "PANEL",
        "GALAXY_SOUNDS", "TRANSLATOR", "SLEEP_POD", "UV_VISOR", "SNACKPACK"
    ]

    # Optimized limits and triggers per family based on volatility analysis
    FAMILY_CONFIG = {
        "PEBBLES": {"limit": 45, "trigger": 12.0, "spread_mult": 1.1, "clip": 10},
        "MICROCHIP": {"limit": 40, "trigger": 10.0, "spread_mult": 1.2, "clip": 8},
        "ROBOT": {"limit": 35, "trigger": 14.0, "spread_mult": 1.3, "clip": 6},
        "OXYGEN_SHAKE": {"limit": 30, "trigger": 9.0, "spread_mult": 1.5, "clip": 5},
        "PANEL": {"limit": 30, "trigger": 9.0, "spread_mult": 1.5, "clip": 5},
        "GALAXY_SOUNDS": {"limit": 25, "trigger": 16.0, "spread_mult": 1.4, "clip": 4},
        "TRANSLATOR": {"limit": 25, "trigger": 11.0, "spread_mult": 1.4, "clip": 4},
        "SLEEP_POD": {"limit": 25, "trigger": 11.0, "spread_mult": 1.4, "clip": 4},
        "UV_VISOR": {"limit": 25, "trigger": 11.0, "spread_mult": 1.4, "clip": 4},
        "SNACKPACK": {"limit": 20, "trigger": 8.0, "spread_mult": 1.6, "clip": 3},
    }

    DEFAULT_CONFIG = {"limit": 20, "trigger": 10.0, "spread_mult": 1.5, "clip": 2}
    
    # Global safety guards
    MAX_SPREAD = 30
    MIN_SHOCK_TO_SPREAD_RATIO = 0.85 # Even for aggressive, don't trade tiny shocks
    
    def _load(self, trader_data: str) -> Dict:
        if not trader_data:
            return {"last_mid": {}, "last_ts": -1, "day_idx": 0, "entry_ts": {}}
        try:
            out = json.loads(trader_data)
            out.setdefault("last_mid", {})
            out.setdefault("last_ts", -1)
            out.setdefault("day_idx", 0)
            out.setdefault("entry_ts", {})
            return out
        except Exception:
            return {"last_mid": {}, "last_ts": -1, "day_idx": 0, "entry_ts": {}}

    def _save(self, mem: Dict) -> str:
        return json.dumps(mem, separators=(",", ":"))

    def _family(self, symbol: str) -> str:
        for prefix in self.FAMILY_PREFIXES:
            if symbol.startswith(prefix + "_"):
                return prefix
        return symbol.split("_", 1)[0]

    def _best_bid_ask(self, state: TradingState, symbol: str) -> Tuple[int, int]:
        depth = state.order_depths.get(symbol)
        if not depth or not depth.buy_orders or not depth.sell_orders:
            return None, None
        return max(depth.buy_orders.keys()), min(depth.sell_orders.keys())

    def _mid(self, state: TradingState, symbol: str) -> float:
        bid, ask = self._best_bid_ask(state, symbol)
        if bid is None or ask is None:
            return None
        return 0.5 * (bid + ask)

    # Highest quality pairs for lead-lag and signal stacking
    # Format: lead -> list of (follower, correlation_strength)
    CORRELATIONS = {
        "TRANSLATOR_ASTRO_BLACK": ["TRANSLATOR_GRAPHITE_MIST"],
        "MICROCHIP_OVAL": ["MICROCHIP_SQUARE"],
        "SLEEP_POD_NYLON": ["SLEEP_POD_POLYESTER"],
        "MICROCHIP_CIRCLE": ["MICROCHIP_OVAL"],
        "ROBOT_DISHES": ["ROBOT_VACUUMING"],
        "PANEL_2X2": ["PANEL_2X4"],
    }

    def run(self, state: TradingState):
        mem = self._load(state.traderData)
        
        # Day wrap detection and state reset
        if mem["last_ts"] >= 0 and state.timestamp < mem["last_ts"]:
            mem["day_idx"] += 1
            mem["last_mid"] = {}
            mem["entry_ts"] = {}
        mem["last_ts"] = state.timestamp

        result: Dict[str, List[Order]] = defaultdict(list)
        
        # Pre-calculate all mids for correlation logic
        mids: Dict[str, float] = {}
        dmids: Dict[str, float] = {}
        for symbol in state.order_depths.keys():
            m = self._mid(state, symbol)
            if m is None:
                continue
            mids[symbol] = m
            last_m = mem["last_mid"].get(symbol, m)
            dmids[symbol] = m - last_m
            mem["last_mid"][symbol] = m

        # Iterate over all available symbols to "go all out"
        for symbol, mid in mids.items():
            bid, ask = self._best_bid_ask(state, symbol)
            if bid is None or ask is None:
                continue
            
            d_mid = dmids[symbol]
            spread = max(1, ask - bid)
            
            # Fetch family-specific config
            fam = self._family(symbol)
            config = self.FAMILY_CONFIG.get(fam, self.DEFAULT_CONFIG)
            
            pos = state.position.get(symbol, 0)
            lim = config["limit"]
            buy_cap = max(0, lim - pos)
            sell_cap = max(0, lim + pos)
            
            # Exit Logic: Close positions from previous shocks
            entry_ts = mem["entry_ts"].get(symbol, -1)
            if pos != 0 and entry_ts >= 0 and state.timestamp > entry_ts:
                # Use taker orders for exit to capture edge
                if pos > 0 and sell_cap > 0:
                    result[symbol].append(Order(symbol, bid, -min(abs(pos), sell_cap)))
                elif pos < 0 and buy_cap > 0:
                    result[symbol].append(Order(symbol, ask, min(abs(pos), buy_cap)))
                mem["entry_ts"][symbol] = -1
                continue

            # Entry Logic: High-conviction shock reversion with Correlation Filtering
            if pos == 0:
                if spread > self.MAX_SPREAD:
                    continue
                
                # Dynamic Trigger: Scaled by spread and family volatility
                trigger = max(config["trigger"], spread * config["spread_mult"])
                
                abs_dmid = abs(d_mid)
                if abs_dmid >= trigger:
                    # CORRELATION FILTER (The "Safe" part of Destroyer)
                    # If our "twin" symbol is also moving in the same direction, 
                    # the shock is likely a trend shift rather than a temporary spike.
                    is_trend = False
                    twins = self.CORRELATIONS.get(symbol, [])
                    for twin in twins:
                        if twin in dmids:
                            twin_dmid = dmids[twin]
                            # If twin moves more than 50% of our shock in same direction, call it a trend
                            if (d_mid > 0 and twin_dmid > 0.5 * trigger) or \
                               (d_mid < 0 and twin_dmid < -0.5 * trigger):
                                is_trend = True
                                break
                    
                    if is_trend:
                        continue # Skip reversion trade on trends

                    # Aggressive sizing scaled by shock magnitude
                    base_qty = config["clip"]
                    bonus_qty = int((abs_dmid - trigger) / 2.0)
                    qty = min(base_qty + bonus_qty, lim)
                    
                    if d_mid <= -trigger and buy_cap > 0:
                        # BUY into the idiosyncratic drop
                        exec_qty = min(qty, buy_cap)
                        if exec_qty > 0:
                            result[symbol].append(Order(symbol, ask, exec_qty))
                            mem["entry_ts"][symbol] = state.timestamp
                    elif d_mid >= trigger and sell_cap > 0:
                        # SELL into the idiosyncratic jump
                        exec_qty = min(qty, sell_cap)
                        if exec_qty > 0:
                            result[symbol].append(Order(symbol, bid, -exec_qty))
                            mem["entry_ts"][symbol] = state.timestamp

        return dict(result), 0, self._save(mem)
