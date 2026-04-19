#!/usr/bin/env python3
"""
One-shot launcher for the vendored Rust IMC backtester (like ``streamlit run tools/dashboard.py``).

From the repo root:

    python tools/run_rust_backtester.py

Override paths:

    python tools/run_rust_backtester.py --trader "ROUND 2/traders/ken/trader_ken_v6.py" --dataset "ROUND 2/data_capsule"

Pass flags through to ``rust_backtester`` (everything this script does not consume):

    python tools/run_rust_backtester.py -- --day -1

Skip rebuild if the release binary already exists:

    python tools/run_rust_backtester.py --no-build

On **Windows**, native ``cargo`` needs the **MSVC linker** (``link.exe`` from Visual Studio Build Tools). If you see
``linker link.exe not found``, either install that workload or run the build inside WSL (Rust + build-essential in Ubuntu):

    python tools/run_rust_backtester.py --use-wsl

Requires ``cargo`` on PATH (Windows host), or ``wsl`` + ``cargo`` inside the distro when using ``--use-wsl``.
"""

from __future__ import annotations

import argparse
import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
RUST_CRATE = REPO_ROOT / "external" / "prosperity_rust_backtester"


def _default_trader() -> Path:
    return REPO_ROOT / "ROUND 2" / "traders" / "ken" / "trader_ken_v6.py"


def _default_dataset() -> Path:
    return REPO_ROOT / "ROUND 2" / "data_capsule"


def _release_binary() -> Path:
    name = "rust_backtester.exe" if os.name == "nt" else "rust_backtester"
    return RUST_CRATE / "target" / "release" / name


def _release_binary_wsl_name() -> str:
    return "rust_backtester"


def _wslpath(p: Path) -> str:
    r = subprocess.run(
        ["wsl", "wslpath", "-a", p.resolve().as_posix()],
        capture_output=True,
        text=True,
        timeout=30,
    )
    if r.returncode != 0:
        raise RuntimeError(r.stderr.strip() or "wslpath failed")
    out = r.stdout.strip()
    if not out:
        raise RuntimeError("wslpath returned empty output")
    return out


def _print_windows_linker_help() -> None:
    has_wsl = shutil.which("wsl") is not None
    print(
        "\n"
        "========== Windows: MSVC linker (link.exe) not found ==========\n"
        "The default Rust toolchain on Windows is `*-pc-windows-msvc` and needs Visual Studio\n"
        "Build Tools with the **Desktop development with C++** workload (provides link.exe).\n"
        "\n"
        "Alternatives:\n"
        "  1) Install Build Tools: https://visualstudio.microsoft.com/visual-cpp-build-tools/\n"
        "  2) From this repo, run via WSL if Rust is installed inside Ubuntu:\n"
        "       python tools/run_rust_backtester.py --use-wsl\n"
        + (
            "     (`wsl` was found on PATH.)\n"
            if has_wsl
            else "     (Install WSL2 + Ubuntu, then `sudo apt install build-essential` and Rust inside WSL.)\n"
        )
        + "  3) Or switch Rust to the GNU toolchain (MinGW): `rustup default stable-x86_64-pc-windows-gnu`\n"
        + "     only if you know you have a working MinGW linker.\n"
        + "================================================================\n",
        file=sys.stderr,
        flush=True,
    )


def _run_via_wsl(
    trader: Path,
    dataset: Path,
    rust_argv: list[str],
    no_build: bool,
) -> int:
    if shutil.which("wsl") is None:
        print("ERROR: `wsl` not found on PATH. Install WSL2, or install MSVC Build Tools for native Windows builds.", file=sys.stderr)
        return 1
    try:
        wc = _wslpath(RUST_CRATE)
        wt = _wslpath(trader)
        wd = _wslpath(dataset)
    except Exception as e:
        print(f"ERROR: could not convert paths for WSL (wslpath): {e}", file=sys.stderr)
        return 1

    exe = f"./target/release/{_release_binary_wsl_name()}"
    parts: list[str] = ["set -e", f"cd {shlex.quote(wc)}"]
    if not no_build:
        parts.append("cargo build --release")
    run_cmd = [exe, "--trader", wt, "--dataset", wd, *[str(a) for a in rust_argv]]
    parts.append(shlex.join(["exec", *run_cmd]))
    inner = " && ".join(parts)
    print("Running under WSL:", inner, flush=True)
    return subprocess.run(["wsl", "-e", "bash", "-lc", inner]).returncode


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build (unless --no-build) and run external/prosperity_rust_backtester against Round 2 capsule data by default.",
    )
    parser.add_argument(
        "--trader",
        type=Path,
        default=None,
        help=f"Trader .py file (default: {_default_trader().relative_to(REPO_ROOT)})",
    )
    parser.add_argument(
        "--dataset",
        type=Path,
        default=None,
        help=f"Directory with prices_*.csv / trades_*.csv (default: {_default_dataset().relative_to(REPO_ROOT)})",
    )
    parser.add_argument(
        "--no-build",
        action="store_true",
        help="Do not run cargo build; fail if release binary is missing.",
    )
    parser.add_argument(
        "--use-wsl",
        action="store_true",
        help="On Windows, run cargo + rust_backtester inside WSL (needs Rust inside the distro).",
    )
    args, rust_argv = parser.parse_known_args()

    trader = (args.trader or _default_trader()).resolve()
    dataset = (args.dataset or _default_dataset()).resolve()

    if not RUST_CRATE.is_dir():
        print(f"ERROR: Rust crate not found: {RUST_CRATE}", file=sys.stderr)
        return 1
    if not trader.is_file():
        print(f"ERROR: Trader file not found: {trader}", file=sys.stderr)
        return 1
    if not dataset.is_dir():
        print(f"ERROR: Dataset directory not found: {dataset}", file=sys.stderr)
        return 1

    if args.use_wsl:
        if os.name != "nt":
            print("INFO: --use-wsl is only needed on Windows; running natively.", flush=True)
        else:
            return _run_via_wsl(trader, dataset, rust_argv, args.no_build)

    if shutil.which("cargo") is None:
        print("ERROR: `cargo` not found on PATH. Install Rust, or use --use-wsl on Windows with Rust in WSL.", file=sys.stderr)
        return 1

    exe = _release_binary()
    if not args.no_build:
        print("Building rust_backtester (cargo build --release) …", flush=True)
        br = subprocess.run(
            ["cargo", "build", "--release"],
            cwd=str(RUST_CRATE),
        )
        if br.returncode != 0:
            if os.name == "nt":
                _print_windows_linker_help()
            return br.returncode
    elif not exe.is_file():
        print(f"ERROR: --no-build but binary missing: {exe}", file=sys.stderr)
        return 1

    if not exe.is_file():
        print(f"ERROR: Release binary not found after build: {exe}", file=sys.stderr)
        return 1

    cmd = [str(exe), "--trader", str(trader), "--dataset", str(dataset), *rust_argv]
    print("Running:", " ".join(cmd), flush=True)
    return subprocess.run(cmd, cwd=str(RUST_CRATE)).returncode


if __name__ == "__main__":
    raise SystemExit(main())
