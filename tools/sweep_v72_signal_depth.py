from __future__ import annotations

import itertools
import subprocess
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
KEN_DIR = REPO / "ROUND 3" / "traders" / "ken"


def write_variant(name: str, vev_z: float, hp_obi_q: int) -> Path:
    p = KEN_DIR / f"{name}.py"
    p.write_text(
        f'''"""Auto-generated v72 signal-depth sweep {name}."""
from __future__ import annotations
from trader_ken_v72_stacked_alpha_champion import Trader as _Base


class Trader(_Base):
    HP_OBI_ENTRY = 0.30
    VEV_REL_Z_ENTRY = 0.90
    VFE_MICRO_TILT = 0.16
    VEV_Z_ENTRY = {vev_z}
    HP_OBI_TAKER_MAX = {hp_obi_q}
''',
        encoding="utf-8",
    )
    return p


def main() -> int:
    variants = []
    i = 0
    for vev_z, hp_obi_q in itertools.product([1.30, 1.40, 1.50], [3, 4, 5, 6]):
        name = f"trader_ken_v72s_{i:02d}"
        fp = write_variant(name, vev_z, hp_obi_q)
        variants.append(str(fp.relative_to(REPO)).replace("\\", "/"))
        i += 1

    cmd = [
        "python",
        "tools/compare_round3_traders.py",
        "ROUND 3/traders/ken/trader_ken_v72_stacked_alpha_champion.py",
        *variants,
    ]
    r = subprocess.run(cmd, cwd=REPO)
    return r.returncode


if __name__ == "__main__":
    raise SystemExit(main())

