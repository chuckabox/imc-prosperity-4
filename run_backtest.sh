#!/bin/bash
# Usage: ./run_backtest.sh --trader path/to/trader.py --dataset tutorial

# Get the absolute path of the backtester binary
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )"
BINARY="$SCRIPT_DIR/backtester/target/release/rust_backtester"

# Check if running in WSL
if grep -q Microsoft /proc/version; then
    # Running in WSL
    "$BINARY" "$@"
else
    # Not in WSL, try to use wsl command
    # Convert args to use /mnt/c/ instead of C:\ if needed
    # (Simple version: just pass them through and hope for the best, or use wslpath)
    wsl bash -c "$BINARY $(printf '%q ' "$@")"
fi
