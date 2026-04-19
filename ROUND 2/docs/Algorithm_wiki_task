# Round 2 - **“Growing Your Outpost”**

It is the second trading round, and your final opportunity to reach the threshold goal of a net PnL of 200,000 XIRECs or more before the leaderboard resets for Phase 2. These first 2 rounds act as qualifiers for the final mission. Trading activity has accelerated significantly since your arrival. With you and the other outposts actively trading ***Ash-Coated Osmium*** and ***Intarian Pepper Root***, the market has become increasingly competitive and dynamic.

In this second and final trading round on Intara, you will continue trading `ASH_COATED_OSMIUM` and `INTARIAN_PEPPER_ROOT`. This time, however, you have the opportunity to gain access to additional market volume. To compete for this increased capacity, you must incorporate a ***Market Access Fee*** bid into your Python program.

Of course, you should also analyze your previous round’s performance and refine your algorithm accordingly.


# **Round Objective**

Optimize your Python program to trade `ASH_COATED_OSMIUM` and `INTARIAN_PEPPER_ROOT`, and incorporate a ***Market Access Fee*** to potentially gain access to additional market volume.

In addition to refining your trading algorithm, ***allocate your 50,000 XIRECs investment budget*** across the three growth pillars to strengthen your outpost’s performance.

# **Algorithmic trading challenge: “limited Market Access”**

[Wiki_ROUND_2_data.zip](attachment:9fa4493f-7e00-4205-a07f-e23f48b34571:Wiki_ROUND_2_data.zip)

The products `INTARIAN_PEPPER_ROOT` and `ASH_COATED_OSMIUM` are the same, but the challenge now primarily lies in deciding how much to bid for extra market access, as well as refining your algorithm. The position limits ([see the Position Limits page for extra context and troubleshooting](https://imc-prosperity.notion.site/writing-an-algorithm-in-python#328e8453a09380cfb53edaa112e960a9)) are again

- `ASH_COATED_OSMIUM`: 80
- `INTARIAN_PEPPER_ROOT`: 80

In this round, you can bid for 25% more quotes in the order book. The volumes and prices of these quotes fit perfectly in the distribution of the already available quotes. A simple example:

<aside>
📖

**Example Extra Market Access**

Order book for participants with no extra market access:
(ask, 10 volume, $9)
(ask, 10 volume, $7)
(bid, 10 volume, $5)
(bid, 5 volume, $4)

Order book for participants with *extra* market access:
(ask, 10 volume, $9)
(ask, 5 volume, $8)          <--- extra flow to trade against
(ask, 10 volume, $7)
(bid, 10 volume, $5)
(bid, 5 volume, $4)

</aside>

You bid for extra market access by incorporating a `bid()` function inside your `class Trader` implementation:

```python
class Trader:
    def bid(self):
        return 15

    def run(self, state: TradingState):
        (Implementation)
```

The Market Access Fee (MAF) is a *one-time fee* at the start of Round 2 paid *only* if your bid is accepted. It only determines who gets extra market access, and is not used in the simulation dynamics whatsoever. The top 50% of bids across all participants are accepted.

<aside>
🔨

**Example Bidding Mechanism**

Bids:           [10,   20,  15,   19,   21,   34]
Accepted:  [No, Yes, No, No, Yes, Yes]
Explanation: the median of the bids is 19.5, so all bids higher (20, 21, 34) are accepted → these participants get extra market access flow while paying the price they bid, and all bids below 19.5 are rejected (and these participants do *not* pay the fee).

</aside>

The accepted bids are subtracted from Round 2 profits to compute the final PnL. To be explicit,

<aside>
ℹ️

For those with full market access (i.e. those in the top 50% of bids),
`profit = profit from round 2 - bid for getting full market access`.

For those with no full market access,
`profit = profit from round 2`.

</aside>

The MAF is unique to Round 2, and does not apply to any other round; any `bid()` function in Rounds 1,3,4,5 is ignored. It is also ignored during testing of round 2, since bids are only compared on our end when the final simulation of Round 2 starts. In that sense, it’s a “blind auction” for extra flow.

During testing of round 2, the default set of quotes you interact with is 80% of all quotes we generated (i.e., no extra market access). This 80% has been slightly randomized for every submission to reflect real-world conditions where not all patterns in trading behavior are up 100% of the time. While you could optimize the PnL by submitting the same file many times, this has very limited payoff and your effort is much better put into improving your algorithm ;).

### **Game theory**

To get extra market access, you just need to be in the top 50% of bidders, not necessarily the highest bidder. Placing an extremely high bid will almost certainly yield full market access, but perhaps you could save (a lot of) XIRECs by bidding less while staying in the top 50% of bidders.