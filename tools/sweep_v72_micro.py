from __future__ import annotations

import itertools
import subprocess
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
KEN_DIR = REPO / "ROUND 3" / "traders" / "ken"
BASE = KEN_DIR / "trader_ken_v72_stacked_alpha_champion.py"


def write_variant(name: str, micro: float, obi: float, relz: float, vfe_edge: float) -> Path:
    p = KEN_DIR / f"{name}.py"
    p.write_text(
        f'''"""Auto-generated v72 sweep {name}."""
from __future__ import annotations
from trader_ken_v72_stacked_alpha_champion import Trader as _Base


class Trader(_Base):
    VFE_MICRO_TILT = {micro}
    HP_OBI_ENTRY = {obi}
    VEV_REL_Z_ENTRY = {relz}
    VFE_TAKER_EDGE = {vfe_edge}
''',
        encoding="utf-8",
    )
    return p


def main() -> int:
    grid = {
        "micro": [0.14, 0.16, 0.18],
        "obi": [0.30, 0.34],
        "relz": [0.82, 0.90],
        "vfe_edge": [4.2, 4.5],
    }
    variants = []
    i = 0
    for micro, obi, relz, vfe_edge in itertools.product(
        grid["micro"], grid["obi"], grid["relz"], grid["vfe_edge"]
    ):
        name = f"trader_ken_v72m_{i:02d}"
        fp = write_variant(name, micro, obi, relz, vfe_edge)
        variants.append(str(fp.relative_to(REPO)).replace("\\", "/"))
        i += 1

    cmd = [
        "python",
        "tools/compare_round3_traders.py",
        str(BASE.relative_to(REPO)).replace("\\", "/"),
        *variants,
    ]
    r = subprocess.run(cmd, cwd=REPO)
    return r.returncode


if __name__ == "__main__":
    raise SystemExit(main())

