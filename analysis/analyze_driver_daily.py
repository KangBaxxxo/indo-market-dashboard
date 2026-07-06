# ==========================================================
# DRIVER DAILY ANALYSIS
# SECTION 1
# LOAD MASTER DATAFRAME
# ==========================================================

import sqlite3
from pathlib import Path

import pandas as pd

# ==========================================================
# CONFIG
# ==========================================================

DB_PATH = Path("data/market.db")
DRIVER_PATH = Path("data/driver_prices.csv")

START_DATE = "2026-01-01"

DRIVER = "GOLD"

TICKERS = [
    "ANTM.JK",
    "HRTA.JK",
    "MDKA.JK",
    "BRMS.JK",
    "ARCI.JK",
]

# ==========================================================
# HELPER
# ==========================================================

def calculate_return(df, price_col, group_col=None):

    if group_col is None:
        return df[price_col].pct_change() * 100

    return (
        df.groupby(group_col)[price_col]
        .pct_change() * 100
    )


# ==========================================================
# LOAD DRIVER
# ==========================================================

driver = pd.read_csv(
    DRIVER_PATH,
    parse_dates=["driver_date"]
)

driver = driver[
    driver["driver"] == DRIVER
].copy()

driver = driver.sort_values("driver_date")

driver["GOLD"] = calculate_return(
    driver,
    "value"
)

driver = driver[
    ["driver_date", "GOLD"]
]

driver = driver.rename(
    columns={
        "driver_date": "trade_date"
    }
)

# ==========================================================
# LOAD STOCKS
# ==========================================================

conn = sqlite3.connect(DB_PATH)

placeholders = ",".join(["?"] * len(TICKERS))

sql = f"""
SELECT
    trade_date,
    ticker,
    close_price
FROM daily_prices
WHERE ticker IN ({placeholders})
"""

stocks = pd.read_sql(
    sql,
    conn,
    params=TICKERS,
    parse_dates=["trade_date"]
)

conn.close()

stocks = stocks.sort_values(
    ["ticker", "trade_date"]
)

stocks["daily_return"] = calculate_return(
    stocks,
    "close_price",
    "ticker"
)

stocks = (
    stocks
    .pivot(
        index="trade_date",
        columns="ticker",
        values="daily_return"
    )
    .reset_index()
)

# ==========================================================
# MERGE
# ==========================================================

master_df = (
    driver.merge(
        stocks,
        on="trade_date",
        how="inner"
    )
)

master_df = master_df[
    master_df["trade_date"] >= START_DATE
]

master_df = master_df.dropna()

master_df = master_df.sort_values(
    "trade_date"
).reset_index(drop=True)

print()

print(master_df.corr(numeric_only=True).round(3))

# ==========================================================
# SUMMARY
# ==========================================================

print("=" * 70)
print("MASTER DATA")
print("=" * 70)

print()

print(f"Rows : {len(master_df):,}")

print(
    "Period :",
    master_df.trade_date.min().date(),
    "~",
    master_df.trade_date.max().date()
)

print()

print(master_df.columns.tolist())

print()

print(master_df.head(10))

print()

print(master_df.describe())