import pandas as pd
import yfinance as yf
from sqlalchemy import create_engine, text
from pathlib import Path

Path("data").mkdir(exist_ok=True)

engine = create_engine("sqlite:///data/market.db")

GOLD_WATCHLIST = [
    "HRTA.JK",
    "MDKA.JK",
    "ANTM.JK",
    "BRMS.JK",
    "EMAS.JK",
]


def flatten_yfinance_columns(df, ticker):
    """
    yfinance kadang return MultiIndex:
    Price      Close High Low Open Volume
    Ticker     HRTA.JK ...
    """
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [
            col[0] if col[0] else col[-1]
            for col in df.columns
        ]

    df = df.reset_index()

    rename_map = {
        "Date": "trade_date",
        "Open": "open_price",
        "High": "high_price",
        "Low": "low_price",
        "Close": "close_price",
        "Volume": "volume",
    }

    df = df.rename(columns=rename_map)

    required_cols = [
        "trade_date",
        "open_price",
        "high_price",
        "low_price",
        "close_price",
        "volume",
    ]

    missing_cols = [
        col for col in required_cols
        if col not in df.columns
    ]

    if missing_cols:
        raise ValueError(
            f"{ticker} missing columns: {missing_cols}. "
            f"Available columns: {df.columns.tolist()}"
        )

    df = df[required_cols].copy()
    df["ticker"] = ticker

    df["trade_date"] = pd.to_datetime(
        df["trade_date"],
        errors="coerce"
    )

    for col in [
        "open_price",
        "high_price",
        "low_price",
        "close_price",
        "volume",
    ]:
        df[col] = pd.to_numeric(
            df[col],
            errors="coerce"
        )

    df = df.dropna(
        subset=["trade_date", "close_price"]
    ).copy()

    df["trade_date"] = df["trade_date"].dt.strftime("%Y-%m-%d")

    df = df[
        [
            "trade_date",
            "open_price",
            "high_price",
            "low_price",
            "close_price",
            "volume",
            "ticker",
        ]
    ].copy()

    return df


def compute_rsi(series, period=14):
    delta = series.diff()

    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)

    avg_gain = gain.rolling(period).mean()
    avg_loss = loss.rolling(period).mean()

    rs = avg_gain / avg_loss

    rsi = 100 - (100 / (1 + rs))

    return rsi


def update_indicators_for_ticker(ticker):
    df = pd.read_sql(
        """
        SELECT
            trade_date,
            open_price,
            high_price,
            low_price,
            close_price,
            volume,
            ticker
        FROM daily_prices
        WHERE ticker = ?
        ORDER BY DATE(trade_date)
        """,
        engine,
        params=(ticker,)
    )

    if df.empty:
        print(f"SKIP indicator: no data for {ticker}")
        return

    df["trade_date"] = pd.to_datetime(
        df["trade_date"],
        format="mixed",
        errors="coerce"
    )

    df = df.dropna(subset=["trade_date"]).copy()
    df = df.sort_values("trade_date").reset_index(drop=True)

    df["ma20"] = df["close_price"].rolling(20).mean()
    df["ma50"] = df["close_price"].rolling(50).mean()
    df["rsi"] = compute_rsi(df["close_price"], 14)

    df["trade_date"] = df["trade_date"].dt.strftime("%Y-%m-%d")

    with engine.begin() as conn:
        conn.execute(
            text(
                """
                DELETE FROM daily_prices
                WHERE ticker = :ticker
                """
            ),
            {"ticker": ticker}
        )

    df.to_sql(
        "daily_prices",
        engine,
        if_exists="append",
        index=False
    )

    print(f"Updated indicators for {ticker}")


def rebuild_latest_snapshot():
    df = pd.read_sql(
        """
        SELECT *
        FROM daily_prices
        ORDER BY ticker, DATE(trade_date)
        """,
        engine
    )

    if df.empty:
        print("daily_prices empty. Skip latest_snapshot.")
        return

    df["trade_date"] = pd.to_datetime(
        df["trade_date"],
        format="mixed",
        errors="coerce"
    )

    df = df.dropna(subset=["trade_date"]).copy()
    df = df.sort_values(["ticker", "trade_date"])

    latest_snapshot = (
        df.groupby("ticker")
        .tail(1)
        .copy()
        .reset_index(drop=True)
    )

    latest_snapshot["ma_distance"] = (
        (
            latest_snapshot["close_price"]
            - latest_snapshot["ma20"]
        )
        / latest_snapshot["ma20"]
        * 100
    )

    latest_snapshot["is_bullish"] = (
        latest_snapshot["close_price"]
        > latest_snapshot["ma50"]
    )

    latest_snapshot["is_oversold"] = (
        latest_snapshot["rsi"] < 30
    )

    latest_snapshot["is_golden_cross"] = (
        latest_snapshot["ma20"]
        > latest_snapshot["ma50"]
    )

    latest_snapshot.to_sql(
        "latest_snapshot",
        engine,
        if_exists="replace",
        index=False
    )

    print("Rebuilt latest_snapshot")


def main():
    all_new_rows = []

    for ticker in GOLD_WATCHLIST:
        print(f"DOWNLOAD GOLD WATCHLIST: {ticker}")

        raw = yf.download(
            ticker,
            period="180d",
            interval="1d",
            auto_adjust=False,
            progress=False
        )

        if raw.empty:
            print(f"WARNING: no data from yfinance for {ticker}")
            continue

        clean_df = flatten_yfinance_columns(raw, ticker)

        print(clean_df.tail(5).to_string(index=False))

        all_new_rows.append(clean_df)

    if not all_new_rows:
        print("No new rows downloaded.")
        return

    new_df = pd.concat(
        all_new_rows,
        ignore_index=True
    )

    min_date = new_df["trade_date"].min()
    max_date = new_df["trade_date"].max()

    print()
    print(f"Downloaded date range: {min_date} -> {max_date}")

    with engine.begin() as conn:
        for ticker in GOLD_WATCHLIST:
            ticker_df = new_df[new_df["ticker"] == ticker].copy()

            if ticker_df.empty:
                continue

            ticker_min_date = ticker_df["trade_date"].min()
            ticker_max_date = ticker_df["trade_date"].max()

            print(
                f"Deleting old rows: {ticker} "
                f"{ticker_min_date} -> {ticker_max_date}"
            )

            conn.execute(
                text(
                    """
                    DELETE FROM daily_prices
                    WHERE ticker = :ticker
                      AND DATE(trade_date) >= DATE(:min_date)
                      AND DATE(trade_date) <= DATE(:max_date)
                    """
                ),
                {
                    "ticker": ticker,
                    "min_date": ticker_min_date,
                    "max_date": ticker_max_date,
                }
            )

    new_df.to_sql(
        "daily_prices",
        engine,
        if_exists="append",
        index=False
    )

    print()
    print(f"Inserted rows: {len(new_df)}")

    for ticker in GOLD_WATCHLIST:
        update_indicators_for_ticker(ticker)

    rebuild_latest_snapshot()

    check_df = pd.read_sql(
        """
        SELECT
            ticker,
            MAX(DATE(trade_date)) AS last_date,
            COUNT(*) AS rows
        FROM daily_prices
        WHERE ticker IN ('HRTA.JK','MDKA.JK','ANTM.JK','BRMS.JK','EMAS.JK')
        GROUP BY ticker
        ORDER BY ticker
        """,
        engine
    )

    print()
    print("=== GOLD WATCHLIST DB CHECK ===")
    print(check_df.to_string(index=False))


if __name__ == "__main__":
    main()