"""sid/sid_v4.py — shock-fade on ALL 50 Round-5 products.

v3 traded 2 products (MICROCHIP_TRIANGLE + PEBBLES_M).
v4 expands to the full 50-product universe so we can collect per-product
PnL logs and feed them into oracle_v2 (the full overfit sanity check).

Strategy is identical to v3:
  - Wait for a mid-price jump ≥ trigger in one tick (reversion signal)
  - Enter against the move (fade it)
  - Hold for `hold` ticks, then exit at market
  - Cooldown 4 ticks after each trade

Parameters per product are derived from the v3 log stats:
  trigger   ≈ 1.5 × avg_|Δmid|   (conservative — avoids momentum trap)
  big_shock ≈ 2.3 × avg_|Δmid|   (size-up on large shocks)
  max_spread = ceil(observed_avg_spread) + 2  (filter wide-spread ticks)

Products with very wide spreads (SNACKPACKs, GALAXY_SOUNDS, UV_VISOR_YELLOW)
get a higher max_spread tolerance so they aren't filtered out completely.

Position limit = 10 per product (per algo.md / backtester constants).
MAX_ORDERS_PER_TICK raised to 10 to let multiple products fire per tick.
"""

import json
from collections import defaultdict
from typing import Dict, List, Tuple

from datamodel import Order, TradingState


class Trader:
    # Params derived from v3.json log stats (avg_dmid, avg_spread per product).
    # trigger ≈ 1.5x avg_dmid, big_shock ≈ 2.3x avg_dmid,
    # max_spread = round(avg_spread) + 3 (a little headroom)
    PARAMS = {
        # ── GALAXY SOUNDS ──────────────────────────────────────────────────────
        "GALAXY_SOUNDS_BLACK_HOLES":       {"trigger": 14.5, "big_shock": 22.0, "max_spread": 20},
        "GALAXY_SOUNDS_DARK_MATTER":       {"trigger": 13.0, "big_shock": 20.0, "max_spread": 19},
        "GALAXY_SOUNDS_PLANETARY_RINGS":   {"trigger": 13.5, "big_shock": 21.0, "max_spread": 19},
        "GALAXY_SOUNDS_SOLAR_FLAMES":      {"trigger": 13.0, "big_shock": 20.0, "max_spread": 19},
        "GALAXY_SOUNDS_SOLAR_WINDS":       {"trigger": 13.5, "big_shock": 21.0, "max_spread": 19},

        # ── MICROCHIP ──────────────────────────────────────────────────────────
        "MICROCHIP_CIRCLE":                {"trigger": 10.0, "big_shock": 15.5, "max_spread": 13},
        "MICROCHIP_OVAL":                  {"trigger": 12.5, "big_shock": 19.5, "max_spread": 12},
        "MICROCHIP_RECTANGLE":             {"trigger": 14.5, "big_shock": 22.0, "max_spread": 13},
        "MICROCHIP_SQUARE":                {"trigger": 29.0, "big_shock": 45.0, "max_spread": 19},
        "MICROCHIP_TRIANGLE":              {"trigger": 13.0, "big_shock": 22.0, "max_spread": 14},  # proven winner — keep v3 params

        # ── OXYGEN SHAKES ──────────────────────────────────────────────────────
        "OXYGEN_SHAKE_CHOCOLATE":          {"trigger": 10.5, "big_shock": 16.5, "max_spread": 17},
        "OXYGEN_SHAKE_EVENING_BREATH":     {"trigger": 10.5, "big_shock": 16.5, "max_spread": 17},
        "OXYGEN_SHAKE_GARLIC":             {"trigger": 14.0, "big_shock": 22.0, "max_spread": 20},
        "OXYGEN_SHAKE_MINT":               {"trigger": 11.5, "big_shock": 17.5, "max_spread": 18},
        "OXYGEN_SHAKE_MORNING_BREATH":     {"trigger": 11.5, "big_shock": 17.5, "max_spread": 18},

        # ── PANELS ─────────────────────────────────────────────────────────────
        "PANEL_1X2":                       {"trigger": 10.5, "big_shock": 16.0, "max_spread": 16},
        "PANEL_1X4":                       {"trigger": 10.0, "big_shock": 15.5, "max_spread": 13},
        "PANEL_2X2":                       {"trigger": 11.0, "big_shock": 17.0, "max_spread": 13},
        "PANEL_2X4":                       {"trigger": 13.5, "big_shock": 20.5, "max_spread": 15},
        "PANEL_4X4":                       {"trigger": 12.5, "big_shock": 19.0, "max_spread": 15},

        # ── PEBBLES ────────────────────────────────────────────────────────────
        "PEBBLES_L":                       {"trigger": 18.0, "big_shock": 27.5, "max_spread": 19},
        "PEBBLES_M":                       {"trigger": 18.0, "big_shock": 28.0, "max_spread": 19},  # v3 params kept
        "PEBBLES_S":                       {"trigger": 17.5, "big_shock": 27.0, "max_spread": 17},
        "PEBBLES_XL":                      {"trigger": 37.0, "big_shock": 56.5, "max_spread": 21},
        "PEBBLES_XS":                      {"trigger": 18.0, "big_shock": 28.0, "max_spread": 15},

        # ── ROBOTS ─────────────────────────────────────────────────────────────
        "ROBOT_DISHES":                    {"trigger": 12.5, "big_shock": 19.0, "max_spread": 13},
        "ROBOT_IRONING":                   {"trigger":  9.5, "big_shock": 14.5, "max_spread": 11},
        "ROBOT_LAUNDRY":                   {"trigger": 11.0, "big_shock": 16.5, "max_spread": 12},
        "ROBOT_MOPPING":                   {"trigger": 14.0, "big_shock": 22.0, "max_spread": 14},
        "ROBOT_VACUUMING":                 {"trigger": 10.0, "big_shock": 15.5, "max_spread": 12},

        # ── SLEEP PODS ─────────────────────────────────────────────────────────
        "SLEEP_POD_COTTON":                {"trigger": 14.5, "big_shock": 22.5, "max_spread": 16},
        "SLEEP_POD_LAMB_WOOL":             {"trigger": 12.5, "big_shock": 19.5, "max_spread": 15},
        "SLEEP_POD_NYLON":                 {"trigger": 11.5, "big_shock": 17.5, "max_spread": 14},
        "SLEEP_POD_POLYESTER":             {"trigger": 15.5, "big_shock": 24.0, "max_spread": 17},
        "SLEEP_POD_SUEDE":                 {"trigger": 14.5, "big_shock": 22.0, "max_spread": 16},

        # ── SNACKPACKS ─────────────────────────────────────────────────────────
        # Very wide spreads + small avg_dmid → raise max_spread, lower trigger
        "SNACKPACK_CHOCOLATE":             {"trigger":  8.0, "big_shock": 12.0, "max_spread": 22},
        "SNACKPACK_PISTACHIO":             {"trigger":  6.5, "big_shock": 10.0, "max_spread": 22},
        "SNACKPACK_RASPBERRY":             {"trigger":  9.5, "big_shock": 15.0, "max_spread": 23},
        "SNACKPACK_STRAWBERRY":            {"trigger": 10.0, "big_shock": 15.0, "max_spread": 24},
        "SNACKPACK_VANILLA":               {"trigger":  8.0, "big_shock": 12.0, "max_spread": 23},

        # ── TRANSLATORS ────────────────────────────────────────────────────────
        "TRANSLATOR_ASTRO_BLACK":          {"trigger": 11.0, "big_shock": 17.0, "max_spread": 14},
        "TRANSLATOR_ECLIPSE_CHARCOAL":     {"trigger": 11.5, "big_shock": 17.5, "max_spread": 14},
        "TRANSLATOR_GRAPHITE_MIST":        {"trigger": 13.0, "big_shock": 20.5, "max_spread": 15},
        "TRANSLATOR_SPACE_GRAY":           {"trigger": 12.0, "big_shock": 18.5, "max_spread": 14},
        "TRANSLATOR_VOID_BLUE":            {"trigger": 12.5, "big_shock": 19.5, "max_spread": 15},

        # ── UV VISORS ──────────────────────────────────────────────────────────
        "UV_VISOR_AMBER":                  {"trigger":  9.0, "big_shock": 13.5, "max_spread": 15},
        "UV_VISOR_MAGENTA":                {"trigger": 13.0, "big_shock": 20.5, "max_spread": 20},
        "UV_VISOR_ORANGE":                 {"trigger": 12.5, "big_shock": 19.0, "max_spread": 19},
        "UV_VISOR_RED":                    {"trigger": 13.5, "big_shock": 20.5, "max_spread": 20},
        "UV_VISOR_YELLOW":                 {"trigger": 14.5, "big_shock": 22.0, "max_spread": 21},
    }

    POS_LIMIT = 10
    HOLD_DEFAULT = 1
    HOLD_BIG = 2
    COOLDOWN_TICKS = 4
    MAX_ORDERS_PER_TICK = 10   # raised from v3's 2 — 50 products need more headroom
    ENTRY_SIZE_DEFAULT = 3
    ENTRY_SIZE_BIG = 5

    # ── state helpers ──────────────────────────────────────────────────────────

    def _load(self, td: str) -> dict:
        if not td:
            return {"last_mid": {}, "entries": {}, "last_trade_ts": {}, "last_ts": -1, "day_idx": 0}
        try:
            mem = json.loads(td)
            mem.setdefault("last_mid", {})
            mem.setdefault("entries", {})
            mem.setdefault("last_trade_ts", {})
            mem.setdefault("last_ts", -1)
            mem.setdefault("day_idx", 0)
            return mem
        except Exception:
            return {"last_mid": {}, "entries": {}, "last_trade_ts": {}, "last_ts": -1, "day_idx": 0}

    def _save(self, mem: dict) -> str:
        return json.dumps(mem, separators=(",", ":"))

    @staticmethod
    def _best_bid_ask(state: TradingState, sym: str):
        d = state.order_depths.get(sym)
        if not d or not d.buy_orders or not d.sell_orders:
            return None, None
        return max(d.buy_orders.keys()), min(d.sell_orders.keys())

    def _entry_size(self, d_mid: float, big_shock: float, spread: int) -> int:
        size = self.ENTRY_SIZE_DEFAULT if abs(d_mid) < big_shock else self.ENTRY_SIZE_BIG
        if spread <= 6:
            size += 1
        return min(self.POS_LIMIT // 2 + 1, max(1, size))

    # ── main ──────────────────────────────────────────────────────────────────

    def run(self, state: TradingState):
        mem = self._load(state.traderData)

        # Day rollover detection
        if mem["last_ts"] >= 0 and state.timestamp < mem["last_ts"]:
            mem["day_idx"] += 1
            mem["last_mid"] = {}
            mem["entries"] = {}
            mem["last_trade_ts"] = {}
        mem["last_ts"] = state.timestamp

        result: Dict[str, List[Order]] = defaultdict(list)
        orders_this_tick = 0

        for sym, cfg in self.PARAMS.items():
            if orders_this_tick >= self.MAX_ORDERS_PER_TICK:
                break
            if sym not in state.order_depths:
                continue

            bid, ask = self._best_bid_ask(state, sym)
            if bid is None or ask is None:
                continue

            spread = ask - bid
            if spread <= 0 or spread > cfg["max_spread"]:
                continue

            mid = 0.5 * (bid + ask)
            last_mid = mem["last_mid"].get(sym, mid)
            d_mid = mid - last_mid
            mem["last_mid"][sym] = mid

            pos = state.position.get(sym, 0)
            buy_cap = max(0, self.POS_LIMIT - pos)
            sell_cap = max(0, self.POS_LIMIT + pos)

            # ── exit open position ────────────────────────────────────────────
            ent = mem["entries"].get(sym)
            if ent:
                target_ts = ent["ts"] + 100 * ent["hold"]
                if state.timestamp >= target_ts:
                    if pos > 0 and sell_cap > 0:
                        q = min(pos, sell_cap)
                        result[sym].append(Order(sym, bid, -q))
                        orders_this_tick += 1
                    elif pos < 0 and buy_cap > 0:
                        q = min(-pos, buy_cap)
                        result[sym].append(Order(sym, ask, q))
                        orders_this_tick += 1
                    mem["entries"].pop(sym, None)
                    mem["last_trade_ts"][sym] = state.timestamp
                continue  # don't open new trades while an entry is pending exit

            # ── skip if already holding or in cooldown ────────────────────────
            if pos != 0:
                continue
            last_trade = mem["last_trade_ts"].get(sym, -10**9)
            if state.timestamp - last_trade < 100 * self.COOLDOWN_TICKS:
                continue

            # ── check trigger ─────────────────────────────────────────────────
            if abs(d_mid) < cfg["trigger"]:
                continue

            big = abs(d_mid) >= cfg["big_shock"]
            hold = self.HOLD_BIG if big else self.HOLD_DEFAULT
            qty_max = self._entry_size(d_mid, cfg["big_shock"], spread)

            if d_mid <= -cfg["trigger"]:           # price dropped → buy the dip
                qty = min(qty_max, buy_cap)
                if qty > 0:
                    result[sym].append(Order(sym, ask, qty))
                    mem["entries"][sym] = {"ts": state.timestamp, "hold": hold, "side": "BUY"}
                    mem["last_trade_ts"][sym] = state.timestamp
                    orders_this_tick += 1

            elif d_mid >= cfg["trigger"]:          # price spiked → sell the spike
                qty = min(qty_max, sell_cap)
                if qty > 0:
                    result[sym].append(Order(sym, bid, -qty))
                    mem["entries"][sym] = {"ts": state.timestamp, "hold": hold, "side": "SELL"}
                    mem["last_trade_ts"][sym] = state.timestamp
                    orders_this_tick += 1

        return dict(result), 0, self._save(mem)