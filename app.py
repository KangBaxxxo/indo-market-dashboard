import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from sqlalchemy import create_engine

st.set_page_config(
    page_title="Indonesia Market Dashboard",
    layout="wide"
)

engine = create_engine("sqlite:///data/market.db")

# ======================
# LOAD DATA
# ======================

latest_df = pd.read_sql(
    "SELECT * FROM latest_snapshot",
    engine
)

latest_df["trade_date"] = pd.to_datetime(latest_df["trade_date"])

# ======================
# Driver Opportunities
# ======================
page = st.sidebar.selectbox(
    "Menu",
    [
        "Dashboard",
        "Driver Opportunities",
        "Economic Intelligence"
    ]
)

# ======================
# ECONOMIC INTELLIGENCE
# ======================

if page == "Economic Intelligence":
    st.title("Economic Intelligence")

    st.caption(
        "Final pattern: GOLD naik >= 5% dalam 10 hari, "
        "cooldown 20 hari, hold 10 hari. Target utama: HRTA.JK"
    )

    TARGET_TICKER = "HRTA.JK"
    DRIVER = "GOLD"
    LOOKBACK = 10
    THRESHOLD = 5.0
    COOLDOWN_DAYS = 20
    HOLD_DAYS = 10

    # ======================
    # LOAD DRIVER PRICES
    # ======================

    driver_prices_df = pd.read_csv("data/driver_prices.csv")
    driver_prices_df.columns = (
        driver_prices_df.columns
        .str.strip()
        .str.lower()
    )

    driver_prices_df["driver_date"] = pd.to_datetime(
        driver_prices_df["driver_date"],
        format="mixed",
        errors="coerce"
    )

    driver_prices_df["value"] = pd.to_numeric(
        driver_prices_df["value"],
        errors="coerce"
    )

    gold_df = driver_prices_df[
        driver_prices_df["driver"].str.upper() == DRIVER
    ].copy()

    gold_df = gold_df.dropna(
        subset=["driver_date", "value"]
    ).copy()

    gold_df = gold_df.sort_values(
        "driver_date"
    ).reset_index(drop=True)

    gold_df["gold_10d_change_pct"] = (
        gold_df["value"].pct_change(LOOKBACK) * 100
    )

    latest_gold = gold_df.dropna(
        subset=["gold_10d_change_pct"]
    ).tail(1)

    if latest_gold.empty:
        st.warning("Data GOLD belum cukup untuk menghitung 10D change.")
        st.stop()

    latest_gold_row = latest_gold.iloc[0]

    latest_gold_date = latest_gold_row["driver_date"]
    latest_gold_value = latest_gold_row["value"]
    latest_gold_change = latest_gold_row["gold_10d_change_pct"]

    # ======================
    # BUILD HISTORICAL GOLD EVENTS
    # ======================

    gold_events = gold_df[
        gold_df["gold_10d_change_pct"] >= THRESHOLD
    ].copy()

    gold_events = gold_events.rename(
        columns={"driver_date": "event_date"}
    )

    gold_events = gold_events.sort_values(
        "event_date"
    ).reset_index(drop=True)

    gold_events["prev_event_date"] = (
        gold_events["event_date"].shift(1)
    )

    gold_events["days_since_prev"] = (
        gold_events["event_date"]
        - gold_events["prev_event_date"]
    ).dt.days

    gold_events = gold_events[
        gold_events["days_since_prev"].isna()
        | (gold_events["days_since_prev"] > COOLDOWN_DAYS)
    ].copy()

    last_signal_date = None
    days_since_last_signal = None

    if not gold_events.empty:
        last_signal_date = gold_events["event_date"].max()
        days_since_last_signal = (
            latest_gold_date - last_signal_date
        ).days

    signal_active = latest_gold_change >= THRESHOLD

    cooldown_active = (
        days_since_last_signal is not None
        and days_since_last_signal <= COOLDOWN_DAYS
    )

    # ======================
    # SIGNAL STATUS
    # ======================

    st.subheader("Gold Today")

    gold_widget_df = gold_df.copy()
    gold_widget_df = gold_widget_df.sort_values("driver_date").reset_index(drop=True)

    gold_widget_df["prev_value"] = gold_widget_df["value"].shift(1)
    gold_widget_df["today_change_pct"] = (
        (gold_widget_df["value"] - gold_widget_df["prev_value"])
        / gold_widget_df["prev_value"]
        * 100
    )

    gold_widget_df["gold_10d_change_pct"] = (
        gold_widget_df["value"].pct_change(LOOKBACK) * 100
    )

    latest_gold_widget = gold_widget_df.dropna(
        subset=["value", "today_change_pct", "gold_10d_change_pct"]
    ).tail(1)

    if latest_gold_widget.empty:
        st.warning("Data GOLD belum cukup untuk widget Gold Today.")
    else:
        gold_row = latest_gold_widget.iloc[0]

        gold_today_date = gold_row["driver_date"]
        gold_today_value = gold_row["value"]
        gold_today_change_pct = gold_row["today_change_pct"]
        gold_10d_change_pct = gold_row["gold_10d_change_pct"]

        signal_status = (
        "ACTIVE"
        if gold_10d_change_pct >= THRESHOLD
        else "WAIT"
        )

        col1, col2, col3, col4 = st.columns(4)

        col1.metric(
            "Gold Date",
            gold_today_date.strftime("%Y-%m-%d")
        )

        col2.metric(
            "Gold Price",
            f"{gold_today_value:,.2f}"
        )

        col3.metric(
            "Gold Today",
            f"{gold_today_change_pct:.2f}%"
        )

        col4.metric(
            "Gold 10D",
            f"{gold_10d_change_pct:.2f}%",
            delta=signal_status
        )

    if signal_active:
        st.success(
            f"ACTIVE SIGNAL: GOLD naik {latest_gold_change:.2f}% "
            f"dalam {LOOKBACK} hari. Watch {TARGET_TICKER}."
        )
    else:
        st.info(
            f"WAIT: GOLD baru naik {latest_gold_change:.2f}% "
            f"dalam {LOOKBACK} hari. Belum tembus threshold +{THRESHOLD}%."
        )

    if last_signal_date is not None:
        st.caption(
            f"Last valid GOLD signal: {last_signal_date.strftime('%Y-%m-%d')} "
            f"({days_since_last_signal} hari lalu)"
        )

        if cooldown_active:
            st.warning(
                f"Cooldown aktif: last signal masih dalam "
                f"{COOLDOWN_DAYS} hari."
            )
        else:
            st.success("Cooldown clear: boleh tunggu signal baru.")

    # ======================
    # GOLD DRIVEN WATCHLIST
    # ======================

    def show_gold_driven_watchlist(engine):
        st.subheader("Gold Driven Stock Watchlist")

        gold_watchlist = [
            "HRTA.JK",
            "MDKA.JK",
            "BRMS.JK",
            "ANTM.JK",
            "EMAS.JK",
        ]

        watchlist_price_df = pd.read_sql(
            """
            SELECT
                trade_date,
                ticker,
                close_price,
                volume
            FROM daily_prices
            WHERE ticker IN (?, ?, ?, ?, ?)
            ORDER BY ticker, DATE(trade_date)
            """,
            engine,
            params=tuple(gold_watchlist)
        )

        if watchlist_price_df.empty:
            st.warning("Belum ada data harga untuk gold watchlist.")
            return

        watchlist_price_df["trade_date"] = pd.to_datetime(
            watchlist_price_df["trade_date"],
            format="mixed",
            errors="coerce"
        )

        watchlist_price_df = watchlist_price_df.dropna(
            subset=["trade_date", "close_price"]
        ).copy()

        watchlist_price_df = watchlist_price_df.sort_values(
            ["ticker", "trade_date"]
        ).reset_index(drop=True)

        watchlist_price_df["prev_close"] = (
            watchlist_price_df
            .groupby("ticker")["close_price"]
            .shift(1)
        )

        watchlist_price_df["prev_close_date"] = (
            watchlist_price_df
            .groupby("ticker")["trade_date"]
            .shift(1)
        )

        watchlist_price_df["change_pct"] = (
            (
                watchlist_price_df["close_price"]
                - watchlist_price_df["prev_close"]
            )
            / watchlist_price_df["prev_close"]
            * 100
        )

        gold_watchlist_today = (
            watchlist_price_df
            .dropna(subset=["close_price"])
            .groupby("ticker")
            .tail(1)
            .copy()
        )

        def stock_status(change_pct):
            if pd.isna(change_pct):
                return "No Data"
            elif change_pct > 0:
                return "Up"
            elif change_pct < 0:
                return "Down"
            else:
                return "Flat"

        gold_watchlist_today["status"] = (
            gold_watchlist_today["change_pct"]
            .apply(stock_status)
        )

        gold_watchlist_today["role"] = gold_watchlist_today["ticker"].map({
            "HRTA.JK": "Primary Target",
            "MDKA.JK": "Secondary Watchlist",
            "BRMS.JK": "High Beta Watchlist",
            "ANTM.JK": "Cyclical Watchlist",
            "EMAS.JK": "New Gold Watchlist",
        })

        gold_watchlist_today["last_close_date"] = (
            gold_watchlist_today["trade_date"]
            .dt.strftime("%Y-%m-%d")
        )

        gold_watchlist_today["prev_close_date"] = (
            gold_watchlist_today["prev_close_date"]
            .dt.strftime("%Y-%m-%d")
        )

        gold_watchlist_today["change_pct"] = (
            gold_watchlist_today["change_pct"]
            .round(2)
        )

        gold_watchlist_today = gold_watchlist_today[
            [
                "ticker",
                "role",
                "last_close_date",
                "close_price",
                "prev_close_date",
                "prev_close",
                "change_pct",
                "volume",
                "status",
            ]
        ].copy()

        gold_watchlist_today = gold_watchlist_today.rename(
            columns={
                "close_price": "last_close",
            }
        )

        st.dataframe(
            gold_watchlist_today,
            use_container_width=True
        )

    show_gold_driven_watchlist(engine)
    
    # ======================
    # RULE CARD
    # ======================

    st.subheader("Final Rule")

    rule_df = pd.DataFrame([
        {
            "item": "Driver",
            "value": DRIVER
        },
        {
            "item": "Trigger",
            "value": f"{DRIVER} >= +{THRESHOLD}% dalam {LOOKBACK} hari"
        },
        {
            "item": "Cooldown",
            "value": f"{COOLDOWN_DAYS} hari"
        },
        {
            "item": "Holding Period",
            "value": f"{HOLD_DAYS} trading days"
        },
        {
            "item": "Primary Target",
            "value": TARGET_TICKER
        },
        {
            "item": "Optional Watchlist",
            "value": "MDKA.JK, BRMS.JK, ANTM.JK"
        }
    ])

    st.dataframe(
        rule_df,
        use_container_width=True
    )

    # ======================
    # LOAD BACKTEST RESULT
    # ======================

    try:
        summary_df = pd.read_sql(
            """
            SELECT *
            FROM gold_beneficiaries_backtest_summary
            WHERE ticker = 'HRTA.JK'
            """,
            engine
        )

        yearly_df = pd.read_sql(
            """
            SELECT *
            FROM gold_beneficiaries_year_by_year
            WHERE ticker = 'HRTA.JK'
            ORDER BY year
            """,
            engine
        )

        trade_df = pd.read_sql(
            """
            SELECT *
            FROM gold_beneficiaries_backtest_trades
            WHERE ticker = 'HRTA.JK'
            ORDER BY buy_date
            """,
            engine
        )

    except Exception as e:
        st.error(
            "Backtest table belum tersedia. "
            "Jalankan dulu backtest_gold.py."
        )
        st.code(str(e))
        st.stop()

    if summary_df.empty:
        st.warning(
            "Data summary HRTA belum tersedia di "
            "gold_beneficiaries_backtest_summary."
        )
        st.stop()

    summary_row = summary_df.iloc[0]

    # ======================
    # HRTA PERFORMANCE
    # ======================

    st.subheader("HRTA Historical Performance")

    perf1, perf2, perf3, perf4 = st.columns(4)

    perf1.metric(
        "Compound Return",
        f"{summary_row['compound_return_pct']:.2f}%"
    )

    perf2.metric(
        "Win Rate",
        f"{summary_row['win_rate_pct']:.2f}%"
    )

    perf3.metric(
        "Profit Factor",
        f"{summary_row['profit_factor']:.2f}"
    )

    perf4.metric(
        "Total Trades",
        int(summary_row["total_trades"])
    )

    perf5, perf6, perf7, perf8 = st.columns(4)

    perf5.metric(
        "Avg Return",
        f"{summary_row['avg_return_pct']:.2f}%"
    )

    perf6.metric(
        "Median Return",
        f"{summary_row['median_return_pct']:.2f}%"
    )

    perf7.metric(
        "Best Trade",
        f"{summary_row['best_return_pct']:.2f}%"
    )

    perf8.metric(
        "Worst Trade",
        f"{summary_row['worst_return_pct']:.2f}%"
    )

    # ======================
    # YEARLY ATTRIBUTION
    # ======================

    st.subheader("HRTA Year-by-Year Attribution")

    if yearly_df.empty:
        st.warning("Yearly attribution HRTA belum tersedia.")
    else:
        st.dataframe(
            yearly_df,
            use_container_width=True
        )

        fig_yearly = go.Figure()

        fig_yearly.add_trace(
            go.Bar(
                x=yearly_df["year"],
                y=yearly_df["annual_return_pct"],
                name="Annual Return %"
            )
        )

        fig_yearly.update_layout(
            title="HRTA Annual Return Attribution",
            xaxis_title="Year",
            yaxis_title="Annual Return %",
            height=450
        )

        st.plotly_chart(
            fig_yearly,
            use_container_width=True
        )

    # ======================
    # TRADE DETAIL
    # ======================

    st.subheader("HRTA Trade Detail")

    if trade_df.empty:
        st.warning("Trade detail HRTA belum tersedia.")
    else:
        show_cols = [
            "event_date",
            "driver_change_pct",
            "buy_date",
            "sell_date",
            "buy_price",
            "sell_price",
            "return_pct",
            "profit_rp",
            "ending_value"
        ]

        show_cols = [
            c for c in show_cols
            if c in trade_df.columns
        ]

        st.dataframe(
            trade_df[show_cols],
            use_container_width=True
        )

    st.stop()
    
# ======================
# ADD STOCK NAME
# ======================

master_df = pd.read_csv("data/stock_master.csv")
master_df.columns = master_df.columns.str.strip().str.lower()

if "ticker" in master_df.columns:
    master_df["ticker"] = master_df["ticker"].astype(str).str.strip()
    master_df["ticker"] = master_df["ticker"].apply(
        lambda x: x if x.endswith(".JK") else x + ".JK"
    )

    latest_df = latest_df.merge(
        master_df,
        on="ticker",
        how="left"
    )

# ======================
# DRIVER SCORE ENGINE
# ======================

mapping_df = pd.read_csv("data/stock_mapping.csv")
driver_df = pd.read_csv("data/driver_scores.csv")

mapping_df.columns = mapping_df.columns.str.strip().str.lower()
driver_df.columns = driver_df.columns.str.strip().str.lower()

mapping_df["ticker"] = mapping_df["ticker"].astype(str).str.strip()
mapping_df["ticker"] = mapping_df["ticker"].apply(
    lambda x: x if x.endswith(".JK") else x + ".JK"
)

mapping_df["driver"] = mapping_df["driver"].astype(str).str.strip().str.upper()
mapping_df["impact_direction"] = mapping_df["impact_direction"].astype(str).str.strip().str.upper()
mapping_df["weight"] = pd.to_numeric(mapping_df["weight"], errors="coerce").fillna(0)

driver_df["driver"] = driver_df["driver"].astype(str).str.strip().str.upper()
driver_df["score"] = pd.to_numeric(driver_df["score"], errors="coerce").fillna(0)

# ======================
# DRIVER STATUS LABEL
# ======================

def driver_status(score):

    if score >= 1:
        return "Bullish"

    elif score <= -1:
        return "Bearish"

    else:
        return "Neutral"


driver_df["status"] = driver_df["score"].apply(driver_status)

score_df = mapping_df.merge(
    driver_df,
    on="driver",
    how="left"
)

score_df["score"] = score_df["score"].fillna(0)

score_df["direction_multiplier"] = score_df["impact_direction"].map({
    "POSITIVE": 1,
    "NEGATIVE": -1
}).fillna(0)

score_df["contribution"] = (
    score_df["weight"]
    * score_df["direction_multiplier"]
    * score_df["score"]
)

stock_score = (
    score_df
    .groupby("ticker")["contribution"]
    .sum()
    .reset_index()
    .rename(columns={"contribution": "driver_score"})
)

latest_df = latest_df.merge(
    stock_score,
    on="ticker",
    how="left"
)

latest_df["driver_score"] = latest_df["driver_score"].fillna(0)

# ======================
# UI FUNCTIONS
# ======================

def show_market_breadth(df):

    if "avg_volume" in df.columns:
        df["is_volume_spike"] = (
            df["volume"] > df["avg_volume"] * 2
        )
    else:
        df["is_volume_spike"] = False

    col1, col2, col3, col4 = st.columns(4)

    col1.metric(
        "Bullish",
        int(df["is_bullish"].sum())
    )

    col2.metric(
        "Oversold",
        int(df["is_oversold"].sum())
    )

    col3.metric(
        "Golden Cross",
        int(df["is_golden_cross"].sum())
    )

    col4.metric(
        "Volume Spike",
        int(df["is_volume_spike"].sum())
    )

def show_screener(df):

    screened_df = df.copy()

    if screener == "RSI Oversold":

        screened_df = screened_df[
            screened_df["is_oversold"] == 1
        ]

    elif screener == "Bullish Trend":

        screened_df = screened_df[
            screened_df["is_bullish"] == 1
        ]

    elif screener == "Golden Cross":

        screened_df = screened_df[
            screened_df["is_golden_cross"] == 1
        ]

    elif screener == "Volume Spike":

        screened_df = screened_df[
            screened_df["is_volume_spike"] == 1
        ]

    show_cols = [
        "ticker",
        "name",
        "stock_name",
        "company_name",
        "sector",
        "trade_date",
        "close_price",
        "volume",
        "ma20",
        "ma50",
        "rsi",
        "ma_distance",
        "driver_score"
    ]

    available_cols = [
        c for c in show_cols
        if c in screened_df.columns
    ]

    with st.expander(
        "Screener Result",
        expanded=False
    ):

        st.dataframe(
            screened_df[available_cols],
            use_container_width=True
        )

def show_driver_ranking(df):

    driver_rank = df.sort_values(
        "driver_score",
        ascending=False
    )

    ranking_cols = [
        "ticker",
        "name",
        "stock_name",
        "company_name",
        "sector",
        "close_price",
        "rsi",
        "ma_distance",
        "driver_score"
    ]

    ranking_cols = [
        c for c in ranking_cols
        if c in driver_rank.columns
    ]

    with st.expander(
        "Driver Score Ranking",
        expanded=False
    ):

        st.dataframe(
            driver_rank[ranking_cols],
            use_container_width=True
        )

def show_momentum(df):

    momentum_df = df.copy()

    momentum_df = momentum_df.sort_values(
        "ma_distance",
        ascending=False
    )

    momentum_cols = [
        "ticker",
        "name",
        "stock_name",
        "company_name",
        "sector",
        "close_price",
        "ma20",
        "ma50",
        "rsi",
        "ma_distance",
        "driver_score"
    ]

    momentum_cols = [
        c for c in momentum_cols
        if c in momentum_df.columns
    ]

    with st.expander(
        "Momentum Ranking",
        expanded=False
    ):

        st.dataframe(
            momentum_df[momentum_cols].head(10),
            use_container_width=True
        )

def show_price_chart(price_df, selected_ticker):

    st.subheader(f"Price Chart - {selected_ticker}")

    fig = go.Figure()

    fig.add_trace(
        go.Candlestick(
            x=price_df["trade_date"],
            open=price_df["open_price"],
            high=price_df["high_price"],
            low=price_df["low_price"],
            close=price_df["close_price"],
            name="Price",
            increasing_line_color="#59CD90",
            decreasing_line_color="#EE6352"
        )
    )

    fig.add_trace(
        go.Scatter(
            x=price_df["trade_date"],
            y=price_df["ma20"],
            mode="lines",
            name="MA20",
            line=dict(color="#3FA7D6")
        )
    )

    fig.add_trace(
        go.Scatter(
            x=price_df["trade_date"],
            y=price_df["ma50"],
            mode="lines",
            name="MA50",
            line=dict(color="#FAC05E")
        )
    )

    fig.update_layout(
        height=600,
        xaxis_rangeslider_visible=False
    )

    st.plotly_chart(
        fig,
        use_container_width=True
    )

def show_driver_breakdown(mapping_df, driver_df, selected_ticker):

    selected_mapping = mapping_df[
        mapping_df["ticker"] == selected_ticker
    ].copy()

    selected_mapping = selected_mapping.merge(
        driver_df,
        on="driver",
        how="left"
    )

    selected_mapping["score"] = (
        selected_mapping["score"]
        .fillna(0)
    )

    selected_mapping["direction_multiplier"] = (
        selected_mapping["impact_direction"]
        .map({
            "POSITIVE": 1,
            "NEGATIVE": -1
        })
        .fillna(0)
    )

    selected_mapping["contribution"] = (
        selected_mapping["weight"]
        * selected_mapping["direction_multiplier"]
        * selected_mapping["score"]
    )

    selected_mapping = selected_mapping.sort_values(
        "contribution",
        ascending=False
    )

    st.subheader(f"Driver Breakdown - {selected_ticker}")

    breakdown_cols = [
        "driver",
        "impact_direction",
        "weight",
        "score",
        "contribution"
    ]

    if selected_mapping.empty:

        st.info("Belum ada mapping driver untuk saham ini.")

    else:

        total_driver_score = selected_mapping["contribution"].sum()

        st.metric(
            "Total Driver Score",
            round(total_driver_score, 2)
        )

        st.dataframe(
            selected_mapping[breakdown_cols],
            use_container_width=True
        )

def show_sector_summary(df):

    if "sector" not in df.columns:
        return

    sector_df = (
        df
        .groupby("sector")
        .agg(
            avg_rsi=("rsi", "mean"),
            total_volume=("volume", "sum"),
            bullish_count=("is_bullish", "sum"),
            stock_count=("ticker", "count"),
            avg_driver_score=("driver_score", "mean")
        )
        .reset_index()
    )

    sector_df["avg_rsi"] = sector_df["avg_rsi"].round(2)
    sector_df["avg_driver_score"] = sector_df[
        "avg_driver_score"
    ].round(2)

    with st.expander(
        "Sector Summary",
        expanded=False
    ):

        st.dataframe(
            sector_df,
            use_container_width=True
        )

def show_economic_drivers(driver_df):

    with st.expander(
        "Economic Drivers Today",
        expanded=False
    ):

        st.dataframe(
            driver_df[
                [
                    "driver",
                    "score",
                    "status"
                ]
            ].sort_values(
                "score",
                ascending=False
            ),
            use_container_width=True
        )


def show_top_beneficiaries(score_df, driver_df):

    with st.expander(
        "Top Beneficiaries per Driver",
        expanded=False
    ):

        selected_driver = st.selectbox(
            "Pilih Driver",
            sorted(driver_df["driver"].dropna().unique())
        )

        beneficiary_df = score_df[
            score_df["driver"] == selected_driver
        ].copy()

        beneficiary_df = beneficiary_df.sort_values(
            "contribution",
            ascending=False
        )

        beneficiary_cols = [
            "ticker",
            "impact_direction",
            "weight",
            "score",
            "contribution"
        ]

        st.dataframe(
            beneficiary_df[beneficiary_cols],
            use_container_width=True
        )


def show_market_regime(
    market_regime,
    top_positive_drivers,
    top_negative_drivers
):

    st.metric(
        "Market Regime",
        market_regime
    )

    with st.expander(
        "Why This Regime?",
        expanded=False
    ):

        st.write("### Top Positive Drivers")

        st.dataframe(
            top_positive_drivers[
                [
                    "driver",
                    "score",
                    "status"
                ]
            ],
            use_container_width=True
        )

        st.write("### Top Negative Drivers")

        st.dataframe(
            top_negative_drivers[
                [
                    "driver",
                    "score",
                    "status"
                ]
            ],
            use_container_width=True
        )

def show_regime_watchlist(df):

    watchlist_df = df.copy()

    watchlist_df["watchlist_score"] = (
        watchlist_df["driver_score"] * 0.7
        +
        watchlist_df["ma_distance"] * 0.3
    )

    watchlist_df = watchlist_df.sort_values(
        "watchlist_score",
        ascending=False
    )

    cols = [
        "ticker",
        "sector",
        "driver_score",
        "ma_distance",
        "watchlist_score"
    ]

    cols = [
        c for c in cols
        if c in watchlist_df.columns
    ]

    with st.expander(
        "Regime Watchlist",
        expanded=False
    ):

        st.dataframe(
            watchlist_df[cols].head(10),
            use_container_width=True
        )

def show_conviction_score(df):

    conviction_df = df.copy()

    conviction_df["momentum_score"] = (
        conviction_df["ma_distance"] / 10
    )

    conviction_df["trend_score"] = conviction_df["is_bullish"].apply(
        lambda x: 1 if x == 1 or x is True else -1
    )

    conviction_df["rsi_score"] = conviction_df["rsi"].apply(
        lambda x: 1 if x < 70 else -1
    )

    conviction_df["conviction_score"] = (
        conviction_df["driver_score"] * 0.40
        +
        conviction_df["momentum_score"] * 0.30
        +
        conviction_df["trend_score"] * 0.20
        +
        conviction_df["rsi_score"] * 0.10
    )

    conviction_df = conviction_df.sort_values(
        "conviction_score",
        ascending=False
    )

    cols = [
        "ticker",
        "sector",
        "driver_score",
        "ma_distance",
        "rsi",
        "momentum_score",
        "trend_score",
        "rsi_score",
        "conviction_score"
    ]

    cols = [
        c for c in cols
        if c in conviction_df.columns
    ]

    with st.expander(
        "Conviction Score Ranking",
        expanded=False
    ):

        st.dataframe(
            conviction_df[cols].head(10),
            use_container_width=True
        )

def show_selected_stock_conviction(df, selected_ticker):

    selected_df = df[
        df["ticker"] == selected_ticker
    ].copy()

    if selected_df.empty:
        return

    row = selected_df.iloc[0]

    momentum_score = row["ma_distance"] / 10

    trend_score = (
        1 if row["is_bullish"] == 1 or row["is_bullish"] is True
        else -1
    )

    rsi_score = (
        1 if row["rsi"] < 70
        else -1
    )

    conviction_score = (
        row["driver_score"] * 0.40
        + momentum_score * 0.30
        + trend_score * 0.20
        + rsi_score * 0.10
    )

    breakdown_df = pd.DataFrame([
        {
            "component": "Driver Score",
            "value": row["driver_score"],
            "weight": 0.40,
            "weighted_score": row["driver_score"] * 0.40
        },
        {
            "component": "Momentum Score",
            "value": momentum_score,
            "weight": 0.30,
            "weighted_score": momentum_score * 0.30
        },
        {
            "component": "Trend Score",
            "value": trend_score,
            "weight": 0.20,
            "weighted_score": trend_score * 0.20
        },
        {
            "component": "RSI Score",
            "value": rsi_score,
            "weight": 0.10,
            "weighted_score": rsi_score * 0.10
        }
    ])

    with st.expander(
        f"Conviction Breakdown - {selected_ticker}",
        expanded=False
    ):

        st.metric(
            "Conviction Score",
            round(conviction_score, 2)
        )

        st.dataframe(
            breakdown_df,
            use_container_width=True
        )

# ======================
# TITLE
# ======================

st.title("Indonesia Market Dashboard")

# ======================
# ECONOMIC DRIVERS TODAY
# ======================

show_economic_drivers(driver_df)

# ======================
# TOP BENEFICIARIES PER DRIVER
# ======================

show_top_beneficiaries(
    score_df,
    driver_df
)

# ======================
# MARKET REGIME
# ======================

commodity_drivers = [
    "COAL",
    "CPO",
    "GOLD",
    "NICKEL",
    "OIL"
]

commodity_score = driver_df[
    driver_df["driver"].isin(commodity_drivers)
]["score"].mean()

rate_score = driver_df[
    driver_df["driver"] == "BI_RATE"
]["score"].mean()

currency_score = driver_df[
    driver_df["driver"] == "USDIDR"
]["score"].mean()

if commodity_score >= 0.5:
    market_regime = "Commodity Bullish"

elif rate_score >= 0.5:
    market_regime = "Rate Sensitive Bullish"

elif currency_score <= -0.5:
    market_regime = "Currency Pressure"

else:
    market_regime = "Neutral / Mixed"

# ======================
# MARKET REGIME REASONS
# ======================

top_positive_drivers = (
    driver_df
    .sort_values("score", ascending=False)
    .head(3)
)

top_negative_drivers = (
    driver_df
    .sort_values("score", ascending=True)
    .head(3)
)
show_market_regime(
    market_regime,
    top_positive_drivers,
    top_negative_drivers
)

show_regime_watchlist(
    latest_df
)

show_conviction_score(
    latest_df
)

# ======================
# SIDEBAR
# ======================

tickers = sorted(latest_df["ticker"].dropna().unique())

selected_ticker = st.sidebar.selectbox(
    "Pilih Saham",
    tickers
)

show_selected_stock_conviction(
    latest_df,
    selected_ticker
)

screener = st.sidebar.selectbox(
    "Screener",
    [
        "All",
        "RSI Oversold",
        "Bullish Trend",
        "Golden Cross",
        "Volume Spike"
    ]
)

range_option = st.sidebar.radio(
    "Range",
    ["1D", "1W", "1M", "3M", "1Y", "Custom"],
    horizontal=True
)

max_date = pd.read_sql(
    "SELECT MAX(trade_date) AS max_date FROM daily_prices",
    engine
)["max_date"].iloc[0]

max_date = pd.to_datetime(max_date).date()

if range_option == "1D":
    start_date = max_date
    end_date = max_date

elif range_option == "1W":
    start_date = max_date - pd.Timedelta(days=7)
    end_date = max_date

elif range_option == "1M":
    start_date = (
        pd.Timestamp(max_date)
        - pd.DateOffset(months=1)
    ).date()
    end_date = max_date

elif range_option == "3M":
    start_date = (
        pd.Timestamp(max_date)
        - pd.DateOffset(months=3)
    ).date()
    end_date = max_date

elif range_option == "1Y":
    start_date = (
        pd.Timestamp(max_date)
        - pd.DateOffset(years=1)
    ).date()
    end_date = max_date

else:
    start_date = st.sidebar.date_input(
        "From",
        value=(
            pd.Timestamp(max_date)
            - pd.DateOffset(months=3)
        ).date()
    )

    end_date = st.sidebar.date_input(
        "To",
        value=max_date
    )

# ======================
# MARKET BREADTH
# ======================

show_market_breadth(latest_df)

# ======================
# SCREENER TABLE
# ======================

show_screener(latest_df)

# ======================
# DRIVER SCORE RANKING
# ======================

show_driver_ranking(latest_df)

# ======================
# QUERY CHART
# ======================

price_df = pd.read_sql(
    """
    SELECT *
    FROM daily_prices
    WHERE ticker = ?
      AND DATE(trade_date) BETWEEN DATE(?) AND DATE(?)
    ORDER BY DATE(trade_date)
    """,
    engine,
    params=(
        selected_ticker,
        str(start_date),
        str(end_date)
    )
)

price_df["trade_date"] = pd.to_datetime(price_df["trade_date"])

st.sidebar.caption(f"Range aktif: {start_date} s/d {end_date}")
st.sidebar.caption(f"Rows loaded: {len(price_df)}")

# ======================
# PRICE CHART
# ======================

show_price_chart(
    price_df,
    selected_ticker
)

# ======================
# DRIVER BREAKDOWN
# ======================

show_driver_breakdown(
    mapping_df,
    driver_df,
    selected_ticker
)

# ======================
# SECTOR SUMMARY
# ======================

show_sector_summary(latest_df)

# ======================
# MOMENTUM RANKING
# ======================

show_momentum(latest_df)