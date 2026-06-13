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

SUMMARY_PATH = OUTPUT_DIR / "gold_backtest_summary.csv"
TRADES_PATH = OUTPUT_DIR / "gold_trade_details.csv"
YEARLY_PATH = OUTPUT_DIR / "gold_year_by_year.csv"

DRIVER = "GOLD"
DRIVER_SYMBOL = "GOLD"

TICKERS = [
    "HRTA.JK",
    "ANTM.JK",
    "MDKA.JK",
    "BRMS.JK",
    "EMAS.JK",
]

LOOKBACK_DAYS = 10
THRESHOLD_PCT = 5.0
HOLD_DAYS = 10
COOLDOWN_DAYS = 20

RULE_TEXT = "GOLD >= +5% in 10D | Hold 10D | Cooldown 20D"


# =====================================================
# HELPERS
# =====================================================
def safe_to_datetime(series):
    return pd.to_datetime(series, format="mixed", errors="coerce")


def safe_numeric(series):
    return pd.to_numeric(series, errors="coerce")


def load_driver_prices():
    if not DRIVER_PATH.exists():
        raise FileNotFoundError(f"File tidak ketemu: {DRIVER_PATH}")

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

    return df


def load_stock_prices():
    if not DB_PATH.exists():
        raise FileNotFoundError(f"DB tidak ketemu: {DB_PATH}")

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

    return df


def build_valid_driver_events(driver_df):
    d = driver_df.copy()
    d["driver_return_pct"] = d["value"].pct_change(LOOKBACK_DAYS) * 100

    events = []
    cooldown_until_idx = -1

    for i, row in d.iterrows():
        if i <= cooldown_until_idx:
            continue

        if pd.notna(row["driver_return_pct"]) and row["driver_return_pct"] >= THRESHOLD_PCT:
            cooldown_end_idx = min(i + COOLDOWN_DAYS, len(d) - 1)

            events.append({
                "signal_idx": i,
                "signal_date": row["driver_date"],
                "driver_symbol": DRIVER_SYMBOL,
                "driver_close": row["value"],
                "driver_return_pct": row["driver_return_pct"],
                "lookback_days": LOOKBACK_DAYS,
                "threshold_pct": THRESHOLD_PCT,
                "hold_days": HOLD_DAYS,
                "cooldown_days": COOLDOWN_DAYS,
                "cooldown_until_est_date": d.loc[cooldown_end_idx, "driver_date"],
            })

            cooldown_until_idx = i + COOLDOWN_DAYS

    return pd.DataFrame(events)


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


def backtest_ticker(ticker, events, stock_df):
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

    trades = []

    for _, ev in events.iterrows():
        signal_date = pd.to_datetime(ev["signal_date"]).normalize()

        # CRITICAL:
        # Skip driver signals before this ticker has valid stock data.
        # Without this, old GOLD signals from 2001-2016 get mapped into
        # HRTA's first available trading day in 2017.
        if signal_date < first_stock_date:
            continue

        if signal_date > last_stock_date:
            continue

        entry_date = next_trading_day_after(signal_date, stock_dates)
        exit_date = nth_trading_day_from_entry(entry_date, HOLD_DAYS, stock_dates)

        if pd.isna(entry_date) or pd.isna(exit_date):
            continue

        entry_price = price_map.get(entry_date)
        exit_price = price_map.get(exit_date)

        if entry_price is None or exit_price is None or entry_price <= 0:
            continue

        ret = exit_price / entry_price - 1

        trades.append({
            "driver": DRIVER,
            "driver_symbol": DRIVER_SYMBOL,
            "ticker": ticker,
            "rule": RULE_TEXT,

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

            "return_pct": ret * 100,
            "return_decimal": ret,

            "lookback_days": LOOKBACK_DAYS,
            "threshold_pct": THRESHOLD_PCT,
            "hold_days": HOLD_DAYS,
            "cooldown_days": COOLDOWN_DAYS,
        })

    return pd.DataFrame(trades)

def calc_profit_factor(returns):
    wins = returns[returns > 0].sum()
    losses = returns[returns <= 0].sum()

    if losses == 0:
        return np.inf if wins > 0 else np.nan

    return wins / abs(losses)


def calc_max_drawdown(returns):
    if len(returns) == 0:
        return np.nan

    equity = (1 + returns).cumprod()
    peak = equity.cummax()
    drawdown = equity / peak - 1

    return drawdown.min() * 100


def build_summary(trades):
    rows = []

    for ticker, g in trades.groupby("ticker"):
        g = g.sort_values("entry_date").copy()
        returns = g["return_decimal"].dropna()

        total = len(returns)
        wins = int((returns > 0).sum())
        losses = int((returns <= 0).sum())

        if total == 0:
            continue

        win_rate = wins / total * 100
        avg_return = returns.mean() * 100
        median_return = returns.median() * 100
        best_return = returns.max() * 100
        worst_return = returns.min() * 100
        compound_return = ((1 + returns).prod() - 1) * 100
        profit_factor = calc_profit_factor(returns)
        max_drawdown = calc_max_drawdown(returns)

        # Simple safety-first score
        # Profit factor bisa inf, jadi cap supaya tidak ngerusak sorting
        pf_for_score = profit_factor
        if pd.isna(pf_for_score):
            pf_for_score = 0
        if pf_for_score == np.inf:
            pf_for_score = 10

        score = (
            0.35 * (win_rate / 100)
            + 0.30 * max(avg_return, -100) / 100
            + 0.20 * min(pf_for_score, 10) / 10
            + 0.15 * min(total, 50) / 50
        )

        rows.append({
            "driver": DRIVER,
            "ticker": ticker,
            "rule": RULE_TEXT,
            "driver_symbol": DRIVER_SYMBOL,
            "lookback_days": LOOKBACK_DAYS,
            "threshold_pct": THRESHOLD_PCT,
            "hold_days": HOLD_DAYS,
            "cooldown_days": COOLDOWN_DAYS,

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
            "score": round(score, 6),
        })

    return pd.DataFrame(rows)


def build_yearly(trades):
    if trades.empty:
        return pd.DataFrame()

    df = trades.copy()
    df["entry_date"] = safe_to_datetime(df["entry_date"])
    df["year"] = df["entry_date"].dt.year

    yearly = df.groupby(["driver", "ticker", "year"]).agg(
        trades=("return_pct", "count"),
        total_simple_return_pct=("return_pct", "sum"),
        avg_return_pct=("return_pct", "mean"),
        best_trade_pct=("return_pct", "max"),
        worst_trade_pct=("return_pct", "min"),
        wins=("return_pct", lambda x: (x > 0).sum()),
        losses=("return_pct", lambda x: (x <= 0).sum()),
    ).reset_index()

    yearly["win_rate"] = yearly["wins"] / yearly["trades"] * 100

    return yearly.round(2)


# =====================================================
# MAIN
# =====================================================
def main():
    print("LOAD DRIVER:", DRIVER_PATH)
    driver_df = load_driver_prices()

    print("LOAD STOCK DB:", DB_PATH)
    stock_df = load_stock_prices()

    print("BUILD VALID GOLD EVENTS")
    events = build_valid_driver_events(driver_df)

    if events.empty:
        print("NO VALID GOLD EVENTS")
        return

    print("VALID EVENTS:", len(events))
    print(events.tail(10).to_string(index=False))

    all_trades = []

    for ticker in TICKERS:
        print(f"BACKTEST {ticker}")
        t = backtest_ticker(ticker, events, stock_df)

        if not t.empty:
            all_trades.append(t)

    if not all_trades:
        print("NO TRADES")
        return

    trades = pd.concat(all_trades, ignore_index=True)

    trades["signal_date"] = safe_to_datetime(trades["signal_date"]).dt.strftime("%Y-%m-%d")
    trades["event_date"] = safe_to_datetime(trades["event_date"]).dt.strftime("%Y-%m-%d")
    trades["entry_date"] = safe_to_datetime(trades["entry_date"]).dt.strftime("%Y-%m-%d")
    trades["buy_date"] = safe_to_datetime(trades["buy_date"]).dt.strftime("%Y-%m-%d")
    trades["exit_date"] = safe_to_datetime(trades["exit_date"]).dt.strftime("%Y-%m-%d")
    trades["sell_date"] = safe_to_datetime(trades["sell_date"]).dt.strftime("%Y-%m-%d")

    summary = build_summary(trades)
    yearly = build_yearly(trades)

    summary = summary.sort_values(["score", "profit_factor", "compound_return_pct"], ascending=False)
    trades = trades.sort_values(["ticker", "entry_date"])
    yearly = yearly.sort_values(["ticker", "year"])

    trades.to_csv(TRADES_PATH, index=False)
    summary.to_csv(SUMMARY_PATH, index=False)
    yearly.to_csv(YEARLY_PATH, index=False)

    print(f"SUCCESS CREATE {TRADES_PATH}")
    print(f"SUCCESS CREATE {SUMMARY_PATH}")
    print(f"SUCCESS CREATE {YEARLY_PATH}")

    print("\nSUMMARY:")
    print(summary.to_string(index=False))

    print("\nYEARLY 2026:")
    y2026 = yearly[yearly["year"] == 2026].copy()
    print(y2026.to_string(index=False))


if __name__ == "__main__":
    main()
