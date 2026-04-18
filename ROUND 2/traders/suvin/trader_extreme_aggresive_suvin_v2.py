import json
from typing import Dict, List, Any
from datamodel import Order, TradingState, Symbol


class Logger:
    def __init__(self) -> None:
        self.logs = ""

    def print(self, *objects: Any, sep: str = " ", end: str = "\n") -> None:
        self.logs += sep.join(map(str, objects)) + end

    def flush(self, state: TradingState, orders: Dict[Symbol, List[Order]], conversions: int, trader_data: str) -> None:
        pass


logger = Logger()


def _median(vals: list) -> float:
    n = len(vals)
    if n == 0:
        return 0.0
    s = sorted(vals)
    mid = n // 2
    return float(s[mid]) if n % 2 == 1 else (s[mid - 1] + s[mid]) / 2.0


def _ema(vals: list, alpha: float = 0.15) -> float:
    if not vals:
        return 0.0
    result = vals[0]
    for v in vals[1:]:
        result = alpha * v + (1 - alpha) * result
    return result


class Trader:
    LIMIT = 80

    # ── PEPPER: regime detection (from example — proven smooth) ──────────
    PEPPER_WARMUP_TICKS     = 1500
    PEPPER_FASTTRACK_TICKS  = 700
    PEPPER_FASTTRACK_SAMPLES= 10
    PEPPER_FASTTRACK_SLOPE  = 0.08   # slightly tighter than example → faster entry
    PEPPER_REEVAL_INTERVAL  = 4000   # re-evaluate sooner for more alpha
    PEPPER_SMOOTH_N         = 15

    PEPPER_SLOPE_STRONG     = 0.05   # tighter than example → more "strong" calls
    PEPPER_SLOPE_MODERATE   = 0.015
    PEPPER_SLOPE_WEAK       = -0.02

    PEPPER_CAP_STRONG       = 80
    PEPPER_CAP_MODERATE     = 65
    PEPPER_CAP_WEAK         = 35
    PEPPER_CAP_NEGATIVE     = 0
    PEPPER_CAP_TENTATIVE    = 15     # smaller than example → less blind risk

    PEPPER_TAKE_PER_TICK         = 12   # slightly more aggressive fills
    PEPPER_TAKE_PER_TICK_STRONG  = 18
    PEPPER_TAKE_PER_TICK_TENT    = 4
    PEPPER_PASSIVE_CAP           = 45

    # ── PEPPER: stop-loss guard (from example) ───────────────────────────
    PEPPER_SLOPE_WINDOW     = 20
    PEPPER_STOP_THRESHOLD   = -10    # tighter stop
    PEPPER_STOP_HYSTERESIS  = 2
    PEPPER_RESUME_THRESHOLD = 4
    PEPPER_FLATTEN_CHUNK    = 15
    PEPPER_FLATTEN_FIRST    = 35

    # ── OSMIUM: proven market-making params (from example) ───────────────
    OSMIUM_ANCHOR           = 10_000
    OSMIUM_TAKE_EDGE        = 1
    OSMIUM_TAKE_EDGE_UNSAFE = 2
    OSMIUM_QUOTE_SIZE       = 30     # bumped from 25 for more volume
    OSMIUM_SECOND_SIZE      = 20     # bumped from 18
    OSMIUM_SKEW_SOFT        = 20
    OSMIUM_SKEW_HARD        = 42
    OSMIUM_FLATTEN          = 52
    OSMIUM_ANCHOR_DRIFT_THRESHOLD = 6
    OSMIUM_ANCHOR_DRIFT_TICKS     = 20
    OSMIUM_TOXIC_VOLUME     = 35     # tighter toxic filter
    OSMIUM_CLAMP            = 4

    # ── OSMIUM: warm-up to prevent early dips ────────────────────────────
    OSMIUM_WARMUP_TICKS     = 20     # pure passive join for first 20 ticks

    def __init__(self):
        self.history: Dict[str, list] = {}

    def _load_state(self, state: TradingState):
        if state.traderData:
            try:
                self.history = json.loads(state.traderData)
            except Exception:
                self.history = {}

    def _pick_pepper_cap(self, slope: float) -> int:
        if slope > self.PEPPER_SLOPE_STRONG:
            return self.PEPPER_CAP_STRONG
        if slope > self.PEPPER_SLOPE_MODERATE:
            return self.PEPPER_CAP_MODERATE
        if slope > self.PEPPER_SLOPE_WEAK:
            return self.PEPPER_CAP_WEAK
        return self.PEPPER_CAP_NEGATIVE

    # ─────────────────────────────────────────────────────────────────────
    #  PEPPER ROOT — regime detection from example + tighter thresholds
    # ─────────────────────────────────────────────────────────────────────
    def _pepper_logic(self, state: TradingState) -> List[Order]:
        product = "INTARIAN_PEPPER_ROOT"
        if product not in state.order_depths:
            return []

        depth = state.order_depths[product]
        pos   = state.position.get(product, 0)

        bb = max(depth.buy_orders.keys())  if depth.buy_orders  else None
        ba = min(depth.sell_orders.keys()) if depth.sell_orders else None
        if bb is None or ba is None:
            return []

        mid = (bb + ba) / 2.0
        ts  = state.timestamp

        # Rolling mid history
        hist = self.history.get("pp", [])
        hist.append(mid)
        if len(hist) > 80:
            hist = hist[-80:]
        self.history["pp"] = hist

        # Lock start baseline
        start_samples = self.history.get("pp_start_samples", [])
        if len(start_samples) < self.PEPPER_SMOOTH_N:
            start_samples.append(mid)
            self.history["pp_start_samples"] = start_samples

        if "pp_start_ts" not in self.history:
            self.history["pp_start_ts"] = ts
        start_ts = self.history["pp_start_ts"]

        cap           = self.history.get("pp_cap", None)
        last_eval_ts  = self.history.get("pp_last_eval_ts", None)

        # ── Fast-track: commit early on obvious strong drift ──────────────
        if (
            cap is None
            and (ts - start_ts) >= self.PEPPER_FASTTRACK_TICKS
            and len(start_samples) >= self.PEPPER_FASTTRACK_SAMPLES
        ):
            sm_start = _median(start_samples)
            sm_now   = _median(hist[-min(len(hist), self.PEPPER_FASTTRACK_SAMPLES):])
            elapsed  = max(1, ts - start_ts)
            slope_early = (sm_now - sm_start) / elapsed * 100.0
            if slope_early >= self.PEPPER_FASTTRACK_SLOPE:
                cap = self.PEPPER_CAP_STRONG
                last_eval_ts = ts
                self.history["pp_cap"]           = cap
                self.history["pp_last_eval_ts"]  = last_eval_ts
                self.history["pp_measured_slope"]= slope_early

        # ── Full warm-up evaluation ───────────────────────────────────────
        warmed_up = (ts - start_ts) >= self.PEPPER_WARMUP_TICKS
        if warmed_up and len(start_samples) >= self.PEPPER_SMOOTH_N:
            smoothed_start = _median(start_samples)
            smoothed_now   = _median(hist[-self.PEPPER_SMOOTH_N:])
            elapsed        = max(1, ts - start_ts)
            slope          = (smoothed_now - smoothed_start) / elapsed * 100.0

            if cap is None:
                cap = self._pick_pepper_cap(slope)
                last_eval_ts = ts
                self.history["pp_cap"]           = cap
                self.history["pp_last_eval_ts"]  = last_eval_ts
                self.history["pp_measured_slope"]= slope
            elif (
                last_eval_ts is not None
                and (ts - last_eval_ts) >= self.PEPPER_REEVAL_INTERVAL
            ):
                fresh = self._pick_pepper_cap(slope)
                if fresh > cap:
                    cap = fresh
                    self.history["pp_cap"]           = cap
                    self.history["pp_measured_slope"]= slope
                last_eval_ts = ts
                self.history["pp_last_eval_ts"] = last_eval_ts

        confirmed     = cap is not None
        effective_cap = cap if confirmed else self.PEPPER_CAP_TENTATIVE

        if not confirmed:
            take_per_tick = self.PEPPER_TAKE_PER_TICK_TENT
        elif cap == self.PEPPER_CAP_STRONG:
            take_per_tick = self.PEPPER_TAKE_PER_TICK_STRONG
        else:
            take_per_tick = self.PEPPER_TAKE_PER_TICK

        # ── Stop-loss guard ───────────────────────────────────────────────
        stop_breach  = int(self.history.get("pp_breach", 0))
        drift_stopped= bool(self.history.get("pp_stopped", False))
        was_stopped  = drift_stopped

        if len(hist) >= self.PEPPER_SLOPE_WINDOW:
            window  = hist[-self.PEPPER_SLOPE_WINDOW:]
            slope_w = window[-1] - window[0]
            if slope_w < self.PEPPER_STOP_THRESHOLD:
                stop_breach += 1
            else:
                stop_breach = 0
            if stop_breach >= self.PEPPER_STOP_HYSTERESIS:
                drift_stopped = True
            elif drift_stopped and slope_w > self.PEPPER_RESUME_THRESHOLD:
                drift_stopped = False

        self.history["pp_breach"]  = stop_breach
        self.history["pp_stopped"] = drift_stopped

        orders: List[Order] = []

        # ── Flatten on stop ───────────────────────────────────────────────
        if drift_stopped or effective_cap == 0:
            if pos > 0:
                just_triggered = drift_stopped and not was_stopped
                chunk = self.PEPPER_FLATTEN_FIRST if just_triggered else self.PEPPER_FLATTEN_CHUNK
                avail = depth.buy_orders.get(bb, 0)
                qty   = min(pos, avail, chunk)
                if qty > 0:
                    orders.append(Order(product, bb, -qty))
            return orders

        rem_cap = effective_cap - pos
        if rem_cap <= 0:
            return orders

        # ── Take liquidity (cross at mid+1 for more fills) ─────────────────
        take_budget = min(rem_cap, take_per_tick)
        taken = 0
        for ask in sorted(depth.sell_orders.keys()):
            if take_budget <= 0:
                break
            avail = -depth.sell_orders[ask]
            if avail <= 0:
                continue
            if ask <= mid + 1:
                qty = min(take_budget, avail)
                orders.append(Order(product, ask, qty))
                take_budget -= qty
                taken += qty

        # ── Passive join above best bid ───────────────────────────────────
        rem_cap -= taken
        if rem_cap > 0:
            passive_qty = min(rem_cap, self.PEPPER_PASSIVE_CAP)
            orders.append(Order(product, bb + 1, passive_qty))

        return orders

    # ─────────────────────────────────────────────────────────────────────
    #  OSMIUM — example's proven MM + warm-up guard to kill early dip
    # ─────────────────────────────────────────────────────────────────────
    def _osmium_logic(self, state: TradingState) -> List[Order]:
        product = "ASH_COATED_OSMIUM"
        if product not in state.order_depths:
            return []

        depth = state.order_depths[product]
        pos   = state.position.get(product, 0)

        bb = max(depth.buy_orders.keys())  if depth.buy_orders  else None
        ba = min(depth.sell_orders.keys()) if depth.sell_orders else None
        if bb is None or ba is None:
            return []

        mid  = (bb + ba) / 2.0
        fair = self.OSMIUM_ANCHOR

        hist = self.history.get("op", [])
        hist.append(mid)
        if len(hist) > 60:
            hist = hist[-60:]
        self.history["op"] = hist
        tick = len(hist)

        # ── Warm-up: observe book, post 1 lot each side at actual prices ──
        # Never quote around the anchor until we've seen enough ticks.
        # This is the fix for the early dip.
        if tick <= 1:
            return []

        if tick < self.OSMIUM_WARMUP_TICKS:
            orders = []
            if pos > 0:
                orders.append(Order(product, ba, -1))
            elif pos < 0:
                orders.append(Order(product, bb, 1))
            else:
                orders.append(Order(product, bb, 1))
                orders.append(Order(product, ba, -1))
            return orders

        # ── Anchor drift detection ────────────────────────────────────────
        anchor_off = False
        if len(hist) >= self.OSMIUM_ANCHOR_DRIFT_TICKS:
            recent = hist[-self.OSMIUM_ANCHOR_DRIFT_TICKS:]
            avg    = sum(recent) / len(recent)
            if abs(avg - fair) > self.OSMIUM_ANCHOR_DRIFT_THRESHOLD:
                anchor_off = True

        size_scale = 0.5 if anchor_off else 1.0
        front_qty  = max(6, int(self.OSMIUM_QUOTE_SIZE * size_scale))
        second_qty = max(4, int(self.OSMIUM_SECOND_SIZE * size_scale))
        take_edge  = self.OSMIUM_TAKE_EDGE_UNSAFE if anchor_off else self.OSMIUM_TAKE_EDGE

        # ── Toxic flow filter ─────────────────────────────────────────────
        buy_vol = sell_vol = 0
        if product in state.market_trades:
            for t in state.market_trades[product]:
                if t.price >= mid:
                    buy_vol += abs(t.quantity)
                else:
                    sell_vol += abs(t.quantity)

        diff             = buy_vol - sell_vol
        toxic_skip_buys  = diff  >=  self.OSMIUM_TOXIC_VOLUME
        toxic_skip_sells = -diff >= self.OSMIUM_TOXIC_VOLUME

        orders   : List[Order] = []
        rem_buy  = self.LIMIT - pos
        rem_sell = self.LIMIT + pos

        # ── Take liquidity vs anchor ──────────────────────────────────────
        if not toxic_skip_buys:
            for ask in sorted(depth.sell_orders.keys()):
                if ask <= fair - take_edge and rem_buy > 0:
                    avail = -depth.sell_orders[ask]
                    qty   = min(rem_buy, avail)
                    if qty > 0:
                        orders.append(Order(product, ask, qty))
                        rem_buy -= qty
                        pos     += qty

        if not toxic_skip_sells:
            for bid in sorted(depth.buy_orders.keys(), reverse=True):
                if bid >= fair + take_edge and rem_sell > 0:
                    avail = depth.buy_orders[bid]
                    qty   = min(rem_sell, avail)
                    if qty > 0:
                        orders.append(Order(product, bid, -qty))
                        rem_sell -= qty
                        pos      -= qty

        # ── Flatten if over limit ─────────────────────────────────────────
        if pos > self.OSMIUM_FLATTEN and rem_sell > 0:
            qty = min(pos - self.OSMIUM_FLATTEN + 5, rem_sell)
            if qty > 0:
                orders.append(Order(product, fair, -qty))
                rem_sell -= qty
        elif pos < -self.OSMIUM_FLATTEN and rem_buy > 0:
            qty = min(-pos - self.OSMIUM_FLATTEN + 5, rem_buy)
            if qty > 0:
                orders.append(Order(product, fair, qty))
                rem_buy -= qty

        # ── Position skew ─────────────────────────────────────────────────
        abs_pos  = abs(pos)
        skew     = 2 if abs_pos > self.OSMIUM_SKEW_HARD else (1 if abs_pos > self.OSMIUM_SKEW_SOFT else 0)
        skew_dir = 1 if pos > 0 else -1

        bid_price = min(bb + 1, fair - 1) - skew * skew_dir
        ask_price = max(ba - 1, fair + 1) - skew * skew_dir

        bid_price = max(int(bid_price), fair - self.OSMIUM_CLAMP)
        ask_price = min(int(ask_price), fair + self.OSMIUM_CLAMP)

        if bid_price >= ask_price:
            bid_price = fair - 1
            ask_price = fair + 1

        # ── Two-tier passive quoting ──────────────────────────────────────
        if rem_buy > 0:
            front = min(rem_buy, front_qty)
            orders.append(Order(product, int(bid_price), front))
            rem_buy -= front
            if rem_buy > 0:
                orders.append(Order(product, int(bid_price - 1), min(rem_buy, second_qty)))

        if rem_sell > 0:
            front = min(rem_sell, front_qty)
            orders.append(Order(product, int(ask_price), -front))
            rem_sell -= front
            if rem_sell > 0:
                orders.append(Order(product, int(ask_price + 1), -min(rem_sell, second_qty)))

        return orders

    # ─────────────────────────────────────────────────────────────────────
    #  MAIN
    # ─────────────────────────────────────────────────────────────────────
    def run(self, state: TradingState):
        self._load_state(state)
        result: Dict[str, List[Order]] = {}

        pep = self._pepper_logic(state)
        if pep:
            result["INTARIAN_PEPPER_ROOT"] = pep

        osm = self._osmium_logic(state)
        if osm:
            result["ASH_COATED_OSMIUM"] = osm

        trader_data = json.dumps(self.history)
        logger.flush(state, result, 0, trader_data)
        return result, 0, trader_data