"""Unit tests for v32 math helpers. Run with: python "ROUND 3/scratch/test_v32_math.py" """
import sys
import math
import types

# Stub datamodel so import works without the exchange runtime
dm = types.ModuleType("datamodel")
class _Stub:
    def __init__(self, *a, **kw): pass
for name in ["Order", "OrderDepth", "TradingState", "Listing", "Observation",
             "ProsperityEncoder", "Symbol", "Product", "Position", "UserId",
             "ObservationValue", "Trade"]:
    setattr(dm, name, _Stub)
sys.modules["datamodel"] = dm

import importlib.util
spec = importlib.util.spec_from_file_location(
    "trader_ken_v32",
    "ROUND 3/traders/ken/trader_ken_v32.py"
)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
Trader = mod.Trader
t = Trader()


def test_norm_cdf_known_values():
    cases = [(0.0, 0.5), (1.0, 0.8413), (-1.0, 0.1587),
             (1.96, 0.9750), (-1.96, 0.0250), (3.0, 0.9987)]
    for x, expected in cases:
        got = t._norm_cdf(x)
        assert abs(got - expected) < 0.001, f"norm_cdf({x})={got:.6f}, expected ~{expected}"
    print("PASS: norm_cdf known values")


def test_bs_call_intrinsic_at_zero_tte():
    assert abs(t._bs_call(5250, 5200, 0.0) - 50.0) < 0.01, "ITM at expiry should be 50"
    assert abs(t._bs_call(5250, 5300, 0.0) - 0.0)  < 0.01, "OTM at expiry should be 0"
    print("PASS: bs_call at TTE=0")


def test_bs_call_capsule_day0():
    # sigma=1.76%/day, TTE=8 days: options should be meaningfully above market
    # Market had K=5200 at ~101.5, K=5300 at ~53. BS should be higher.
    got_5200 = t._bs_call(5250.0, 5200, 8.0)
    got_5300 = t._bs_call(5250.0, 5300, 8.0)
    assert got_5200 > 101.5, f"BS K=5200 should exceed market 101.5, got {got_5200:.2f}"
    assert got_5300 > 53.0,  f"BS K=5300 should exceed market 53.0, got {got_5300:.2f}"
    assert got_5200 < 300,   f"BS K=5200 sanity upper bound, got {got_5200:.2f}"
    assert got_5300 < 200,   f"BS K=5300 sanity upper bound, got {got_5300:.2f}"
    print(f"PASS: bs_call capsule day0 — K=5200: {got_5200:.1f}, K=5300: {got_5300:.1f}")


def test_bs_call_monotone_in_tte():
    # Call value increases with time to expiry (all else equal)
    v1 = t._bs_call(5250.0, 5300, 3.0)
    v2 = t._bs_call(5250.0, 5300, 5.0)
    v3 = t._bs_call(5250.0, 5300, 8.0)
    assert v1 < v2 < v3, f"Call not monotone in TTE: {v1:.2f} {v2:.2f} {v3:.2f}"
    print(f"PASS: bs_call monotone in TTE — {v1:.1f} < {v2:.1f} < {v3:.1f}")


if __name__ == "__main__":
    test_norm_cdf_known_values()
    test_bs_call_intrinsic_at_zero_tte()
    test_bs_call_capsule_day0()
    test_bs_call_monotone_in_tte()
    print("\nAll math tests passed.")
