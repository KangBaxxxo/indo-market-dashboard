from pathlib import Path

import pandas as pd
import yfinance as yf


# =====================================================
# CONFIG
# =====================================================
OUTPUT_PATH = Path("data/driver_prices.csv")
SCORE_PATH = Path("data/driver_scores.csv")

OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)

# Drivers yang diambil otomatis dari Yahoo Finance
YF_DRIVERS = {
    "USDIDR": "IDR=X",
    "OIL": "CL=F",
    "GOLD": "GC=F",
    "NICKEL": "^SPGSIK",
    "USD INDEX": "DX-Y.NYB",
}

# Drivers yang bukan dari Yahoo Finance dan harus dipertahankan dari file existing
PRESERVE_DRIVERS = [
    "COAL",
]


# =====================================================
# HELPERS
# =====================================================
def normalize_driver_name(value):
    return str(value).upper().strip()


def safe_numeric(series):
    return pd.to_numeric(series, errors="coerce")


def load_existing_driver_prices(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame(columns=["driver", "driver_date", "value"])

    df = pd.read_csv(path)
    df.columns = df.columns.str.strip().str.lower()

    required_cols = {"driver", "driver_date", "value"}
    missing = required_cols - set(df.columns)

    if missing:
        print(f"WARNING existing driver_prices.csv kolom kurang: {sorted(missing)}")
        return pd.DataFrame(columns=["driver", "driver_date", "value"])

    df["driver"] = df["driver"].apply(normalize_driver_name)
    df["driver_date"] = pd.to_datetime(df["driver_date"], format="mixed", errors="coerce")
    df["value"] = safe_numeric(df["value"])

    df = df.dropna(subset=["driver", "driver_date", "value"])
    df = df[["driver", "driver_date", "value"]].copy()

    return df


def extract_close(downloaded: pd.DataFrame, symbol: str) -> pd.Series:
    if downloaded.empty:
        return pd.Series(dtype="float64")

    # yfinance kadang return MultiIndex columns
    if isinstance(downloaded.columns, pd.MultiIndex):
        level0 = downloaded.columns.get_level_values(0)

        if "Close" in level0:
            close_obj = downloaded["Close"]
        elif "Adj Close" in level0:
            close_obj = downloaded["Adj Close"]
        else:
            raise ValueError(f"Close column tidak ketemu untuk {symbol}: {downloaded.columns}")

        if isinstance(close_obj, pd.DataFrame):
            close = close_obj.iloc[:, 0]
        else:
            close = close_obj

        return close

    # normal single-index columns
    if "Close" in downloaded.columns:
        return downloaded["Close"]

    if "Adj Close" in downloaded.columns:
        return downloaded["Adj Close"]

    raise ValueError(f"Close column tidak ketemu untuk {symbol}: {downloaded.columns}")


def download_yfinance_driver(driver_name: str, symbol: str) -> pd.DataFrame:
    print(f"DOWNLOAD {driver_name} ({symbol})")

    df = yf.download(
        symbol,
        period="max",
        auto_adjust=False,
        progress=False,
    )

    if df.empty:
        print(f"NO DATA: {driver_name}")
        return pd.DataFrame(columns=["driver", "driver_date", "value"])

    close = extract_close(df, symbol)

    out = pd.DataFrame({
        "driver_date": close.index,
        "value": close.values,
    })

    out["driver"] = normalize_driver_name(driver_name)
    out["driver_date"] = pd.to_datetime(out["driver_date"], errors="coerce").dt.tz_localize(None)
    out["value"] = safe_numeric(out["value"])

    out = out.dropna(subset=["driver_date", "value"])
    out = out[["driver", "driver_date", "value"]].copy()

    return out


def build_driver_scores(driver_prices: pd.DataFrame) -> pd.DataFrame:
    rows = []

    df = driver_prices.copy()
    df["driver"] = df["driver"].apply(normalize_driver_name)
    df["driver_date"] = pd.to_datetime(df["driver_date"], format="mixed", errors="coerce")
    df["value"] = safe_numeric(df["value"])

    df = df.dropna(subset=["driver", "driver_date", "value"])
    df = df.sort_values(["driver", "driver_date"]).reset_index(drop=True)

    for driver, g in df.groupby("driver"):
        g = g.sort_values("driver_date").reset_index(drop=True).copy()

        if len(g) <= 20:
            continue

        g["change_20d"] = (g["value"] / g["value"].shift(20) - 1) * 100

        latest = g.dropna(subset=["change_20d"]).tail(1)

        if latest.empty:
            continue

        latest = latest.iloc[0]

        change_20d = float(latest["change_20d"])

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

        rows.append({
            "driver": driver,
            "latest_value": round(float(latest["value"]), 4),
            "change_20d": round(change_20d, 2),
            "score": score,
        })

    return pd.DataFrame(rows)

def load_coal_driver_from_raw():
    raw_path = Path("data/raw/newcastle_coal.csv")

    if not raw_path.exists():
        print(f"COAL raw file not found: {raw_path}")
        return pd.DataFrame(columns=["driver", "driver_date", "value"])

    raw = pd.read_csv(raw_path)
    raw.columns = [str(c).strip() for c in raw.columns]

    date_col = None
    price_col = None

    for col in raw.columns:
        col_lower = col.lower().strip()

        if col_lower in ["date", "driver_date"]:
            date_col = col

        if col_lower in ["price", "close", "last", "value"]:
            price_col = col

    if date_col is None:
        raise ValueError(f"COAL raw date column not found. Columns: {raw.columns.tolist()}")

    if price_col is None:
        raise ValueError(f"COAL raw price column not found. Columns: {raw.columns.tolist()}")

    coal = pd.DataFrame({
        "driver_date": pd.to_datetime(
            raw[date_col],
            format="mixed",
            errors="coerce",
        ),
        "value": safe_numeric(raw[price_col]),
    })

    coal["driver"] = "COAL"

    coal = coal[["driver", "driver_date", "value"]]
    coal = coal.dropna(subset=["driver", "driver_date", "value"])
    coal = coal.drop_duplicates(subset=["driver", "driver_date"], keep="last")
    coal = coal.sort_values("driver_date").reset_index(drop=True)

    if not coal.empty:
        latest = coal.tail(1).iloc[0]
        print(
            f"LOAD COAL RAW: latest={latest['driver_date'].date()} "
            f"value={latest['value']}"
        )

    return coal    
# =====================================================
# MAIN
# =====================================================
def main():
    existing = load_existing_driver_prices(OUTPUT_PATH)

    existing["driver"] = existing["driver"].apply(normalize_driver_name)

    # Preserve non-YFinance drivers selain COAL.
    # COAL sekarang selalu rebuild dari data/raw/newcastle_coal.csv
    preserved = existing[
        existing["driver"].isin(PRESERVE_DRIVERS)
        & (existing["driver"] != "COAL")
    ].copy()

    coal_data = load_coal_driver_from_raw()

    yf_frames = []
    for driver_name, symbol in YF_DRIVERS.items():
        downloaded = download_yfinance_driver(driver_name, symbol)

        if not downloaded.empty:
            yf_frames.append(downloaded)

    if yf_frames:
        yf_data = pd.concat(yf_frames, ignore_index=True)
    else:
        yf_data = pd.DataFrame(columns=["driver", "driver_date", "value"])

    merged = pd.concat([preserved, coal_data, yf_data], ignore_index=True)

    merged["driver"] = merged["driver"].apply(normalize_driver_name)
    merged["driver_date"] = pd.to_datetime(merged["driver_date"], format="mixed", errors="coerce")
    merged["value"] = safe_numeric(merged["value"])

    merged = merged.dropna(subset=["driver", "driver_date", "value"])
    merged = merged.drop_duplicates(subset=["driver", "driver_date"], keep="last")
    merged = merged.sort_values(["driver", "driver_date"]).reset_index(drop=True)

    # save clean CSV
    save_df = merged.copy()
    save_df["driver_date"] = save_df["driver_date"].dt.strftime("%Y-%m-%d")
    save_df.to_csv(OUTPUT_PATH, index=False)

    print("SUCCESS MERGE driver_prices.csv")

    score_df = build_driver_scores(merged)

    if not score_df.empty:
        score_df = score_df.sort_values("driver").reset_index(drop=True)

    score_df.to_csv(SCORE_PATH, index=False)

    print("SUCCESS CREATE driver_scores.csv")
    print(score_df.to_string())


if __name__ == "__main__":
    main()
