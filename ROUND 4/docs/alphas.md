# Round 4 Alpha Log

This file tracks candidate alphas and status for quick iteration.

## Legend

- `NEW`: not yet tested
- `TESTING`: in backtest loop
- `KEEP`: survives robustness checks
- `DROP`: remove from production candidate

## Alpha Descriptions

**A1 — Hydrogel inventory-aware MM (status: `KEEP`)**  
This alpha focuses on `HYDROGEL_PACK` market-making around rolling fair value, with inventory skew to avoid drift. Entry/quote logic follows best bid/ask context and tries to monetize spread while keeping inventory balanced. It has been the most consistent contributor in Round 4 so far, so it remains a core alpha.

**A2 — Velvetfruit Mark-flow skew (status: `TESTING`)**  
This alpha uses `VELVETFRUIT_EXTRACT` counterparty flow (Mark IDs) to skew quotes in the expected direction of short-term pressure. The idea is good, but current implementation is conservative and under-trades. Keep testing with slightly higher participation while preserving risk limits.

**A3 — Broad VEV intrinsic-floor mispricing (status: `DROP`)**  
This alpha traded a broad range of VEV strikes using `mid - (max(VFE-K,0)+floor[K])` mispricing. In practice it overexposed mid strikes (`5000/5100/5200`) and produced unstable losses. Marked as drop for now; only reconsider with stronger strike gating and stricter risk controls.

**A4 — VEV_5400/5500 counterparty-assisted timing (status: `KEEP`)**  
This alpha narrows the VEV scope to selective strikes and uses Mark imbalance as a timing filter rather than a standalone signal. The reduced-size constrained-strike approach has been stable and complements Hydrogel alpha without reopening high-variance VEV risk.

**A5 — VFE + VEV basket hedge overlay (status: `NEW`)**  
This alpha is a hedge framework to balance VEV exposure with VFE directional drift. It is intended to smooth PnL and reduce downside during option mispricing shocks. Not enabled yet in production candidate; keep as next candidate once base alpha stack is locked.

## Guardrails

- Hard cap DD per product before widening quotes.
- Track worst-day and concentration in every batch.
- Prefer stable medium-edge alpha over high-variance spikes.

## Latest Backtest Snapshot (`table.py`)

- Dataset: `round4` (day1-day3)
- Total PnL: `+18,035.0`
- Day PnL: `D+1 +10,796.0`, `D+2 +1,074.0`, `D+3 +6,165.0`
- Main drivers: `HYDROGEL_PACK +15,164.0`, `VELVETFRUIT_EXTRACT +3,239.5`
- Minor drag: `VEV_4000 -471.5`

Tuning notes:

- Added opportunistic take-edge logic around fair value for Hydrogel and VFE.
- Added light momentum tilt to fair-value skew.
- Kept constrained VEV strike universe to avoid previous losses in 5000/5100/5200.

## Furniture Versions (for compare-later workflow)

Created trader variants:

- `ROUND 4/traders/ken/chair.py` (conservative passive MM)
- `ROUND 4/traders/ken/wardrobe.py` (flow-following)
- `ROUND 4/traders/ken/sofa.py` (mean-reversion leaning)
- `ROUND 4/traders/ken/shelf.py` (vol-protective)
- `ROUND 4/traders/ken/lamp.py` (optionality-focused)

Each furniture trader is now self-contained for IMC single-file upload compatibility.

Round 4 comparison snapshot:

- `chair.py`: D+1 `11,070.5`, D+2 `1,604.0`, D+3 `5,975.5`, TOTAL `18,650.0`.
- `wardrobe.py`: D+1 `10,268.0`, D+2 `1,295.5`, D+3 `6,182.5`, TOTAL `17,746.0`.
- `sofa.py`: D+1 `10,457.5`, D+2 `1,650.5`, D+3 `5,513.0`, TOTAL `17,621.0`.
- `shelf.py`: D+1 `10,075.5`, D+2 `1,738.0`, D+3 `8,177.5`, TOTAL `19,991.0`.
- `lamp.py`: D+1 `11,916.0`, D+2 `2,518.5`, D+3 `7,575.5`, TOTAL `22,010.0`.

Current leader by total PnL: `lamp.py`.


