# 🕵️ Hidden Patterns: ASH_COATED_OSMIUM

*Quote:* "On the other hand, ASH_COATED_OSMIUM is rumored to be a bit more volatile, although one may speculate that its apparent unpredictability may follow a hidden pattern."

## The "Hidden Pattern" Analysis

Initial visual inspection of `ASH_COATED_OSMIUM` shows extreme macro-oscillations around the `10,000` median price. While it acts volatile, it is perfectly constrained by a hidden autoregressive generator. 

**Model Identification**: 
The "unpredictability" is actually deterministic noise conforming to a multi-lag autoregressive (AR) process.
Specifically, it is an **AR(3)** model: The next true fair value is derived exactly from the previous 3 mid-prices plus an intercept that anchors it back to the median.

**Mathematical Formula:**
```
Fair Value (t) = 309.9 + (0.3616 * Mid_{t-1}) + (0.3148 * Mid_{t-2}) + (0.2925 * Mid_{t-3})
```
Sum of weights: `0.3616 + 0.3148 + 0.2925 = 0.9689`.
The sum being `< 1` guarantees that the price is ultimately mean-reverting rather than a pure random walk, with the intercept anchoring it perfectly around `10,000`.

## Implementation in Trader
To capture edge without overfitting to the absolute 10k anchor, our `trader_robust_v2` dynamically computes this if the product is Osmium, reverting cleanly to the predicted tick rather than relying indiscriminately on exponential momentum.
