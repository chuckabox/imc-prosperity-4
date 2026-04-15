import os
import subprocess
import pandas as pd
import sys

# Ensure datamodel is found
os.environ["PYTHONPATH"] = "ROUND 1/config;ROUND 1/traders"

traders = [
    "ROUND 1/traders/trader.py",
    "ROUND 1/traders/trader_10k.py",
    "ROUND 1/traders/trader_10k_clean.py",
    "ROUND 1/traders/trader_adin.py",
    "ROUND 1/traders/trader_peter_v1.py",
    "ROUND 1/traders/trader_peter_v2.py",
    "ROUND 1/traders/trader_osmium_v1.py",
    "ROUND 1/traders/trader_ken_v6_6.py"
]

results = []

print("Starting Full Benchmarks...")

for t_path in traders:
    t_name = os.path.basename(t_path)
    if not os.path.exists(t_path):
        print(f"File not found: {t_path}")
        continue

    print(f"\n--- Benchmarking {t_name} ---")
    
    # 1. CLI Backtest (Total PnL)
    try:
        cmd = f"python \"ROUND 1/tools/backtest_cli.py\" \"{t_path}\""
        output = subprocess.check_output(cmd, shell=True, stderr=subprocess.STDOUT).decode()
        
        total_pnl = 0.0
        day_results = {}
        for line in output.split("\n"):
            if "Total PnL:" in line:
                total_pnl = float(line.split("$")[-1].replace(",", "").strip())
            if "Final PnL:" in line and "Day" not in line: # Usually shows per day in order -2, -1, 0
                pass 
                
        # Better extraction for day by day
        day_PnLs = []
        for line in output.split("\n"):
            if "Final PnL:" in line:
                val = float(line.split("$")[-1].split("|")[0].replace(",", "").strip())
                day_PnLs.append(val)
        
        # We expect 3 days
        d_minus2 = day_PnLs[0] if len(day_PnLs) > 0 else 0
        d_minus1 = day_PnLs[1] if len(day_PnLs) > 1 else 0
        d_zero = day_PnLs[2] if len(day_PnLs) > 2 else 0

    except Exception as e:
        print(f"Error in backtest for {t_name}: {e}")
        d_minus2 = d_minus1 = d_zero = total_pnl = 0.0

    results.append({
        "Trader": t_name,
        "Day_-2": d_minus2,
        "Day_-1": d_minus1,
        "Day_0": d_zero,
        "Total_PnL": total_pnl
    })

df = pd.DataFrame(results)
df = df.sort_values(by="Total_PnL", ascending=False)

markdown = "| Trader | Day -2 | Day -1 | Day 0 | Total PnL |\n"
markdown += "| :--- | :--- | :--- | :--- | :--- |\n"
for _, r in df.iterrows():
    markdown += f"| {r['Trader']} | {r['Day_-2']:,.2f} | {r['Day_-1']:,.2f} | {r['Day_0']:,.2f} | **{r['Total_PnL']:,.2f}** |\n"

print("\nFinal Result Table:")
print(markdown)

with open("ROUND 1/docs/peter_comparisons.md", "w") as f:
    f.write("# Trader Benchmarks & Comparisons\n\n")
    f.write("Generated: 2026-04-16\n\n")
    f.write(markdown)
    f.write("\n\n## Analysis Summary\n")
    
    best = df.iloc[0]
    f.write(f"\n- **Best Overall**: `{best['Trader']}` with a total PnL of **{best['Total_PnL']:,.2f}**.\n")
    
    # Check for Day 0 robustness
    day0best = df.sort_values(by="Day_0", ascending=False).iloc[0]
    f.write(f"- **Day 0 Champion**: `{day0best['Trader']}` ({day0best['Day_0']:,.2f}). This version handles reversals best.\n")

print("\nFull report saved to ROUND 1/docs/peter_comparisons.md")
