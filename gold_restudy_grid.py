from pathlib import Path
import sqlite3
import pandas as pd
import numpy as np


# =====================================================
# CONFIG
# =====================================================
DB_PATH = Path("data/market.db")
DRIVER_PATH = Path("data/driver_prices.csv")

OUTPUT_DIR = Path("data/output")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

SUMMARY_PATH = OUTPUT_DIR / "gold_restudy_grid_results.csv"
TRADES_PATH = OUTPUT_DIR / "gold_restudy_trade_details.csv"

DRIVER = "GOLD"
START_DATE = "2012-01-01"

TICKERS = [
    "HRTA.JK",
    "ANTM.JK",
    "MDKA.JK",
    "BRMS.JK",
    "EMAS.JK",
]

ENTRY_MODES = [
    "SAME_DAY",   # entry di close signal day
    "NEXT_DAY",   # entry di close trading day setelah signal
]

LOOKBACKS = [5, 10, 20, 30, 60]
THRESHOLDS = [5, 7, 10, 15]
HOLDS = [5, 10, 20, 40]
COOLDOWNS = [10, 20, 30, 60]

MIN_SIGNALS_ROBUST = 10


# =====================================================
# HELPERS
# =====================================================
def safe_to_datetime(series):
    return pd.to_datetime(series, format="mixed", errors="coerce")


def safe_numeric(series):
    return pd.to_numeric(series, errors="coerce")


def load_driver_prices():
    df = pd.read_csv(DRIVER_PATH)
    df.columns = df.columns.str.strip().str.lower()

    required = {"driver", "driver_date", "value"}
    missing = required - set(df.columns)

    if missing:
        raise ValueError(f"Kolom kurang di driver_prices.csv: {sorted(missing)}")

    df["driver"] = df["driver"].astype(str).str.upper().str.strip()
    df["driver_date"] = safe_to_datetime(df["driver_date"])
    df["value"] = safe_numeric(df["value"])

    df = df[df["driver"] == DRIVER].copy()
    df = df.dropna(subset=["driver_date", "value"])
    df = df.sort_values("driver_date").reset_index(drop=True)
    df = df[df["driver_date"] >= pd.to_datetime(START_DATE)].copy()
    df = df.reset_index(drop=True)
    return df


def load_stock_prices():
    placeholders = ",".join(["?"] * len(TICKERS))

    query = f"""
        SELECT trade_date, ticker, close_price
        FROM daily_prices
        WHERE ticker IN ({placeholders})
        ORDER BY ticker, DATE(trade_date)
    """

    with sqlite3.connect(DB_PATH) as con:
        df = pd.read_sql(query, con, params=tuple(TICKERS))

    df["ticker"] = df["ticker"].astype(str).str.upper().str.strip()
    df["trade_date"] = safe_to_datetime(df["trade_date"])
    df["close_price"] = safe_numeric(df["close_price"])

    df = df.dropna(subset=["ticker", "trade_date", "close_price"])
    df = df.sort_values(["ticker", "trade_date"]).reset_index(drop=True)
    df = df[df["trade_date"] >= pd.to_datetime(START_DATE)].copy()
    df = df.reset_index(drop=True)
    return df


def build_valid_events(driver_df, lookback, threshold, cooldown):
    d = driver_df.copy()
    d["driver_return_pct"] = d["value"].pct_change(lookback) * 100

    events = []
    cooldown_until_idx = -1

    for i, row in d.iterrows():
        if i <= cooldown_until_idx:
            continue

        if pd.notna(row["driver_return_pct"]) and row["driver_return_pct"] >= threshold:
            cooldown_end_idx = min(i + cooldown, len(d) - 1)

            events.append({
                "signal_idx": i,
                "signal_date": row["driver_date"],
                "driver_close": row["value"],
                "driver_return_pct": row["driver_return_pct"],
                "lookback_days": lookback,
                "threshold_pct": threshold,
                "cooldown_days": cooldown,
                "cooldown_until_est_date": d.loc[cooldown_end_idx, "driver_date"],
            })

            cooldown_until_idx = i + cooldown

    return pd.DataFrame(events)


def get_entry_date(signal_date, stock_dates, entry_mode):
    signal_date = pd.to_datetime(signal_date).normalize()

    if entry_mode == "SAME_DAY":
        valid = stock_dates[stock_dates >= signal_date]
    elif entry_mode == "NEXT_DAY":
        valid = stock_dates[stock_dates > signal_date]
    else:
        raise ValueError(f"ENTRY_MODE tidak dikenal: {entry_mode}")

    if len(valid) == 0:
        return pd.NaT

    return valid.iloc[0]


def get_exit_date(entry_date, hold_days, stock_dates):
    if pd.isna(entry_date):
        return pd.NaT

    entry_date = pd.to_datetime(entry_date).normalize()
    valid = stock_dates[stock_dates >= entry_date]

    # entry date dihitung day 1
    if len(valid) < hold_days:
        return pd.NaT

    return valid.iloc[hold_days - 1]


def calc_profit_factor(returns_decimal):
    wins = returns_decimal[returns_decimal > 0].sum()
    losses = returns_decimal[returns_decimal <= 0].sum()

    if losses == 0:
        return np.inf if wins > 0 else np.nan

    return wins / abs(losses)


def calc_max_drawdown(returns_decimal):
    if len(returns_decimal) == 0:
        return np.nan

    equity = (1 + returns_decimal).cumprod()
    peak = equity.cummax()
    drawdown = equity / peak - 1

    return drawdown.min() * 100


def backtest_one_combo(
    ticker,
    stock_df,
    events,
    entry_mode,
    lookback,
    threshold,
    hold,
    cooldown,
):
    s = stock_df[stock_df["ticker"] == ticker].copy()

    if s.empty or events.empty:
        return pd.DataFrame()

    s = s.sort_values("trade_date").reset_index(drop=True)
    s["trade_date_norm"] = s["trade_date"].dt.normalize()

    stock_dates = s["trade_date_norm"].drop_duplicates().reset_index(drop=True)
        
    if stock_dates.empty:
        return pd.DataFrame()

    first_stock_date = stock_dates.iloc[0]
    last_stock_date = stock_dates.iloc[-1]
        
    price_map = (
        s.drop_duplicates("trade_date_norm", keep="last")
        .set_index("trade_date_norm")["close_price"]
        .to_dict()
    )

    rows = []

    for _, ev in events.iterrows():
        signal_date = pd.to_datetime(ev["signal_date"]).normalize()

        if signal_date < first_stock_date:
            continue

        if signal_date > last_stock_date:
            continue
        
        entry_date = get_entry_date(
            signal_date=signal_date,
            stock_dates=stock_dates,
            entry_mode=entry_mode,
        )

        exit_date = get_exit_date(
            entry_date=entry_date,
            hold_days=hold,
            stock_dates=stock_dates,
        )

        if pd.isna(entry_date) or pd.isna(exit_date):
            continue

        entry_price = price_map.get(entry_date)
        exit_price = price_map.get(exit_date)

        if entry_price is None or exit_price is None or entry_price <= 0:
            continue

        ret_decimal = exit_price / entry_price - 1

        rows.append({
            "driver": DRIVER,
            "ticker": ticker,
            "entry_mode": entry_mode,

            "signal_date": signal_date,
            "event_date": signal_date,
            "driver_close": ev["driver_close"],
            "driver_return_pct": ev["driver_return_pct"],

            "entry_date": entry_date,
            "buy_date": entry_date,
            "exit_date": exit_date,
            "sell_date": exit_date,

            "entry_price": entry_price,
            "buy_price": entry_price,
            "exit_price": exit_price,
            "sell_price": exit_price,

            "return_pct": ret_decimal * 100,
            "return_decimal": ret_decimal,

            "lookback_days": lookback,
            "threshold_pct": threshold,
            "hold_days": hold,
            "cooldown_days": cooldown,

            "rule": (
                f"GOLD >= +{threshold}% in {lookback}D | "
                f"Entry {entry_mode} | Hold {hold}D | Cooldown {cooldown}D"
            ),
        })

    return pd.DataFrame(rows)


def summarize_trades(trades):
    rows = []

    group_cols = [
        "ticker",
        "entry_mode",
        "lookback_days",
        "threshold_pct",
        "hold_days",
        "cooldown_days",
        "rule",
    ]

    for keys, g in trades.groupby(group_cols):
        g = g.sort_values("entry_date").copy()

        returns = g["return_decimal"].dropna()
        total = len(returns)

        if total == 0:
            continue

        wins = int((returns > 0).sum())
        losses = int((returns <= 0).sum())

        win_rate = wins / total * 100
        avg_return = returns.mean() * 100
        median_return = returns.median() * 100
        best_return = returns.max() * 100
        worst_return = returns.min() * 100
        compound_return = ((1 + returns).prod() - 1) * 100
        profit_factor = calc_profit_factor(returns)
        max_drawdown = calc_max_drawdown(returns)

        ticker, entry_mode, lookback, threshold, hold, cooldown, rule = keys

        sample_flag = "ROBUST" if total >= MIN_SIGNALS_ROBUST else "LOW_SAMPLE"

        pf_for_score = profit_factor
        if pd.isna(pf_for_score):
            pf_for_score = 0
        if pf_for_score == np.inf:
            pf_for_score = 10

        # Safety-first score:
        # WR + median + avg + PF + sample + drawdown penalty
        score = (
            0.30 * (win_rate / 100)
            + 0.25 * (median_return / 100)
            + 0.20 * (avg_return / 100)
            + 0.15 * min(pf_for_score, 10) / 10
            + 0.10 * min(total, 50) / 50
        )

        # Penalize very bad worst trade
        if worst_return <= -30:
            score -= 0.10
        elif worst_return <= -20:
            score -= 0.05

        # Penalize low sample so it doesn't become fake champion
        if sample_flag == "LOW_SAMPLE":
            score -= 0.15

        rows.append({
            "driver": DRIVER,
            "ticker": ticker,
            "entry_mode": entry_mode,
            "lookback_days": lookback,
            "threshold_pct": threshold,
            "hold_days": hold,
            "cooldown_days": cooldown,
            "rule": rule,

            "total_trades": total,
            "wins": wins,
            "losses": losses,
            "win_rate": round(win_rate, 2),
            "profit_factor": round(profit_factor, 4) if profit_factor != np.inf else 999.0,
            "compound_return_pct": round(compound_return, 2),
            "avg_trade_return_pct": round(avg_return, 2),
            "median_trade_return_pct": round(median_return, 2),
            "best_trade_pct": round(best_return, 2),
            "worst_trade_pct": round(worst_return, 2),
            "max_drawdown_pct": round(max_drawdown, 2),
            "sample_flag": sample_flag,
            "score": round(score, 6),
        })

    return pd.DataFrame(rows)


# =====================================================
# MAIN
# =====================================================
def main():
    print("LOAD GOLD DRIVER:", DRIVER_PATH)
    driver_df = load_driver_prices()

    print("LOAD STOCK PRICES:", DB_PATH)
    stock_df = load_stock_prices()

    all_trades = []

    total_jobs = (
        len(TICKERS)
        * len(ENTRY_MODES)
        * len(LOOKBACKS)
        * len(THRESHOLDS)
        * len(HOLDS)
        * len(COOLDOWNS)
    )

    job = 0

    for lookback in LOOKBACKS:
        for threshold in THRESHOLDS:
            for cooldown in COOLDOWNS:
                events = build_valid_events(
                    driver_df=driver_df,
                    lookback=lookback,
                    threshold=threshold,
                    cooldown=cooldown,
                )

                if events.empty:
                    continue

                for hold in HOLDS:
                    for entry_mode in ENTRY_MODES:
                        for ticker in TICKERS:
                            job += 1

                            trades = backtest_one_combo(
                                ticker=ticker,
                                stock_df=stock_df,
                                events=events,
                                entry_mode=entry_mode,
                                lookback=lookback,
                                threshold=threshold,
                                hold=hold,
                                cooldown=cooldown,
                            )

                            if not trades.empty:
                                all_trades.append(trades)

    if not all_trades:
        print("NO TRADES")
        return

    trade_df = pd.concat(all_trades, ignore_index=True)

    summary_df = summarize_trades(trade_df)

    # Convert dates for CSV output
    for col in ["signal_date", "event_date", "entry_date", "buy_date", "exit_date", "sell_date"]:
        trade_df[col] = safe_to_datetime(trade_df[col]).dt.strftime("%Y-%m-%d")

    summary_df = summary_df.sort_values(
        ["ticker", "score"],
        ascending=[True, False],
    ).reset_index(drop=True)

    trade_df = trade_df.sort_values(
        ["ticker", "entry_mode", "lookback_days", "threshold_pct", "hold_days", "cooldown_days", "entry_date"]
    ).reset_index(drop=True)

    summary_df.to_csv(SUMMARY_PATH, index=False)
    trade_df.to_csv(TRADES_PATH, index=False)

    print(f"SUCCESS CREATE {SUMMARY_PATH}")
    print(f"SUCCESS CREATE {TRADES_PATH}")

    display_cols = [
        "ticker",
        "entry_mode",
        "lookback_days",
        "threshold_pct",
        "hold_days",
        "cooldown_days",
        "total_trades",
        "win_rate",
        "avg_trade_return_pct",
        "median_trade_return_pct",
        "worst_trade_pct",
        "profit_factor",
        "sample_flag",
        "score",
    ]

    print("\nBEST RULE PER TICKER:")
    best = summary_df.sort_values("score", ascending=False).groupby("ticker").head(1)
    print(best[display_cols].to_string(index=False))

    print("\nTOP 30 OVERALL:")
    top = summary_df.sort_values("score", ascending=False).head(30)
    print(top[display_cols].to_string(index=False))

    print("\nHRTA 2026 CHECK FOR OLD RULE:")
    old = trade_df[
        (trade_df["ticker"] == "HRTA.JK")
        & (trade_df["lookback_days"] == 10)
        & (trade_df["threshold_pct"] == 5)
        & (trade_df["hold_days"] == 10)
        & (trade_df["cooldown_days"] == 20)
    ].copy()

    old_2026 = old[old["entry_date"].astype(str).str.startswith("2026")].copy()

    if old_2026.empty:
        print("NO HRTA 2026 OLD RULE TRADES")
    else:
        print(old_2026[[
            "entry_mode",
            "signal_date",
            "entry_date",
            "exit_date",
            "entry_price",
            "exit_price",
            "return_pct",
        ]].to_string(index=False))


if __name__ == "__main__":
    main()
