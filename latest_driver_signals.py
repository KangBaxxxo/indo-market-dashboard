# latest_driver_signals.py

import os
import sqlite3
from pathlib import Path

import pandas as pd


DB_PATH = "data/market.db"
DRIVER_CSV_PATH = "data/driver_prices.csv"
OUTPUT_DIR = Path("data/processed")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

OUTPUT_PATH = OUTPUT_DIR / "latest_driver_signals.csv"


# ==============================
# FINAL / CANDIDATE RULES
# ==============================

SIGNAL_RULES = [
    {
        "driver_group": "GOLD",
        "driver_symbol": "GOLD",
        "target_ticker": "HRTA.JK",
        "lookback_days": 10,
        "threshold_pct": 5.0,
        "hold_days": 10,
        "cooldown_days": 20,
        "status": "FINAL",
        "notes": "Final main rule from GOLD research",
    },
    {
        "driver_group": "COAL",
        "driver_symbol": "COAL",
        "target_ticker": "ADRO.JK",
        "lookback_days": 10,
        "threshold_pct": 10.0,
        "hold_days": 10,
        "cooldown_days": 30,
        "status": "FINAL_CANDIDATE",
        "notes": "Strong final candidate from COAL research",
    },
]


# ==============================
# HELPERS
# ==============================

def read_driver_prices():
    if not os.path.exists(DRIVER_CSV_PATH):
        raise FileNotFoundError(f"Driver CSV not found: {DRIVER_CSV_PATH}")

    df = pd.read_csv(DRIVER_CSV_PATH)

    required = {"driver", "driver_date", "value"}
    missing = required - set(df.columns)

    if missing:
        raise ValueError(
            f"Missing columns in {DRIVER_CSV_PATH}: {missing}. "
            f"Columns found: {df.columns.tolist()}"
        )

    df = df.rename(
        columns={
            "driver": "driver_symbol",
            "driver_date": "date",
            "value": "driver_close",
        }
    )

    df["driver_symbol"] = df["driver_symbol"].astype(str).str.upper().str.strip()
    df["date"] = pd.to_datetime(df["date"], format="mixed", errors="coerce")
    df["driver_close"] = pd.to_numeric(df["driver_close"], errors="coerce")

    df = df.dropna(subset=["driver_symbol", "date", "driver_close"])
    df = df.sort_values(["driver_symbol", "date"]).reset_index(drop=True)

    return df


def read_stock_prices():
    if not os.path.exists(DB_PATH):
        raise FileNotFoundError(f"Database not found: {DB_PATH}")

    con = sqlite3.connect(DB_PATH)

    df = pd.read_sql(
        """
        SELECT trade_date, ticker, close_price
        FROM daily_prices
        """,
        con,
    )

    con.close()

    df = df.rename(
        columns={
            "trade_date": "date",
            "close_price": "stock_close",
        }
    )

    df["ticker"] = df["ticker"].astype(str).str.upper().str.strip()
    df["date"] = pd.to_datetime(df["date"], format="mixed", errors="coerce")
    df["stock_close"] = pd.to_numeric(df["stock_close"], errors="coerce")

    df = df.dropna(subset=["ticker", "date", "stock_close"])
    df = df.sort_values(["ticker", "date"]).reset_index(drop=True)

    return df


def get_latest_driver_snapshot(driver_df, driver_symbol, lookback_days):
    d = driver_df[driver_df["driver_symbol"] == driver_symbol].copy()
    d = d.sort_values("date").reset_index(drop=True)

    if len(d) <= lookback_days:
        return None

    latest = d.iloc[-1]
    previous = d.iloc[-1 - lookback_days]

    driver_return_pct = (latest["driver_close"] / previous["driver_close"] - 1) * 100

    return {
        "driver_latest_date": latest["date"],
        "driver_latest_close": latest["driver_close"],
        "driver_prev_date": previous["date"],
        "driver_prev_close": previous["driver_close"],
        "driver_return_pct": driver_return_pct,
    }


def get_latest_stock_snapshot(stock_df, ticker):
    s = stock_df[stock_df["ticker"] == ticker].copy()
    s = s.sort_values("date").reset_index(drop=True)

    if s.empty:
        return None

    latest = s.iloc[-1]

    return {
        "stock_latest_date": latest["date"],
        "stock_latest_close": latest["stock_close"],
    }


def get_last_event(driver_df, driver_symbol, lookback_days, threshold_pct):
    d = driver_df[driver_df["driver_symbol"] == driver_symbol].copy()
    d = d.sort_values("date").reset_index(drop=True)

    if len(d) <= lookback_days:
        return None

    d["driver_return_pct"] = d["driver_close"].pct_change(lookback_days) * 100
    latest_date = d["date"].max()

    events = d[
        (d["driver_return_pct"] >= threshold_pct) &
        (d["date"] < latest_date)
    ].copy()

    if events.empty:
        return None

    last = events.iloc[-1]

    return {
        "last_signal_date": last["date"],
        "last_signal_driver_close": last["driver_close"],
        "last_signal_return_pct": last["driver_return_pct"],
    }


def trading_days_since(driver_df, driver_symbol, start_date, end_date):
    d = driver_df[driver_df["driver_symbol"] == driver_symbol].copy()
    d = d.sort_values("date")

    mask = (d["date"] > start_date) & (d["date"] <= end_date)
    return int(mask.sum())


def build_latest_signals():
    driver_df = read_driver_prices()
    stock_df = read_stock_prices()

    rows = []

    for rule in SIGNAL_RULES:
        driver_symbol = rule["driver_symbol"].upper()
        ticker = rule["target_ticker"].upper()
        lookback_days = int(rule["lookback_days"])
        threshold_pct = float(rule["threshold_pct"])
        cooldown_days = int(rule["cooldown_days"])

        driver_snapshot = get_latest_driver_snapshot(
            driver_df=driver_df,
            driver_symbol=driver_symbol,
            lookback_days=lookback_days,
        )

        stock_snapshot = get_latest_stock_snapshot(
            stock_df=stock_df,
            ticker=ticker,
        )

        if driver_snapshot is None:
            rows.append({
                **rule,
                "error": f"Not enough driver data for {driver_symbol}",
            })
            continue

        latest_date = driver_snapshot["driver_latest_date"]
        driver_return_pct = driver_snapshot["driver_return_pct"]

        raw_signal_active = driver_return_pct >= threshold_pct

        last_event = get_last_event(
            driver_df=driver_df,
            driver_symbol=driver_symbol,
            lookback_days=lookback_days,
            threshold_pct=threshold_pct,
        )

        if last_event is None:
            last_signal_date = pd.NaT
            last_signal_return_pct = None
            days_since_last_signal = None
            cooldown_remaining_days = 0
            in_cooldown = False
        else:
            last_signal_date = last_event["last_signal_date"]
            last_signal_return_pct = last_event["last_signal_return_pct"]

            days_since_last_signal = trading_days_since(
                driver_df=driver_df,
                driver_symbol=driver_symbol,
                start_date=last_signal_date,
                end_date=latest_date,
            )

            cooldown_remaining_days = max(cooldown_days - days_since_last_signal, 0)
            in_cooldown = cooldown_remaining_days > 0

        actionable_signal = raw_signal_active and not in_cooldown

        if actionable_signal:
            signal_status = "ACTIVE_ACTIONABLE"
        elif raw_signal_active and in_cooldown:
            signal_status = "ACTIVE_BUT_COOLDOWN"
        else:
            signal_status = "NO_SIGNAL"

        row = {
            **rule,

            "driver_latest_date": driver_snapshot["driver_latest_date"],
            "driver_latest_close": driver_snapshot["driver_latest_close"],
            "driver_prev_date": driver_snapshot["driver_prev_date"],
            "driver_prev_close": driver_snapshot["driver_prev_close"],
            "driver_return_pct": round(driver_return_pct, 2),

            "threshold_hit": bool(raw_signal_active),
            "signal_status": signal_status,
            "actionable_signal": bool(actionable_signal),

            "last_signal_date": last_signal_date,
            "last_signal_return_pct": round(last_signal_return_pct, 2)
            if last_signal_return_pct is not None else None,
            "days_since_last_signal": days_since_last_signal,
            "cooldown_days": cooldown_days,
            "cooldown_remaining_days": cooldown_remaining_days,
            "in_cooldown": bool(in_cooldown),

            "stock_latest_date": stock_snapshot["stock_latest_date"] if stock_snapshot else pd.NaT,
            "stock_latest_close": stock_snapshot["stock_latest_close"] if stock_snapshot else None,

            "error": "",
        }

        rows.append(row)

    result = pd.DataFrame(rows)

    date_cols = [
        "driver_latest_date",
        "driver_prev_date",
        "last_signal_date",
        "stock_latest_date",
    ]

    for col in date_cols:
        if col in result.columns:
            result[col] = pd.to_datetime(result[col], errors="coerce").dt.strftime("%Y-%m-%d")

    result.to_csv(OUTPUT_PATH, index=False)

    return result


def main():
    result = build_latest_signals()

    print("")
    print("=" * 100)
    print("LATEST DRIVER SIGNALS")
    print("=" * 100)

    cols = [
        "driver_group",
        "driver_symbol",
        "target_ticker",
        "status",
        "driver_latest_date",
        "driver_return_pct",
        "threshold_pct",
        "threshold_hit",
        "signal_status",
        "last_signal_date",
        "last_signal_return_pct",
        "cooldown_remaining_days",
        "stock_latest_date",
        "stock_latest_close",
        "notes",
        "error",
    ]

    existing_cols = [c for c in cols if c in result.columns]

    print(result[existing_cols].to_string(index=False))

    print("")
    print(f"Saved to: {OUTPUT_PATH}")


if __name__ == "__main__":
    main()