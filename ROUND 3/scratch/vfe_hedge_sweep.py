"""Fine sweep around the best VFE hedge configs."""
import subprocess
import json
import re
from pathlib import Path

TRADER_SRC = Path(r"ROUND 3/traders/ken/we found smile mm.py")
TRADER_TMP = Path(r"ROUND 3/traders/ken/_tmp_vfe_sweep.py")
DATASET = "ROUND 3/data_capsule"

def modify_param(src_path, dst_path, replacements):
    content = src_path.read_text()
    for param, value in replacements.items():
        pattern = rf'({param}\s*=\s*)([\d.]+)'
        content = re.sub(pattern, rf'\g<1>{value}', content)
    dst_path.write_text(content)

def run_backtest(trader_path):
    result = subprocess.run(
        ["python", "tools/run_prosperity4bt.py",
         "--trader", str(trader_path),
         "--dataset", DATASET,
         "--day", "2",
         "--no-progress"],
        capture_output=True, text=True, cwd="."
    )
    match = re.search(r'->\s+(\S+)\s+PnL=([\d,.-]+)', result.stdout)
    if not match:
        return None, None
    run_path = Path(match.group(1))
    total_pnl = float(match.group(2).replace(",", ""))
    metrics_path = run_path / "metrics.json"
    if metrics_path.exists():
        with open(metrics_path) as f:
            metrics = json.load(f)
        return total_pnl, metrics.get("final_pnl_by_product", {})
    return total_pnl, None

configs = [
    # Fine sweep: band 25-40, with taker edge variations
    ("b25_t1.6",          {"VFE_HEDGE_BAND": 25, "VFE_TAKER_EDGE": 1.6, "VFE_HEDGE_MAX": 64}),
    ("b28_t1.6",          {"VFE_HEDGE_BAND": 28, "VFE_TAKER_EDGE": 1.6, "VFE_HEDGE_MAX": 64}),
    ("b30_t1.6",          {"VFE_HEDGE_BAND": 30, "VFE_TAKER_EDGE": 1.6, "VFE_HEDGE_MAX": 64}),
    ("b32_t1.6",          {"VFE_HEDGE_BAND": 32, "VFE_TAKER_EDGE": 1.6, "VFE_HEDGE_MAX": 64}),
    ("b35_t1.6",          {"VFE_HEDGE_BAND": 35, "VFE_TAKER_EDGE": 1.6, "VFE_HEDGE_MAX": 64}),
    ("b40_t1.6",          {"VFE_HEDGE_BAND": 40, "VFE_TAKER_EDGE": 1.6, "VFE_HEDGE_MAX": 64}),
    # Best band + taker edge combo
    ("b30_t2.0",          {"VFE_HEDGE_BAND": 30, "VFE_TAKER_EDGE": 2.0, "VFE_HEDGE_MAX": 64}),
    ("b30_t2.5",          {"VFE_HEDGE_BAND": 30, "VFE_TAKER_EDGE": 2.5, "VFE_HEDGE_MAX": 64}),
    ("b30_t3.0",          {"VFE_HEDGE_BAND": 30, "VFE_TAKER_EDGE": 3.0, "VFE_HEDGE_MAX": 64}),
    # Aggressive aggro band too
    ("b30_t1.6_ab60",     {"VFE_HEDGE_BAND": 30, "VFE_TAKER_EDGE": 1.6, "VFE_HEDGE_MAX": 64, "VFE_HEDGE_AGGRO_BAND": 60}),
    ("b30_t1.6_ab80",     {"VFE_HEDGE_BAND": 30, "VFE_TAKER_EDGE": 1.6, "VFE_HEDGE_MAX": 64, "VFE_HEDGE_AGGRO_BAND": 80}),
    # Also check upload slice
]

print(f"{'Config':<25} {'Total':>8} {'HP':>8} {'VFE':>8} {'VEV':>8}")
print("-" * 55)

best_config = None
best_pnl = 0

for name, params in configs:
    modify_param(TRADER_SRC, TRADER_TMP, params)
    total_pnl, by_product = run_backtest(TRADER_TMP)
    if total_pnl is None:
        print(f"{name:<25}  FAILED")
        continue
    
    hp = by_product.get("HYDROGEL_PACK", 0) if by_product else 0
    vfe = by_product.get("VELVETFRUIT_EXTRACT", 0) if by_product else 0
    vev_net = sum(v for k, v in by_product.items() if k.startswith("VEV_")) if by_product else 0
    
    print(f"{name:<25} {total_pnl:>8.0f} {hp:>8.0f} {vfe:>8.0f} {vev_net:>8.0f}")
    
    if total_pnl > best_pnl:
        best_pnl = total_pnl
        best_config = (name, params)

print(f"\nBest: {best_config[0]} -> PnL={best_pnl}")
print(f"Params: {best_config[1]}")

if TRADER_TMP.exists():
    TRADER_TMP.unlink()
