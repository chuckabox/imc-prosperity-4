"""Serve visualizer and expose APIs for loading and managing visualizer data."""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from build_live_comparison import write_live_data_js
from build_i4bt_comparison import write_i4bt_data_js


class VisualizerHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, repo_root: Path, **kwargs):
        self.repo_root = repo_root
        super().__init__(*args, directory=str(repo_root), **kwargs)

    def _json(self, payload: dict, status: int = 200) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")
        self.end_headers()
        self.wfile.write(body)

    def end_headers(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path
        # Prevent stale UI/data after refetch; always validate with fresh fetch.
        if path.endswith("visualizer.html") or path.endswith("backtest_comparison.js") or path.endswith("live_comparison.js") or path.endswith("i4bt_comparison.js"):
            self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
            self.send_header("Pragma", "no-cache")
            self.send_header("Expires", "0")
        super().end_headers()

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path == "/api/load-data":
            self._handle_load_data()
            return
        if parsed.path == "/api/remove-runs":
            self._handle_remove_runs()
            return
        self.send_error(HTTPStatus.NOT_FOUND)

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path == "/api/load-data":
            self._handle_load_data()
            return
        super().do_GET()

    def _handle_load_data(self) -> None:
        try:
            backtest_rebuild = self._rebuild_backtest_dataset()
            backtest_cleanup = self._clean_backtest_dataset()
            live_cleanup = self._clean_live_logs()
            live_stats = write_live_data_js(self.repo_root, "live_comparison.js")
            i4bt_stats = write_i4bt_data_js("i4bt_comparison.js")
            result = {
                "ok": True,
                "backtest_rebuild": backtest_rebuild,
                "backtest_cleanup": backtest_cleanup,
                "live_cleanup": live_cleanup,
                "live": live_stats,
                "i4bt": i4bt_stats,
            }
            backtest_path = self.repo_root / "backtest_comparison.js"
            if backtest_path.exists():
                result["backtest"] = {"saved": str(backtest_path)}
            self._json(result, 200)
        except Exception as exc:
            self._json({"ok": False, "error": str(exc)}, 500)

    def _rebuild_backtest_dataset(self) -> dict:
        parser_script = self.repo_root / "tools" / "parse_runs.py"
        if not parser_script.exists():
            return {"ok": False, "skipped": True, "reason": "tools/parse_runs.py not found"}
        proc = subprocess.run(
            [sys.executable, str(parser_script)],
            cwd=str(self.repo_root),
            capture_output=True,
            text=True,
            check=False,
        )
        return {
            "ok": proc.returncode == 0,
            "return_code": proc.returncode,
            "stdout": (proc.stdout or "").strip(),
            "stderr": (proc.stderr or "").strip(),
        }

    @staticmethod
    def _run_id_score(run_id: str) -> int:
        digits = "".join(ch for ch in str(run_id) if ch.isdigit())
        if len(digits) < 6:
            return 0
        try:
            return int(digits)
        except Exception:
            return 0

    def _clean_backtest_dataset(self) -> dict:
        path = self.repo_root / "backtest_comparison.js"
        if not path.exists():
            return {"backtest_exists": False}
        prefix, data = self._parse_js_assignment(path)
        before = len(data)
        buckets: dict[str, list[tuple[str, dict]]] = {}
        for run_id, rec in data.items():
            if not isinstance(rec, dict):
                continue
            fp = json.dumps(
                {
                    "trader": rec.get("trader"),
                    "round": rec.get("round"),
                    "day": rec.get("day"),
                    "dataset": rec.get("dataset"),
                    "pnl": round(float(rec.get("final_pnl", 0.0)), 2),
                    "by_prod": rec.get("final_pnl_by_product", {}),
                },
                sort_keys=True,
                separators=(",", ":"),
            )
            buckets.setdefault(fp, []).append((run_id, rec))

        deduped: dict[str, dict] = {}
        removed_ids: list[str] = []
        for items in buckets.values():
            items_sorted = sorted(items, key=lambda x: self._run_id_score(x[0]), reverse=True)
            keep_id, keep_rec = items_sorted[0]
            deduped[keep_id] = keep_rec
            for rid, _ in items_sorted[1:]:
                removed_ids.append(rid)

        # Also dedupe per-run history lines if repeated.
        history_rows_removed = 0
        for rec in deduped.values():
            hist = rec.get("history")
            if not isinstance(hist, list):
                continue
            seen = set()
            clean_hist = []
            for row in hist:
                key = json.dumps(row, sort_keys=True, separators=(",", ":"))
                if key in seen:
                    history_rows_removed += 1
                    continue
                seen.add(key)
                clean_hist.append(row)
            rec["history"] = clean_hist

        if len(deduped) != before or history_rows_removed > 0:
            self._write_js_assignment(path, prefix, deduped)
        return {
            "backtest_exists": True,
            "runs_before": before,
            "runs_after": len(deduped),
            "duplicate_runs_removed": max(0, before - len(deduped)),
            "history_rows_removed": history_rows_removed,
            "removed_run_ids_sample": removed_ids[:10],
            "saved": str(path),
        }

    def _remove_backtest_artifacts(self, run_ids: list[str]) -> dict:
        # Best-effort cleanup of exported per-run artifacts.
        candidate_dirs = [
            self.repo_root / "tools" / "out",
            self.repo_root / "tools" / "backtests",
            self.repo_root / "backtests",
            self.repo_root / "ROUND 3",
            self.repo_root / "ROUND 4",
            self.repo_root / "ROUND 5",
        ]
        removed = 0
        for rid in run_ids:
            rid = str(rid)
            if not rid:
                continue
            for d in candidate_dirs:
                if not d.exists() or not d.is_dir():
                    continue
                for p in d.rglob(f"*{rid}*"):
                    try:
                        if p.is_file():
                            p.unlink()
                            removed += 1
                    except Exception:
                        continue
        return {"removed_files": removed}

    @staticmethod
    def _dedupe_activities_log(raw: str) -> tuple[str, bool]:
        lines = [ln for ln in raw.splitlines() if ln.strip()]
        if not lines:
            return raw, False
        header = lines[0]
        data_lines = lines[1:]
        seen = set()
        deduped = []
        for line in data_lines:
            if line in seen:
                continue
            seen.add(line)
            deduped.append(line)
        rebuilt = "\n".join([header] + deduped)
        return rebuilt, rebuilt != raw

    @staticmethod
    def _dedupe_trade_history(trades) -> tuple[list, bool]:
        if not isinstance(trades, list):
            return trades, False
        seen = set()
        deduped = []
        changed = False
        for trade in trades:
            key = json.dumps(trade, sort_keys=True, separators=(",", ":"))
            if key in seen:
                changed = True
                continue
            seen.add(key)
            deduped.append(trade)
        return deduped, changed

    def _clean_live_logs(self) -> dict:
        json_paths = sorted(self.repo_root.glob("ROUND */live_logs/**/*.json"))
        cleaned_files = 0
        deduped_activity_lines = 0
        deduped_trades = 0
        for path in json_paths:
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                continue
            changed = False

            raw_activities = str(payload.get("activitiesLog", ""))
            if raw_activities:
                before_count = max(0, len([ln for ln in raw_activities.splitlines() if ln.strip()]) - 1)
                rebuilt, did_change = self._dedupe_activities_log(raw_activities)
                if did_change:
                    after_count = max(0, len([ln for ln in rebuilt.splitlines() if ln.strip()]) - 1)
                    deduped_activity_lines += max(0, before_count - after_count)
                    payload["activitiesLog"] = rebuilt
                    changed = True

            trades = payload.get("tradeHistory")
            deduped_trades_list, trades_changed = self._dedupe_trade_history(trades)
            if trades_changed:
                deduped_trades += max(0, len(trades) - len(deduped_trades_list))
                payload["tradeHistory"] = deduped_trades_list
                changed = True

            if changed:
                path.write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")
                cleaned_files += 1

        return {
            "json_files_scanned": len(json_paths),
            "json_files_rewritten": cleaned_files,
            "activity_lines_removed": deduped_activity_lines,
            "trade_history_rows_removed": deduped_trades,
        }

    def _parse_js_assignment(self, path: Path) -> tuple[str, dict]:
        text = path.read_text(encoding="utf-8")
        eq_idx = text.find("=")
        if eq_idx == -1:
            raise ValueError(f"Missing assignment in {path.name}")
        prefix = text[: eq_idx + 1]
        json_start = text.find("{", eq_idx)
        if json_start == -1:
            raise ValueError(f"Missing JSON object start in {path.name}")
        json_end = text.rfind("};")
        if json_end == -1:
            json_end = text.rfind("}")
        if json_end == -1 or json_end <= json_start:
            raise ValueError(f"Missing JSON object end in {path.name}")
        data = json.loads(text[json_start : json_end + 1])
        return prefix, data

    def _write_js_assignment(self, path: Path, prefix: str, data: dict) -> None:
        payload = json.dumps(data, separators=(",", ":"))
        path.write_text(f"{prefix} {payload};\n", encoding="utf-8")

    def _handle_remove_runs(self) -> None:
        try:
            length = int(self.headers.get("Content-Length", "0"))
            body = self.rfile.read(length) if length > 0 else b"{}"
            payload = json.loads(body.decode("utf-8"))
            source = str(payload.get("source", ""))
            run_ids = payload.get("run_ids", [])
            if source not in {"backtest", "live"}:
                self._json({"ok": False, "error": "source must be backtest or live"}, 400)
                return
            if not isinstance(run_ids, list):
                self._json({"ok": False, "error": "run_ids must be a list"}, 400)
                return

            target_file = self.repo_root / ("backtest_comparison.js" if source == "backtest" else "live_comparison.js")
            if not target_file.exists():
                self._json({"ok": False, "error": f"{target_file.name} not found"}, 404)
                return
            prefix, data = self._parse_js_assignment(target_file)
            before = len(data)

            removed_files = 0
            if source == "live":
                # Remove selected underlying live log files from disk too.
                for run_id in run_ids:
                    rec = data.get(run_id)
                    if not isinstance(rec, dict):
                        continue
                    rel = rec.get("log_file")
                    if not isinstance(rel, str) or not rel.strip():
                        continue
                    p = (self.repo_root / rel).resolve()
                    try:
                        p.relative_to(self.repo_root.resolve())
                    except Exception:
                        continue
                    if p.exists() and p.is_file():
                        p.unlink()
                        removed_files += 1
                    # Also remove sibling portal artifacts with same stem
                    # (e.g. remove .json and .log together) so refetch does not
                    # resurrect the run from the remaining sibling file.
                    stem = p.stem
                    parent = p.parent
                    for ext in (".json", ".log"):
                        sib = parent / f"{stem}{ext}"
                        if sib == p:
                            continue
                        if sib.exists() and sib.is_file():
                            sib.unlink()
                            removed_files += 1

            for run_id in run_ids:
                if isinstance(run_id, str):
                    data.pop(run_id, None)
            removed = before - len(data)
            self._write_js_assignment(target_file, prefix, data)
            if source == "live":
                cleanup_stats = self._clean_live_logs()
                rebuild_stats = write_live_data_js(self.repo_root, "live_comparison.js")
                self._json(
                    {
                        "ok": True,
                        "removed": removed,
                        "removed_files": removed_files,
                        "saved": str(self.repo_root / "live_comparison.js"),
                        "live_cleanup": cleanup_stats,
                        "live_rebuild": rebuild_stats,
                    },
                    200,
                )
                return
            artifact_stats = self._remove_backtest_artifacts([str(x) for x in run_ids if isinstance(x, str)])
            backtest_cleanup = self._clean_backtest_dataset()
            self._json(
                {
                    "ok": True,
                    "removed": removed,
                    "saved": str(target_file),
                    "backtest_artifacts": artifact_stats,
                    "backtest_cleanup": backtest_cleanup,
                },
                200,
            )
        except Exception as exc:
            self._json({"ok": False, "error": str(exc)}, 500)


def make_handler(repo_root: Path):
    def _factory(*args, **kwargs):
        return VisualizerHandler(*args, repo_root=repo_root, **kwargs)

    return _factory


def main() -> None:
    ap = argparse.ArgumentParser(description="Run visualizer server with load-data API.")
    ap.add_argument("--repo-root", default=".", help="Repository root")
    ap.add_argument("--host", default="127.0.0.1", help="Server host")
    ap.add_argument("--port", type=int, default=8765, help="Server port")
    args = ap.parse_args()

    repo_root = Path(args.repo_root).resolve()
    httpd = ThreadingHTTPServer((args.host, args.port), make_handler(repo_root))
    print(f"Serving: http://{args.host}:{args.port}/visualizer.html")
    print("Load API: GET|POST /api/load-data")
    print("Remove API: POST /api/remove-runs")
    httpd.serve_forever()


if __name__ == "__main__":
    main()
