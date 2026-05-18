from sqlalchemy import create_engine
from dotenv import load_dotenv
import os
import yfinance as yf
import pandas as pd
import ta

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")

engine = create_engine(DATABASE_URL)

tickers = [
    "BBCA.JK",
    "BBRI.JK",
    "BMRI.JK",
    "TLKM.JK",
    "ASII.JK",
    "ADRO.JK"
]

all_data = []

for ticker_name in tickers:

    ticker = yf.Ticker(ticker_name)

    df = ticker.history(period="5y")

    df = df.reset_index()

    df = df.rename(columns={
        "Date": "trade_date",
        "Open": "open_price",
        "High": "high_price",
        "Low": "low_price",
        "Close": "close_price",
        "Volume": "volume"
    })

    df["ticker"] = ticker_name
    df["ma20"] = df["close_price"].rolling(20).mean()

    df["ma50"] = df["close_price"].rolling(50).mean()

    df["rsi"] = ta.momentum.RSIIndicator(
        close=df["close_price"],
        window=14
    ).rsi()

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

final_df = pd.concat(all_data)

final_df.to_sql(
    "daily_prices",
    engine,
    if_exists="append",
    index=False
)

print("SUCCESS INSERT MULTI STOCK")