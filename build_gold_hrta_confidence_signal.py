from pathlib import Path
import sqlite3
import pandas as pd
import numpy as np


# =====================================================
# CONFIG
# =====================================================
DB_PATH = Path("data/market.db")
DRIVER_PATH = Path("data/driver_prices.csv")

OUTPUT_DIR = Path("data/processed")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

OUTPUT_PATH = OUTPUT_DIR / "gold_hrta_confidence_signal.csv"

DRIVER = "GOLD"
TARGET_TICKER = "HRTA.JK"

GOLD_LOOKBACK = 10
GOLD_THRESHOLD_PCT = 5.0
HOLD_DAYS = 10
COOLDOWN_DAYS = 20

# Confidence guardrail
HIGH_CONF_RET20_MAX = 5.0
NORMAL_CONF_RET20_MAX = 10.0


# =====================================================
# HELPERS
# =====================================================
def safe_dt(s):
    return pd.to_datetime(s, format="mixed", errors="coerce")


def safe_num(s):
    return pd.to_numeric(s, errors="coerce")


def load_gold_driver():
    df = pd.read_csv(DRIVER_PATH)
    df.columns = df.columns.str.strip().str.lower()

    required = {"driver", "driver_date", "value"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"Kolom kurang di driver_prices.csv: {sorted(missing)}")

    df["driver"] = df["driver"].astype(str).str.upper().str.strip()
    df["driver_date"] = safe_dt(df["driver_date"])
    df["value"] = safe_num(df["value"])

    df = df[df["driver"] == DRIVER].copy()
    df = df.dropna(subset=["driver_date", "value"])
    df = df.sort_values("driver_date").reset_index(drop=True)

    df["gold_return_10d_pct"] = df["value"].pct_change(GOLD_LOOKBACK) * 100

    return df


def load_hrta_prices():
    query = """
        SELECT trade_date, ticker, close_price, volume, ma20, ma50, rsi
        FROM daily_prices
        WHERE ticker = ?
        ORDER BY DATE(trade_date)
    """

    with sqlite3.connect(DB_PATH) as con:
        df = pd.read_sql(query, con, params=(TARGET_TICKER,))

    df["trade_date"] = safe_dt(df["trade_date"])
    df["ticker"] = df["ticker"].astype(str).str.upper().str.strip()

    for c in ["close_price", "volume", "ma20", "ma50", "rsi"]:
        df[c] = safe_num(df[c])

    df = df.dropna(subset=["trade_date", "close_price"])
    df = df.sort_values("trade_date").reset_index(drop=True)

    df["hrta_ret_5d_pct"] = df["close_price"].pct_change(5) * 100
    df["hrta_ret_10d_pct"] = df["close_price"].pct_change(10) * 100
    df["hrta_ret_20d_pct"] = df["close_price"].pct_change(20) * 100
    df["dist_ma20_pct"] = (df["close_price"] / df["ma20"] - 1) * 100
    df["dist_ma50_pct"] = (df["close_price"] / df["ma50"] - 1) * 100

    return df


def build_valid_gold_signals(gold_df):
    signals = []
    cooldown_until_idx = -1

    for idx, row in gold_df.iterrows():
        if idx <= cooldown_until_idx:
            continue

        ret = row["gold_return_10d_pct"]

        if pd.notna(ret) and ret >= GOLD_THRESHOLD_PCT:
            cooldown_idx = min(idx + COOLDOWN_DAYS, len(gold_df) - 1)

            signals.append({
                "signal_idx": idx,
                "signal_date": row["driver_date"],
                "gold_close": row["value"],
                "gold_return_10d_pct": ret,
                "cooldown_until_date": gold_df.loc[cooldown_idx, "driver_date"],
                "cooldown_until_idx": cooldown_idx,
            })

            cooldown_until_idx = idx + COOLDOWN_DAYS

    return pd.DataFrame(signals)


def next_trading_day_after(signal_date, stock_dates):
    signal_date = pd.to_datetime(signal_date).normalize()
    future = stock_dates[stock_dates > signal_date]

    if len(future) == 0:
        return pd.NaT

    return future.iloc[0]


def nth_trading_day_from_entry(entry_date, hold_days, stock_dates):
    if pd.isna(entry_date):
        return pd.NaT

    entry_date = pd.to_datetime(entry_date).normalize()
    valid = stock_dates[stock_dates >= entry_date]

    if len(valid) < hold_days:
        return pd.NaT

    return valid.iloc[hold_days - 1]


def get_stock_row_on_or_before(hrta_df, date_value):
    date_value = pd.to_datetime(date_value).normalize()

    temp = hrta_df.copy()
    temp["date_norm"] = temp["trade_date"].dt.normalize()

    result = temp[temp["date_norm"] <= date_value].tail(1)

    if result.empty:
        return None

    return result.iloc[0]


def classify_confidence(
    hrta_ret20,
    gold_ret5=None,
    gold_ret10=None,
    close=None,
    ma20=None,
    ma50=None,
    rsi14=None,
    dist_ma20_pct=None,
):
    reasons = []

    if pd.isna(hrta_ret20):
        return {
            "confidence_level": "UNKNOWN",
            "recommended_action": "WAIT",
            "position_size_hint": "NO_SIZE",
            "reason": "HRTA ret20D data unavailable.",
        }

    # Optional safety blocker: GOLD trend weakening
    if gold_ret10 is not None and not pd.isna(gold_ret10) and gold_ret10 < 0:
        return {
            "confidence_level": "BLOCKED_GOLD_WEAK",
            "recommended_action": "NO_ENTRY",
            "position_size_hint": "NO_SIZE",
            "reason": (
                f"GOLD trigger invalid/weak because GOLD ret10D={gold_ret10:.2f}% is negative."
            ),
        }

    # Optional safety blocker: HRTA already overheated by RSI
    if rsi14 is not None and not pd.isna(rsi14) and rsi14 > 75:
        return {
            "confidence_level": "BLOCKED_RSI_OVERHEATED",
            "recommended_action": "NO_ENTRY",
            "position_size_hint": "NO_SIZE",
            "reason": (
                f"GOLD trigger valid but HRTA RSI14={rsi14:.2f} is > 75. Avoid chasing."
            ),
        }

    # Base rule: HRTA 20D return heat filter
    if hrta_ret20 <= HIGH_CONF_RET20_MAX:
        confidence_level = "ACTIVE_HIGH_CONFIDENCE"
        recommended_action = "BUY_ALLOWED"
        position_size_hint = "FULL_PLANNED_SIZE"
        reasons.append(
            f"GOLD trigger valid and HRTA ret20D={hrta_ret20:.2f}% "
            f"is <= {HIGH_CONF_RET20_MAX:.0f}%. HRTA has not rallied too far yet."
        )

    elif hrta_ret20 <= NORMAL_CONF_RET20_MAX:
        confidence_level = "ACTIVE_NORMAL"
        recommended_action = "BUY_ALLOWED_SMALLER_SIZE"
        position_size_hint = "HALF_SIZE_OR_TRADING_SIZE"
        reasons.append(
            f"GOLD trigger valid but HRTA ret20D={hrta_ret20:.2f}% "
            f"is already above {HIGH_CONF_RET20_MAX:.0f}%."
        )

    else:
        return {
            "confidence_level": "BLOCKED_OVERHEATED",
            "recommended_action": "NO_ENTRY",
            "position_size_hint": "NO_SIZE",
            "reason": (
                f"GOLD trigger valid but HRTA ret20D={hrta_ret20:.2f}% "
                f"is > {NORMAL_CONF_RET20_MAX:.0f}%. Avoid chasing."
            ),
        }

    # Optional confirmation bonus / note
    confirmation_notes = []

    if close is not None and ma20 is not None:
        if not pd.isna(close) and not pd.isna(ma20):
            if close >= ma20:
                confirmation_notes.append("HRTA close >= MA20")
            else:
                confirmation_notes.append("HRTA close < MA20, momentum not fully confirmed")

        if dist_ma20_pct is not None and not pd.isna(dist_ma20_pct):
            if dist_ma20_pct >= 0:
                confirmation_notes.append(
                    f"HRTA above MA20 by {dist_ma20_pct:.2f}%"
                )
            else:
                confirmation_notes.append(
                    f"HRTA below MA20 by {dist_ma20_pct:.2f}%, momentum not fully confirmed"
                )
    
    if ma20 is not None and ma50 is not None:
        if not pd.isna(ma20) and not pd.isna(ma50):
            if ma20 >= ma50:
                confirmation_notes.append("MA20 >= MA50")
            else:
                confirmation_notes.append("MA20 < MA50")

    if rsi14 is not None and not pd.isna(rsi14):
        if 35 <= rsi14 <= 70:
            confirmation_notes.append("RSI14 healthy 35-70")
        elif rsi14 < 35:
            confirmation_notes.append("RSI14 weak/oversold < 35")

    if gold_ret5 is not None and not pd.isna(gold_ret5):
        if gold_ret5 >= 3:
            confirmation_notes.append(f"GOLD ret5D={gold_ret5:.2f}% supports early momentum")

    if gold_ret10 is not None and not pd.isna(gold_ret10):
        if gold_ret10 >= 5:
            confirmation_notes.append(f"GOLD ret10D={gold_ret10:.2f}% confirms main trigger")

    if confirmation_notes:
        reasons.append("Confirmation: " + " | ".join(confirmation_notes))

    return {
        "confidence_level": confidence_level,
        "recommended_action": recommended_action,
        "position_size_hint": position_size_hint,
        "reason": " ".join(reasons),
    }


def main():
    print("LOAD GOLD DRIVER:", DRIVER_PATH)
    gold_df = load_gold_driver()

    print("LOAD HRTA STOCK:", DB_PATH)
    hrta_df = load_hrta_prices()

    if gold_df.empty:
        raise ValueError("GOLD driver data kosong.")

    if hrta_df.empty:
        raise ValueError("HRTA stock data kosong.")

    signals = build_valid_gold_signals(gold_df)

    latest_gold = gold_df.tail(1).iloc[0]
    latest_stock = hrta_df.tail(1).iloc[0]

    base_row = {
        "driver_group": DRIVER,
        "driver_symbol": DRIVER,
        "target_ticker": TARGET_TICKER,
        "rule_name": (
            f"GOLD {GOLD_LOOKBACK}D >= +{GOLD_THRESHOLD_PCT:.0f}% | "
            f"Entry NEXT_DAY | Hold {HOLD_DAYS}D | Cooldown {COOLDOWN_DAYS}D"
        ),
        "gold_latest_date": latest_gold["driver_date"],
        "gold_latest_value": latest_gold["value"],
        "gold_latest_return_10d_pct": latest_gold["gold_return_10d_pct"],
        "stock_latest_date": latest_stock["trade_date"],
        "stock_latest_close": latest_stock["close_price"],
        "stock_latest_ret20_pct": latest_stock["hrta_ret_20d_pct"],
        "high_conf_ret20_max": HIGH_CONF_RET20_MAX,
        "normal_conf_ret20_max": NORMAL_CONF_RET20_MAX,
    }

    if signals.empty:
        out = {
            **base_row,
            "signal_status": "NO_SIGNAL",
            "confidence_level": "NO_SIGNAL",
            "recommended_action": "WATCH_ONLY",
            "position_size_hint": "NO_SIZE",
            "last_signal_date": pd.NaT,
            "entry_date": pd.NaT,
            "exit_date": pd.NaT,
            "cooldown_until_date": pd.NaT,
            "entry_hrta_ret20_pct": np.nan,
            "entry_hrta_ret10_pct": np.nan,
            "entry_rsi": np.nan,
            "entry_dist_ma20_pct": np.nan,
            "entry_close": np.nan,
            "reason": "No valid GOLD trigger found.",
        }

        out_df = pd.DataFrame([out])
        out_df.to_csv(OUTPUT_PATH, index=False)
        print(out_df.to_string(index=False))
        return

    last_signal = signals.tail(1).iloc[0]

    stock_dates = hrta_df["trade_date"].dt.normalize().drop_duplicates().reset_index(drop=True)

    first_stock_date = stock_dates.iloc[0]
    last_stock_date = stock_dates.iloc[-1]

    signal_date = pd.to_datetime(last_signal["signal_date"]).normalize()

    # If last signal is before HRTA data existed, ignore it.
    if signal_date < first_stock_date:
        out = {
            **base_row,
            "signal_status": "NO_SIGNAL",
            "confidence_level": "NO_SIGNAL",
            "recommended_action": "WATCH_ONLY",
            "position_size_hint": "NO_SIZE",
            "last_signal_date": last_signal["signal_date"],
            "entry_date": pd.NaT,
            "exit_date": pd.NaT,
            "cooldown_until_date": last_signal["cooldown_until_date"],
            "entry_hrta_ret20_pct": np.nan,
            "entry_hrta_ret10_pct": np.nan,
            "entry_rsi": np.nan,
            "entry_dist_ma20_pct": np.nan,
            "entry_close": np.nan,
            "reason": "Latest GOLD signal happened before HRTA valid stock data.",
        }

        out_df = pd.DataFrame([out])
        out_df.to_csv(OUTPUT_PATH, index=False)
        print(out_df.to_string(index=False))
        return

    entry_date = next_trading_day_after(signal_date, stock_dates)
    exit_date = nth_trading_day_from_entry(entry_date, HOLD_DAYS, stock_dates)

    entry_row = get_stock_row_on_or_before(hrta_df, entry_date)

    latest_stock_date = pd.to_datetime(latest_stock["trade_date"]).normalize()

    cooldown_until_date = pd.to_datetime(last_signal["cooldown_until_date"]).normalize()

    if pd.isna(entry_date):
        signal_status = "WAIT_ENTRY"

    elif latest_stock_date < entry_date:
        signal_status = "WAIT_ENTRY"

    elif entry_date <= latest_stock_date <= exit_date:
        signal_status = "ACTIVE_HOLD_PERIOD"

    elif exit_date < latest_stock_date <= cooldown_until_date:
        signal_status = "COOLDOWN_PERIOD"

    else:
        signal_status = "EXPIRED_SIGNAL"

    if entry_row is None:
        confidence = {
            "confidence_level": "UNKNOWN",
            "recommended_action": "WAIT",
            "position_size_hint": "NO_SIZE",
            "reason": "Entry stock row unavailable.",
        }
        entry_close = np.nan
        entry_ret20 = np.nan
        entry_ret10 = np.nan
        entry_rsi = np.nan
        entry_dist_ma20 = np.nan

    else:
        entry_close = entry_row["close_price"]
        entry_ret20 = entry_row["hrta_ret_20d_pct"]
        entry_ret10 = entry_row["hrta_ret_10d_pct"]
        entry_rsi = entry_row["rsi"]
        entry_dist_ma20 = entry_row["dist_ma20_pct"]

        if signal_status in ["WAIT_ENTRY", "ACTIVE_HOLD_PERIOD"]:
            confidence = classify_confidence(
                hrta_ret20=entry_ret20,
                gold_ret10=last_signal["gold_return_10d_pct"],
                rsi14=entry_rsi,
                dist_ma20_pct=entry_dist_ma20,
            )
        else:
            confidence = {
                "confidence_level": "INACTIVE",
                "recommended_action": "WAIT",
                "position_size_hint": "NO_SIZE",
                "reason": "Last GOLD-HRTA signal has expired. Wait for a new valid GOLD trigger.",
            }

        elif signal_status == "COOLDOWN_PERIOD":
            confidence = {
                "confidence_level": "COOLDOWN_PERIOD",
                "recommended_action": "NO_NEW_ENTRY",
                "position_size_hint": "NO_SIZE",
                "reason": (
                    "Last GOLD-HRTA signal is already past entry/exit window "
                    "and currently in cooldown period. No new entry."
                ),
            }

        else:
            confidence = {
                "confidence_level": "NO_ACTIVE_SIGNAL",
                "recommended_action": "WATCH_ONLY",
                "position_size_hint": "NO_SIZE",
                "reason": (
                    "Last GOLD-HRTA signal has expired. "
                    "Wait for a new GOLD 10D >= +5% trigger."
                ),
            }

    out = {
        **base_row,
        "signal_status": signal_status,
        "confidence_level": confidence["confidence_level"],
        "recommended_action": confidence["recommended_action"],
        "position_size_hint": confidence["position_size_hint"],
        "last_signal_date": last_signal["signal_date"],
        "last_signal_gold_close": last_signal["gold_close"],
        "last_signal_gold_return_10d_pct": last_signal["gold_return_10d_pct"],
        "entry_date": entry_date,
        "exit_date": exit_date,
        "cooldown_until_date": last_signal["cooldown_until_date"],
        "entry_close": entry_close,
        "entry_hrta_ret20_pct": entry_ret20,
        "entry_hrta_ret10_pct": entry_ret10,
        "entry_rsi": entry_rsi,
        "entry_dist_ma20_pct": entry_dist_ma20,
        "reason": confidence["reason"],
    }

    out_df = pd.DataFrame([out])

    # format dates
    for c in [
        "gold_latest_date",
        "stock_latest_date",
        "last_signal_date",
        "entry_date",
        "exit_date",
        "cooldown_until_date",
    ]:
        out_df[c] = pd.to_datetime(out_df[c], errors="coerce").dt.strftime("%Y-%m-%d")

    out_df.to_csv(OUTPUT_PATH, index=False)

    print(f"SUCCESS CREATE {OUTPUT_PATH}")
    print(out_df.to_string(index=False))


if __name__ == "__main__":
    main()
