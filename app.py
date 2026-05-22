from sqlalchemy import create_engine
from dotenv import load_dotenv
import os
import yfinance as yf
import pandas as pd
import ta

# =========================
# LOAD ENV
# =========================

load_dotenv()

DATABASE_URL = os.getenv(
    "DATABASE_URL"
)

engine = create_engine(
    DATABASE_URL
)

# =========================
# LOAD MASTER DATA
# =========================

master_df = pd.read_csv(
    "data/stock_master.csv"
)

# AMBIL TICKER DARI CSV

tickers = master_df[
    "ticker"
].tolist()

# =========================
# DOWNLOAD DATA
# =========================

all_data = []

for ticker_name in tickers:

    print(
        f"DOWNLOAD: {ticker_name}"
    )

    ticker = yf.Ticker(
        ticker_name
    )

    df = ticker.history(
        period="5y"
    )

    # SKIP JIKA KOSONG

    if df.empty:

        print(
            f"NO DATA: {ticker_name}"
        )

        continue

    # RESET INDEX

    df = df.reset_index()

    # RENAME COLUMN

    df = df.rename(columns={
        "Date": "trade_date",
        "Open": "open_price",
        "High": "high_price",
        "Low": "low_price",
        "Close": "close_price",
        "Volume": "volume"
    })

    # ADD TICKER

    df["ticker"] = ticker_name

    # =========================
    # TECHNICAL INDICATORS
    # =========================

    # MA20

    df["ma20"] = df[
        "close_price"
    ].rolling(20).mean()

    # MA50

    df["ma50"] = df[
        "close_price"
    ].rolling(50).mean()

    # RSI

    df["rsi"] = ta.momentum.RSIIndicator(
        close=df["close_price"],
        window=14
    ).rsi()

    # =========================
    # SELECT COLUMN
    # =========================

    df = df[
        [
            "ticker",
            "trade_date",
            "open_price",
            "high_price",
            "low_price",
            "close_price",
            "volume",
            "ma20",
            "ma50",
            "rsi"
        ]
    ]

    all_data.append(df)

# =========================
# CONCAT ALL DATA
# =========================

final_df = pd.concat(
    all_data
)

# =========================
# FIX TIMEZONE
# =========================

final_df["trade_date"] = pd.to_datetime(
    final_df["trade_date"]
).dt.tz_localize(None)

# =========================
# MERGE MASTER DATA
# =========================

final_df = final_df.merge(
    master_df,
    on="ticker",
    how="left"
)

# =========================
# INSERT TO DATABASE
# =========================

final_df.to_sql(
    "daily_prices",
    engine,
    if_exists="append",
    index=False
)

# =========================
# VALIDATION
# =========================

check_df = pd.read_sql(
    """
    SELECT
        MAX(trade_date) as max_date
    FROM daily_prices
    """,
    engine
)

print(check_df)

print(
    final_df.tail()
)

print(
    "SUCCESS INSERT MULTI STOCK"
)