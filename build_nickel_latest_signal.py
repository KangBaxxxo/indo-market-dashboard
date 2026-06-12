from pathlib import Path
import sqlite3

import pandas as pd


# =====================================================
# CONFIG
# =====================================================
DRIVER_CSV_PATH = Path("data/driver_prices.csv")
DB_PATH = Path("data/market.db")

OUTPUT_DIR = Path("data/processed")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

LATEST_SIGNAL_PATH = OUTPUT_DIR / "latest_driver_signals.csv"

DRIVER_GROUP = "NICKEL"
DRIVER_SYMBOL = "NICKEL"
TARGET_TICKER = "INCO.JK"

LOOKBACK_DAYS = 60
THRESHOLD_PCT = 9.0
HOLD_DAYS = 60
COOLDOWN_DAYS = 60


# =====================================================
# HELPERS
# =====================================================
def safe_to_datetime(series):
    return pd.to_datetime(series, format="mixed", errors="coerce")


def safe_numeric(series):
    return pd.to_numeric(series, errors="coerce")


def load_driver_prices():
    if not DRIVER_CSV_PATH.exists():
        raise FileNotFoundError(f"File tidak ketemu: {DRIVER_CSV_PATH}")

    df = pd.read_csv(DRIVER_CSV_PATH)
    df.columns = df.columns.str.strip().str.lower()

    required_cols = {"driver", "driver_date", "value"}
    missing = required_cols - set(df.columns)

    if missing:
        raise ValueError(f"Kolom driver_prices.csv kurang: {sorted(missing)}")

    df["driver"] = df["driver"].astype(str).str.upper().str.strip()
    df["driver_date"] = safe_to_datetime(df["driver_date"])
    df["value"] = safe_numeric(df["value"])

    df = df.dropna(subset=["driver", "driver_date", "value"])
    df = df[df["driver"] == DRIVER_SYMBOL].copy()
    df = df.sort_values("driver_date").reset_index(drop=True)

    return df


def load_latest_stock_row():
    if not DB_PATH.exists():
        return {
            "stock_latest_date": pd.NaT,
            "stock_latest_close": None,
        }

    query = """
        SELECT trade_date, ticker, close_price
        FROM daily_prices
        WHERE ticker = ?
        ORDER BY DATE(trade_date)
    """

    with sqlite3.connect(DB_PATH) as con:
        df = pd.read_sql(query, con, params=(TARGET_TICKER,))

    if df.empty:
        return {
            "stock_latest_date": pd.NaT,
            "stock_latest_close": None,
        }

    df["trade_date"] = safe_to_datetime(df["trade_date"])
    df["close_price"] = safe_numeric(df["close_price"])
    df = df.dropna(subset=["trade_date", "close_price"])
    df = df.sort_values("trade_date").reset_index(drop=True)

    if df.empty:
        return {
            "stock_latest_date": pd.NaT,
            "stock_latest_close": None,
        }

    latest = df.iloc[-1]

    return {
        "stock_latest_date": latest["trade_date"],
        "stock_latest_close": latest["close_price"],
    }


def build_valid_signal_events(driver_df):
    d = driver_df.copy()
    d["driver_return_pct"] = d["value"].pct_change(LOOKBACK_DAYS) * 100

    events = []
    cooldown_until_idx = -1

    for i, row in d.iterrows():
        if i <= cooldown_until_idx:
            continue

        if pd.notna(row["driver_return_pct"]) and row["driver_return_pct"] >= THRESHOLD_PCT:
            cooldown_end_idx = min(i + COOLDOWN_DAYS, len(d) - 1)
            cooldown_end_date = d.loc[cooldown_end_idx, "driver_date"]

            events.append({
                "signal_idx": i,
                "signal_date": row["driver_date"],
                "driver_return_pct": row["driver_return_pct"],
                "driver_close": row["value"],
                "cooldown_until_idx": cooldown_end_idx,
                "cooldown_until_est_date": cooldown_end_date,
            })

            cooldown_until_idx = i + COOLDOWN_DAYS

    return pd.DataFrame(events)


def upsert_latest_signal(new_row):
    new_df = pd.DataFrame([new_row])

    if LATEST_SIGNAL_PATH.exists():
        old = pd.read_csv(LATEST_SIGNAL_PATH)
        old.columns = old.columns.str.strip()

        if "driver_group" in old.columns:
            old["driver_group"] = old["driver_group"].astype(str).str.upper().str.strip()
            old = old[old["driver_group"] != DRIVER_GROUP].copy()

        final = pd.concat([old, new_df], ignore_index=True)
    else:
        final = new_df

    final.to_csv(LATEST_SIGNAL_PATH, index=False)


# =====================================================
# MAIN
# =====================================================
def main():
    driver_df = load_driver_prices()

    if driver_df.empty or len(driver_df) <= LOOKBACK_DAYS:
        raise ValueError("Data NICKEL belum cukup untuk hitung latest signal.")

    driver_df["driver_return_pct"] = driver_df["value"].pct_change(LOOKBACK_DAYS) * 100

    latest = driver_df.iloc[-1]
    prev = driver_df.iloc[-2] if len(driver_df) >= 2 else latest

    latest_idx = driver_df.index[-1]
    latest_return = latest["driver_return_pct"]
    threshold_hit = bool(pd.notna(latest_return) and latest_return >= THRESHOLD_PCT)

    valid_events = build_valid_signal_events(driver_df)

    last_signal_date = pd.NaT
    last_signal_return_pct = None
    cooldown_remaining_days = 0
    signal_status = "INACTIVE"

    if not valid_events.empty:
        last_event = valid_events.iloc[-1]

        last_signal_idx = int(last_event["signal_idx"])
        last_signal_date = last_event["signal_date"]
        last_signal_return_pct = last_event["driver_return_pct"]

        cooldown_end_idx = int(last_event["cooldown_until_idx"])
        cooldown_remaining_days = max(cooldown_end_idx - latest_idx, 0)

        # Fresh valid signal if latest date itself is the accepted cooldown-debounced event
        if threshold_hit and latest_idx == last_signal_idx:
            signal_status = "ACTIVE_ACTIONABLE"

        # Still in active trade/cooldown window after latest accepted event
        elif latest_idx <= max(last_signal_idx + HOLD_DAYS, cooldown_end_idx):
            signal_status = "ACTIVE_BUT_COOLDOWN"

        else:
            signal_status = "INACTIVE"

    stock_info = load_latest_stock_row()

    row = {
        "driver_group": DRIVER_GROUP,
        "driver_symbol": DRIVER_SYMBOL,
        "target_ticker": TARGET_TICKER,

        "driver_latest_date": latest["driver_date"].strftime("%Y-%m-%d"),
        "driver_latest_value": latest["value"],

        "driver_prev_date": prev["driver_date"].strftime("%Y-%m-%d"),
        "driver_prev_value": prev["value"],

        "driver_return_pct": latest_return,
        "threshold_pct": THRESHOLD_PCT,
        "threshold_hit": threshold_hit,
        "signal_status": signal_status,

        "last_signal_date": None if pd.isna(last_signal_date) else pd.to_datetime(last_signal_date).strftime("%Y-%m-%d"),
        "last_signal_return_pct": last_signal_return_pct,
        "cooldown_remaining_days": cooldown_remaining_days,

        "stock_latest_date": None if pd.isna(stock_info["stock_latest_date"]) else pd.to_datetime(stock_info["stock_latest_date"]).strftime("%Y-%m-%d"),
        "stock_latest_close": stock_info["stock_latest_close"],

        "lookback_days": LOOKBACK_DAYS,
        "hold_days": HOLD_DAYS,
        "cooldown_days": COOLDOWN_DAYS,
    }

    upsert_latest_signal(row)

    print(f"SUCCESS UPSERT {DRIVER_GROUP} latest signal to {LATEST_SIGNAL_PATH}")
    print(pd.DataFrame([row]).to_string(index=False))


if __name__ == "__main__":
    main()
