import pandas as pd
from sqlalchemy import create_engine

# ======================
# CONFIG
# ======================

TICKER = "ANTM.JK"
YEAR = 2026

engine = create_engine("sqlite:///data/market.db")

# ======================
# LOAD PRICE
# ======================

prices = pd.read_sql(
    f"""
    SELECT trade_date, close_price
    FROM daily_prices
    WHERE ticker = '{TICKER}'
    ORDER BY trade_date
    """,
    engine
)

prices["trade_date"] = pd.to_datetime(prices["trade_date"])
prices = prices[
    prices["trade_date"] >= f"{YEAR}-01-01"
].copy()

prices["return_h1"] = (
    prices["close_price"].shift(-1)
    / prices["close_price"]
    - 1
) * 100

prices = prices.dropna(subset=["return_h1"])

# ======================
# BASELINE
# ======================

total_days = len(prices)

win_days = (prices["return_h1"] > 0).sum()

lose_days = (prices["return_h1"] <= 0).sum()

win_rate = win_days / total_days * 100

avg_return = prices["return_h1"].mean()

median_return = prices["return_h1"].median()

best_return = prices["return_h1"].max()

worst_return = prices["return_h1"].min()

print("\n==============================")
print(f"{TICKER} BASELINE {YEAR}")
print("==============================")

print(f"Trading Days : {total_days}")
print(f"Win Days     : {win_days}")
print(f"Lose Days    : {lose_days}")
print(f"Win Rate     : {win_rate:.2f}%")
print(f"Avg Return   : {avg_return:.2f}%")
print(f"Median       : {median_return:.2f}%")
print(f"Best Day     : {best_return:.2f}%")
print(f"Worst Day    : {worst_return:.2f}%")