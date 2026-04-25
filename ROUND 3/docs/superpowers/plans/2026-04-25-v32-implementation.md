# trader_ken_v32 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build `trader_ken_v32.py` — a clean three-module trader with imbalance-aware HYDROGEL market-making, passive VFE quoting, and a minimal BS-fair-value-taker for VEV_5200/5300.

**Architecture:** Three fully independent modules (`_hp_logic`, `_vfe_logic`, `_vev_logic`) sharing only a thin JSON state blob via `traderData`. No global risk governor. HYDROGEL fair value is a pure EWMA (no static anchor); imbalance signal drives quote skew. VEV entries are triggered when `market_ask < BS_fair − 5`.

**Tech Stack:** Python 3.11, `datamodel` (exchange-provided), `prosperity4bt` for backtesting. No external math libraries — `norm_cdf` implemented inline.

---

## File Map

| Action | Path | Purpose |
|---|---|---|
| Create | `ROUND 3/traders/ken/trader_ken_v32.py` | Main trader — all logic |
| Create | `ROUND 3/scratch/test_v32_math.py` | Unit tests for `norm_cdf` and `bs_call` |
| Run | `tools/run_prosperity4bt.py` | Backtest against data capsule |
| Run | `tools/compare_round3_traders.py` | Compare v32 vs v30 |

---

## Task 1: File skeleton + constants

**Files:**
- Create: `ROUND 3/traders/ken/trader_ken_v32.py`

- [ ] **Step 1: Create the file with all constants and the empty Trader class**

```python
"""trader_ken_v32.py

Three-module trader for Round 3:
  - HYDROGEL_PACK: EWMA fair + L1 imbalance quote skew
  - VELVETFRUIT_EXTRACT: passive symmetric maker
  - VEV_5200 / VEV_5300: BS-fair taker when ask < fair - MIN_EDGE

Single-file, no local imports beyond datamodel.
"""
from __future__ import annotations

import json
import math
from typing import Dict, List, Optional, Tuple

from datamodel import Order, OrderDepth, TradingState

# ── Products ──────────────────────────────────────────────────────────────────
HP  = "HYDROGEL_PACK"
VFE = "VELVETFRUIT_EXTRACT"
VEV_ACTIVE_STRIKES = [5200, 5300]

# ── HYDROGEL parameters ───────────────────────────────────────────────────────
HP_LIMIT         = 80
HP_EWMA_ALPHA    = 0.003   # half-life ≈ 300 ticks, matches OU from data analysis
HP_EDGE          = 8       # half of observed 16-wide spread
HP_SKEW          = 4       # matches ~4 XIRECs predicted by imbalance signal
HP_INV_TRIGGER   = 40      # |pos| threshold to start inventory lean
HP_INV_FACTOR    = 0.15    # quote shift per unit of pos above trigger
HP_TAKER_MAX     = 5       # max lots to take when reducing wrong-side exposure

# ── VFE parameters ────────────────────────────────────────────────────────────
VFE_LIMIT        = 60
VFE_EWMA_ALPHA   = 0.05
VFE_EDGE         = 3
VFE_INV_TRIGGER  = 30
VFE_INV_FACTOR   = 0.10

# ── VEV parameters ────────────────────────────────────────────────────────────
VEV_LIMIT        = 20      # per strike
VEV_SIGMA        = 0.0176  # bias-corrected realized vol per day
VEV_MIN_EDGE     = 5       # minimum XIRECs edge to enter


class Trader:

    def __init__(self) -> None:
        self._state: Dict = {}

    # ── State persistence ──────────────────────────────────────────────────────

    def _load(self, state: TradingState) -> None:
        if state.traderData:
            try:
                self._state = json.loads(state.traderData)
            except Exception:
                self._state = {}
        self._state.setdefault("hp_ewma", None)
        self._state.setdefault("vfe_ewma", None)

    def _save(self) -> str:
        return json.dumps(self._state)

    # ── Helpers ────────────────────────────────────────────────────────────────

    @staticmethod
    def _top(depth: OrderDepth) -> Tuple[Optional[int], Optional[int]]:
        bb = max(depth.buy_orders) if depth.buy_orders else None
        ba = min(depth.sell_orders) if depth.sell_orders else None
        return bb, ba

    @staticmethod
    def _top_vol(depth: OrderDepth) -> Tuple[int, int]:
        """Return (bid_vol_1, ask_vol_1) at the best level."""
        bv = depth.buy_orders[max(depth.buy_orders)] if depth.buy_orders else 0
        av = abs(depth.sell_orders[min(depth.sell_orders)]) if depth.sell_orders else 0
        return bv, av

    # ── BS helpers (no scipy — inline approximation) ───────────────────────────

    @staticmethod
    def _norm_cdf(x: float) -> float:
        """Abramowitz & Stegun 26.2.17 rational approximation, error < 1.5e-7."""
        sign = 1.0 if x >= 0 else -1.0
        x = abs(x)
        t = 1.0 / (1.0 + 0.2316419 * x)
        p = t * (0.319381530
              + t * (-0.356563782
              + t * (1.781477937
              + t * (-1.821255978
              + t * 1.330274429))))
        return sign * (0.5 - (1.0 / math.sqrt(2 * math.pi)) * math.exp(-0.5 * x * x) * p) + 0.5 * (1 - sign)

    def _bs_call(self, S: float, K: int, tte: float) -> float:
        """Black-Scholes call price, r=0."""
        if tte <= 0:
            return max(S - K, 0.0)
        sigma_sqrt_t = VEV_SIGMA * math.sqrt(tte)
        if sigma_sqrt_t == 0:
            return max(S - K, 0.0)
        d1 = (math.log(S / K) + 0.5 * VEV_SIGMA ** 2 * tte) / sigma_sqrt_t
        d2 = d1 - sigma_sqrt_t
        return S * self._norm_cdf(d1) - K * self._norm_cdf(d2)

    @staticmethod
    def _tte(state: TradingState) -> float:
        """Time-to-expiry in days. TTE=8 at ts=0 day=0; decays continuously."""
        day = int(getattr(state, "timestamp", 0) // 1_000_000)
        # state.timestamp is the tick timestamp within the day (0–999900)
        # day is encoded separately; use state.timestamp for within-day position
        # The exchange encodes day in traderData or we infer from timestamp scale.
        # In prosperity4bt, timestamp is global: day*1e6 + tick_ts
        ts = int(state.timestamp)
        day_num = ts // 1_000_000
        tick_ts = ts % 1_000_000
        return 8.0 - day_num - tick_ts / 1_000_000.0

    # ── Module 1: HYDROGEL ─────────────────────────────────────────────────────

    def _hp_logic(self, state: TradingState) -> List[Order]:
        pass  # implemented in Task 2

    # ── Module 2: VFE ─────────────────────────────────────────────────────────

    def _vfe_logic(self, state: TradingState) -> Tuple[List[Order], Optional[float]]:
        pass  # implemented in Task 3

    # ── Module 3: VEV ─────────────────────────────────────────────────────────

    def _vev_logic(self, state: TradingState, vfe_mid: float) -> List[Order]:
        pass  # implemented in Task 4

    # ── Entry point ────────────────────────────────────────────────────────────

    def run(self, state: TradingState):
        self._load(state)
        result: Dict[str, List[Order]] = {}

        hp_orders = self._hp_logic(state)
        for o in (hp_orders or []):
            result.setdefault(o.symbol, []).append(o)

        vfe_orders, vfe_mid = self._vfe_logic(state)
        for o in (vfe_orders or []):
            result.setdefault(o.symbol, []).append(o)

        if vfe_mid is not None:
            vev_orders = self._vev_logic(state, vfe_mid)
            for o in (vev_orders or []):
                result.setdefault(o.symbol, []).append(o)

        return result, 0, self._save()
```

- [ ] **Step 2: Verify file is syntactically valid**

```bash
cd "C:/Users/kentrn/Desktop/Prosperity 4/imc-prosperity-4"
python -c "import ast; ast.parse(open('ROUND 3/traders/ken/trader_ken_v32.py').read()); print('OK')"
```

Expected: `OK`

- [ ] **Step 3: Commit skeleton**

```bash
git add "ROUND 3/traders/ken/trader_ken_v32.py"
git commit -m "feat: add trader_ken_v32 skeleton with constants and helpers"
```

---

## Task 2: Math unit tests + verify `norm_cdf` / `bs_call`

**Files:**
- Create: `ROUND 3/scratch/test_v32_math.py`

- [ ] **Step 1: Create the test file**

```python
"""Unit tests for v32 math helpers — run with: python ROUND\ 3/scratch/test_v32_math.py"""
import sys
import math
sys.path.insert(0, ".")

# Import trader
import importlib.util
spec = importlib.util.spec_from_file_location(
    "trader_ken_v32",
    "ROUND 3/traders/ken/trader_ken_v32.py"
)
mod = importlib.util.module_from_spec(spec)

# Stub datamodel so import works without the exchange runtime
import types
dm = types.ModuleType("datamodel")
class _Stub:
    def __init__(self, *a, **kw): pass
for name in ["Order","OrderDepth","TradingState","Listing","Observation",
             "ProsperityEncoder","Symbol","Product","Position","UserId",
             "ObservationValue","Trade"]:
    setattr(dm, name, _Stub)
sys.modules["datamodel"] = dm

spec.loader.exec_module(mod)
Trader = mod.Trader
t = Trader()

# ── norm_cdf tests ────────────────────────────────────────────────────────────
def test_norm_cdf_known_values():
    cases = [(0.0, 0.5), (1.0, 0.8413), (-1.0, 0.1587),
             (1.96, 0.9750), (-1.96, 0.0250), (3.0, 0.9987)]
    for x, expected in cases:
        got = t._norm_cdf(x)
        assert abs(got - expected) < 0.001, f"norm_cdf({x})={got}, expected {expected}"
    print("PASS: norm_cdf known values")

# ── bs_call tests ─────────────────────────────────────────────────────────────
def test_bs_call_intrinsic_at_zero_tte():
    # TTE=0: call = max(S-K, 0)
    assert abs(t._bs_call(5250, 5200, 0.0) - 50.0) < 0.01, "ITM at expiry"
    assert abs(t._bs_call(5250, 5300, 0.0) - 0.0)  < 0.01, "OTM at expiry"
    print("PASS: bs_call at TTE=0")

def test_bs_call_atm_approximation():
    # ATM approximation: C ≈ S * sigma * sqrt(T) * 0.3989
    S, K, T = 5250.0, 5200, 5.0
    approx = S * 0.0176 * math.sqrt(T) * 0.3989
    got = t._bs_call(S, K, T)
    # Should be within 30 XIRECs of the approximation for near-ATM
    assert abs(got - (50 + approx)) < 40, f"bs_call ATM: got={got:.2f}"
    print(f"PASS: bs_call near-ATM: S={S} K={K} T={T} -> {got:.2f}")

def test_bs_call_capsule_day0():
    # From data capsule analysis: day0 S=5250, K=5200, TTE=8, market=101.5
    # BS at sigma=1.76% should give ~130-150 (market is cheap)
    got = t._bs_call(5250.0, 5200, 8.0)
    assert 100 < got < 200, f"bs_call capsule K=5200: {got:.2f}"
    # BS at sigma=1.76% K=5300 TTE=8: should be > market mid of 53
    got2 = t._bs_call(5250.0, 5300, 8.0)
    assert 50 < got2 < 150, f"bs_call capsule K=5300: {got2:.2f}"
    print(f"PASS: bs_call capsule values K=5200->{got:.1f}, K=5300->{got2:.1f}")

if __name__ == "__main__":
    test_norm_cdf_known_values()
    test_bs_call_intrinsic_at_zero_tte()
    test_bs_call_atm_approximation()
    test_bs_call_capsule_day0()
    print("\nAll math tests passed.")
```

- [ ] **Step 2: Run the tests**

```bash
cd "C:/Users/kentrn/Desktop/Prosperity 4/imc-prosperity-4"
python "ROUND 3/scratch/test_v32_math.py"
```

Expected:
```
PASS: norm_cdf known values
PASS: bs_call at TTE=0
PASS: bs_call near-ATM: S=5250 K=5200 T=5.0 -> <number>
PASS: bs_call capsule values K=5200-><number>, K=5300-><number>

All math tests passed.
```

- [ ] **Step 3: Commit tests**

```bash
git add "ROUND 3/scratch/test_v32_math.py"
git commit -m "test: add v32 math unit tests for norm_cdf and bs_call"
```

---

## Task 3: Implement `_hp_logic`

**Files:**
- Modify: `ROUND 3/traders/ken/trader_ken_v32.py` — replace `_hp_logic` stub

- [ ] **Step 1: Replace the `_hp_logic` stub with full implementation**

Replace the entire `_hp_logic` method (the `pass` stub) with:

```python
def _hp_logic(self, state: TradingState) -> List[Order]:
    depth = state.order_depths.get(HP)
    if depth is None:
        return []
    bb, ba = self._top(depth)
    if bb is None or ba is None:
        return []

    mid = (bb + ba) / 2.0

    # EWMA fair — no static anchor
    prev = self._state["hp_ewma"]
    ewma = mid if prev is None else (1 - HP_EWMA_ALPHA) * prev + HP_EWMA_ALPHA * mid
    self._state["hp_ewma"] = ewma
    fair = ewma

    # L1 imbalance signal
    bv, av = self._top_vol(depth)
    total_vol = bv + av
    imb = (bv - av) / total_vol if total_vol > 0 else 0.0

    # Inventory skew — lean against large positions
    pos = state.position.get(HP, 0)
    inv_lean = 0.0
    if abs(pos) > HP_INV_TRIGGER:
        inv_lean = pos * HP_INV_FACTOR  # positive pos → push quotes up → harder to buy more

    # Quote prices: shift both quotes in direction of imbalance
    skew = HP_SKEW * (1 if imb > 0 else -1 if imb < 0 else 0)
    q_bid = round(fair - HP_EDGE + skew - inv_lean)
    q_ask = round(fair + HP_EDGE + skew - inv_lean)

    # Clamp: never cross the existing inside market
    if q_bid >= ba:
        q_bid = ba - 1
    if q_ask <= bb:
        q_ask = bb + 1
    if q_bid >= q_ask:
        q_bid = q_ask - 1

    orders: List[Order] = []

    # Defensive taker: reduce wrong-side exposure when imbalance is present
    if imb != 0.0:
        if imb < 0 and pos > 0:  # price moving down, we are long → hit bid to reduce
            reduce = min(HP_TAKER_MAX, pos, depth.buy_orders.get(bb, 0))
            if reduce > 0:
                orders.append(Order(HP, bb, -reduce))
                pos -= reduce
        elif imb > 0 and pos < 0:  # price moving up, we are short → lift ask to reduce
            reduce = min(HP_TAKER_MAX, -pos, abs(depth.sell_orders.get(ba, 0)))
            if reduce > 0:
                orders.append(Order(HP, ba, reduce))
                pos += reduce

    # Passive maker quotes
    room_long  = HP_LIMIT - pos
    room_short = HP_LIMIT + pos
    if room_long > 0:
        orders.append(Order(HP, q_bid, room_long))
    if room_short > 0:
        orders.append(Order(HP, q_ask, -room_short))

    return orders
```

- [ ] **Step 2: Verify syntax**

```bash
cd "C:/Users/kentrn/Desktop/Prosperity 4/imc-prosperity-4"
python -c "import ast; ast.parse(open('ROUND 3/traders/ken/trader_ken_v32.py').read()); print('OK')"
```

Expected: `OK`

- [ ] **Step 3: Run backtest day 0 only — check HP is quoting**

```bash
python tools/run_prosperity4bt.py \
  --trader "ROUND 3/traders/ken/trader_ken_v32.py" \
  --dataset "ROUND 3/data_capsule" \
  --day 0 --no-progress 2>&1 | tail -20
```

Expected: no errors, HP shows non-zero trades and PnL > 0.

- [ ] **Step 4: Commit**

```bash
git add "ROUND 3/traders/ken/trader_ken_v32.py"
git commit -m "feat: implement v32 HYDROGEL module with imbalance skew"
```

---

## Task 4: Implement `_vfe_logic`

**Files:**
- Modify: `ROUND 3/traders/ken/trader_ken_v32.py` — replace `_vfe_logic` stub

- [ ] **Step 1: Replace the `_vfe_logic` stub**

Replace `_vfe_logic` method with:

```python
def _vfe_logic(self, state: TradingState) -> Tuple[List[Order], Optional[float]]:
    depth = state.order_depths.get(VFE)
    if depth is None:
        return [], None
    bb, ba = self._top(depth)
    if bb is None or ba is None:
        return [], None

    mid = (bb + ba) / 2.0

    prev = self._state["vfe_ewma"]
    ewma = mid if prev is None else (1 - VFE_EWMA_ALPHA) * prev + VFE_EWMA_ALPHA * mid
    self._state["vfe_ewma"] = ewma
    fair = ewma

    pos = state.position.get(VFE, 0)
    inv_lean = 0.0
    if abs(pos) > VFE_INV_TRIGGER:
        inv_lean = pos * VFE_INV_FACTOR

    q_bid = round(fair - VFE_EDGE - inv_lean)
    q_ask = round(fair + VFE_EDGE - inv_lean)

    if q_bid >= ba:
        q_bid = ba - 1
    if q_ask <= bb:
        q_ask = bb + 1
    if q_bid >= q_ask:
        q_bid = q_ask - 1

    orders: List[Order] = []
    room_long  = VFE_LIMIT - pos
    room_short = VFE_LIMIT + pos
    if room_long > 0:
        orders.append(Order(VFE, q_bid, room_long))
    if room_short > 0:
        orders.append(Order(VFE, q_ask, -room_short))

    return orders, mid
```

- [ ] **Step 2: Verify syntax**

```bash
cd "C:/Users/kentrn/Desktop/Prosperity 4/imc-prosperity-4"
python -c "import ast; ast.parse(open('ROUND 3/traders/ken/trader_ken_v32.py').read()); print('OK')"
```

Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add "ROUND 3/traders/ken/trader_ken_v32.py"
git commit -m "feat: implement v32 VFE passive maker module"
```

---

## Task 5: Implement `_vev_logic`

**Files:**
- Modify: `ROUND 3/traders/ken/trader_ken_v32.py` — replace `_vev_logic` stub

- [ ] **Step 1: Replace the `_vev_logic` stub**

Replace `_vev_logic` method with:

```python
def _vev_logic(self, state: TradingState, vfe_mid: float) -> List[Order]:
    tte = self._tte(state)
    if tte <= 0:
        return []

    orders: List[Order] = []
    for strike in VEV_ACTIVE_STRIKES:
        sym = f"VEV_{strike}"
        depth = state.order_depths.get(sym)
        if depth is None:
            continue
        bb, ba = self._top(depth)
        if bb is None or ba is None:
            continue

        fair = self._bs_call(vfe_mid, strike, tte)
        pos  = state.position.get(sym, 0)

        # Buy when market ask is meaningfully below BS fair (cheap option)
        if ba < fair - VEV_MIN_EDGE:
            room = VEV_LIMIT - pos
            avail = abs(depth.sell_orders.get(ba, 0))
            qty = min(room, avail)
            if qty > 0:
                orders.append(Order(sym, ba, qty))

        # Sell when market bid is meaningfully above BS fair (expensive option)
        if bb > fair + VEV_MIN_EDGE:
            room = VEV_LIMIT + pos
            avail = depth.buy_orders.get(bb, 0)
            qty = min(room, avail)
            if qty > 0:
                orders.append(Order(sym, bb, -qty))

    return orders
```

- [ ] **Step 2: Verify syntax**

```bash
cd "C:/Users/kentrn/Desktop/Prosperity 4/imc-prosperity-4"
python -c "import ast; ast.parse(open('ROUND 3/traders/ken/trader_ken_v32.py').read()); print('OK')"
```

Expected: `OK`

- [ ] **Step 3: Run math tests to confirm bs_call still works**

```bash
python "ROUND 3/scratch/test_v32_math.py"
```

Expected: `All math tests passed.`

- [ ] **Step 4: Commit**

```bash
git add "ROUND 3/traders/ken/trader_ken_v32.py"
git commit -m "feat: implement v32 VEV BS-fair taker for VEV_5200 and VEV_5300"
```

---

## Task 6: Full backtest vs v30 — 3 days

**Files:** none to modify — run existing tools

- [ ] **Step 1: Run v32 backtest all 3 days**

```bash
cd "C:/Users/kentrn/Desktop/Prosperity 4/imc-prosperity-4"
python tools/run_prosperity4bt.py \
  --trader "ROUND 3/traders/ken/trader_ken_v32.py" \
  --dataset "ROUND 3/data_capsule" \
  --no-progress 2>&1 | tail -30
```

Note the total PnL. Expectation: > v30 (v30 baseline TBD from next step).

- [ ] **Step 2: Run v30 backtest for baseline**

```bash
python tools/run_prosperity4bt.py \
  --trader "ROUND 3/traders/ken/trader_ken_v30_standalone.py" \
  --dataset "ROUND 3/data_capsule" \
  --no-progress 2>&1 | tail -30
```

- [ ] **Step 3: Compare using the compare tool**

```bash
python tools/compare_round3_traders.py 2>&1 | tail -20
```

- [ ] **Step 4: Check per-product PnL breakdown**

VEV orders should show > 0 fills. HYDROGEL should show higher PnL than v30.
If HYDROGEL PnL is lower than v30, check whether `HP_EWMA_ALPHA=0.003` makes fair value diverge — if so, increase to `0.005`.

- [ ] **Step 5: Tune if needed**

If VEV PnL is 0 (no fills), reduce `VEV_MIN_EDGE` from 5 to 3.
If HP PnL is dominated by a large open position rather than spread capture, reduce `HP_LIMIT` to 60 or add a position-cap taker at `HP_LIMIT * 0.8`.

Document the final parameter values in a comment block at the top of `trader_ken_v32.py`:

```python
# Backtest results (data capsule, 3 days):
# v32: HP=XX,XXX  VFE=XX,XXX  VEV=X,XXX  Total=XX,XXX
# v30: Total=XX,XXX  (baseline)
```

- [ ] **Step 6: Commit final version**

```bash
git add "ROUND 3/traders/ken/trader_ken_v32.py"
git commit -m "feat: finalize trader_ken_v32 with backtest results"
```

---

## Self-Review Checklist

- [x] Spec coverage: HP imbalance skew ✓, HP EWMA no anchor ✓, VFE passive maker ✓, VEV BS-fair taker ✓, VEV_5200+5300 only ✓, no global risk governor ✓, no delta hedging ✓
- [x] No placeholders: all steps have actual code
- [x] Type consistency: `_hp_logic → List[Order]`, `_vfe_logic → Tuple[List[Order], Optional[float]]`, `_vev_logic → List[Order]` — consistent across skeleton (Task 1) and implementations (Tasks 3-5)
- [x] `_tte()` uses combined day+timestamp formula as required by spec
- [x] `_norm_cdf` approximation cited (A&S 26.2.17), error bound noted
