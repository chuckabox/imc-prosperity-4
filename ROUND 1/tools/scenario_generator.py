"""
Regime-Based Scenario Generator for IMC Prosperity 4
=====================================================
Generates synthetic IMC-format market data for diverse regimes:
  - bull_trend     : Steady climb (like the current 3-day data)
  - crash          : Sharp drop, slow recovery
  - bear_trend     : Steady decline
  - sideways       : Range-bound oscillation
  - spike_crash    : Fast spike up, then violent crash
  - high_vol       : Wild swings both directions
  - v_recovery     : Crash then V-shaped bounce
  - sawtooth       : Repeated spike-crash cycles (real pepper pattern)

Usage:
    python scenario_generator.py                    # Generate all regimes
    python scenario_generator.py --regime crash     # Generate specific regime
    python scenario_generator.py --list             # List available regimes
"""

import os
import sys
import json
import argparse
import numpy as np
import pandas as pd
from pathlib import Path
from typing import Dict, List, Tuple

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
DATA_DIR = PROJECT_ROOT / "data_capsule"
SCENARIO_DIR = DATA_DIR / "scenarios"
SCENARIO_DIR.mkdir(parents=True, exist_ok=True)

TICKS = 10000
TICK_INTERVAL = 100


def _build_orderbook_row(
    day_label: str, ts: int, product: str, mid: float,
    spread_mean: float = 14.0, vol_mean: float = 15.0,
) -> dict:
    """Construct one order-book snapshot row in IMC CSV format."""
    noise = np.random.normal(0, 0.3)
    half = max(1, int(np.random.exponential(spread_mean / 2)))

    bid1 = int(mid - half + noise)
    ask1 = int(mid + half + noise)
    if bid1 >= ask1:
        ask1 = bid1 + 1

    bv1 = int(np.clip(np.random.normal(vol_mean, 5), 5, 30))
    av1 = int(np.clip(np.random.normal(vol_mean, 5), 5, 30))
    bid2 = bid1 - int(np.random.uniform(2, 5))
    ask2 = ask1 + int(np.random.uniform(2, 5))
    bv2 = int(np.clip(np.random.normal(20, 5), 8, 35))
    av2 = int(np.clip(np.random.normal(20, 5), 8, 35))

    return {
        "day": day_label,
        "timestamp": ts,
        "product": product,
        "bid_price_1": bid1, "bid_volume_1": bv1,
        "bid_price_2": bid2, "bid_volume_2": bv2,
        "bid_price_3": "", "bid_volume_3": "",
        "ask_price_1": ask1, "ask_volume_1": av1,
        "ask_price_2": ask2, "ask_volume_2": av2,
        "ask_price_3": "", "ask_volume_3": "",
        "mid_price": round((bid1 + ask1) / 2, 1),
        "profit_and_loss": 0.0,
    }


# ---------------------------------------------------------------------------
# Pepper Root regime generators
# ---------------------------------------------------------------------------

def _pepper_bull(ticks: int = TICKS) -> np.ndarray:
    """Steady uptrend like the provided IMC data (+1000 per day)."""
    base = np.linspace(10000, 13000, ticks)
    noise = np.cumsum(np.random.normal(0, 1.5, ticks))
    return base + noise


def _pepper_crash(ticks: int = TICKS) -> np.ndarray:
    """Climb to peak then sharp crash, slow partial recovery."""
    peak_tick = int(ticks * 0.35)
    base = np.zeros(ticks)
    base[:peak_tick] = np.linspace(11000, 12800, peak_tick)

    crash_end = int(ticks * 0.45)
    base[peak_tick:crash_end] = np.linspace(12800, 10500, crash_end - peak_tick)

    base[crash_end:] = np.linspace(10500, 11200, ticks - crash_end)

    noise = np.cumsum(np.random.normal(0, 2.0, ticks))
    return base + noise


def _pepper_bear(ticks: int = TICKS) -> np.ndarray:
    """Steady downtrend."""
    base = np.linspace(13000, 10000, ticks)
    noise = np.cumsum(np.random.normal(0, 1.5, ticks))
    return base + noise


def _pepper_sideways(ticks: int = TICKS) -> np.ndarray:
    """Range-bound oscillation around 11500."""
    t = np.linspace(0, 8 * np.pi, ticks)
    base = 11500 + 600 * np.sin(t) + 300 * np.sin(2.7 * t)
    noise = np.cumsum(np.random.normal(0, 1.0, ticks))
    return base + noise


def _pepper_spike_crash(ticks: int = TICKS) -> np.ndarray:
    """Fast spike up then violent crash below starting price."""
    spike_peak = int(ticks * 0.25)
    crash_bottom = int(ticks * 0.40)

    base = np.zeros(ticks)
    base[:spike_peak] = np.linspace(11000, 13500, spike_peak)
    base[spike_peak:crash_bottom] = np.linspace(13500, 9800, crash_bottom - spike_peak)
    base[crash_bottom:] = np.linspace(9800, 10800, ticks - crash_bottom)

    noise = np.cumsum(np.random.normal(0, 2.5, ticks))
    return base + noise


def _pepper_high_vol(ticks: int = TICKS) -> np.ndarray:
    """Wild swings -- no clear direction, just chaos."""
    t = np.linspace(0, 20 * np.pi, ticks)
    base = 11500 + 800 * np.sin(t) + 500 * np.sin(3.1 * t) + 300 * np.cos(7.3 * t)
    noise = np.cumsum(np.random.normal(0, 3.0, ticks))
    return base + noise


def _pepper_v_recovery(ticks: int = TICKS) -> np.ndarray:
    """Sharp V: crash down, then equally sharp recovery."""
    bottom = int(ticks * 0.5)
    base = np.zeros(ticks)
    base[:bottom] = np.linspace(12500, 9500, bottom)
    base[bottom:] = np.linspace(9500, 12800, ticks - bottom)
    noise = np.cumsum(np.random.normal(0, 2.0, ticks))
    return base + noise


def _pepper_sawtooth(ticks: int = TICKS) -> np.ndarray:
    """
    Repeated spike-crash cycles (like real pepper commodities).
    Slow climb, sharp drop, repeat 3-4 times.
    """
    cycles = 4
    cycle_len = ticks // cycles
    base = np.zeros(ticks)

    level = 10500
    for c in range(cycles):
        start = c * cycle_len
        end = min(start + cycle_len, ticks)
        rise_end = start + int(cycle_len * 0.7)

        peak = level + np.random.uniform(800, 1500)
        drop = level + np.random.uniform(-200, 300)

        base[start:rise_end] = np.linspace(level, peak, rise_end - start)
        base[rise_end:end] = np.linspace(peak, drop, end - rise_end)
        level = drop

    noise = np.cumsum(np.random.normal(0, 1.5, ticks))
    return base[:ticks] + noise


# ---------------------------------------------------------------------------
# Osmium regime generators
# ---------------------------------------------------------------------------

def _osmium_normal(ticks: int = TICKS) -> np.ndarray:
    """Standard mean-reverting around 10000."""
    ou_path = np.zeros(ticks)
    ou_path[0] = 10000
    theta, mu, sigma = 0.05, 10000, 3.0
    for i in range(1, ticks):
        ou_path[i] = ou_path[i-1] + theta * (mu - ou_path[i-1]) + sigma * np.random.normal()
    return ou_path


def _osmium_volatile(ticks: int = TICKS) -> np.ndarray:
    """Wider swings during a crisis."""
    ou_path = np.zeros(ticks)
    ou_path[0] = 10000
    theta, mu = 0.03, 10000
    for i in range(1, ticks):
        sigma = 8.0 if 2000 < i < 5000 else 3.0
        ou_path[i] = ou_path[i-1] + theta * (mu - ou_path[i-1]) + sigma * np.random.normal()
    return ou_path


def _osmium_drift(ticks: int = TICKS) -> np.ndarray:
    """Slow drift away from 10000 then back."""
    base = np.concatenate([
        np.linspace(10000, 10080, ticks // 3),
        np.linspace(10080, 9920, ticks // 3),
        np.linspace(9920, 10000, ticks - 2 * (ticks // 3)),
    ])
    noise = np.cumsum(np.random.normal(0, 2.0, ticks))
    return base + noise


# ---------------------------------------------------------------------------
# Scenario registry
# ---------------------------------------------------------------------------

PEPPER_REGIMES = {
    "bull_trend":   _pepper_bull,
    "crash":        _pepper_crash,
    "bear_trend":   _pepper_bear,
    "sideways":     _pepper_sideways,
    "spike_crash":  _pepper_spike_crash,
    "high_vol":     _pepper_high_vol,
    "v_recovery":   _pepper_v_recovery,
    "sawtooth":     _pepper_sawtooth,
}

OSMIUM_REGIMES = {
    "normal":   _osmium_normal,
    "volatile": _osmium_volatile,
    "drift":    _osmium_drift,
}

SCENARIOS = {
    "bull_normal":          ("bull_trend", "normal"),
    "crash_normal":         ("crash", "normal"),
    "crash_volatile":       ("crash", "volatile"),
    "bear_normal":          ("bear_trend", "normal"),
    "bear_volatile":        ("bear_trend", "volatile"),
    "sideways_normal":      ("sideways", "normal"),
    "sideways_drift":       ("sideways", "drift"),
    "spike_crash_volatile": ("spike_crash", "volatile"),
    "high_vol_volatile":    ("high_vol", "volatile"),
    "v_recovery_normal":    ("v_recovery", "normal"),
    "v_recovery_drift":     ("v_recovery", "drift"),
    "sawtooth_normal":      ("sawtooth", "normal"),
    "sawtooth_volatile":    ("sawtooth", "volatile"),
}


def generate_scenario(
    scenario_name: str,
    pepper_regime: str,
    osmium_regime: str,
    seed: int = 42,
) -> pd.DataFrame:
    """Generate one full IMC-format day for a given regime combo."""
    np.random.seed(seed)

    pepper_gen = PEPPER_REGIMES[pepper_regime]
    osmium_gen = OSMIUM_REGIMES[osmium_regime]

    pepper_prices = pepper_gen(TICKS)
    osmium_prices = osmium_gen(TICKS)

    rows = []
    for i in range(TICKS):
        ts = i * TICK_INTERVAL
        rows.append(_build_orderbook_row(
            scenario_name, ts, "INTARIAN_PEPPER_ROOT", pepper_prices[i],
            spread_mean=14.0, vol_mean=15.0,
        ))
        rows.append(_build_orderbook_row(
            scenario_name, ts, "ASH_COATED_OSMIUM", osmium_prices[i],
            spread_mean=16.0, vol_mean=13.0,
        ))

    return pd.DataFrame(rows)


def generate_all(regimes_filter: str = None, num_seeds: int = 3) -> Dict[str, str]:
    """Generate all scenarios (or a specific one) with multiple random seeds."""
    scenarios_to_run = SCENARIOS
    if regimes_filter:
        scenarios_to_run = {k: v for k, v in SCENARIOS.items() if regimes_filter in k}
        if not scenarios_to_run:
            if regimes_filter in PEPPER_REGIMES:
                scenarios_to_run = {
                    f"{regimes_filter}_{o}": (regimes_filter, o) for o in OSMIUM_REGIMES
                }

    if not scenarios_to_run:
        print(f"No matching scenarios for '{regimes_filter}'")
        return {}

    saved_files = {}
    total = len(scenarios_to_run) * num_seeds
    count = 0

    for name, (pep_regime, osm_regime) in scenarios_to_run.items():
        for seed in range(num_seeds):
            label = f"{name}_s{seed}"
            print(f"  [{count+1}/{total}] Generating {label}...")

            df = generate_scenario(label, pep_regime, osm_regime, seed=seed)
            out_path = SCENARIO_DIR / f"prices_{label}.csv"
            df.to_csv(out_path, sep=";", index=False)

            saved_files[label] = str(out_path)
            count += 1

    print(f"\nGenerated {count} scenario files in {SCENARIO_DIR}")
    return saved_files


def list_scenarios():
    """List all available scenarios and any generated files."""
    print("Available regime combinations:")
    print(f"  Pepper regimes: {list(PEPPER_REGIMES.keys())}")
    print(f"  Osmium regimes: {list(OSMIUM_REGIMES.keys())}")
    print(f"\nPre-defined scenarios:")
    for name, (pep, osm) in SCENARIOS.items():
        print(f"  {name:30s} -> pepper={pep}, osmium={osm}")

    existing = list(SCENARIO_DIR.glob("prices_*.csv"))
    print(f"\nGenerated files: {len(existing)}")
    for f in sorted(existing)[:10]:
        print(f"  {f.name}")
    if len(existing) > 10:
        print(f"  ... and {len(existing) - 10} more")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate synthetic market scenarios")
    parser.add_argument("--list", action="store_true", help="List available scenarios")
    parser.add_argument("--regime", type=str, default=None, help="Generate specific regime(s)")
    parser.add_argument("--seeds", type=int, default=3, help="Number of random seeds per scenario")
    args = parser.parse_args()

    if args.list:
        list_scenarios()
    else:
        print("=== GENERATING SYNTHETIC SCENARIOS ===")
        generate_all(args.regime, args.seeds)
