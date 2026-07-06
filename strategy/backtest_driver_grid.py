import pandas as pd
from pathlib import Path
from sqlalchemy import create_engine

engine = create_engine("sqlite:///data/market.db")

# ======================
# CONFIG
# ======================

# Driver
DRIVER = "GOLD"

# Universe
TICKERS = [
    "HRTA.JK",
    "MDKA.JK",
    "ANTM.JK",
    "BRMS.JK",
    "PSAB.JK",
]

# Grid Search
LOOKBACKS = [
    1,
    3,
    5,
    10,
]

THRESHOLDS = [
    0.5,
    1.0,
    1.5,
    2.0,
    2.5,
    3.0,
    5.0,
]

HOLDINGS = [
    1,
    2,
    3,
    5,
    10,
]

# Entry Mode
BUY_MODE = "NEXT_DAY"
# BUY_MODE = "SAME_DAY"

# Filter
START_DATE = "2026-01-01"
END_DATE = None

# Signal
COOLDOWN_DAYS = 20

# Capital
CAPITAL_PER_TRADE = 1_000_000
INITIAL_CAPITAL = 1_000_000

# Output
OUTPUT_DIR = Path("data/processed")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

EXPORT_EXCEL = True

# ======================
# LOAD DRIVER DATA
# ======================

drivers = pd.read_csv("data/driver_prices.csv")

drivers["driver_date"] = pd.to_datetime(
    drivers["driver_date"],
    format="mixed",
    errors="coerce",
)

drivers = drivers.dropna(subset=["driver_date"]).copy()

drivers = drivers[
    drivers["driver"] == DRIVER
].copy()

drivers = drivers.sort_values(
    "driver_date"
).reset_index(drop=True)

if START_DATE is not None:
    drivers = drivers[
        drivers["driver_date"] >= START_DATE
    ].copy()

if END_DATE is not None:
    drivers = drivers[
        drivers["driver_date"] <= END_DATE
    ].copy()
    
# ======================
# BUILD EVENTS
# ======================

def build_events(
    drivers,
    lookback,
    threshold,
    cooldown_days,
):
    df = drivers.copy()

    df["driver_change_pct"] = (
        df["value"].pct_change(lookback) * 100
    )

    events = df[
        df["driver_change_pct"] >= threshold
    ].copy()

    events = events.rename(
        columns={
            "driver_date": "event_date"
        }
    )

    events = events.sort_values(
        "event_date"
    ).reset_index(drop=True)

    # ======================
    # APPLY COOLDOWN
    # ======================

    filtered = []

    last_event_date = None

    for _, row in events.iterrows():

        current_date = row["event_date"]

        if last_event_date is None:

            filtered.append(row.to_dict())
            last_event_date = current_date
            continue

        days_since_last = (
            current_date - last_event_date
        ).days

        if days_since_last > cooldown_days:

            filtered.append(row.to_dict())
            last_event_date = current_date

    events = pd.DataFrame(filtered)

    if not events.empty:

        events = events.sort_values(
            "event_date"
        ).reset_index(drop=True)

    print(
        f"LB={lookback} "
        f"TH={threshold} "
        f"Events={len(events)}"
    )
    return events

# ======================
# BACKTEST FUNCTION
# ======================

def run_backtest_for_ticker(
    ticker,
    events,
    lookback,
    threshold,
    holding,
):
    prices = pd.read_sql(
        f"""
        SELECT trade_date, ticker, close_price
        FROM daily_prices
        WHERE ticker = '{ticker}'
        ORDER BY trade_date
        """,
        engine,
    )

    if prices.empty:
        print(f"WARNING: Tidak ada data harga untuk {ticker}")
        return pd.DataFrame()

    prices["trade_date"] = pd.to_datetime(
        prices["trade_date"],
        format="mixed",
        errors="coerce",
    )

    prices = prices.dropna(
        subset=["trade_date"]
    ).copy()

    prices = prices.sort_values(
        "trade_date"
    ).reset_index(drop=True)

    if START_DATE is not None:
        prices = prices[
            prices["trade_date"] >= START_DATE
        ].copy()

    if END_DATE is not None:
        prices = prices[
            prices["trade_date"] <= END_DATE
        ].copy()

    if prices.empty:
        return pd.DataFrame()

    first_stock_date = prices["trade_date"].min()
    last_stock_date = prices["trade_date"].max()

    # ANTM data valid mulai 2012
    if ticker == "ANTM.JK":
        first_stock_date = max(
            first_stock_date,
            pd.Timestamp("2012-03-02"),
        )

    valid_events = events[
        (events["event_date"] >= first_stock_date)
        & (events["event_date"] <= last_stock_date)
    ].copy()

    rows = []

    for _, event in valid_events.iterrows():

        stock_after_event = prices[
            prices["trade_date"] >= event["event_date"]
        ].reset_index(drop=True)

        if stock_after_event.empty:
            continue

        # ==========================
        # BUY MODE
        # ==========================

        if BUY_MODE == "SAME_DAY":
            buy_idx = 0

        elif BUY_MODE == "NEXT_DAY":
            buy_idx = 1

        else:
            raise ValueError(
                "BUY_MODE harus SAME_DAY atau NEXT_DAY"
            )

        sell_idx = buy_idx + holding

        if len(stock_after_event) <= sell_idx:
            continue

        buy_date = stock_after_event.loc[
            buy_idx,
            "trade_date",
        ]

        sell_date = stock_after_event.loc[
            sell_idx,
            "trade_date",
        ]

        buy_price = stock_after_event.loc[
            buy_idx,
            "close_price",
        ]

        sell_price = stock_after_event.loc[
            sell_idx,
            "close_price",
        ]

        if buy_price <= 0:
            continue

        shares = CAPITAL_PER_TRADE / buy_price

        ending_value = shares * sell_price

        profit_rp = (
            ending_value
            - CAPITAL_PER_TRADE
        )

        return_pct = (
            profit_rp
            / CAPITAL_PER_TRADE
            * 100
        )

        rows.append({
            "driver": DRIVER,
            "ticker": ticker,
            "lookback": lookback,
            "threshold": threshold,
            "holding": holding,
            "event_date": event["event_date"],
            "driver_change_pct": round(event["driver_change_pct"], 2),
            "buy_date": buy_date,
            "sell_date": sell_date,
            "buy_price": buy_price,
            "sell_price": sell_price,
            "capital": CAPITAL_PER_TRADE,
            "shares": round(shares, 2),
            "buy_mode": BUY_MODE,
            "return_pct": round(return_pct, 2),
            "profit_rp": round(profit_rp, 0),
            "ending_value": round(ending_value, 0),
        })

    return pd.DataFrame(rows)

# ========================
# YEAR BY YEAR ATTRIBUTION
# ========================

def year_by_year_attribution(
    trade_df,
):
    if trade_df.empty:
        return pd.DataFrame()

    df = trade_df.copy()

    df["buy_date"] = pd.to_datetime(
        df["buy_date"]
    )

    df["year"] = (
        df["buy_date"]
        .dt.year
    )

    results = []

    group_cols = [
        "driver",
        "ticker",
        "lookback",
        "threshold",
        "holding",
    ]

    for keys, dft in df.groupby(group_cols):

        driver, ticker, lookback, threshold, holding = keys

        capital = INITIAL_CAPITAL

        for year, dfy in dft.groupby("year"):

            capital_start = capital

            for r in dfy["return_pct"]:
                capital *= (
                    1 + r / 100
                )

            capital_end = capital

            win = (
                dfy["return_pct"] > 0
            ).sum()

            lose = (
                dfy["return_pct"] <= 0
            ).sum()

            results.append({

                "driver": driver,

                "ticker": ticker,

                "lookback": lookback,

                "threshold": threshold,

                "holding": holding,

                "year": year,

                "event_count": len(dfy),

                "win_count": win,

                "lose_count": lose,

                "win_rate_pct": round(
                    win / len(dfy) * 100,
                    2,
                ),

                "avg_return_pct": round(
                    dfy["return_pct"].mean(),
                    2,
                ),

                "best_return_pct": round(
                    dfy["return_pct"].max(),
                    2,
                ),

                "worst_return_pct": round(
                    dfy["return_pct"].min(),
                    2,
                ),

                "annual_return_pct": round(
                    (
                        capital_end
                        / capital_start
                        - 1
                    ) * 100,
                    2,
                ),

                "capital_end_year": round(
                    capital_end,
                    0,
                ),

            })

    return pd.DataFrame(results)

# =====================
# SUMMARY
# ======================

def build_summary(
    trade_df,
):
    if trade_df.empty:
        return pd.DataFrame()

    rows = []

    group_cols = [
        "driver",
        "ticker",
        "lookback",
        "threshold",
        "holding",
    ]

    for keys, dft in trade_df.groupby(group_cols):

        driver, ticker, lookback, threshold, holding = keys

        dft = dft.sort_values(
            "buy_date"
        ).reset_index(drop=True)

        total_trades = len(dft)

        winning_trades = (
            dft["profit_rp"] > 0
        ).sum()

        losing_trades = (
            dft["profit_rp"] < 0
        ).sum()

        gross_profit = dft.loc[
            dft["profit_rp"] > 0,
            "profit_rp"
        ].sum()

        gross_loss = abs(
            dft.loc[
                dft["profit_rp"] < 0,
                "profit_rp"
            ].sum()
        )

        if gross_loss == 0:
             profit_factor = float("inf")
        else:
            profit_factor = gross_profit / gross_loss

        capital = INITIAL_CAPITAL

        equity = [capital]

        for r in dft["return_pct"]:

            capital *= (
                1 + r / 100
            )

            equity.append(capital)

        compound_return = (
            capital /
            INITIAL_CAPITAL
            - 1
        ) * 100

        peak = equity[0]

        max_dd = 0

        for value in equity:

            if value > peak:
                peak = value

            dd = (
                peak - value
            ) / peak * 100

            if dd > max_dd:
                max_dd = dd

        expectancy = dft[
            "return_pct"
        ].mean()

        rows.append({

            "driver": driver,

            "ticker": ticker,

            "lookback": lookback,

            "threshold": threshold,

            "holding": holding,

            "events": total_trades,

            "winrate": round(
                winning_trades /
                total_trades * 100,
                2,
            ),

            "avg_return": round(
                expectancy,
                2,
            ),

            "compound": round(
                compound_return,
                2,
            ),

            "profit_factor": round(
                    profit_factor,
                    2,
                ),

            "mdd": round(
                max_dd,
                2,
            ),

            "expectancy": round(
                expectancy,
                2,
            ),
        })

    summary = pd.DataFrame(rows)

    summary = summary.sort_values(
        [
            "profit_factor",
            "compound",
        ],
        ascending=False,
    ).reset_index(drop=True)

    return summary

# ======================
# RUN
# ======================

trade_all = []
summary_all = []

for lookback in LOOKBACKS:

    print(f"\nLOOKBACK = {lookback}")

    for threshold in THRESHOLDS:

        events = build_events(
            drivers,
            lookback,
            threshold,
            COOLDOWN_DAYS,
        )

        if events.empty:
            continue

        print(
            f"Threshold {threshold}% | Events = {len(events)}"
        )

        for holding in HOLDINGS:

            all_trades = []

            for ticker in TICKERS:

                print(
                    f"  {ticker} | HOLD={holding}"
                )

                ticker_trades = run_backtest_for_ticker(
                    ticker=ticker,
                    events=events,
                    lookback=lookback,
                    threshold=threshold,
                    holding=holding,
                )

                if ticker_trades.empty:
                    continue

                all_trades.append(
                    ticker_trades
                )

            if len(all_trades) == 0:
                continue

            trade_df = pd.concat(
                all_trades,
                ignore_index=True,
            )

            summary_df = build_summary(
                trade_df,
            )

            trade_all.append(
                trade_df
            )

            summary_all.append(
                summary_df
            )

if len(trade_all) == 0:

    print("Tidak ada trade.")
    sys.exit()

trade_df = pd.concat(
    trade_all,
    ignore_index=True,
)

summary_df = pd.concat(
    summary_all,
    ignore_index=True,
)

# ======================
# GLOBAL RANKING
# ======================

summary_df = summary_df.sort_values(
    by=[
        "profit_factor",
        "compound",
    ],
    ascending=[
        False,
        False,
    ],
    na_position="last",
).reset_index(drop=True)

summary_df["ranking"] = (
    summary_df.index + 1
)

yearly_df = year_by_year_attribution(
    trade_df
)

# ======================
# SAVE SQLITE
# ======================

# ======================
# SAVE SQLITE
# ======================

summary_df.to_sql(
    "driver_grid_summary",
    engine,
    if_exists="replace",
    index=False,
)

trade_df.to_sql(
    "driver_grid_trade_detail",
    engine,
    if_exists="replace",
    index=False,
)

yearly_df.to_sql(
    "driver_grid_yearly",
    engine,
    if_exists="replace",
    index=False,
)

# ======================
# SAVE CSV
# ======================

# ======================
# SAVE CSV
# ======================

summary_df.to_csv(
    OUTPUT_DIR / "driver_grid_summary.csv",
    index=False,
)

trade_df.to_csv(
    OUTPUT_DIR / "driver_grid_trade_detail.csv",
    index=False,
)

yearly_df.to_csv(
    OUTPUT_DIR / "driver_grid_yearly.csv",
    index=False,
)

# ======================
# SAVE EXCEL OPTIONAL
# ======================

if EXPORT_EXCEL:

    with pd.ExcelWriter(
        OUTPUT_DIR / "driver_grid_result.xlsx",
        engine="openpyxl",
    ) as writer:

        summary_df.to_excel(
            writer,
            sheet_name="Summary",
            index=False,
        )

        yearly_df.to_excel(
            writer,
            sheet_name="Yearly",
            index=False,
        )

        trade_df.to_excel(
            writer,
            sheet_name="Trades",
            index=False,
        )
        
# ======================
# PRINT
# ======================

print("\n")
print("=" * 70)
print("BACKTEST FINISHED")
print("=" * 70)

print(f"Driver      : {DRIVER}")
print(f"Trades      : {len(trade_df):,}")
print(f"Summary Row : {len(summary_df):,}")
print(f"Yearly Row  : {len(yearly_df):,}")

print("\nTOP 20 RESULT")
print("=" * 70)

cols = [
    "ranking",
    "ticker",
    "lookback",
    "threshold",
    "holding",
    "events",
    "winrate",
    "compound",
    "profit_factor",
    "mdd",
]

print(
    summary_df[
    [c for c in cols if c in summary_df.columns]
    ]
    .head(20)
    .to_string(index=False)
)

print("\nOutput Files")
print("-" * 70)

print(
    OUTPUT_DIR / "driver_grid_summary.csv"
)

print(
    OUTPUT_DIR / "driver_grid_trade_detail.csv"
)

print(
    OUTPUT_DIR / "driver_grid_yearly.csv"
)

if EXPORT_EXCEL:

    print(
        OUTPUT_DIR / "driver_grid_result.xlsx"
    )

print("\nDONE.")