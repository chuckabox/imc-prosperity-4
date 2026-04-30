"""sid/sid_oracle.py — backtester sanity check.

Hard-coded "perfect foresight" trades on MICROCHIP_TRIANGLE for day 4.
Top 200 most profitable shock-fade trades extracted from
prices_round_5_day_4.csv (lookahead 5 ticks, min move 10).

Expected total profit if backtester is honest: ~100940.

If actual backtest profit is dramatically lower, the backtester is doing
something unexpected (slippage model, partial fills, position accounting,
day mismatch). Otherwise our shock-fade strategy just doesn't have signal
on most products and TRIANGLE is one of the few that works.
"""

import json
from collections import defaultdict
from typing import Dict, List

from datamodel import Order, TradingState


PRODUCT = "MICROCHIP_TRIANGLE"

# (entry_ts, side, qty, exit_ts) tuples, sorted by entry_ts
ORACLE_TRADES = [
    (1000, 'BUY', 10, 1200),
    (1800, 'SELL', 10, 2000),
    (3200, 'SELL', 10, 3700),
    (3800, 'SELL', 10, 4000),
    (7100, 'BUY', 10, 7500),
    (12200, 'BUY', 10, 12600),
    (13800, 'BUY', 10, 14300),
    (16100, 'BUY', 10, 16600),
    (19400, 'SELL', 10, 19900),
    (20900, 'SELL', 10, 21300),
    (21400, 'BUY', 10, 21900),
    (22000, 'BUY', 10, 22500),
    (34000, 'SELL', 10, 34500),
    (34800, 'BUY', 10, 35300),
    (36500, 'SELL', 10, 37000),
    (38200, 'SELL', 10, 38600),
    (39000, 'BUY', 10, 39500),
    (40200, 'BUY', 10, 40700),
    (43400, 'BUY', 10, 43900),
    (45500, 'BUY', 10, 46000),
    (48800, 'BUY', 10, 49300),
    (49400, 'BUY', 10, 49900),
    (52700, 'SELL', 10, 53200),
    (57400, 'BUY', 10, 57800),
    (57900, 'SELL', 10, 58400),
    (61400, 'SELL', 10, 61900),
    (63500, 'SELL', 10, 64000),
    (69600, 'SELL', 10, 70100),
    (75000, 'BUY', 10, 75300),
    (89700, 'BUY', 10, 90200),
    (94400, 'BUY', 10, 94900),
    (105000, 'SELL', 10, 105200),
    (107600, 'SELL', 10, 108000),
    (108100, 'SELL', 10, 108600),
    (108700, 'SELL', 10, 109100),
    (114400, 'BUY', 10, 114900),
    (116200, 'SELL', 10, 116600),
    (120600, 'BUY', 10, 121000),
    (131600, 'SELL', 10, 132100),
    (144300, 'SELL', 10, 144600),
    (146700, 'BUY', 10, 147200),
    (152800, 'BUY', 10, 153300),
    (163500, 'BUY', 10, 163600),
    (167400, 'BUY', 10, 167900),
    (170000, 'BUY', 10, 170500),
    (171700, 'BUY', 10, 172200),
    (176300, 'BUY', 10, 176800),
    (177800, 'SELL', 10, 178200),
    (179300, 'SELL', 10, 179700),
    (183900, 'BUY', 10, 184200),
    (189800, 'SELL', 10, 190000),
    (191200, 'BUY', 10, 191700),
    (192400, 'BUY', 10, 192900),
    (194400, 'SELL', 10, 194900),
    (195000, 'SELL', 10, 195400),
    (196100, 'SELL', 10, 196600),
    (196700, 'SELL', 10, 197200),
    (198500, 'SELL', 10, 198900),
    (205600, 'BUY', 10, 206000),
    (206100, 'SELL', 10, 206500),
    (212100, 'SELL', 10, 212600),
    (216200, 'SELL', 10, 216500),
    (217500, 'BUY', 10, 217700),
    (219000, 'SELL', 10, 219500),
    (220700, 'SELL', 10, 221200),
    (231700, 'BUY', 10, 232100),
    (235300, 'SELL', 10, 235800),
    (243000, 'BUY', 10, 243500),
    (256900, 'SELL', 10, 257200),
    (257300, 'SELL', 10, 257800),
    (258500, 'SELL', 10, 258900),
    (260700, 'BUY', 10, 261000),
    (262800, 'SELL', 10, 263300),
    (268100, 'SELL', 10, 268400),
    (276700, 'SELL', 10, 277200),
    (277300, 'BUY', 10, 277800),
    (283000, 'BUY', 10, 283300),
    (290700, 'SELL', 10, 291200),
    (291600, 'BUY', 10, 292100),
    (296800, 'BUY', 10, 297300),
    (298000, 'BUY', 10, 298500),
    (310900, 'BUY', 10, 311400),
    (312400, 'BUY', 10, 312800),
    (314800, 'SELL', 10, 315300),
    (320000, 'SELL', 10, 320500),
    (333000, 'BUY', 10, 333500),
    (344500, 'BUY', 10, 344800),
    (362800, 'SELL', 10, 363300),
    (363400, 'SELL', 10, 363700),
    (364800, 'SELL', 10, 365300),
    (369000, 'BUY', 10, 369500),
    (378800, 'BUY', 10, 379300),
    (383300, 'SELL', 10, 383800),
    (392600, 'SELL', 10, 393100),
    (396100, 'SELL', 10, 396600),
    (396700, 'BUY', 10, 397200),
    (404000, 'BUY', 10, 404400),
    (405400, 'SELL', 10, 405800),
    (405900, 'BUY', 10, 406400),
    (407400, 'SELL', 10, 407900),
    (414000, 'SELL', 10, 414500),
    (439300, 'SELL', 10, 439800),
    (445400, 'BUY', 10, 445900),
    (453200, 'SELL', 10, 453700),
    (465800, 'BUY', 10, 466300),
    (467300, 'SELL', 10, 467700),
    (468000, 'BUY', 10, 468500),
    (469200, 'BUY', 10, 469700),
    (471500, 'BUY', 10, 472000),
    (475300, 'SELL', 10, 475800),
    (477300, 'SELL', 10, 477600),
    (495600, 'BUY', 10, 496100),
    (506800, 'BUY', 10, 507300),
    (513000, 'SELL', 10, 513500),
    (514800, 'BUY', 10, 515200),
    (530400, 'SELL', 10, 530700),
    (533700, 'SELL', 10, 534200),
    (535200, 'SELL', 10, 535700),
    (539100, 'SELL', 10, 539600),
    (547800, 'SELL', 10, 548200),
    (553400, 'SELL', 10, 553900),
    (564400, 'BUY', 10, 564900),
    (569700, 'BUY', 10, 570200),
    (574800, 'BUY', 10, 575300),
    (576700, 'BUY', 10, 577200),
    (580000, 'SELL', 10, 580400),
    (580500, 'SELL', 10, 580800),
    (602600, 'BUY', 10, 602900),
    (607000, 'SELL', 10, 607200),
    (623500, 'BUY', 10, 624000),
    (628700, 'BUY', 10, 629000),
    (641300, 'SELL', 10, 641700),
    (644400, 'SELL', 10, 644800),
    (650600, 'SELL', 10, 651100),
    (658500, 'SELL', 10, 659000),
    (662000, 'SELL', 10, 662500),
    (664100, 'BUY', 10, 664600),
    (665300, 'BUY', 10, 665800),
    (668700, 'SELL', 10, 669200),
    (673300, 'SELL', 10, 673600),
    (681600, 'SELL', 10, 682000),
    (683400, 'BUY', 10, 683900),
    (690200, 'SELL', 10, 690600),
    (691600, 'SELL', 10, 692100),
    (697600, 'SELL', 10, 698000),
    (702000, 'SELL', 10, 702500),
    (716400, 'SELL', 10, 716900),
    (718700, 'SELL', 10, 719200),
    (725600, 'SELL', 10, 726100),
    (728100, 'BUY', 10, 728600),
    (731300, 'BUY', 10, 731800),
    (739800, 'BUY', 10, 740300),
    (744100, 'SELL', 10, 744500),
    (747000, 'SELL', 10, 747400),
    (747500, 'SELL', 10, 747800),
    (749900, 'BUY', 10, 750300),
    (760600, 'BUY', 10, 761000),
    (766900, 'BUY', 10, 767300),
    (768000, 'BUY', 10, 768400),
    (769000, 'SELL', 10, 769500),
    (773600, 'SELL', 10, 774100),
    (778900, 'BUY', 10, 779200),
    (784500, 'SELL', 10, 784900),
    (788300, 'BUY', 10, 788800),
    (795100, 'SELL', 10, 795400),
    (806400, 'BUY', 10, 806900),
    (808100, 'BUY', 10, 808600),
    (811100, 'BUY', 10, 811600),
    (817500, 'BUY', 10, 818000),
    (818700, 'SELL', 10, 819200),
    (823500, 'SELL', 10, 824000),
    (824600, 'SELL', 10, 825100),
    (831100, 'SELL', 10, 831600),
    (840300, 'SELL', 10, 840800),
    (853000, 'BUY', 10, 853500),
    (857200, 'BUY', 10, 857700),
    (863100, 'BUY', 10, 863500),
    (866300, 'BUY', 10, 866800),
    (870600, 'SELL', 10, 871000),
    (875300, 'SELL', 10, 875800),
    (887600, 'SELL', 10, 888100),
    (889200, 'SELL', 10, 889700),
    (890800, 'BUY', 10, 891300),
    (893500, 'SELL', 10, 893800),
    (898100, 'SELL', 10, 898600),
    (901500, 'SELL', 10, 902000),
    (908100, 'BUY', 10, 908600),
    (912000, 'BUY', 10, 912500),
    (915600, 'BUY', 10, 916100),
    (921800, 'SELL', 10, 922200),
    (937200, 'BUY', 10, 937700),
    (963700, 'BUY', 10, 964200),
    (965100, 'BUY', 10, 965600),
    (966900, 'BUY', 10, 967400),
    (973100, 'SELL', 10, 973500),
    (976500, 'SELL', 10, 977000),
    (978300, 'BUY', 10, 978700),
    (982100, 'SELL', 10, 982400),
    (994300, 'BUY', 10, 994700),
    (994800, 'SELL', 10, 995100),
]


class Trader:
    def _load(self, td: str) -> Dict:
        if not td:
            return {"trade_idx": 0}
        try:
            mem = json.loads(td)
            mem.setdefault("trade_idx", 0)
            return mem
        except Exception:
            return {"trade_idx": 0}

    def _save(self, mem: Dict) -> str:
        return json.dumps(mem, separators=(",", ":"))

    def run(self, state: TradingState):
        mem = self._load(state.traderData)
        idx = mem["trade_idx"]
        ts = state.timestamp
        pos = state.position.get(PRODUCT, 0)
        result: Dict[str, List[Order]] = defaultdict(list)

        # Skip past stale trades whose exit_ts already passed.
        while idx < len(ORACLE_TRADES) and ts > ORACLE_TRADES[idx][3] and pos == 0:
            idx += 1

        if idx >= len(ORACLE_TRADES):
            mem["trade_idx"] = idx
            return dict(result), 0, self._save(mem)

        d = state.order_depths.get(PRODUCT)
        if not d or not d.buy_orders or not d.sell_orders:
            mem["trade_idx"] = idx
            return dict(result), 0, self._save(mem)
        bid = max(d.buy_orders.keys())
        ask = min(d.sell_orders.keys())

        entry_ts, side, qty, exit_ts = ORACLE_TRADES[idx]

        if pos != 0 and ts >= exit_ts:
            # Close: cross the spread to guarantee fill.
            if pos > 0:
                result[PRODUCT].append(Order(PRODUCT, bid, -pos))
            else:
                result[PRODUCT].append(Order(PRODUCT, ask, -pos))
            idx += 1
        elif pos == 0 and ts >= entry_ts and ts < exit_ts:
            if side == "BUY":
                result[PRODUCT].append(Order(PRODUCT, ask, qty))
            else:
                result[PRODUCT].append(Order(PRODUCT, bid, -qty))

        mem["trade_idx"] = idx
        return dict(result), 0, self._save(mem)
