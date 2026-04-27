from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
BASE = ROOT / "ROUND 4" / "traders" / "ken" / "quant_scaled_shelf.py"
TMP = ROOT / "ROUND 4" / "traders" / "ken" / "_sweep"
DATASET = ROOT / "ROUND 4" / "data_capsule"


VARIANTS = [
    (14, 14, 8, 8, 4),
    (18, 18, 10, 10, 5),
    (22, 18, 12, 10, 5),
    (18, 22, 10, 12, 5),
    (22, 22, 12, 12, 6),
    (12, 12, 6, 6, 4),
    (16, 12, 8, 6, 4),
    (12, 16, 6, 8, 4),
]


def replace_once(text: str, pattern: str, repl: str) -> str:
    new_text, n = re.subn(pattern, repl, text, count=1)
    if n != 1:
        raise RuntimeError(f"failed to replace pattern: {pattern}")
    return new_text


def main() -> int:
    base_text = BASE.read_text()
    TMP.mkdir(exist_ok=True)

    for i, (hydro_clip, vfe_clip, hydro_take, vfe_take, vev_size) in enumerate(VARIANTS):
        text = base_text
        text = replace_once(text, r'"hydro_clip": \d+', f'"hydro_clip": {hydro_clip}')
        text = replace_once(text, r'"vfe_clip": \d+', f'"vfe_clip": {vfe_clip}')
        text = replace_once(text, r'"hydro_take_size": \d+', f'"hydro_take_size": {hydro_take}')
        text = replace_once(text, r'"vfe_take_size": \d+', f'"vfe_take_size": {vfe_take}')
        text = replace_once(text, r'"vev_size": \d+', f'"vev_size": {vev_size}')

        path = TMP / f"tune_{i}.py"
        path.write_text(text)

        print(f"\n=== tune_{i} {(hydro_clip, vfe_clip, hydro_take, vfe_take, vev_size)} ===")
        subprocess.run(
            [
                sys.executable,
                str(ROOT / "tools" / "run_prosperity4bt.py"),
                "--trader",
                str(path),
                "--dataset",
                str(DATASET),
                "--no-progress",
            ],
            check=False,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

