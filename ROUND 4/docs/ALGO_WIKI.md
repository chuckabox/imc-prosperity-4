For this second round of the Great Orbital Ascension Trials, the **Frontier Trade Watch** (FTW) has disclosed information about the counterparties active in the market. Their IDs have been added to the historical trade data available in the Data Capsule.

You will continue trading ***Hydrogel Packs*** (`HYDROGEL_PACK`), ***Velvetfruit Extract*** (`VELVETFRUIT_EXTRACT`), and ***10 Velvetfruit Extract Vouchers*** (`VELVETFRUIT_EXTRACT_VOUCHER`). This time, however, having insight into your counterparties, and understanding what defines their trading behavior and the unique opportunities they bring, could shift the balance for teams that know how to separate profit from pretense.

In addition to your algorithmic trading activities, you will also have the opportunity to manually trade the ***Aether Crystal***, along with ***a collection of option contracts*** based on it. Some of these contracts are more exotic than others. You must determine a strategy that turns this one-time opportunity into profit.

Be aware that these exotic options operate independently from your algorithmic trading activities.

# **Round Objective**

Optimize your Python program to trade `HYDROGEL_PACK`, `VELVETFRUIT_EXTRACT`, and `VELVETFRUIT_EXTRACT_VOUCHER`, incorporating the newly disclosed counterparty information into your strategy.

Select from the available Aether Crystal and corresponding option contracts, and submit your orders to generate additional profit.

# **Algorithmic trading challenge: “Hello, I’m Mark”**

The products are the same as in Round 3 (`HYDROGEL_PACK`, `VELVETFRUIT_EXTRACT`, and 10 `VELVETFRUIT_EXTRACT_VOUCHER` options), but now you have counterparty information available. That is, you can identify every other participant in the market and study their behavior.

In the datamodel described in [Appendix B: datamodel.py file in 💻 **Writing an Algorithm in Python**](https://www.notion.so/2a9e8453a093813cab3df6e22b7e9e7d?pvs=21), you will find the `Trade` class defined. For previous rounds 1,2,3, the `self.buyer` and `self.seller` fields were always `None` as no counterparty information was available.

**Code snippet for `class Trade`**:

```python
class Trade:
    def __init__(self, symbol: Symbol, price: int, quantity: int, buyer: UserId = None, seller: UserId = None, timestamp: int = 0) -> None:
        self.symbol = symbol
        self.price: int = price
        self.quantity: int = quantity
        self.buyer = buyer
        self.seller = seller
        self.timestamp = timestamp

    # Some methods
```

With increased transparency in the market, however, these `self.buyer` and `self.seller` fields now represent the names of the participants! Please feel free to leverage this information however you see fit, and refine your strategy using this extra visibility! 

The position limits ([see the Position Limits page for extra context and troubleshooting](https://imc-prosperity.notion.site/writing-an-algorithm-in-python#328e8453a09380cfb53edaa112e960a9)) are still

- `HYDROGEL_PACK`: 200
- `VELVETFRUIT_EXTRACT`: 200
- `VELVETFRUIT_EXTRACT_VOUCHER`: 300 for each of the 10 vouchers.

<aside>
📃

**Example** (building on the example from Round 3): `VEV_5000` is an option with strike price 5000, has TTE=4 days in round 4, and has a position limit of 300.

</aside>