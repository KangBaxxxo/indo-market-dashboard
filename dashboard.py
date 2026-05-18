import streamlit as st
import pandas as pd
from sqlalchemy import create_engine
from dotenv import load_dotenv
import os
import plotly.graph_objects as go

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")

engine = create_engine(DATABASE_URL)

query = """
SELECT *
FROM daily_prices
"""

df = pd.read_sql(query, engine)

# FIX TIMEZONE
df["trade_date"] = pd.to_datetime(
    df["trade_date"]
).dt.tz_localize(None)

# LATEST DATA PER TICKER
latest_df = df.sort_values(
    "trade_date"
).groupby(
    "ticker"
).tail(1)

st.title("Dashboard Saham Indonesia")

# SIDEBAR
ticker_list = sorted(df["ticker"].unique())

selected_ticker = st.sidebar.selectbox(
    "Pilih Saham",
    ticker_list
)

screen_type = st.sidebar.selectbox(
    "Screener",
    [
        "All",
        "Uptrend",
        "Oversold",
        "Golden Cross"
    ]
)

# SCREENER LOGIC
if screen_type == "Uptrend":

    latest_df = latest_df[
        (latest_df["close_price"] > latest_df["ma20"])
        &
        (latest_df["ma20"] > latest_df["ma50"])
        &
        (latest_df["rsi"] > 55)
    ]

elif screen_type == "Oversold":

    latest_df = latest_df[
        latest_df["rsi"] < 30
    ]

elif screen_type == "Golden Cross":

    latest_df = latest_df[
        latest_df["ma20"] > latest_df["ma50"]
    ]

# SHOW SCREENER
st.subheader(f"Screener: {screen_type}")

st.dataframe(
    latest_df[
        [
            "ticker",
            "close_price",
            "ma20",
            "ma50",
            "rsi"
        ]
    ].sort_values(
        by="rsi",
        ascending=False
    )
)

# DATE RANGE
min_date = df["trade_date"].min()

max_date = df["trade_date"].max()

start_date = st.sidebar.date_input(
    "From",
    value=min_date,
    min_value=min_date,
    max_value=max_date
)

end_date = st.sidebar.date_input(
    "To",
    value=max_date,
    min_value=min_date,
    max_value=max_date
)

# CONVERT DATE
start_date = pd.to_datetime(start_date)

end_date = pd.to_datetime(end_date)

# FILTER DATA
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

st.subheader(selected_ticker)

latest = filtered_df.iloc[-1]

# METRICS
col1, col2, col3 = st.columns(3)

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

# CANDLESTICK CHART
fig = go.Figure()

fig.add_trace(
    go.Candlestick(
        x=filtered_df["trade_date"],
        open=filtered_df["open_price"],
        high=filtered_df["high_price"],
        low=filtered_df["low_price"],
        close=filtered_df["close_price"],
        name="Price"
    )
)

# MA20
fig.add_trace(
    go.Scatter(
        x=filtered_df["trade_date"],
        y=filtered_df["ma20"],
        mode="lines",
        name="MA20"
    )
)

# MA50
fig.add_trace(
    go.Scatter(
        x=filtered_df["trade_date"],
        y=filtered_df["ma50"],
        mode="lines",
        name="MA50"
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

# TABLE
st.dataframe(
    filtered_df.tail(20)
)