import json
from typing import Dict, List, Tuple
from datamodel import Order, TradingState


def _median(vals: list) -> float:
    n = len(vals)
    if n == 0:
        return 0.0
    s = sorted(vals)
    mid = n // 2
    return float(s[mid]) if n % 2 == 1 else (s[mid - 1] + s[mid]) / 2.0


def _vwap(orders: dict, side: str) -> float:
    """Volume-weighted average price from an order book side."""
    total_vol = 0
    total_val = 0.0
    for price, qty in orders.items():
        vol = abs(qty)
        total_vol += vol
        total_val += price * vol
    return total_val / total_vol if total_vol > 0 else 0.0


class Trader:
    LIMIT = 80
    OSMIUM_ANCHOR = 10_000

    # --- Pepper warm-up config ---
    WARMUP_TICKS = 20          # Hold fire until we have this many mid samples
    BASE_SAMPLE_SIZE = 15      # Samples used to establish baseline
    HIST_MAX = 100             # Rolling history window
    SIGNAL_WINDOW = 15         # Recent window for drift calc

    # --- Drift thresholds (lower = more sensitive) ---
    DRIFT_LARGE = 0.015        # Was 0.02 — slight tightening for stability
    DRIFT_SMALL = 0.004        # Was 0.005

    # --- Osmium imbalance config ---
    IMBALANCE_RATIO = 1.3      # Tighter than 1.5 — faster to react
    IMBALANCE_NUDGE = 1.5      # Bigger nudge for more alpha

    def __init__(self):
        self.history: Dict[str, list] = {}

    def _load_state(self, state: TradingState):
        if state.traderData:
            try:
                self.history = json.loads(state.traderData)
            except Exception:
                self.history = {}

    # ------------------------------------------------------------------ #
    #  PEPPER LOGIC                                                        #
    # ------------------------------------------------------------------ #
    def _pepper_logic(self, state: TradingState) -> List[Order]:
        product = "INTARIAN_PEPPER_ROOT"
        if product not in state.order_depths:
            return []

        depth = state.order_depths[product]
        pos = state.position.get(product, 0)

        if not depth.buy_orders or not depth.sell_orders:
            return []

        bb = max(depth.buy_orders.keys())
        ba = min(depth.sell_orders.keys())
        spread = ba - bb
        mid = (bb + ba) / 2.0
        ts = state.timestamp

        # --- Rolling history ---
        hist = self.history.setdefault("pp", [])
        hist.append(mid)
        if len(hist) > self.HIST_MAX:
            hist.pop(0)

        # --- Baseline: lock in during first BASE_SAMPLE_SIZE ticks ---
        base_samples = self.history.setdefault("pp_base", [])
        if len(base_samples) < self.BASE_SAMPLE_SIZE:
            base_samples.append(mid)

        # Record start timestamp once
        if "pp_t0" not in self.history:
            self.history["pp_t0"] = ts
        start_ts = self.history["pp_t0"]

        # ----------------------------------------------------------------
        # WARM-UP GUARD: do nothing aggressive until we have enough data.
        # Place a tiny passive spread to avoid being flat & paying spread.
        # ----------------------------------------------------------------
        if len(hist) < self.WARMUP_TICKS:
            # Passive quotes only — no crossing, tiny size
            orders = []
            if pos < self.LIMIT:
                orders.append(Order(product, bb, 1))      # join best bid
            if pos > -self.LIMIT:
                orders.append(Order(product, ba, -1))     # join best ask
            return orders

        # ----------------------------------------------------------------
        # DRIFT SIGNAL
        # ----------------------------------------------------------------
        target_pos = 0
        if len(base_samples) >= self.BASE_SAMPLE_SIZE:
            base_mean = _median(base_samples)
            current_mean = _median(hist[-self.SIGNAL_WINDOW:])
            elapsed = max(1, ts - start_ts)
            drift = (current_mean - base_mean) / elapsed * 100.0

            if drift > self.DRIFT_LARGE:
                target_pos = 80
            elif drift < -self.DRIFT_LARGE:
                target_pos = -80
            elif drift > self.DRIFT_SMALL:
                target_pos = 60
            elif drift < -self.DRIFT_SMALL:
                target_pos = -60
            # else: flat — market-make the spread below

        orders: List[Order] = []
        rem = target_pos - pos

        # ----------------------------------------------------------------
        # EXECUTION: aggressive crossing when we have a signal
        # ----------------------------------------------------------------
        CROSS_PREMIUM = max(2, spread)   # Don't over-cross a wide spread

        if rem > 0:
            take_budget = min(rem, self.LIMIT - pos)
            for ask in sorted(depth.sell_orders.keys()):
                if take_budget <= 0:
                    break
                if ask <= mid + CROSS_PREMIUM:
                    q = min(take_budget, -depth.sell_orders[ask])
                    orders.append(Order(product, ask, q))
                    take_budget -= q
            # Residual: post at best bid + 1 to attract fills
            if take_budget > 0:
                orders.append(Order(product, bb + 1, take_budget))

        elif rem < 0:
            take_budget = min(-rem, self.LIMIT + pos)
            for bid in sorted(depth.buy_orders.keys(), reverse=True):
                if take_budget <= 0:
                    break
                if bid >= mid - CROSS_PREMIUM:
                    q = min(take_budget, depth.buy_orders[bid])
                    orders.append(Order(product, bid, -q))
                    take_budget -= q
            if take_budget > 0:
                orders.append(Order(product, ba - 1, -take_budget))

        else:
            # No directional signal → market-make the spread for rebate PnL
            if pos < self.LIMIT:
                orders.append(Order(product, bb + 1, min(20, self.LIMIT - pos)))
            if pos > -self.LIMIT:
                orders.append(Order(product, ba - 1, -min(20, self.LIMIT + pos)))

        return orders

    # ------------------------------------------------------------------ #
    #  OSMIUM LOGIC                                                        #
    # ------------------------------------------------------------------ #
    def _osmium_logic(self, state: TradingState) -> List[Order]:
        product = "ASH_COATED_OSMIUM"
        if product not in state.order_depths:
            return []

        depth = state.order_depths[product]
        pos = state.position.get(product, 0)

        if not depth.buy_orders or not depth.sell_orders:
            return []

        bb = max(depth.buy_orders.keys())
        ba = min(depth.sell_orders.keys())
        mid = (bb + ba) / 2.0
        fair = float(self.OSMIUM_ANCHOR)

        # --- Enhanced order-flow imbalance ---
        bv = sum(depth.buy_orders.values())
        av = sum(-v for v in depth.sell_orders.values())

        # Multi-level VWAP comparison for stronger signal
        buy_vwap = _vwap(depth.buy_orders, "buy")
        sell_vwap = _vwap(depth.sell_orders, "sell")

        if bv > av * self.IMBALANCE_RATIO:
            fair += self.IMBALANCE_NUDGE
        elif av > bv * self.IMBALANCE_RATIO:
            fair -= self.IMBALANCE_NUDGE

        # Blend anchor with mid price (80/20) to track any slow drift
        fair = 0.80 * fair + 0.20 * mid

        rb = self.LIMIT - pos   # remaining buy capacity
        rs = self.LIMIT + pos   # remaining sell capacity

        # ----------------------------------------------------------------
        # TIERED QUOTING: stack multiple price levels for more fill rate
        # ----------------------------------------------------------------
        orders: List[Order] = []

        # Tier 1 — aggressive (1 tick inside fair)
        bp1 = min(int(fair - 1), bb + 1)
        ap1 = max(int(fair + 1), ba - 1)

        # Tier 2 — passive backup
        bp2 = bp1 - 1
        ap2 = ap1 + 1

        if rb > 0:
            q1 = min(rb, 50)
            orders.append(Order(product, bp1, q1))
            if rb - q1 > 0:
                orders.append(Order(product, bp2, min(rb - q1, 30)))

        if rs > 0:
            q1 = min(rs, 50)
            orders.append(Order(product, ap1, -q1))
            if rs - q1 > 0:
                orders.append(Order(product, ap2, -min(rs - q1, 30)))

        # ----------------------------------------------------------------
        # TAKE LIQUIDITY when mid is far from fair (mean-reversion)
        # ----------------------------------------------------------------
        revert_threshold = 3.0
        if mid < fair - revert_threshold and rb > 0:
            # Price is cheap vs anchor → buy aggressively
            for ask in sorted(depth.sell_orders.keys()):
                if ask < fair:
                    q = min(rb, -depth.sell_orders[ask])
                    orders.append(Order(product, ask, q))
                    rb -= q
                    if rb <= 0:
                        break

        elif mid > fair + revert_threshold and rs > 0:
            # Price is expensive vs anchor → sell aggressively
            for bid in sorted(depth.buy_orders.keys(), reverse=True):
                if bid > fair:
                    q = min(rs, depth.buy_orders[bid])
                    orders.append(Order(product, bid, -q))
                    rs -= q
                    if rs <= 0:
                        break

        return orders

    # ------------------------------------------------------------------ #
    #  MAIN                                                               #
    # ------------------------------------------------------------------ #
    def run(self, state: TradingState):
        self._load_state(state)

        res = {}

        pep = self._pepper_logic(state)
        if pep:
            res["INTARIAN_PEPPER_ROOT"] = pep

        osm = self._osmium_logic(state)
        if osm:
            res["ASH_COATED_OSMIUM"] = osm

        return res, 0, json.dumps(self.history)