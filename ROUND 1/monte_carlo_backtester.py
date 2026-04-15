"""
Monte Carlo Backtester for IMC Prosperity 4 Round 1
Extends the tutorial-only repo to support Round 1 products:
- ASH_COATED_OSMIUM (anchored fair value)
- INTARIAN_PEPPER_ROOT (random walk fair value)
"""

import json
import math
import random
import numpy as np
import pandas as pd
from pathlib import Path
from typing import Dict, List, Tuple, Any
from datamodel import Order, OrderDepth, TradingState, Symbol, Trade, Listing, Observation
import importlib.util

class MarketSimulator:
    """Generate synthetic order books and trades for Monte Carlo simulation."""

    def __init__(self, osmium_anchor: float = 10000, pepper_volatility: float = 0.5):
        """
        Parameters calibrated from Round 1 data.

        osmium_anchor: Fair value anchor for Osmium (~10000)
        pepper_volatility: Random walk volatility per step
        """
        self.osmium_anchor = osmium_anchor
        self.pepper_volatility = pepper_volatility

        # Bot placement spreads (calibrated from data)
        self.osmium_outer_spread = 10
        self.osmium_inner_spread = 8
        self.pepper_outer_spread = 8
        self.pepper_inner_spread = 6.5

        # Bot sizes (typical)
        self.bot_outer_size = 500
        self.bot_inner_size = 300

        # Trade flow statistics
        self.trade_intensity = 0.3  # Trades per timestamp
        self.trade_size_mean = 15
        self.trade_size_std = 8

    def generate_fair_price(self, product: str, step: int, history: Dict) -> float:
        """Generate fair value for this step."""
        if product == 'ASH_COATED_OSMIUM':
            # Osmium anchored at 10000 + tape adjustment
            if 'osmium_tape' not in history:
                history['osmium_tape'] = 0

            # Simulate tape momentum
            tape_drift = np.random.normal(0, 0.5)
            history['osmium_tape'] = 0.8 * history['osmium_tape'] + tape_drift

            fair = self.osmium_anchor + history['osmium_tape']
            return fair

        elif product == 'INTARIAN_PEPPER_ROOT':
            # Pepper Root is a random walk
            if 'pepper_fair' not in history:
                history['pepper_fair'] = 5000  # Start around 5000

            # Random walk with mean reversion
            drift = -0.1 * (history['pepper_fair'] - 5000) / 100  # Mean reversion to 5000
            shock = np.random.normal(drift, self.pepper_volatility)
            history['pepper_fair'] = max(1, history['pepper_fair'] + shock)

            return history['pepper_fair']

        return 0

    def build_order_book(self, product: str, fair: float) -> Tuple[Dict, Dict]:
        """Generate bot order book around fair value."""
        buy_orders = {}
        sell_orders = {}

        if product == 'ASH_COATED_OSMIUM':
            spread = self.osmium_outer_spread
            inner = self.osmium_inner_spread
        else:  # PEPPER_ROOT
            spread = self.pepper_outer_spread
            inner = self.pepper_inner_spread

        # Outer wall (symmetric)
        buy_price = int(fair - spread)
        sell_price = int(fair + spread)
        buy_orders[buy_price] = self.bot_outer_size
        sell_orders[sell_price] = self.bot_outer_size

        # Inner wall (symmetric)
        buy_price = int(fair - inner)
        sell_price = int(fair + inner)
        buy_orders[buy_price] = self.bot_inner_size
        sell_orders[sell_price] = self.bot_inner_size

        # Optional one-sided inside quote (add noise)
        if np.random.rand() > 0.5:
            if np.random.rand() > 0.5:  # Buy side
                inside_buy = int(fair - inner + 1)
                buy_orders[inside_buy] = self.bot_inner_size // 2
            else:  # Sell side
                inside_sell = int(fair + inner - 1)
                sell_orders[inside_sell] = self.bot_inner_size // 2

        return buy_orders, sell_orders

    def generate_trades(self, product: str, fair: float, your_orders: List[Order]) -> List[Trade]:
        """Generate simulated trades after your orders."""
        trades = []

        # Simulate bot taker aggression
        if np.random.rand() < self.trade_intensity:
            # Random side
            side_is_buy = np.random.rand() > 0.5
            size = max(1, int(np.random.normal(self.trade_size_mean, self.trade_size_std)))

            # Trade price: somewhere around fair
            if side_is_buy:
                price = fair + np.random.uniform(0, 2)
            else:
                price = fair - np.random.uniform(0, 2)

            trades.append(Trade(product, int(price), size, (None, side_is_buy), None, 0))

        return trades


class MonteCarloBacktester:
    """Run trader on synthetic market paths."""

    def __init__(self, trader_file: str, num_sessions: int = 100, steps_per_session: int = 1000):
        self.trader_file = trader_file
        self.num_sessions = num_sessions
        self.steps_per_session = steps_per_session
        self.simulator = MarketSimulator()
        self.trader = self._load_trader()
        self.results = []

    def _load_trader(self):
        """Import trader module dynamically."""
        spec = importlib.util.spec_from_file_location("trader", self.trader_file)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module.Trader()

    def run_session(self, session_id: int, seed: int = None) -> Dict:
        """Run one Monte Carlo session."""
        if seed is not None:
            np.random.seed(seed)
            random.seed(seed)

        # Initialize
        cash = 0
        position = {'ASH_COATED_OSMIUM': 0, 'INTARIAN_PEPPER_ROOT': 0}
        history = {}
        pnl_history = []
        max_position = {'ASH_COATED_OSMIUM': 0, 'INTARIAN_PEPPER_ROOT': 0}
        trade_count = {'ASH_COATED_OSMIUM': 0, 'INTARIAN_PEPPER_ROOT': 0}

        # Track fair values for MTM
        fair_values = {'ASH_COATED_OSMIUM': 10000, 'INTARIAN_PEPPER_ROOT': 5000}

        # Create listings once (reuse each step)
        listings = {
            'ASH_COATED_OSMIUM': Listing('ASH_COATED_OSMIUM', 'ASH_COATED_OSMIUM', 'SEASHELLS'),
            'INTARIAN_PEPPER_ROOT': Listing('INTARIAN_PEPPER_ROOT', 'INTARIAN_PEPPER_ROOT', 'SEASHELLS')
        }

        # Run simulation
        for step in range(self.steps_per_session):
            # Generate fair values
            fair_values['ASH_COATED_OSMIUM'] = self.simulator.generate_fair_price(
                'ASH_COATED_OSMIUM', step, history
            )
            fair_values['INTARIAN_PEPPER_ROOT'] = self.simulator.generate_fair_price(
                'INTARIAN_PEPPER_ROOT', step, history
            )

            # Build order books
            order_depths = {}
            for product in ['ASH_COATED_OSMIUM', 'INTARIAN_PEPPER_ROOT']:
                buy_orders, sell_orders = self.simulator.build_order_book(
                    product, fair_values[product]
                )
                depth = OrderDepth()
                depth.buy_orders = buy_orders
                depth.sell_orders = sell_orders
                order_depths[product] = depth

            # Create market trades (history is empty in this simple version)
            market_trades = {
                'ASH_COATED_OSMIUM': self.simulator.generate_trades(
                    'ASH_COATED_OSMIUM', fair_values['ASH_COATED_OSMIUM'], []
                ),
                'INTARIAN_PEPPER_ROOT': self.simulator.generate_trades(
                    'INTARIAN_PEPPER_ROOT', fair_values['INTARIAN_PEPPER_ROOT'], []
                ),
            }

            # Create state with required arguments
            state = TradingState(
                timestamp=step * 100,  # Arbitrary ms
                traderData=json.dumps(history) if history else "",
                market_trades=market_trades,
                order_depths=order_depths,
                position=position,
                own_trades={},
                listings=listings,
                observations=Observation({}, {})
            )

            # Run trader
            try:
                orders, conversions, trader_data = self.trader.run(state)
                history = json.loads(trader_data) if trader_data else {}
            except Exception as e:
                print(f"Session {session_id}: Error on step {step}: {e}")
                continue

            # Simulate fills (aggressive matching)
            for product, order_list in orders.items():
                for order in order_list:
                    if order.quantity > 0:  # Buy
                        # Try to match at best ask
                        if order_depths[product].sell_orders:
                            best_ask = min(order_depths[product].sell_orders.keys())
                            if order.price >= best_ask:
                                fill_qty = min(order.quantity,
                                             order_depths[product].sell_orders[best_ask])
                                position[product] += fill_qty
                                cash -= fill_qty * best_ask
                                trade_count[product] += 1
                    else:  # Sell
                        # Try to match at best bid
                        if order_depths[product].buy_orders:
                            best_bid = max(order_depths[product].buy_orders.keys())
                            if order.price <= best_bid:
                                fill_qty = min(abs(order.quantity),
                                             order_depths[product].buy_orders[best_bid])
                                position[product] -= fill_qty
                                cash += fill_qty * best_bid
                                trade_count[product] += 1

            # Calculate MTM PnL
            mtm = cash
            for product in ['ASH_COATED_OSMIUM', 'INTARIAN_PEPPER_ROOT']:
                mtm += position[product] * fair_values[product]

            pnl_history.append(mtm)
            max_position['ASH_COATED_OSMIUM'] = max(
                max_position['ASH_COATED_OSMIUM'], abs(position['ASH_COATED_OSMIUM'])
            )
            max_position['INTARIAN_PEPPER_ROOT'] = max(
                max_position['INTARIAN_PEPPER_ROOT'], abs(position['INTARIAN_PEPPER_ROOT'])
            )

        # Calculate final stats
        final_pnl = pnl_history[-1] if pnl_history else 0

        # Compute max drawdown (peak-to-trough)
        max_drawdown = 0
        peak = 0
        for pnl in pnl_history:
            if pnl > peak:
                peak = pnl
            dd = peak - pnl
            if dd > max_drawdown:
                max_drawdown = dd

        return {
            'session_id': session_id,
            'final_pnl': final_pnl,
            'max_drawdown': max_drawdown,
            'max_position_osmium': max_position['ASH_COATED_OSMIUM'],
            'max_position_pepper': max_position['INTARIAN_PEPPER_ROOT'],
            'trades_osmium': trade_count['ASH_COATED_OSMIUM'],
            'trades_pepper': trade_count['INTARIAN_PEPPER_ROOT'],
            'pnl_history': pnl_history,
        }

    def run(self) -> Dict:
        """Run all Monte Carlo sessions."""
        print(f"Running {self.num_sessions} Monte Carlo sessions...")

        for session_id in range(self.num_sessions):
            result = self.run_session(session_id, seed=session_id)
            self.results.append(result)

            if (session_id + 1) % 10 == 0:
                print(f"  Completed {session_id + 1}/{self.num_sessions} sessions")

        return self._compute_stats()

    def _compute_stats(self) -> Dict:
        """Compute summary statistics."""
        pnls = [r['final_pnl'] for r in self.results]
        drawdowns = [r['max_drawdown'] for r in self.results]

        return {
            'num_sessions': self.num_sessions,
            'mean_pnl': np.mean(pnls),
            'std_pnl': np.std(pnls),
            'min_pnl': np.min(pnls),
            'max_pnl': np.max(pnls),
            'percentile_5': np.percentile(pnls, 5),
            'percentile_25': np.percentile(pnls, 25),
            'median_pnl': np.median(pnls),
            'percentile_75': np.percentile(pnls, 75),
            'percentile_95': np.percentile(pnls, 95),
            'mean_drawdown': np.mean(drawdowns),
            'worst_drawdown': np.min(drawdowns),
            'best_drawdown': np.max(drawdowns),
            'win_rate': sum(1 for p in pnls if p > 0) / len(pnls) if pnls else 0,
            'all_pnls': pnls,
            'all_drawdowns': drawdowns,
        }

    def print_results(self, stats: Dict):
        """Print formatted results."""
        print("\n" + "="*60)
        print("MONTE CARLO SIMULATION RESULTS")
        print("="*60)
        print(f"Sessions: {stats['num_sessions']}")
        print(f"Steps per session: {self.steps_per_session}")
        print()
        print("PnL Distribution:")
        print(f"  Mean:          ${stats['mean_pnl']:>10,.2f}")
        print(f"  Median:        ${stats['median_pnl']:>10,.2f}")
        print(f"  Std Dev:       ${stats['std_pnl']:>10,.2f}")
        print()
        print("Percentiles:")
        print(f"  5th:           ${stats['percentile_5']:>10,.2f}")
        print(f"  25th:          ${stats['percentile_25']:>10,.2f}")
        print(f"  75th:          ${stats['percentile_75']:>10,.2f}")
        print(f"  95th:          ${stats['percentile_95']:>10,.2f}")
        print()
        print("Range:")
        print(f"  Min:           ${stats['min_pnl']:>10,.2f}")
        print(f"  Max:           ${stats['max_pnl']:>10,.2f}")
        print()
        print("Drawdown Statistics:")
        print(f"  Mean DD:       ${stats['mean_drawdown']:>10,.2f}")
        print(f"  Worst DD:      ${stats['worst_drawdown']:>10,.2f}")
        print(f"  Best DD:       ${stats['best_drawdown']:>10,.2f}")
        print()
        print(f"Win Rate:        {stats['win_rate']*100:>6.1f}%")
        print("="*60)

    def save_results(self, output_file: str):
        """Save results to CSV."""
        df = pd.DataFrame(self.results)
        # Remove pnl_history for CSV (too verbose)
        df = df.drop(columns=['pnl_history'])
        df.to_csv(output_file, index=False)
        print(f"\nDetailed results saved to: {output_file}")


if __name__ == "__main__":
    import sys

    # Usage: python monte_carlo_backtester.py <trader_file> [num_sessions] [steps_per_session]
    trader_file = sys.argv[1] if len(sys.argv) > 1 else "ROUND 1/trader_peter4.py"
    num_sessions = int(sys.argv[2]) if len(sys.argv) > 2 else 100
    steps_per_session = int(sys.argv[3]) if len(sys.argv) > 3 else 1000

    backtester = MonteCarloBacktester(trader_file, num_sessions, steps_per_session)
    stats = backtester.run()
    backtester.print_results(stats)

    # Save results
    output_file = trader_file.replace(".py", "_mc_results.csv")
    backtester.save_results(output_file)
