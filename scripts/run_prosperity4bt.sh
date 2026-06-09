#!/bin/bash
# Wrapper to run the python backtester located in external/imc-prosperity-4-backtester
# Usage: ./run_prosperity4bt.sh "ROUND 5/traders/peter/answer2.py" 5

export PYTHONPATH="external/imc-prosperity-4-backtester"
python3 -m prosperity4bt "$@"
