import os
import subprocess
import pandas as pd
import sys

# Ensure datamodel is found
os.environ["PYTHONPATH"] = "ROUND 1/config;ROUND 1/traders"

traders = [
    "ROUND 1/traders/trader.py",
    "ROUND 1/traders/trader_10k_clean.py",
    "ROUND 1/traders/trader_ken_v6_6.py",
    "ROUND 1/traders/trader_osmium_v1.py"
]

results = []

print("Starting Benchmarks...")

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
        
        total_pnl = "N/A"
        for line in output.split("\n"):
            if "Total PnL:" in line:
                total_pnl = line.split("$")[-1].strip()
                break
    except subprocess.CalledProcessError as e:
        print(f"Error in backtest for {t_name}: {e.output.decode()}")
        total_pnl = "Error"
    except Exception as e:
        print(f"Error in backtest for {t_name}: {e}")
        total_pnl = "Error"

    # 2. Monte Carlo (Mean PnL & Win Rate)
    try:
        # Run 10 sessions for speed
        cmd = f"python \"ROUND 1/tools/monte_carlo_backtester.py\" \"{t_path}\" 10 1000"
        output = subprocess.check_output(cmd, shell=True, stderr=subprocess.STDOUT).decode()
        
        mc_mean = "N/A"
        mc_win = "N/A"
        for line in output.split("\n"):
            if "Mean:" in line:
                mc_mean = line.split("$")[-1].strip()
            if "Win Rate:" in line:
                mc_win = line.split(":")[-1].strip()
    except subprocess.CalledProcessError as e:
        print(f"Error in Monte Carlo for {t_name}: {e.output.decode()}")
        mc_mean = "Error"
        mc_win = "Error"
    except Exception as e:
        print(f"Error in Monte Carlo for {t_name}: {e}")
        mc_mean = "Error"
        mc_win = "Error"
    
    results.append({
        "Trader": t_name,
        "Total_PnL_Hist": total_pnl,
        "MC_Mean": mc_mean,
        "MC_Win_Rate": mc_win
    })

# Manual markdown generation
markdown = "| Trader | Total PnL (Hist) | MC Mean | MC Win Rate |\n"
markdown += "| --- | --- | --- | --- |\n"
for r in results:
    markdown += f"| {r['Trader']} | {r['Total_PnL_Hist']} | {r['MC_Mean']} | {r['MC_Win_Rate']} |\n"

print("\nFinal Result Table:")
print(markdown)

with open("ROUND 1/docs/full_benchmark_report.md", "w") as f:
    f.write("# Full Benchmark Report\n\n")
    f.write(markdown)
    f.write("\n\n*Note: MC Mean is often 0 for pure market-makers because the simulator only handles taker fills.*")

print("\nFull report saved to ROUND 1/docs/full_benchmark_report.md")
