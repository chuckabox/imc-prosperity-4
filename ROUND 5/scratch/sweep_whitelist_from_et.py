from __future__ import annotations

import json
from pathlib import Path

import pandas as pd


REPO_ROOT = Path(__file__).resolve().parents[2]
ROUND5 = REPO_ROOT / "ROUND 5"
DOCS = ROUND5 / "docs"
TRADERS = ROUND5 / "traders" / "ken"
TMP = ROUND5 / "scratch" / "_tmp_whitelist_sweep"
SUMMARY_CSV = DOCS / "et_signal_quality_summary.csv"


TRADER_TEMPLATE = """import json
from collections import defaultdict
from typing import Dict, List, Tuple

from datamodel import Order, TradingState

class Trader:
    SYMBOLS = {symbols_set}
    LIMITS = {limits_dict}
    MM_EDGE = 2
    MM_CLIP = 2
    INV_SKEW = 0.10
    SHOCK_TRIGGER = 14.0
    TAKE_CLIP = 5
    COOLDOWN_TICKS = 3
    MAX_SPREAD = 14

    def _load(self, trader_data: str) -> Dict:
        if not trader_data:
            return {{"last_mid": {{}}, "last_trade_ts": {{}}, "last_ts": -1}}
        try:
            m = json.loads(trader_data)
            m.setdefault("last_mid", {{}})
            m.setdefault("last_trade_ts", {{}})
            m.setdefault("last_ts", -1)
            return m
        except Exception:
            return {{"last_mid": {{}}, "last_trade_ts": {{}}, "last_ts": -1}}

    def _save(self, mem: Dict) -> str:
        return json.dumps(mem, separators=(",", ":"))

    @staticmethod
    def _best_bid_ask(state: TradingState, symbol: str) -> Tuple[int, int]:
        depth = state.order_depths.get(symbol)
        if not depth or not depth.buy_orders or not depth.sell_orders:
            return None, None
        return max(depth.buy_orders.keys()), min(depth.sell_orders.keys())

    def run(self, state: TradingState):
        mem = self._load(state.traderData)
        if mem["last_ts"] >= 0 and state.timestamp < mem["last_ts"]:
            mem["last_mid"] = {{}}
            mem["last_trade_ts"] = {{}}
        mem["last_ts"] = state.timestamp

        result: Dict[str, List[Order]] = defaultdict(list)
        for symbol in self.SYMBOLS:
            if symbol not in state.order_depths:
                continue
            bid, ask = self._best_bid_ask(state, symbol)
            if bid is None or ask is None:
                continue
            spread = ask - bid
            if spread <= 0 or spread > self.MAX_SPREAD:
                continue

            mid = 0.5 * (bid + ask)
            last_mid = mem["last_mid"].get(symbol, mid)
            d_mid = mid - last_mid
            mem["last_mid"][symbol] = mid

            pos = state.position.get(symbol, 0)
            lim = self.LIMITS.get(symbol, 10)
            buy_cap = max(0, lim - pos)
            sell_cap = max(0, lim + pos)
            if buy_cap <= 0 and sell_cap <= 0:
                continue

            fair = mid - self.INV_SKEW * pos
            mm_bid = int(fair - self.MM_EDGE)
            mm_ask = int(fair + self.MM_EDGE)
            if mm_bid >= mm_ask:
                mm_ask = mm_bid + 1
            if buy_cap > 0:
                result[symbol].append(Order(symbol, mm_bid, min(self.MM_CLIP, buy_cap)))
            if sell_cap > 0:
                result[symbol].append(Order(symbol, mm_ask, -min(self.MM_CLIP, sell_cap)))

            last_trade = mem["last_trade_ts"].get(symbol, -10**9)
            if state.timestamp - last_trade >= 100 * self.COOLDOWN_TICKS:
                if d_mid <= -self.SHOCK_TRIGGER and buy_cap > 0:
                    q = min(self.TAKE_CLIP, buy_cap)
                    result[symbol].append(Order(symbol, ask, q))
                    mem["last_trade_ts"][symbol] = state.timestamp
                elif d_mid >= self.SHOCK_TRIGGER and sell_cap > 0:
                    q = min(self.TAKE_CLIP, sell_cap)
                    result[symbol].append(Order(symbol, bid, -q))
                    mem["last_trade_ts"][symbol] = state.timestamp

        return dict(result), 0, self._save(mem)
"""


def build_trader(symbols: list[str], path: Path) -> None:
    limits = {s: 14 for s in symbols}
    content = TRADER_TEMPLATE.format(symbols_set=repr(set(symbols)), limits_dict=repr(limits))
    path.write_text(content, encoding="utf-8")


def run_bt(trader_path: Path) -> tuple[int, str]:
    import subprocess

    cmd = [
        "python",
        "tools/run_python_bt.py",
        str(trader_path.relative_to(REPO_ROOT)).replace("\\", "/"),
        "5",
    ]
    proc = subprocess.run(cmd, cwd=str(REPO_ROOT), capture_output=True, text=True)
    return proc.returncode, (proc.stdout or "") + "\n" + (proc.stderr or "")


def parse_total_profit(output: str) -> float:
    for line in output.splitlines():
        if line.startswith("Total profit:"):
            try:
                return float(line.split(":")[1].strip().replace(",", ""))
            except Exception:
                pass
    return float("nan")


def main() -> None:
    df = pd.read_csv(SUMMARY_CSV)
    top_symbols = df["symbol"].dropna().tolist()
    TMP.mkdir(parents=True, exist_ok=True)

    candidates: list[tuple[str, list[str]]] = []
    for n in [2, 3, 4, 5, 6, 8, 10]:
        candidates.append((f"top{n}", top_symbols[:n]))
    # Family-diversified slices
    by_family = df.groupby("family", sort=False).head(1)["symbol"].tolist()
    candidates.append(("best_per_family_10", by_family[:10]))
    candidates.append(("best_per_family_6", by_family[:6]))

    rows = []
    for name, syms in candidates:
        path = TMP / f"wl_{name}.py"
        build_trader(syms, path)
        rc, out = run_bt(path)
        total = parse_total_profit(out)
        rows.append(
            {
                "candidate": name,
                "symbols_count": len(syms),
                "symbols": ",".join(syms),
                "return_code": rc,
                "total_profit": total,
            }
        )
        (TMP / f"wl_{name}.log.txt").write_text(out, encoding="utf-8")

    res = pd.DataFrame(rows).sort_values("total_profit", ascending=False).reset_index(drop=True)
    out_csv = ROUND5 / "scratch" / "whitelist_sweep_results.csv"
    res.to_csv(out_csv, index=False)
    print(f"Wrote {out_csv}")
    print(res.to_string(index=False))


if __name__ == "__main__":
    main()
