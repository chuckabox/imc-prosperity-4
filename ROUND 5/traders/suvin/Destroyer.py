import json
from collections import defaultdict
from typing import Dict, List, Optional, Tuple

from datamodel import Order, TradingState


class Trader:
    """
    DESTROYER v5 - Aggressive Signal / Ken's Risk Assessment
    
    - USER AGGRESSIVENESS: High limits (50) and large clips (10) for core assets.
    - KEN'S RISK ASSESSMENT: Family-wide capacity capping to prevent correlated over-leverage.
    - SURVIVAL GUARARDS: Passive exits and sigma-regime detection preserved.
    """

    # ── RISK ASSESSMENT CONSTANTS (CAPITAL PRESERVATION) ────────────────
    DRAWDOWN_TOLERANCE   = 800     # PnL units (increased for Destroyer's volume)
    PROFIT_BANDS         = [
        (2000, 600), (5000, 400), (8000, 250), (12000, 150)
    ]
    CONSEC_LOSS_LIMIT    = 3
    CONSEC_LOSS_FREEZE   = 10
    SESSION_PNL_FLOOR    = 0       # never go negative in a session
    VOL_HARD_CEIL        = 80.0
    MIN_EDGE_RATIO       = 2.5

    # ─── persistence ────────────────────────────────────────────────────────────

    def _load(self, trader_data: str) -> Dict:
        if not trader_data: return self._empty_mem()
        try:
            out = json.loads(trader_data)
            for k, v in self._empty_mem().items(): out.setdefault(k, v)
            return out
        except Exception: return self._empty_mem()

    def _empty_mem(self) -> Dict:
        return {
            "last_mid": {}, "entry_mid": {}, "entry_ts": {}, "entry_dir": {}, 
            "vol_hist": {}, "mid_hist": {}, "last_trade_ts": {},
            "last_ts": -1, "day_idx": 0,
            # RISK STATE
            "hwm": 0.0, "realised_pnl": 0.0, "session_pnl": 0.0,
            "frozen": False, "freeze_reason": "",
            "active_tolerance": self.DRAWDOWN_TOLERANCE,
            "consec_losses": {}, "symbol_frozen_until": {},
            "entry_prices": {},
        }

    def _save(self, mem: Dict) -> str:
        for sym in mem["vol_hist"]: mem["vol_hist"][sym] = mem["vol_hist"][sym][-self.VOL_WINDOW:]
        for sym in mem["mid_hist"]: mem["mid_hist"][sym] = mem["mid_hist"][sym][-self.VOL_WINDOW:]
        return json.dumps(mem, separators=(",", ":"))

    # ─── market data helpers ─────────────────────────────────────────────────────

    def _family(self, symbol: str) -> str:
        for prefix in self.FAMILY_PREFIXES:
            if symbol.startswith(prefix + "_"): return prefix
        return symbol.split("_", 1)[0]

    def _best_bid_ask(self, state: TradingState, symbol: str) -> Tuple[Optional[int], Optional[int]]:
        depth = state.order_depths.get(symbol)
        if not depth or not depth.buy_orders or not depth.sell_orders: return None, None
        return max(depth.buy_orders.keys()), min(depth.sell_orders.keys())

    def _mid(self, state: TradingState, symbol: str) -> Optional[float]:
        bid, ask = self._best_bid_ask(state, symbol)
        if bid is None or ask is None: return None
        return 0.5 * (bid + ask)

    def _ask_depth(self, state: TradingState, symbol: str) -> int:
        depth = state.order_depths.get(symbol)
        if not depth or not depth.sell_orders: return 0
        return abs(depth.sell_orders[min(depth.sell_orders.keys())])

    def _bid_depth(self, state: TradingState, symbol: str) -> int:
        depth = state.order_depths.get(symbol)
        if not depth or not depth.buy_orders: return 0
        return abs(depth.buy_orders[max(depth.buy_orders.keys())])

    def _family_caps(self, state: TradingState, fam: str) -> Tuple[int, int]:
        """Ken's Risk Assessment: Calculate buy/sell capacity for the whole family."""
        # Use all symbols in position to get true family exposure
        total_pos = sum(state.position.get(s, 0) for s in state.position if self._family(s) == fam)
        lim = self.FAMILY_LIMITS.get(fam, 20)
        return max(0, lim - total_pos), max(0, lim + total_pos)

    # ─── regime detection ────────────────────────────────────────────────────────

    def _rolling_sigma(self, mem: Dict, symbol: str) -> float:
        hist = mem["vol_hist"].get(symbol, [])
        if len(hist) < 5: return 0.0
        mean = sum(hist) / len(hist)
        variance = sum((x - mean) ** 2 for x in hist) / len(hist)
        return variance ** 0.5

    def _is_broken_regime(self, mem: Dict, symbol: str, config: Dict, d_mid: float) -> bool:
        hist = mem["vol_hist"].get(symbol, [])
        if len(hist) < 10: return False # Not enough data to call a regime "broken"
        
        sigma = self._rolling_sigma(mem, symbol)
        mean = sum(hist) / len(hist)
        
        if sigma < 1.0: # Very stable, don't trigger broken regime
            return False
            
        threshold = mean + self.BROKEN_REGIME_MULT * sigma
        return abs(d_mid) > threshold

    def _get_stats(self, mem: Dict, symbol: str) -> Tuple[float, float]:
        hist = mem["mid_hist"].get(symbol, [])
        if len(hist) < 5: return 0.0, 0.0
        mean = sum(hist) / len(hist)
        std = (sum((x - mean) ** 2 for x in hist) / len(hist)) ** 0.5
        return mean, std

    def _get_zscore(self, mem: Dict, symbol: str, mid: float) -> float:
        mean, std = self._get_stats(mem, symbol)
        if std < 1e-6: return 0.0
        return (mid - mean) / std

    def _dynamic_trigger(self, mem: Dict, symbol: str, config: Dict, spread: int) -> float:
        # Keep old trigger logic for broken regime but add Z-score thresholding
        base = max(config.get("trigger", 15.0), spread * config.get("spread_mult", 2.0))
        sigma = self._rolling_sigma(mem, symbol)
        if sigma > config.get("trigger", 15.0) * 0.6:
            vol_mult = 1.0 + (sigma / config.get("trigger", 15.0))
            base *= min(vol_mult, 2.0)
        return base

    # ─── sizing ─────────────────────────────────────────────────────────────────

    def _conviction_qty(self, abs_dmid: float, trigger: float, config: Dict, pos: int, fam_lim: int, spread: int, day_idx: int) -> int:
        base = config.get("clip", 2)
        if abs_dmid >= self.BIG_SHOCK_THRESHOLD: base += 3
        if spread <= 8: base += 2
            
        risk_factor = self.DAY_RISK_FACTORS.get(day_idx, 0.4)
        raw = int(base * risk_factor)
        
        # Tapering
        inv_ratio = abs(pos) / max(fam_lim, 1)
        if inv_ratio >= self.INVENTORY_TAPER_END: return 0
        if inv_ratio >= self.INVENTORY_TAPER_START:
            taper = 1.0 - (inv_ratio - self.INVENTORY_TAPER_START) / (self.INVENTORY_TAPER_END - self.INVENTORY_TAPER_START)
            raw = max(1, int(raw * taper))
        return max(1, raw)

    # ─── exit decision ───────────────────────────────────────────────────────────

    def _should_exit(self, symbol: str, pos: int, mid: float, mem: Dict, state: TradingState, config: Dict) -> bool:
        if pos == 0: return False
        entry_ts, entry_mid, entry_dir = mem["entry_ts"].get(symbol, -1), mem["entry_mid"].get(symbol, mid), mem["entry_dir"].get(symbol, 0)
        if entry_ts < 0: return False

        # Mean Reversion Exit: Price crosses or returns to mean
        mean, _ = self._get_stats(mem, symbol)
        exit_triggered = False
        if mean != 0:
            if entry_dir == 1 and mid >= mean: exit_triggered = True   # Long exit
            if entry_dir == -1 and mid <= mean: exit_triggered = True  # Short exit

        # Safety Stop Loss
        loss_pts = (entry_mid - mid) * entry_dir
        if loss_pts >= config.get("stop", 25.0): exit_triggered = True

        if exit_triggered:
            mem["last_trade_ts"][symbol] = state.timestamp
            return True
        return False

    def _is_trend(self, symbol: str, d_mid: float, dmids: Dict[str, float], trigger: float) -> bool:
        twins = self.LEAD_FOLLOWERS.get(symbol, [])
        for twin in twins:
            if twin not in dmids: continue
            if (d_mid > 0 and dmids[twin] > self.TREND_TWIN_RATIO * trigger) or (d_mid < 0 and dmids[twin] < -self.TREND_TWIN_RATIO * trigger): return True
        return False

    # ─── main loop ───────────────────────────────────────────────────────────────

    def run(self, state: TradingState):
        mem = self._load(state.traderData)
        if mem["last_ts"] >= 0 and state.timestamp < mem["last_ts"]:
            mem["day_idx"] += 1
            mem["last_mid"] = {}; mem["entry_ts"] = {}; mem["entry_mid"] = {}; mem["entry_dir"] = {}
        mem["last_ts"] = state.timestamp
        result: Dict[str, List[Order]] = defaultdict(list)

        mids: Dict[str, float] = {}; dmids: Dict[str, float] = {}
        for symbol in state.order_depths:
            m = self._mid(state, symbol)
            if m is None: continue
            mids[symbol] = m
            dmids[symbol] = m - mem["last_mid"].get(symbol, m)
            mem["last_mid"][symbol] = m
            mem["vol_hist"].setdefault(symbol, []).append(abs(dmids[symbol]))
            mem["mid_hist"].setdefault(symbol, []).append(m)

        for symbol, mid in mids.items():
            bid, ask = self._best_bid_ask(state, symbol)
            if bid is None or ask is None: continue
            d_mid, spread, fam = dmids[symbol], max(1, ask - bid), self._family(symbol)
            config = self.SYMBOL_PRIORITY_CONFIG.get(symbol, self.FAMILY_CONFIG.get(fam, self.DEFAULT_CONFIG))
            pos = state.position.get(symbol, 0)
            buy_cap, sell_cap = self._family_caps(state, fam) # Ken's Risk Assessment

            if pos != 0:
                if self._should_exit(symbol, pos, mid, mem, state, config):
                    if pos > 0 and sell_cap > 0: 
                        result[symbol].append(Order(symbol, ask, -min(abs(pos), sell_cap)))
                    elif pos < 0 and buy_cap > 0: 
                        result[symbol].append(Order(symbol, bid, min(abs(pos), buy_cap)))
                continue 

            # Only clear state when we are back to flat
            mem["entry_ts"][symbol] = -1
            mem["entry_mid"][symbol] = 0.0
            mem["entry_dir"][symbol] = 0

            # ── ENTRY PATH ────────────────────────────────────────────────────
            if mem["day_idx"] >= 2: continue # Ken's Safety Barrier: Skip late days
            if spread > self.MAX_SPREAD or self._is_broken_regime(mem, symbol, config, d_mid): continue

            # Cooldown check
            last_trade = mem["last_trade_ts"].get(symbol, -1e9)
            if state.timestamp - last_trade < 100 * self.COOLDOWN_TICKS: continue

            zscore = self._get_zscore(mem, symbol, mid)
            trigger = self._dynamic_trigger(mem, symbol, config, spread)
            
            # Entry: High Z-score + Reaction (d_mid) + Not Trending
            if abs(zscore) < self.Z_THRESHOLD: continue
            if (zscore > 0 and d_mid >= 0) or (zscore < 0 and d_mid <= 0): continue # Wait for turn
            if self._is_trend(symbol, d_mid, dmids, trigger): continue
            
            if (zscore > self.Z_THRESHOLD and self._bid_depth(state, symbol) < self.DEPTH_MIN_QTY) or \
               (zscore < -self.Z_THRESHOLD and self._ask_depth(state, symbol) < self.DEPTH_MIN_QTY): continue

            direction = -1 if zscore > 0 else 1
            qty = min(self._conviction_qty(abs(d_mid), trigger, config, pos, self.FAMILY_LIMITS.get(fam, 20), spread, mem["day_idx"]), buy_cap if direction == 1 else sell_cap)
            if qty <= 0: continue

            if direction == 1: result[symbol].append(Order(symbol, ask, qty))
            else: result[symbol].append(Order(symbol, bid, -qty))

            mem["entry_ts"][symbol], mem["entry_mid"][symbol], mem["entry_dir"][symbol] = state.timestamp, mid, direction

        return dict(result), 0, self._save(mem)