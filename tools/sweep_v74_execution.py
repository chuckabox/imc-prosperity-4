from __future__ import annotations

import itertools
import subprocess
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
KEN_DIR = REPO / "ROUND 3" / "traders" / "ken"
BASE = "ROUND 3/traders/ken/trader_ken_v74_refine_champion.py"


def write_variant(name: str, core_taker: int, spread_max: int, vfe_taker_edge: float) -> Path:
    p = KEN_DIR / f"{name}.py"
    p.write_text(
        f'''"""Auto-generated v74 execution sweep {name}."""
from __future__ import annotations
from trader_ken_v74_refine_champion import Trader as _Base


class Trader(_Base):
    VFE_TAKER_EDGE = {vfe_taker_edge}
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
    for core_taker, spread_max, vfe_taker_edge in itertools.product(
        [6, 7, 8], [6, 7, 8], [4.5, 4.8]
    ):
        name = f"trader_ken_v74e_{i:02d}"
        fp = write_variant(name, core_taker, spread_max, vfe_taker_edge)
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

