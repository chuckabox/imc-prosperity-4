import argparse
import hashlib
import json
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Tuple


REPO_ROOT = Path(__file__).resolve().parents[1]
RUNS_DIR = REPO_ROOT / "external" / "prosperity_rust_backtester" / "runs"


@dataclass
class RunInfo:
    path: Path
    run_id: str
    trader_path: str
    dataset_id: str
    day: int
    final_pnl: float
    own_trade_count: int
    tick_count: int
    metrics_mtime: float
    fingerprint: str


def _safe_int(value, default=-999):
    try:
        return int(value)
    except Exception:
        return default


def _safe_float(value, default=0.0):
    try:
        return float(value)
    except Exception:
        return default


def _build_fingerprint(metrics: Dict) -> str:
    payload = {
        "trader_path": metrics.get("trader_path"),
        "dataset_id": metrics.get("dataset_id"),
        "day": metrics.get("day"),
        "final_pnl_total": _safe_float(metrics.get("final_pnl_total")),
        "own_trade_count": _safe_int(metrics.get("own_trade_count")),
        "tick_count": _safe_int(metrics.get("tick_count")),
        "final_pnl_by_product": metrics.get("final_pnl_by_product", {}),
    }
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha1(blob).hexdigest()


def _load_run_info(run_dir: Path) -> RunInfo:
    metrics_path = run_dir / "metrics.json"
    if not metrics_path.exists():
        return None
    try:
        metrics = json.loads(metrics_path.read_text(encoding="utf-8"))
    except Exception:
        return None

    trader_path = str(metrics.get("trader_path", "unknown"))
    dataset_id = str(metrics.get("dataset_id", "unknown"))
    day = _safe_int(metrics.get("day"), -999)
    final_pnl = _safe_float(metrics.get("final_pnl_total"), 0.0)
    own_trade_count = _safe_int(metrics.get("own_trade_count"), -1)
    tick_count = _safe_int(metrics.get("tick_count"), -1)
    fingerprint = _build_fingerprint(metrics)

    return RunInfo(
        path=run_dir,
        run_id=run_dir.name,
        trader_path=trader_path,
        dataset_id=dataset_id,
        day=day,
        final_pnl=final_pnl,
        own_trade_count=own_trade_count,
        tick_count=tick_count,
        metrics_mtime=metrics_path.stat().st_mtime,
        fingerprint=fingerprint,
    )


def collect_runs(runs_dir: Path) -> List[RunInfo]:
    runs: List[RunInfo] = []
    if not runs_dir.exists():
        return runs
    for p in sorted(runs_dir.iterdir()):
        if not p.is_dir():
            continue
        info = _load_run_info(p)
        if info:
            runs.append(info)
    return runs


def group_duplicates(runs: List[RunInfo]) -> Dict[Tuple[str, str, int, str], List[RunInfo]]:
    groups: Dict[Tuple[str, str, int, str], List[RunInfo]] = {}
    for r in runs:
        key = (r.trader_path, r.dataset_id, r.day, r.fingerprint)
        groups.setdefault(key, []).append(r)
    return {k: v for k, v in groups.items() if len(v) > 1}


def choose_keep_and_delete(dupe_groups: Dict[Tuple[str, str, int, str], List[RunInfo]]):
    keep: List[RunInfo] = []
    delete: List[RunInfo] = []
    for _, items in dupe_groups.items():
        sorted_items = sorted(items, key=lambda x: (x.metrics_mtime, x.run_id), reverse=True)
        keep.append(sorted_items[0])
        delete.extend(sorted_items[1:])
    return keep, delete


def print_plan(dupe_groups, keep: List[RunInfo], delete: List[RunInfo]):
    print(f"Duplicate groups: {len(dupe_groups)}")
    print(f"Runs to keep: {len(keep)}")
    print(f"Runs to delete: {len(delete)}")
    if not dupe_groups:
        print("No duplicates found.")
        return
    print()
    print("Planned deletions:")
    for r in sorted(delete, key=lambda x: (x.trader_path, x.dataset_id, x.day, x.run_id)):
        print(
            f"- {r.run_id} | trader={Path(r.trader_path).name} | dataset={r.dataset_id} "
            f"| day={r.day} | pnl={r.final_pnl:.2f}"
        )


def apply_delete(delete_runs: List[RunInfo]):
    for r in delete_runs:
        shutil.rmtree(r.path, ignore_errors=True)


def main():
    parser = argparse.ArgumentParser(
        description="Manage rust backtester results and remove duplicate runs safely."
    )
    parser.add_argument(
        "--runs-dir",
        default=str(RUNS_DIR),
        help="Path to runs directory (default: external/prosperity_rust_backtester/runs)",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Actually delete duplicate runs (without this flag, dry-run only).",
    )
    args = parser.parse_args()

    runs_dir = Path(args.runs_dir)
    runs = collect_runs(runs_dir)

    dupe_groups = group_duplicates(runs)
    keep, delete = choose_keep_and_delete(dupe_groups)
    print_plan(dupe_groups, keep, delete)

    if args.apply and delete:
        apply_delete(delete)
        print()
        print(f"Deleted {len(delete)} duplicate run folders.")
    elif args.apply:
        print()
        print("Nothing deleted.")
    else:
        print()
        print("Dry-run mode only. Re-run with --apply to delete duplicates.")


if __name__ == "__main__":
    main()
