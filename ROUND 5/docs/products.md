# Round 5 — Products

## What sid_oracle trades

[sid_oracle.py](../traders/sid/sid_oracle.py) trades **exactly one product**:

- **`MICROCHIP_TRIANGLE`** — hard-coded perfect-foresight oracle (top 200 most-profitable shock-fade trades on day 4, lookahead 5 ticks, min move 10). Used as a backtester sanity check, not a real strategy. Expected PnL ~100,940 if the matcher is honest.

## Full Round 5 universe (50 products)

Pulled from the data capsule price CSVs at [external/imc-prosperity-4-backtester/prosperity4bt/resources/round5/](../../external/imc-prosperity-4-backtester/prosperity4bt/resources/round5/). All three days (2, 3, 4) share the same 50 symbols. Position limit per backtester `constants.py` is **10** for every symbol below.

### Pebbles family (5)
- `PEBBLES_XS`
- `PEBBLES_S`
- `PEBBLES_M`
- `PEBBLES_L`
- `PEBBLES_XL`

### Microchip family (5)
- `MICROCHIP_CIRCLE`
- `MICROCHIP_OVAL`
- `MICROCHIP_RECTANGLE`
- `MICROCHIP_SQUARE`
- `MICROCHIP_TRIANGLE`

### Galaxy Sounds (5)
- `GALAXY_SOUNDS_BLACK_HOLES`
- `GALAXY_SOUNDS_DARK_MATTER`
- `GALAXY_SOUNDS_PLANETARY_RINGS`
- `GALAXY_SOUNDS_SOLAR_FLAMES`
- `GALAXY_SOUNDS_SOLAR_WINDS`

### Sleep Pods (5)
- `SLEEP_POD_COTTON`
- `SLEEP_POD_LAMB_WOOL`
- `SLEEP_POD_NYLON`
- `SLEEP_POD_POLYESTER`
- `SLEEP_POD_SUEDE`

### Robots (5)
- `ROBOT_DISHES`
- `ROBOT_IRONING`
- `ROBOT_LAUNDRY`
- `ROBOT_MOPPING`
- `ROBOT_VACUUMING`

### UV Visors (5)
- `UV_VISOR_AMBER`
- `UV_VISOR_MAGENTA`
- `UV_VISOR_ORANGE`
- `UV_VISOR_RED`
- `UV_VISOR_YELLOW`

### Translators (5)
- `TRANSLATOR_ASTRO_BLACK`
- `TRANSLATOR_ECLIPSE_CHARCOAL`
- `TRANSLATOR_GRAPHITE_MIST`
- `TRANSLATOR_SPACE_GRAY`
- `TRANSLATOR_VOID_BLUE`

### Panels (5)
- `PANEL_1X2`
- `PANEL_1X4`
- `PANEL_2X2`
- `PANEL_2X4`
- `PANEL_4X4`

### Oxygen Shakes (5)
- `OXYGEN_SHAKE_CHOCOLATE`
- `OXYGEN_SHAKE_EVENING_BREATH`
- `OXYGEN_SHAKE_GARLIC`
- `OXYGEN_SHAKE_MINT`
- `OXYGEN_SHAKE_MORNING_BREATH`

### Snackpacks (5)
- `SNACKPACK_CHOCOLATE`
- `SNACKPACK_PISTACHIO`
- `SNACKPACK_RASPBERRY`
- `SNACKPACK_STRAWBERRY`
- `SNACKPACK_VANILLA`

## Coverage gap

`sid_oracle.py` exercises 1/50 = **2%** of the available universe. Any general-purpose trader (e.g. `peter/answer2.py`, `adin/Blue.py`) that ignores 49 of these products is leaving the rest of the order book untouched. Worth noting when comparing PnL — universal MM strategies cover all 50, while shock-fade strategies typically pick a handful.
