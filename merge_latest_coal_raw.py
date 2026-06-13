import pandas as pd
from pathlib import Path


MASTER_PATH = Path("data/raw/newcastle_coal.csv")
LATEST_PATH = Path("Newcastle Coal Historical Data.csv")


def detect_columns(df):
    date_col = None
    price_col = None

    for c in ["Date", "date", "Tanggal"]:
        if c in df.columns:
            date_col = c
            break

    for c in ["Price", "Close", "close", "Last", "value"]:
        if c in df.columns:
            price_col = c
            break

    if date_col is None or price_col is None:
        raise ValueError(
            f"Cannot detect Date/Price columns. Columns found: {df.columns.tolist()}"
        )

    return date_col, price_col


def normalize_raw_coal(df):
    df = df.copy()

    date_col, price_col = detect_columns(df)

    df["_date_key"] = pd.to_datetime(
        df[date_col],
        format="mixed",
        errors="coerce"
    )

    df["_price_key"] = (
        df[price_col]
        .astype(str)
        .str.replace(",", "", regex=False)
        .str.strip()
    )

    df["_price_key"] = pd.to_numeric(df["_price_key"], errors="coerce")

    df = df.dropna(subset=["_date_key", "_price_key"])

    df["_date_key"] = df["_date_key"].dt.strftime("%Y-%m-%d")

    return df


def main():
    if not MASTER_PATH.exists():
        raise FileNotFoundError(f"Master file not found: {MASTER_PATH}")

    if not LATEST_PATH.exists():
        raise FileNotFoundError(f"Latest file not found: {LATEST_PATH}")

    master = pd.read_csv(MASTER_PATH)
    latest = pd.read_csv(LATEST_PATH)

    print("MASTER columns:", master.columns.tolist())
    print("LATEST columns:", latest.columns.tolist())

    master_norm = normalize_raw_coal(master)
    latest_norm = normalize_raw_coal(latest)

    combined = pd.concat(
        [master_norm, latest_norm],
        ignore_index=True
    )

    # Kalau tanggal sama, pakai row dari latest.
    combined = combined.drop_duplicates(
        subset=["_date_key"],
        keep="last"
    )

    combined = combined.sort_values("_date_key")

    # Buang helper columns sebelum save.
    combined = combined.drop(columns=["_date_key", "_price_key"])

    combined.to_csv(MASTER_PATH, index=False)

    print("")
    print("=" * 80)
    print("MERGED LATEST COAL INTO MASTER RAW")
    print("=" * 80)
    print(f"Master saved to : {MASTER_PATH}")
    print(f"Latest source   : {LATEST_PATH}")
    print(f"Rows master old : {len(master):,}")
    print(f"Rows latest     : {len(latest):,}")
    print(f"Rows combined   : {len(combined):,}")

    check = normalize_raw_coal(combined)

    print("")
    print("Latest rows in master:")
    print(check.tail(10).to_string(index=False))


if __name__ == "__main__":
    main()