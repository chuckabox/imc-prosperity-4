"""
Monte Carlo Backtester CLI with presets (quick/default/heavy)
Inspired by: https://github.com/chrispyroberts/imc-prosperity-4

Quick start:
    python monte_carlo_cli.py trader_peter4.py --quick
    python monte_carlo_cli.py trader_peter3.py --heavy
    python monte_carlo_cli.py trader_peter2.py --sessions 500 --steps 2000
"""

import argparse
import sys
import os
from pathlib import Path

# Add relevant directories to sys.path to resolve imports
current_dir = Path(__file__).parent
root_dir = current_dir.parent
sys.path.append(str(current_dir))        # tools/
sys.path.append(str(root_dir / "config"))  # config/ (for datamodel)

from monte_carlo_backtester import MonteCarloBacktester

# Presets
PRESETS = {
    'quick': {
        'num_sessions': 50,
        'steps_per_session': 500,
        'description': 'Quick smoke test (50 sessions × 500 steps)'
    },
    'default': {
        'num_sessions': 100,
        'steps_per_session': 1000,
        'description': 'Standard analysis (100 sessions × 1000 steps)'
    },
    'heavy': {
        'num_sessions': 1000,
        'steps_per_session': 1000,
        'description': 'Deep analysis (1000 sessions × 1000 steps)'
    },
    'ultra': {
        'num_sessions': 5000,
        'steps_per_session': 1000,
        'description': 'Expert mode (5000 sessions × 1000 steps)'
    }
}

def main():
    parser = argparse.ArgumentParser(
        description='Monte Carlo Backtester for IMC Prosperity 4 Round 1',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='''
Examples:
  %(prog)s trader_peter4.py
  %(prog)s trader_peter4.py --quick
  %(prog)s trader_peter4.py --heavy
  %(prog)s trader_peter3.py --sessions 200 --steps 1500
  %(prog)s trader_peter2.py --quick --compare

Presets:
  --quick:     50 sessions × 500 steps (fast feedback)
  --default:   100 sessions × 1000 steps (recommended)
  --heavy:     1000 sessions × 1000 steps (comprehensive)
  --ultra:     5000 sessions × 1000 steps (expert)
        '''
    )

    parser.add_argument('trader', help='Path to trader file (e.g., ROUND 1/trader_peter4.py)')
    parser.add_argument('--quick', action='store_const', dest='preset', const='quick',
                       help=f'{PRESETS["quick"]["description"]}')
    parser.add_argument('--default', action='store_const', dest='preset', const='default',
                       help=f'{PRESETS["default"]["description"]}')
    parser.add_argument('--heavy', action='store_const', dest='preset', const='heavy',
                       help=f'{PRESETS["heavy"]["description"]}')
    parser.add_argument('--ultra', action='store_const', dest='preset', const='ultra',
                       help=f'{PRESETS["ultra"]["description"]}')
    parser.add_argument('--sessions', type=int, default=None,
                       help='Override number of sessions')
    parser.add_argument('--steps', type=int, default=None,
                       help='Override steps per session')
    parser.add_argument('--output', '-o', type=str, default=None,
                       help='Output CSV file (default: <trader>_mc_results.csv)')
    parser.add_argument('--seed', type=int, default=42,
                       help='Random seed for reproducibility')

    args = parser.parse_args()

    # Check trader file exists
    trader_path = Path(args.trader)
    if not trader_path.exists():
        print(f"Error: Trader file not found: {trader_path}")
        sys.exit(1)

    # Determine parameters
    preset = args.preset or 'default'
    params = PRESETS[preset].copy()

    # Allow overrides
    if args.sessions is not None:
        params['num_sessions'] = args.sessions
    if args.steps is not None:
        params['steps_per_session'] = args.steps

    num_sessions = params['num_sessions']
    steps_per_session = params['steps_per_session']

    print(f"\n{'='*60}")
    print(f"Monte Carlo Backtester for {trader_path.name}")
    print(f"{'='*60}")
    print(f"Preset:    {preset.upper()}")
    print(f"Sessions:  {num_sessions}")
    print(f"Steps:     {steps_per_session} per session")
    print(f"Total:     {num_sessions * steps_per_session:,} simulation steps")
    print(f"{'='*60}\n")

    # Run backtester
    backtester = MonteCarloBacktester(
        str(trader_path),
        num_sessions=num_sessions,
        steps_per_session=steps_per_session
    )

    stats = backtester.run()
    backtester.print_results(stats)

    # Save results
    results_dir = Path(root_dir) / "results"
    results_dir.mkdir(exist_ok=True)
    
    if args.output:
        output_file = args.output
    else:
        output_file = results_dir / trader_path.name.replace('.py', '_mc_results.csv')

    backtester.save_results(str(output_file))

    # Additional interpretation
    print("\n" + "="*60)
    print("INTERPRETATION GUIDE")
    print("="*60)

    mean = stats['mean_pnl']
    std = stats['std_pnl']
    p5 = stats['percentile_5']
    p95 = stats['percentile_95']

    print(f"\n1. Expected Performance:")
    print(f"   Average session: ${mean:>10,.0f}")
    print(f"   Confidence 90%: ${p5:>10,.0f} to ${p95:>10,.0f}")

    print(f"\n2. Risk Assessment:")
    if abs(stats['worst_drawdown']) > mean:
        print(f"   [!] Drawdown risk is high (worst DD > mean)")
    else:
        print(f"   [OK] Drawdown risk is acceptable")

    print(f"\n3. Robustness:")
    if stats['std_pnl'] / max(mean, 0.1) > 0.5:
        print(f"   [!] High variance - strategy is not robust")
    else:
        print(f"   [OK] Variance is reasonable")

    print(f"\n4. Win Rate:")
    print(f"   {stats['win_rate']*100:.1f}% of sessions are profitable")

    print("\n" + "="*60)

if __name__ == '__main__':
    main()
