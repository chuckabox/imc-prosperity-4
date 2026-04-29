# Round 5 Alpha Sweep

Sweep outputs:
- Full grid results: `ROUND 5/scratch/round5_alpha_sweep.csv`
- Top ranked by alpha score: `ROUND 5/scratch/round5_alpha_sweep_top25.json`
- Robust-only positive sets: `ROUND 5/scratch/round5_alpha_sweep_robust.csv`

## Ranking metric
- 45% day3 first 10% alpha edge (mid-to-mid, per unit)
- 20% day2 full alpha edge
- 20% day3 full alpha edge
- 15% day4 full alpha edge

## Important interpretation
- Pure top-ranked score can overfit one slice (day3 first 10%).
- For production candidates, prefer the **robust set** where all day-level alpha edges are positive.
- Under this filter, the sweep strongly favors **reversal after large one-tick shock**.

## Robust winners (recommended starting points)
1. `reversal` threshold=8 hold=3  
   - alpha score: 0.2264  
   - day3 first 10% alpha edge/unit: 0.2861  
   - day2/day3/day4 alpha edges: 0.0891 / 0.1533 / 0.3274
2. `reversal` threshold=8 hold=1  
   - alpha score: 0.1949  
   - day3 first 10% alpha edge/unit: 0.1784  
   - day2/day3/day4 alpha edges: 0.1258 / 0.1657 / 0.3758
3. `reversal` threshold=8 hold=2  
   - alpha score: 0.1871  
   - day3 first 10% alpha edge/unit: 0.2483  
   - day2/day3/day4 alpha edges: 0.0821 / 0.1912 / 0.1378

## Execution note
- Even when alpha edge is positive, crossing spread both entry+exit can still make naive strategy PnL negative.
- Use this sweep to choose signal families/thresholds, then layer execution logic (passive entry, smarter exits, inventory constraints).
