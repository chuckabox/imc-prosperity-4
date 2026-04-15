import numpy as np

def manual_trade_optimizer():
    # Dryland Flax
    flax_exit = 30
    flax_asks = [(28, 40000), (31, 20000), (32, 20000), (33, 30000)]
    flax_bids = [(30, 30000), (29, 5000), (28, 12000), (27, 28000)]
    
    # Ember Mushroom
    mush_exit = 20
    mush_fee = 0.10
    mush_asks = [(12, 20000), (13, 25000), (14, 35000), (15, 6000), (16, 5000), (18, 10000), (19, 12000)]
    mush_bids = [(20, 43000), (19, 17000), (18, 6000), (17, 5000), (16, 10000), (15, 5000), (14, 10000), (13, 7000)]

    print("--- Manual Trade Scenarios ---")

    # Scenario: Expected Value against a Distribution
    # 87995.1 is very specific.
    # What if it's the result of a bidding strategy where volume is shared?
    
    # Try Mushroom Calculation with Bid Shading
    # If the crowd bids 15 on average.
    # If we bid 15, we share the volume?
    
    mush_vol_limit = 43000 # Typical cap
    
    # Let's see if 87995.1 is related to a 10,000 unit bid
    # 87995.1 / 11138.6 = 7.9 (Profit @ 12)
    # This implies we ONLY get filled on the 12s, and we only get 11,138.6 units.
    
    # Why 11,138.6? 
    # 1/9 of 100,000? No.
    
    # WAIT! 87995.1
    # 87995.1 * 1.0 = 87995.1
    
    # Is it a Poisson distribution?
    
    # Let's try every integer profit on flax + mushroom
    # 43k mushroom @ 13 = 316.7k
    # 30k flax @ 28 = 60k
    # sum = 376.7k
    
    # If the user's score 87995.1 is real, it must be higher-level math.
    # Let's check: 87995.1 / 50000 = 1.75
    
    print("No simple integer combination matches 87995.1.")
    print("Possibility: The score is based on a Logarithmic Utility function.")
    print("Maximized: sum log(1 + profit_i)")
    
    # If profit is 87995.1, what is the bid?
    # I'll check if any single product profit equals 87995.1
    
    target = 87995.1
    for p in range(12, 21):
        # Profit per unit
        unit_p = 20 - p - 0.1
        if unit_p > 0:
            vol_needed = target / unit_p
            print(f"To get {target} profit at price {p}, you need {vol_needed:.1f} units.")

manual_trade_optimizer()
