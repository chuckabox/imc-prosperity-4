"""SMM Strike Sweep: Find the most profitable strikes to MM."""
import subprocess
import json
import re
from pathlib import Path

TRADER_SRC = Path(r"ROUND 3/traders/ken/we found vfe gold.py")
TRADER_TMP = Path(r"ROUND 3/traders/ken/_tmp_smm_sweep.py")
DATASET = "ROUND 3/data_capsule"

def modify_smm_strikes(src_path, dst_path, strikes):
    content = src_path.read_text()
    # Replace SMM_STRIKES = [...]
    pattern = r'(SMM_STRIKES\s*=\s*)\[.*?\]'
    content = re.sub(pattern, rf'\g<1>{strikes}', content)
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
    ("baseline_all", [5200, 5300, 5400, 5500]),
    ("no_5300",      [5200, 5400, 5500]),
    ("no_5200",      [5300, 5400, 5500]),
    ("only_5400",    [5400]),
    ("only_5300_5400", [5300, 5400]),
    ("add_5100",     [5100, 5200, 5300, 5400, 5500]),
    ("smm_off",      []),
]

print(f"{'Config':<25} {'Total':>8} {'VFE':>8} {'VEV_net':>8} {'5300':>8} {'5400':>8}")
print("-" * 70)

for name, strikes in configs:
    modify_smm_strikes(TRADER_SRC, TRADER_TMP, strikes)
    total_pnl, by_product = run_backtest(TRADER_TMP)
    if total_pnl is None:
        print(f"{name:<25}  FAILED")
        continue
    
    vfe = by_product.get("VELVETFRUIT_EXTRACT", 0)
    vev_net = sum(v for k, v in by_product.items() if k.startswith("VEV_"))
    p5300 = by_product.get("VEV_5300", 0)
    p5400 = by_product.get("VEV_5400", 0)
    
    print(f"{name:<25} {total_pnl:>8.0f} {vfe:>8.0f} {vev_net:>8.0f} {p5300:>8.0f} {p5400:>8.0f}")

if TRADER_TMP.exists(): TRADER_TMP.unlink()
