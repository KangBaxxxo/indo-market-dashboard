import streamlit as st
import pandas as pd
from sqlalchemy import create_engine
from dotenv import load_dotenv
import os
import plotly.graph_objects as go

# =========================
# LOAD ENV
# =========================

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")

engine = create_engine(DATABASE_URL)

# =========================
# QUERY
# =========================

query = """
SELECT *
FROM daily_prices
"""

@st.cache_data
def load_data():

    query = """
    SELECT *
    FROM daily_prices
    """

    return pd.read_sql(
        query,
        engine
    )

df = load_data()


# =========================
# FIX TIMEZONE
# =========================

df["trade_date"] = pd.to_datetime(
    df["trade_date"]
).dt.tz_localize(None)
latest_update = df["trade_date"].max()

# =========================
# DOWNLOAD FULL DATA
# =========================

csv_all = df.to_csv(
    index=False
).encode(
    "utf-8"
)

st.sidebar.download_button(
    label="Download Semua Data CSV",
    data=csv_all,
    file_name="indo_market_dashboard_data.csv",
    mime="text/csv"
)

# =========================
# LATEST DATA PER TICKER
# =========================

latest_df = df.sort_values(
    "trade_date"
).groupby(
    "ticker"
).tail(1)

import streamlit as st
import pandas as pd
from sqlalchemy import create_engine
from dotenv import load_dotenv
import os
import plotly.graph_objects as go

# =========================
# LOAD ENV
# =========================

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")

engine = create_engine(DATABASE_URL)

# =========================
# QUERY
# =========================

query = """
SELECT *
FROM daily_prices
"""

df = pd.read_sql(query, engine)

# =========================
# FIX TIMEZONE
# =========================

df["trade_date"] = pd.to_datetime(
    df["trade_date"]
).dt.tz_localize(None)

latest_update = df["trade_date"].max()

# =========================
# LATEST DATA PER TICKER
# =========================

latest_df = df.sort_values(
    "trade_date"
).groupby(
    "ticker"
).tail(1)

# =========================
# VOLUME AVG
# =========================

volume_avg = df.groupby(
    "ticker"
)["volume"].mean()

latest_df["avg_volume"] = latest_df[
    "ticker"
].map(volume_avg)

# =========================
# SIDEBAR
# =========================

ticker_list = sorted(
    df["ticker"].unique()
)

ticker_options = (
    latest_df["name"]
    +
    " ("
    +
    latest_df["ticker"]
    +
    ")"
).tolist()

selected_option = st.sidebar.selectbox(
    "Cari Saham",
    sorted(ticker_options)
)

selected_ticker = selected_option.split(
    "("
)[-1].replace(
    ")",
    ""
)

portfolio_watchlist = st.sidebar.multiselect(
    "Portfolio Monitor",
    ticker_list,
    default=[
        "BBCA.JK",
        "BBRI.JK"
    ]
)

sr_period = st.sidebar.selectbox(
    "Support/Resistance Period",
    [20, 50, 100],
    index=0
)

screen_option = st.sidebar.selectbox(
    "Screener",
    [
        "All",
        "RSI Oversold",
        "Bullish Trend",
        "Golden Cross",
        "Volume Spike"
    ]
)

screen_notes = {
    "All":
    "Menampilkan semua saham.",

    "RSI Oversold":
    "RSI < 30. Menandakan saham oversold dan berpotensi rebound.",

    "Bullish Trend":
    "Harga berada di atas MA50. Trend menengah bullish.",

    "Golden Cross":
    "MA20 berada di atas MA50. Momentum bullish.",

    "Volume Spike":
    "Volume hari ini > 2x rata-rata volume."
}

st.sidebar.info(
    screen_notes[screen_option]
)

# =========================
# MARKET BREADTH
# =========================

bullish_count = len(
    latest_df[
        latest_df["close_price"]
        >
        latest_df["ma50"]
    ]
)

oversold_count = len(
    latest_df[
        latest_df["rsi"] < 30
    ]
)

golden_cross_count = len(
    latest_df[
        latest_df["ma20"]
        >
        latest_df["ma50"]
    ]
)

# VOLUME SPIKE

volume_avg = df.groupby(
    "ticker"
)["volume"].mean()

latest_df["avg_volume"] = latest_df[
    "ticker"
].map(volume_avg)

volume_spike_count = len(
    latest_df[
        latest_df["volume"]
        >
        latest_df["avg_volume"] * 2
    ]
)

# =========================
# SECTOR ANALYSIS
# =========================

sector_summary = latest_df.groupby(
    "sector"
).agg({
    "rsi": "mean",
    "volume": "sum"
}).reset_index()

bullish_sector = (
    latest_df[
        latest_df["close_price"]
        >
        latest_df["ma50"]
    ]
    .groupby("sector")
    .size()
    .reset_index(name="bullish_count")
)

sector_summary = sector_summary.merge(
    bullish_sector,
    on="sector",
    how="left"
)

sector_summary["bullish_count"] = sector_summary[
    "bullish_count"
].fillna(0)

sector_summary["rsi"] = sector_summary[
    "rsi"
].round(2)

sector_summary = sector_summary.sort_values(
    by="rsi",
    ascending=False
)

with st.expander(
    "Sector Analysis",
    expanded=False
):

    st.dataframe(
        sector_summary
    )

# =========================
# MARKET BREADTH UI
# =========================

st.subheader("Market Breadth")

b1, b2, b3, b4 = st.columns(4)

b1.metric(
    "Bullish",
    bullish_count
)

b2.metric(
    "Oversold",
    oversold_count
)

b3.metric(
    "Golden Cross",
    golden_cross_count
)

b4.metric(
    "Volume Spike",
    volume_spike_count
)

# =========================
# MOMENTUM RANKING
# =========================

latest_df["ma_distance"] = (
    (
        latest_df["close_price"]
        -
        latest_df["ma20"]
    )
    /
    latest_df["ma20"]
) * 100

momentum_df = latest_df.sort_values(
    by="ma_distance",
    ascending=False
)

momentum_df["ma_distance"] = (
    momentum_df["ma_distance"]
).round(2).astype(str) + "%"

st.subheader(
    "Top Momentum Stocks"
)

st.dataframe(
    momentum_df[
        [
            "ticker",
            "close_price",
            "rsi",
            "ma_distance",
            "volume"
        ]
    ].head(10)
)

# =========================
# SELL SIGNAL ENGINE
# =========================

sell_df = latest_df.copy()

sell_df["sell_signal"] = "HOLD"

sell_df["sell_score"] = 0

# WEAK MOMENTUM

sell_df.loc[
    sell_df["rsi"] < 45,
    "sell_signal"
] = "Weak Momentum"

sell_df.loc[
    sell_df["rsi"] < 45,
    "sell_score"
] += 20

# TREND BREAKDOWN

sell_df.loc[
    sell_df["close_price"]
    <
    sell_df["ma20"],
    "sell_signal"
] = "Trend Breakdown"

sell_df.loc[
    sell_df["close_price"]
    <
    sell_df["ma20"],
    "sell_score"
] += 30

# BEARISH TREND

sell_df.loc[
    sell_df["ma20"]
    <
    sell_df["ma50"],
    "sell_signal"
] = "Bearish Trend"

sell_df.loc[
    sell_df["ma20"]
    <
    sell_df["ma50"],
    "sell_score"
] += 50

# SHOW TABLE

st.subheader(
    "Sell Signal Monitor"
)

st.caption(
    "Signal berdasarkan kondisi 20 hari terakhir."
)

# FILTER SELL CANDIDATE

sell_candidates = sell_df[
    (sell_df["sell_signal"] != "HOLD")
    &
    (
        sell_df["ticker"].isin(
            portfolio_watchlist
        )
    )
]
st.dataframe(
    sell_candidates[
        [
            "ticker",
            "name",
            "sector",
            "close_price",
            "rsi",
            "sell_signal",
            "sell_score"
        ]
    ].sort_values(
    by="sell_score",
    ascending=False
    )
)

# =========================
# SCREENER LOGIC
# =========================

screened_df = latest_df.copy()

screened_df["status"] = ""
screened_df["score"] = 0

# OVERSOLD

screened_df.loc[
    screened_df["rsi"] < 30,
    "status"
] += "Oversold | "
screened_df.loc[
    screened_df["rsi"] < 30,
    "score"
] += 20

# BULLISH

screened_df.loc[
    screened_df["close_price"]
    >
    screened_df["ma50"],
    "status"
] += "Bullish | "
screened_df.loc[
    screened_df["close_price"]
    >
    screened_df["ma50"],
    "score"
] += 30

# GOLDEN CROSS

screened_df.loc[
    screened_df["ma20"]
    >
    screened_df["ma50"],
    "status"
] += "Golden Cross | "
screened_df.loc[
    screened_df["ma20"]
    >
    screened_df["ma50"],
    "score"
] += 30

# VOLUME SPIKE

screened_df.loc[
    screened_df["volume"]
    >
    screened_df["avg_volume"] * 2,
    "status"
] += "Volume Spike | "
screened_df.loc[
    screened_df["volume"]
    >
    screened_df["avg_volume"] * 2,
    "score"
] += 20

# DEFAULT

screened_df.loc[
    screened_df["status"] == "",
    "status"
] = "Neutral"

# REMOVE LAST |

screened_df["status"] = screened_df[
    "status"
].str.rstrip(" | ")

if screen_option == "RSI Oversold":

    screened_df = screened_df[
        screened_df["rsi"] < 30
    ]

elif screen_option == "Bullish Trend":

    screened_df = screened_df[
        screened_df["close_price"]
        >
        screened_df["ma50"]
    ]

elif screen_option == "Golden Cross":

    screened_df = screened_df[
        screened_df["ma20"]
        >
        screened_df["ma50"]
    ]

elif screen_option == "Volume Spike":

    screened_df = screened_df[
        screened_df["volume"]
        >
        screened_df["avg_volume"] * 2
    ]

# =========================
# DATE RANGE
# =========================

min_date = df["trade_date"].min()

max_date = df["trade_date"].max()

start_date = st.sidebar.date_input(
    "From",
    value=min_date
)

end_date = st.sidebar.date_input(
    "To",
    value=max_date
)

start_date = pd.to_datetime(
    start_date
)

end_date = pd.to_datetime(
    end_date
)

# =========================
# FILTER DATA
# =========================

filtered_df = df[
    (df["ticker"] == selected_ticker)
    &
    (df["trade_date"] >= start_date)
    &
    (df["trade_date"] <= end_date)
]

filtered_df = filtered_df.sort_values(
    by="trade_date"
)

latest = filtered_df.iloc[-1]

csv_filtered = filtered_df.to_csv(
    index=False
).encode(
    "utf-8"
)

st.download_button(
    label=f"Download Data {selected_ticker}",
    data=csv_filtered,
    file_name=f"{selected_ticker}_data.csv",
    mime="text/csv"
)

# =========================
# SUPPORT & RESISTANCE
# =========================

support = filtered_df[
    "low_price"
].tail(sr_period).min()

resistance = filtered_df[
    "high_price"
].tail(sr_period).max()

current_price = latest["close_price"]

support_distance = (
    (
        current_price - support
    )
    /
    support
) * 100

resistance_distance = (
    (
        resistance - current_price
    )
    /
    current_price
) * 100

# =========================
# METRICS
# =========================

st.subheader(selected_ticker)

col1, col2, col3, col4, col5 = st.columns(5)

col1.metric(
    "Close",
    round(latest["close_price"], 2)
)

col2.metric(
    "RSI",
    round(latest["rsi"], 2)
)

col3.metric(
    "Volume",
    int(latest["volume"])
)

col4.metric(
    "Support",
    round(support, 2)
)

col5.metric(
    "Resistance",
    round(resistance, 2)
)

st.caption(
    f"Support & Resistance dihitung dari highest high dan lowest low {sr_period} hari terakhir."
)

if support_distance < 3:

    st.success(
        f"Harga dekat SUPPORT ({support_distance:.2f}% dari support)"
    )

if resistance_distance < 3:

    st.warning(
        f"Harga dekat RESISTANCE ({resistance_distance:.2f}% dari resistance)"
    )

# =========================
# SCREENER TABLE
# =========================

st.subheader(
    f"Screener: {screen_option}"
)

st.dataframe(
    screened_df[
        [
            "ticker",
            "name",
            "sector",
            "board",
            "score",
            "status",
            "close_price",
            "rsi",
            "ma20",
            "ma50",
            "volume"
        ]
    ].sort_values(
    by="score",
    ascending=False
    )
)

# =========================
# CANDLESTICK CHART
# =========================

fig = go.Figure()

fig.add_trace(
    go.Candlestick(
        x=filtered_df["trade_date"],
        open=filtered_df["open_price"],
        high=filtered_df["high_price"],
        low=filtered_df["low_price"],
        close=filtered_df["close_price"],
        name="Price",
        increasing_line_color="#59CD90",
        increasing_fillcolor="#59CD90",
        decreasing_line_color="#EE6352",
        decreasing_fillcolor="#EE6352"
    )
)

# MA20

fig.add_trace(
    go.Scatter(
        x=filtered_df["trade_date"],
        y=filtered_df["ma20"],
        mode="lines",
        name="MA20",
        line=dict(
            color="#3FA7D6",
            width=2
        )
    )
)

# MA50

fig.add_trace(
    go.Scatter(
        x=filtered_df["trade_date"],
        y=filtered_df["ma50"],
        mode="lines",
        name="MA50",
        line=dict(
            color="#FAC05E",
            width=2
        )
    )
)

fig.update_layout(
    title=f"{selected_ticker} Candlestick Chart",
    xaxis_title="Date",
    yaxis_title="Price",
    xaxis_rangeslider_visible=False,
    height=700
)

st.plotly_chart(
    fig,
    use_container_width=True
)

# =========================
# DATA TABLE
# =========================

st.dataframe(
    filtered_df.tail(20)
)