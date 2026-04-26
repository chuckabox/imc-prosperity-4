"""SMM Quantity Sweep: How much inventory should we feed the VFE beast?"""
import subprocess
import json
import re
from pathlib import Path

TRADER_SRC = Path(r"ROUND 3/traders/ken/we found vfe gold.py")
TRADER_TMP = Path(r"ROUND 3/traders/ken/_tmp_qty_sweep.py")
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
    if not match: return None, None
    run_path = Path(match.group(1))
    total_pnl = float(match.group(2).replace(",", ""))
    metrics_path = run_path / "metrics.json"
    if metrics_path.exists():
        with open(metrics_path) as f:
            metrics = json.load(f)
        return total_pnl, metrics.get("final_pnl_by_product", {})
    return total_pnl, None

configs = [
    ("qty_10", {"SMM_QTY": 10, "SMM_POS_CAP": 35}),
    ("qty_15", {"SMM_QTY": 15, "SMM_POS_CAP": 50}),
    ("qty_20", {"SMM_QTY": 20, "SMM_POS_CAP": 65}),
    ("qty_25", {"SMM_QTY": 25, "SMM_POS_CAP": 80}),
    ("qty_30", {"SMM_QTY": 30, "SMM_POS_CAP": 100}),
]

print(f"{'Config':<25} {'Total':>8} {'VFE':>8} {'VEV_net':>8}")
print("-" * 50)

for name, params in configs:
    modify_param(TRADER_SRC, TRADER_TMP, params)
    total_pnl, by_product = run_backtest(TRADER_TMP)
    if total_pnl is None:
        print(f"{name:<25}  FAILED")
        continue
    
    vfe = by_product.get("VELVETFRUIT_EXTRACT", 0)
    vev_net = sum(v for k, v in by_product.items() if k.startswith("VEV_"))
    
    print(f"{name:<25} {total_pnl:>8.0f} {vfe:>8.0f} {vev_net:>8.0f}")

if TRADER_TMP.exists(): TRADER_TMP.unlink()
