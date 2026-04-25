from __future__ import annotations

import itertools
import subprocess
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
KEN_DIR = REPO / "ROUND 3" / "traders" / "ken"
BASE = "ROUND 3/traders/ken/trader_ken_v76_execution_champion.py"


def write_variant(name: str, core_taker: int, spread_max: int, rel_z: float, z_entry: float) -> Path:
    p = KEN_DIR / f"{name}.py"
    p.write_text(
        f'''"""Auto-generated v76 local sweep {name}."""
from __future__ import annotations
from trader_ken_v76_execution_champion import Trader as _Base


class Trader(_Base):
    VEV_Z_ENTRY = {z_entry}
    VEV_REL_Z_ENTRY = {rel_z}
    VEV_TAKER_MAX_BY_STRIKE = {{
        5000: 4,
        5100: 5,
        5200: {core_taker},
        5300: {core_taker},
        5400: 4,
    }}
    VEV_SPREAD_MAX_BY_STRIKE = {{
        5000: {spread_max},
        5100: {spread_max},
        5200: {spread_max},
        5300: {spread_max},
        5400: {spread_max},
    }}
''',
        encoding="utf-8",
    )
    return p


def main() -> int:
    variants = []
    i = 0
    for core_taker, spread_max, rel_z, z_entry in itertools.product(
        [5, 6, 7], [5, 6, 7], [0.85, 0.90], [1.15, 1.20]
    ):
        name = f"trader_ken_v76l_{i:02d}"
        fp = write_variant(name, core_taker, spread_max, rel_z, z_entry)
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

