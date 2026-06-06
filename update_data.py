from sqlalchemy import create_engine
import pandas as pd
import yfinance as yf
import ta

# ======================
# SQLITE DATABASE
# ======================

engine = create_engine(
    "sqlite:///data/market.db"
)

# ======================
# 2. Load ticker dari mapping
# ======================
mapping_df = pd.read_csv(
    "data/stock_mapping.csv"
)

mapping_df.columns = (
    mapping_df.columns
    .str.strip()
    .str.lower()
)

tickers = (
    mapping_df["ticker"]
    .dropna()
    .unique()
    .tolist()
)

tickers = [
    t if t.endswith(".JK")
    else t + ".JK"
    for t in tickers
]

# ======================
# 3. Download data
# ======================
all_data = []

for ticker_name in tickers:

    print(f"DOWNLOAD {ticker_name}")

    df = yf.download(
        ticker_name,
        period="max",
        auto_adjust=False,
        progress=False
    )

    if ticker_name == "ANTM.JK":

        print(df.loc[
        "2012-09-01":"2012-10-01"
        ][["Close"]])

        exit()

    if df.empty:
        continue

    df = df.reset_index()

    df.columns = [
        c[0] if isinstance(c, tuple) else c
        for c in df.columns
    ]

    df.columns = [
        str(c).lower().replace(" ", "_")
        for c in df.columns
    ]

    df = df[[
        "date",
        "open",
        "high",
        "low",
        "close",
        "volume"
    ]].copy()

    df["ticker"] = ticker_name

    all_data.append(df)

# ======================
# 4. Gabung data
# ======================
    final_df = pd.concat(
    all_data,
    ignore_index=True
)

# ======================
# 5. Rename kolom
# ======================
final_df = final_df.rename(
    columns={
        "date": "trade_date",
        "open": "open_price",
        "high": "high_price",
        "low": "low_price",
        "close": "close_price",
        "volume": "volume"
    }
)
    
# ======================
# 6. Hitung indikator
# ======================
result = []

for ticker_name, df in final_df.groupby("ticker"):

    df = df.sort_values(
        "trade_date"
    )

    df["ma20"] = (
        df["close_price"]
        .rolling(20)
        .mean()
    )

    df["ma50"] = (
        df["close_price"]
        .rolling(50)
        .mean()
    )

    df["rsi"] = ta.momentum.RSIIndicator(
        close=df["close_price"],
        window=14
    ).rsi()

    result.append(df)

final_df = pd.concat(
    result,
    ignore_index=True
)

# ======================
# 7. Simpan ke SQLite
# ======================
final_df.to_sql(
    "daily_prices",
    engine,
    if_exists="replace",
    index=False
)

# ======================
# 8. Buat latest_snapshot
# ======================
latest_snapshot = (
    final_df
    .sort_values("trade_date")
    .groupby("ticker")
    .tail(1)
)

latest_snapshot["ma_distance"] = (
    (
        latest_snapshot["close_price"]
        - latest_snapshot["ma20"]
    )
    /
    latest_snapshot["ma20"]
) * 100

latest_snapshot["is_bullish"] = (
    latest_snapshot["close_price"]
    > latest_snapshot["ma50"]
)

latest_snapshot["is_oversold"] = (
    latest_snapshot["rsi"]
    < 30
)

latest_snapshot["is_golden_cross"] = (
    latest_snapshot["ma20"]
    > latest_snapshot["ma50"]
)

# ======================
# 9. Simpan latest_snapshot
# ======================
latest_snapshot.to_sql(
    "latest_snapshot",
    engine,
    if_exists="replace",
    index=False
)
# ======================
# 10. Tambah index SQLite
# ======================
from sqlalchemy import text

with engine.begin() as conn:

    conn.execute(
        text("""
        CREATE INDEX IF NOT EXISTS idx_ticker
        ON daily_prices(ticker)
        """)
    )

    conn.execute(
        text("""
        CREATE INDEX IF NOT EXISTS idx_trade_date
        ON daily_prices(trade_date)
        """)
    )