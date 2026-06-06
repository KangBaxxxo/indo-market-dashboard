import yfinance as yf
import pandas as pd

# ======================
# LOAD DRIVER MASTER
# ======================

driver_master = pd.read_csv(
    "data/driver_master.csv"
)

# ======================
# DOWNLOAD DRIVER PRICES
# ======================

all_data = []

for _, row in driver_master.iterrows():

    driver = row["driver"]
    yahoo_ticker = row["yahoo_ticker"]

    print(f"DOWNLOAD {driver} ({yahoo_ticker})")

    df = yf.download(
        yahoo_ticker,
        period="max",
        auto_adjust=True,
        progress=False
    )

    if df.empty:
        print(f"NO DATA: {driver}")
        continue

    df = df.reset_index()

    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

    df.columns = [
        str(c).lower().replace(" ", "_")
        for c in df.columns
    ]

    df["driver"] = driver

    df = df.rename(
        columns={
            "date": "driver_date",
            "close": "value"
        }
    )

    df = df[
        [
            "driver",
            "driver_date",
            "value"
        ]
    ]

    all_data.append(df)

driver_prices = pd.concat(
    all_data,
    ignore_index=True
)

driver_prices["driver_date"] = pd.to_datetime(
    driver_prices["driver_date"]
).dt.date

driver_prices.to_csv(
    "data/driver_prices.csv",
    index=False
)

print("SUCCESS CREATE driver_prices.csv")

# ======================
# CREATE DRIVER SCORES
# ======================

latest_scores = []

for driver, df in driver_prices.groupby("driver"):

    df = df.sort_values("driver_date").copy()

    latest_value = df["value"].iloc[-1]

    value_20d_ago = df["value"].iloc[-21]

    change_20d = (
        latest_value / value_20d_ago - 1
    ) * 100

    if change_20d >= 10:
        score = 2

    elif change_20d >= 5:
        score = 1

    elif change_20d <= -10:
        score = -2

    elif change_20d <= -5:
        score = -1

    else:
        score = 0

    latest_scores.append(
        {
            "driver": driver,
            "latest_value": round(latest_value, 4),
            "change_20d": round(change_20d, 2),
            "score": score
        }
    )

driver_scores = pd.DataFrame(
    latest_scores
)

driver_scores.to_csv(
    "data/driver_scores.csv",
    index=False
)

print("SUCCESS CREATE driver_scores.csv")
print(driver_scores)