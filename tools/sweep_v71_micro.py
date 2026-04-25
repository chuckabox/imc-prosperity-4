from __future__ import annotations

import itertools
import re
import subprocess
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
KEN_DIR = REPO / "ROUND 3" / "traders" / "ken"
BASE_FILE = KEN_DIR / "trader_ken_v71_crossstrike_blend.py"
DATASET = "ROUND 3/data_capsule"


def write_variant(name: str, micro_tilt: float, obi_entry: float, rel_z: float) -> Path:
    dst = KEN_DIR / f"{name}.py"
    dst.write_text(
        f'''"""Auto-generated v71 micro sweep: {name}."""
from __future__ import annotations
from trader_ken_v71_crossstrike_blend import Trader as _Base


class Trader(_Base):
    VFE_MICRO_TILT = {micro_tilt}
    HP_OBI_ENTRY = {obi_entry}
    VEV_REL_Z_ENTRY = {rel_z}
''',
        encoding="utf-8",
    )
    return dst


def parse_totals(text: str) -> dict[str, int]:
    # From compare_round3_traders output line format:
    # ROUND 3/traders/...   17,159   17,366   23,091   57,616 ...
    out: dict[str, int] = {}
    for line in text.splitlines():
        if "ROUND 3/traders/ken/trader_ken_v71m_" not in line:
            continue
        nums = re.findall(r"(-?\d[\d,]*)", line)
        if len(nums) < 4:
            continue
        total = int(nums[3].replace(",", ""))
        t = line.split()[0]
        out[t] = total
    return out


def main() -> int:
    grid = {
        "micro_tilt": [0.08, 0.12, 0.16],
        "obi_entry": [0.34, 0.40],
        "rel_z": [0.90, 1.00],
    }
    variants = []
    i = 0
    for mt, oe, rz in itertools.product(grid["micro_tilt"], grid["obi_entry"], grid["rel_z"]):
        name = f"trader_ken_v71m_{i:02d}"
        fp = write_variant(name, mt, oe, rz)
        variants.append(str(fp.relative_to(REPO)).replace("\\", "/"))
        i += 1

    cmd = [
        "python",
        "tools/compare_round3_traders.py",
        str(BASE_FILE.relative_to(REPO)).replace("\\", "/"),
        *variants,
    ]
    p = subprocess.run(cmd, cwd=REPO, text=True, capture_output=True)
    print(p.stdout)
    if p.returncode != 0:
        print(p.stderr)
        return p.returncode

    totals = parse_totals(p.stdout)
    ranked = sorted(totals.items(), key=lambda kv: kv[1], reverse=True)
    print("\n=== V71 MICRO SWEEP TOP ===")
    for t, v in ranked[:8]:
        print(f"{t:65s} {v:8d}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

