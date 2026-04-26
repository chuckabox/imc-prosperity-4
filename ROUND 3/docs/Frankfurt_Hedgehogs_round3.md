In Round 3, the competition introduced a new class of assets: Volcanic Rock Vouchers — effectively call options on a new underlying product, Volcanic Rock (VR). There were five vouchers available, each with a distinct strike price — 9500, 9750, 10000, 10250, and 10500 — while the underlying Volcanic Rock itself traded around 10,000. Each voucher granted the right (but not the obligation) to buy Volcanic Rock at the specified strike at expiry. Importantly, options had limited time to live: starting with seven days until expiry in the first round, decreasing to just two days by the final round. Without basic familiarity with options theory, particularly concepts like implied volatility and option pricing models, it would have been difficult to design strong strategies for this product.

IV Scalping
Our first major insight came from following hints dropped in the competition wiki, suggesting the construction of a volatility smile: plotting implied volatility (IV) against moneyness. By fitting a parabola to the observed IVs across strikes and then detrending (subtracting the fitted curve from observed values), we could isolate IV deviations that were no longer dependent on moneyness.

To convert these into actionable trading signals, we input the volatility-smile-implied IV into a Black-Scholes model to calculate a theoretical fair price, then compared it to the actual market price to find price deviations. Plots of these price deviations — especially for the 10,000 strike call early on — revealed sharp short-term fluctuations, indicating scalping opportunities.

We initially focused on the 10,000 strike, but dynamically expanded to include other strikes as the underlying shifted and expiry approached, tracking profitability thresholds in real time to decide when to activate scalping on new options. Statistical analysis, specifically testing for 1-lag negative autocorrelation in returns, strongly supported the existence of exploitable short-term inefficiencies across several strikes, further validating this approach.

Gamma Scalping
The expected value from gamma scalping was consistently positive, as the gains from underlying price movements outweighed the losses from time decay. This made buying options and rehedging the resulting deltas from gamma exposure a relatively low-risk way to generate profit. However, while the approach was stable and mostly safe, the absolute returns were limited. It was a reliable source of small gains, but ultimately, we had a higher risk appetite and wanted better returns.

Mean Reversion Trading
Simultaneously, analysis of the underlying Volcanic Rock asset suggested potential mean reversion behavior. Return distributions and price dynamics resembled Squid Ink, which was explicitly designed to mean revert in Round 1. Autocorrelation analysis of Volcanic Rock returns, compared against randomized normal samples, confirmed significant short-term negative autocorrelation at various horizons, although caution was needed given the presence of large jumps and non-normal return distributions. Given the limited historical data available (only three days), and uncertainty about future dynamics, fully committing to mean reversion was considered too risky. Instead, we implemented a lightweight mean reversion model: tracking a fast rolling Exponential Moving Average (EMA) and trading deviations from this EMA using fixed thresholds — without scaling by rolling volatility — to keep the model simple and robust.



In the end, we deployed a hybrid strategy combining both alpha sources. Our core focus remained on IV scalping, dynamically expanding across strikes and adjusting thresholds based on evolving conditions, while simultaneously maintaining a moderate mean reversion position — both in the underlying Volcanic Rock and in the deepest in-the-money call (the highest delta option available). Importantly, this was not a delta hedge in the traditional sense: the delta exposure from scalping was relatively small, and explicit delta hedging would have been prohibitively expensive bid-ask spreads. It was rather a hedge against bad luck. Because this hybrid model was designed to minimize maximum regret across different possible market outcomes: it protected us if strong mean reversion materialized (even if other teams aggressively leveraged mean reversion delta exposure across multiple options and therefore outperforming us in a relative sense), while keeping our core reliance on the more stable, theory-supported scalping opportunities.


# **Algorithmic trading challenge: “Options Require Decisions”**

There are 2 ‘asset classes’ in the three products you trade. The `HYDROGEL_PACK` and `VELVETFRUIT_EXTRACT` are “delta 1” products, similar to the products in the tutorial and rounds 1 and 2. The 10 `VELVETFRUIT_EXTRACT_VOUCHER` products (each with a different strike price) are options, and thus follow different dynamics. All products are traded independently, even though the price of `VELVETFRUIT_EXTRACT_VOUCHER` might be related to that of `VELVETFRUIT_EXTRACT` due to the nature of options.

The vouchers are labeled `VEV_4000`, `VEV_4500`, `VEV_5000`, `VEV_5100`, `VEV_5200`, `VEV_5300`, `VEV_5400`, `VEV_5500`, `VEV_6000`, `VEV_6500`, where VEV stands for **V**elvetfruit **E**xtract **V**oucher, and the number represents the strike price. They all have a 7-day expiration deadline starting from round 1, where each round represents 1 day. Thus, the ‘time till expiry’ (TTE) is 7 days at the start of round 1 (TTE=7d), 6 days at the start of round 2, 5 days at the start of round 3, and so on.

The position limits ([see the Position Limits page for extra context and troubleshooting](https://imc-prosperity.notion.site/writing-an-algorithm-in-python#328e8453a09380cfb53edaa112e960a9)) are:

- `HYDROGEL_PACK`: 200
- `VELVETFRUIT_EXTRACT`: 200
- `VELVETFRUIT_EXTRACT_VOUCHER`: 300 for each of the 10 vouchers.

<aside>
📃

**Example**: `VEV_5000` is an option on the underlying VEV with a strike price of 5000 and a position limit of 300. At the start of the final simulation of Round 3, its time to expiry (TTE) is 5 days. In the historical data, the corresponding TTE values are:

- TTE=8d at the start of historical day 0 (coinciding with the tutorial round),
- TTE=7d at the start of historical day 1 (coinciding with Round 1),
- TTE=6d at the start of historical day 2 (coinciding with Round 2).
</aside>

Vouchers cannot be exercised before their expiry, and inventory does not carry over into the next round. Like in previous rounds, any open positions are automatically liquidated against a hidden fair value at the end of the round.