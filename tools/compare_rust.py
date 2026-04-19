#!/usr/bin/env python3
import subprocess
import os
import sys
from pathlib import Path
import argparse

def main():
    parser = argparse.ArgumentParser(description="Quickly compare multiple traders using the Rust backtester.")
    parser.add_argument("traders", nargs="+", help="Paths to trader .py files")
    parser.add_argument("--dataset", type=str, default="ROUND 2/data_capsule", help="Path to dataset")
    parser.add_argument("--use-wsl", action="store_true", help="Run via WSL")
    
    args = parser.parse_known_args()[0]
    
    for trader in args.traders:
        print(f"\n🚀 Running backtest for: {trader}")
        cmd = [
            "python", "tools/run_rust_backtester.py",
            "--trader", trader,
            "--dataset", args.dataset
        ]
        if args.use_wsl:
            cmd.append("--use-wsl")
            
        subprocess.run(cmd)

    print("\n✅ All backtests complete. View the comparison in the 'Rust Backtester' tab of the dashboard!")

if __name__ == "__main__":
    main()
