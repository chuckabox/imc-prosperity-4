from __future__ import annotations

import itertools
import subprocess
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
KEN_DIR = REPO / "ROUND 3" / "traders" / "ken"


def write_variant(name: str, hp_obi: float, vev_z: float, rel_z: float) -> Path:
    p = KEN_DIR / f"{name}.py"
    p.write_text(
        f'''"""Auto-generated v73 refine sweep {name}."""
from __future__ import annotations
from trader_ken_v73_signal_depth_champion import Trader as _Base


class Trader(_Base):
    HP_OBI_ENTRY = {hp_obi}
    VEV_Z_ENTRY = {vev_z}
    VEV_REL_Z_ENTRY = {rel_z}
''',
        encoding="utf-8",
    )
    return p


def main() -> int:
    variants = []
    i = 0
    for hp_obi, vev_z, rel_z in itertools.product(
        [0.26, 0.30, 0.34], [1.20, 1.30, 1.40], [0.85, 0.90]
    ):
        name = f"trader_ken_v73r_{i:02d}"
        fp = write_variant(name, hp_obi, vev_z, rel_z)
        variants.append(str(fp.relative_to(REPO)).replace("\\", "/"))
        i += 1

    cmd = [
        "python",
        "tools/compare_round3_traders.py",
        "ROUND 3/traders/ken/trader_ken_v73_signal_depth_champion.py",
        *variants,
    ]
    r = subprocess.run(cmd, cwd=REPO)
    return r.returncode


if __name__ == "__main__":
    raise SystemExit(main())

