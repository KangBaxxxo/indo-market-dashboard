import pandas as pd
from sqlalchemy import create_engine

engine = create_engine("sqlite:///data/market.db")

# ======================
# CONFIG
# ======================

DRIVER = "GOLD"

TICKERS = [
    "HRTA.JK",
    "MDKA.JK",
    "ANTM.JK",
    "BRMS.JK",
    "PSAB.JK",
]

LOOKBACK = 10
THRESHOLD = 5.0
HORIZON = 10
COOLDOWN_DAYS = 20

CAPITAL_PER_TRADE = 1_000_000
INITIAL_CAPITAL = 1_000_000

EXPORT_EXCEL = True

# ======================
# LOAD DRIVER DATA
# ======================

drivers = pd.read_csv("data/driver_prices.csv")
drivers["driver_date"] = pd.to_datetime(
    drivers["driver_date"],
    format="mixed",
    errors="coerce"
)

drivers = drivers.dropna(subset=["driver_date"]).copy()

drivers = drivers[drivers["driver"] == DRIVER].copy()
drivers = drivers.sort_values("driver_date").reset_index(drop=True)

# ======================
# BUILD GOLD TRIGGER
# ======================

drivers["driver_change_pct"] = drivers["value"].pct_change(LOOKBACK) * 100

events = drivers[drivers["driver_change_pct"] >= THRESHOLD].copy()
events = events.rename(columns={"driver_date": "event_date"})
events = events.sort_values("event_date").reset_index(drop=True)

events["prev_event_date"] = events["event_date"].shift(1)
events["days_since_prev"] = (
    events["event_date"] - events["prev_event_date"]
).dt.days

events = events[
    events["days_since_prev"].isna()
    | (events["days_since_prev"] > COOLDOWN_DAYS)
].copy()

events = events.sort_values("event_date").reset_index(drop=True)

# ======================
# BACKTEST FUNCTION
# ======================

def run_backtest_for_ticker(ticker):
    prices = pd.read_sql(
        f"""
        SELECT trade_date, ticker, close_price
        FROM daily_prices
        WHERE ticker = '{ticker}'
        ORDER BY trade_date
        """,
        engine
    )

    if prices.empty:
        print(f"WARNING: Tidak ada data harga untuk {ticker}")
        return pd.DataFrame()

    prices["trade_date"] = pd.to_datetime(
        prices["trade_date"],
        format="mixed",
        errors="coerce"
    )

    prices = prices.dropna(subset=["trade_date"]).copy()
    prices = prices.sort_values("trade_date").reset_index(drop=True)

    first_stock_date = prices["trade_date"].min()
    last_stock_date = prices["trade_date"].max()

    # Special rule:
    # ANTM data sebelum 2021 kita percaya dari Investing.com.
    # File Investing yang tersedia mulai 2012-03-02.
    if ticker == "ANTM.JK":
        first_stock_date = max(
            first_stock_date,
            pd.Timestamp("2012-03-02")
        )

    valid_events = events[
        (events["event_date"] >= first_stock_date)
        & (events["event_date"] <= last_stock_date)
    ].copy()

    rows = []

    for _, event in valid_events.iterrows():
        event_date = event["event_date"]

        stock_after_event = prices[
            prices["trade_date"] >= event_date
        ].reset_index(drop=True)

        if stock_after_event.empty:
            continue

        if len(stock_after_event) <= HORIZON:
            continue

        buy_date = stock_after_event.loc[0, "trade_date"]
        sell_date = stock_after_event.loc[HORIZON, "trade_date"]

        buy_price = stock_after_event.loc[0, "close_price"]
        sell_price = stock_after_event.loc[HORIZON, "close_price"]

        if buy_price <= 0:
            continue

        shares = CAPITAL_PER_TRADE / buy_price
        ending_value = shares * sell_price
        profit_rp = ending_value - CAPITAL_PER_TRADE
        return_pct = profit_rp / CAPITAL_PER_TRADE * 100

        rows.append({
            "driver": DRIVER,
            "ticker": ticker,
            "event_date": event_date,
            "driver_change_pct": round(event["driver_change_pct"], 2),
            "buy_date": buy_date,
            "sell_date": sell_date,
            "buy_price": buy_price,
            "sell_price": sell_price,
            "capital": CAPITAL_PER_TRADE,
            "shares": round(shares, 2),
            "return_pct": round(return_pct, 2),
            "profit_rp": round(profit_rp, 0),
            "ending_value": round(ending_value, 0),
        })

    return pd.DataFrame(rows)

# ======================
# YEAR BY YEAR ATTRIBUTION
# ======================

def year_by_year_attribution(trade_df):
    df = trade_df.copy()
    df["buy_date"] = pd.to_datetime(df["buy_date"])
    df["year"] = df["buy_date"].dt.year
    df = df.sort_values(["ticker", "buy_date"]).reset_index(drop=True)

    results = []

    for ticker, dft in df.groupby("ticker"):
        capital = INITIAL_CAPITAL

        for year, dfy in dft.groupby("year"):
            capital_start_year = capital

            event_count = len(dfy)
            win_count = (dfy["return_pct"] > 0).sum()
            lose_count = (dfy["return_pct"] <= 0).sum()

            for r in dfy["return_pct"]:
                capital *= 1 + (r / 100)

            capital_end_year = capital
            annual_return_pct = (
                capital_end_year / capital_start_year - 1
            ) * 100

            results.append({
                "driver": DRIVER,
                "ticker": ticker,
                "year": year,
                "event_count": event_count,
                "annual_return_pct": round(annual_return_pct, 2),
                "capital_end_year": round(capital_end_year, 0),
                "win_count": win_count,
                "lose_count": lose_count,
                "win_rate_pct": round(win_count / event_count * 100, 2),
                "avg_return_pct": round(dfy["return_pct"].mean(), 2),
                "best_return_pct": round(dfy["return_pct"].max(), 2),
                "worst_return_pct": round(dfy["return_pct"].min(), 2),
            })

    return pd.DataFrame(results).sort_values(["ticker", "year"]).reset_index(drop=True)

# ======================
# SUMMARY
# ======================

def build_summary(trade_df):
    rows = []

    for ticker, dft in trade_df.groupby("ticker"):
        dft = dft.sort_values("buy_date").reset_index(drop=True)

        total_trades = len(dft)
        winning_trades = (dft["profit_rp"] > 0).sum()
        losing_trades = (dft["profit_rp"] < 0).sum()

        gross_profit = dft.loc[dft["profit_rp"] > 0, "profit_rp"].sum()
        gross_loss = abs(dft.loc[dft["profit_rp"] < 0, "profit_rp"].sum())
        profit_factor = gross_profit / gross_loss if gross_loss != 0 else None

        compound_capital = INITIAL_CAPITAL
        for r in dft["return_pct"]:
            compound_capital *= 1 + (r / 100)

        compound_return_pct = (
            compound_capital / INITIAL_CAPITAL - 1
        ) * 100

        rows.append({
            "driver": DRIVER,
            "ticker": ticker,
            "trigger": f"{DRIVER} >= +{THRESHOLD}% in {LOOKBACK}D",
            "cooldown_days": COOLDOWN_DAYS,
            "holding_period": f"H+{HORIZON}",
            "capital_per_trade": CAPITAL_PER_TRADE,
            "initial_compound_capital": INITIAL_CAPITAL,
            "total_trades": total_trades,
            "winning_trades": winning_trades,
            "losing_trades": losing_trades,
            "win_rate_pct": round(winning_trades / total_trades * 100, 2),
            "avg_return_pct": round(dft["return_pct"].mean(), 2),
            "median_return_pct": round(dft["return_pct"].median(), 2),
            "best_return_pct": round(dft["return_pct"].max(), 2),
            "worst_return_pct": round(dft["return_pct"].min(), 2),
            "total_capital_deployed": total_trades * CAPITAL_PER_TRADE,
            "total_profit_rp": round(dft["profit_rp"].sum(), 0),
            "compound_capital_end": round(compound_capital, 0),
            "compound_return_pct": round(compound_return_pct, 2),
            "profit_factor": round(profit_factor, 2) if profit_factor is not None else None,
            "first_trade_date": dft["buy_date"].min(),
            "last_trade_date": dft["buy_date"].max(),
        })

    return pd.DataFrame(rows).sort_values("compound_return_pct", ascending=False)

# ======================
# RUN
# ======================

all_trades = []

for ticker in TICKERS:
    print(f"Running backtest for {ticker}...")
    ticker_trades = run_backtest_for_ticker(ticker)

    if not ticker_trades.empty:
        all_trades.append(ticker_trades)

if len(all_trades) == 0:
    print("Tidak ada trade.")
    exit()

trade_df = pd.concat(all_trades, ignore_index=True)
trade_df = trade_df.sort_values(["ticker", "buy_date"]).reset_index(drop=True)

summary_df = build_summary(trade_df)
yearly_df = year_by_year_attribution(trade_df)

# ======================
# SAVE SQLITE
# ======================

trade_df.to_sql(
    "gold_beneficiaries_backtest_trades",
    engine,
    if_exists="replace",
    index=False
)

summary_df.to_sql(
    "gold_beneficiaries_backtest_summary",
    engine,
    if_exists="replace",
    index=False
)

yearly_df.to_sql(
    "gold_beneficiaries_year_by_year",
    engine,
    if_exists="replace",
    index=False
)

# ======================
# SAVE CSV
# ======================

summary_df.to_csv("gold_beneficiaries_summary.csv", index=False)
yearly_df.to_csv("gold_beneficiaries_year_by_year.csv", index=False)
trade_df.to_csv("gold_beneficiaries_trade_detail.csv", index=False)

# ======================
# SAVE EXCEL OPTIONAL
# ======================

if EXPORT_EXCEL:
    try:
        excel_file = "gold_beneficiaries_year_by_year.xlsx"

        with pd.ExcelWriter(excel_file, engine="openpyxl") as writer:
            summary_df.to_excel(writer, sheet_name="summary", index=False)
            yearly_df.to_excel(writer, sheet_name="year_by_year", index=False)
            trade_df.to_excel(writer, sheet_name="trade_detail", index=False)

        print(f"Saved Excel file: {excel_file}")

    except ModuleNotFoundError:
        print()
        print("WARNING: openpyxl belum terinstall.")
        print("Excel tidak dibuat, tapi CSV dan SQLite tetap aman.")
        print("Install kalau mau Excel:")
        print("python -m pip install openpyxl")

# ======================
# PRINT
# ======================

print()
print("=== BACKTEST SUMMARY ===")
print(summary_df.to_string(index=False))

print()
print("=== YEAR BY YEAR ATTRIBUTION ===")
print(yearly_df.to_string(index=False))

print()
print("=== TRADE DETAIL SAMPLE ===")
print(trade_df.head(20).to_string(index=False))

print()
print("Saved SQLite table: gold_beneficiaries_backtest_trades")
print("Saved SQLite table: gold_beneficiaries_backtest_summary")
print("Saved SQLite table: gold_beneficiaries_year_by_year")

print()
print("Saved CSV file: gold_beneficiaries_summary.csv")
print("Saved CSV file: gold_beneficiaries_year_by_year.csv")
print("Saved CSV file: gold_beneficiaries_trade_detail.csv")