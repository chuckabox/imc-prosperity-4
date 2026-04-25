from __future__ import annotations

import itertools
import subprocess
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
KEN_DIR = REPO / "ROUND 3" / "traders" / "ken"
BASE = "ROUND 3/traders/ken/trader_ken_v75_phase_adaptive.py"


def write_variant(
    name: str,
    z_early: float,
    rel_early: float,
    size_early: float,
    z_late: float,
    rel_late: float,
    size_late: float,
) -> Path:
    p = KEN_DIR / f"{name}.py"
    p.write_text(
        f'''"""Auto-generated v75 phase sweep {name}."""
from __future__ import annotations
from trader_ken_v75_phase_adaptive import Trader as _Base


class Trader(_Base):
    VEV_Z_MULT_EARLY = {z_early}
    VEV_REL_MULT_EARLY = {rel_early}
    VEV_SIZE_MULT_EARLY = {size_early}
    VEV_Z_MULT_LATE = {z_late}
    VEV_REL_MULT_LATE = {rel_late}
    VEV_SIZE_MULT_LATE = {size_late}
''',
        encoding="utf-8",
    )
    return p


def main() -> int:
    variants = []
    i = 0
    for z_early, rel_early, size_early, z_late, rel_late, size_late in itertools.product(
        [0.90, 0.95],
        [0.90, 0.95],
        [1.00, 1.10],
        [1.00, 1.08],
        [1.00, 1.08],
        [0.85, 0.95],
    ):
        name = f"trader_ken_v75p_{i:02d}"
        fp = write_variant(name, z_early, rel_early, size_early, z_late, rel_late, size_late)
        variants.append(str(fp.relative_to(REPO)).replace("\\", "/"))
        i += 1

    cmd = [
        "python",
        "tools/compare_round3_traders.py",
        BASE,
        *variants,
    ]
    r = subprocess.run(cmd, cwd=REPO)
    return r.returncode


if __name__ == "__main__":
    raise SystemExit(main())

