from sqlalchemy import create_engine, text
import pandas as pd
import yfinance as yf
import ta


# ======================
# CONFIG
# ======================

DB_PATH = "sqlite:///data/market.db"
STOCK_MAPPING_PATH = "data/stock_mapping.csv"

engine = create_engine(DB_PATH)


# ======================
# LOAD TICKER UNIVERSE
# ======================

mapping_df = pd.read_csv(STOCK_MAPPING_PATH)

mapping_df.columns = (
    mapping_df.columns
    .str.strip()
    .str.lower()
)

if "ticker" not in mapping_df.columns:
    raise ValueError("Column 'ticker' tidak ditemukan di data/stock_mapping.csv")

mapping_tickers = (
    mapping_df["ticker"]
    .dropna()
    .astype(str)
    .str.strip()
    .tolist()
)

# Tambahan ticker driver study.
# Ini supaya EMAS.JK dan BUMI.JK tetap ke-update meskipun belum ada study final.
extra_tickers = [
    # Gold driver universe
    "HRTA.JK",
    "ANTM.JK",
    "MDKA.JK",
    "BRMS.JK",
    "EMAS.JK",
    "ARCI.JK",

    # Coal driver universe
    "ADRO.JK",
    "PTBA.JK",
    "ITMG.JK",
    "HRUM.JK",
    "BYAN.JK",
    "BUMI.JK",
    
    # Nickel driver universe
    "ANTM.JK",
    "INCO.JK",
    "NCKL.JK",
    "MBMA.JK",
]

# ========================================================
# 🚀 MODIFIKASI: DETEKSI ARGUMEN TURBO REFRESH
# ========================================================
import sys

is_turbo_mode = False
watchlist_args = []

if "--tickers" in sys.argv:
    try:
        idx = sys.argv.index("--tickers")
        tickers_input = sys.argv[idx+1]
        watchlist_args = [t.strip().upper() for t in tickers_input.split() if t.strip()]
        if watchlist_args:
            is_turbo_mode = True
            print(f"⚡ Mode Turbo Aktif: Hanya memproses {len(watchlist_args)} saham watchlist.")
    except Exception as e:
        is_turbo_mode = False

# Jika mode turbo aktif, kita hanya download yang diminta saja
if is_turbo_mode:
    tickers = watchlist_args
else:
    tickers = mapping_tickers + extra_tickers
    
# ==========================================================

tickers = [
    t if t.upper().endswith(".JK") else t + ".JK"
    for t in tickers
]

tickers = sorted(set([t.upper().strip() for t in tickers]))

print("")
print("=" * 80)
print("TICKER UNIVERSE")
print("=" * 80)
print(tickers)
print(f"Total tickers: {len(tickers)}")


# ======================
# DOWNLOAD DATA
# ======================

all_data = []

for ticker_name in tickers:
    print(f"DOWNLOAD {ticker_name}")

    try:
        df = yf.download(
            ticker_name,
            period="max",
            interval="1d",
            auto_adjust=False,
            progress=False,
            threads=False,
        )

        if df.empty:
            print(f"WARNING: {ticker_name} data kosong dari yfinance.")
            continue

        df = df.reset_index()

        # Handle yfinance MultiIndex columns
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = [
                c[0] if isinstance(c, tuple) else c
                for c in df.columns
            ]

        df.columns = [
            str(c).lower().replace(" ", "_").strip()
            for c in df.columns
        ]

        required_cols = [
            "date",
            "open",
            "high",
            "low",
            "close",
            "volume",
        ]

        missing_cols = [
            c for c in required_cols
            if c not in df.columns
        ]

        if missing_cols:
            print(
                f"WARNING: {ticker_name} missing columns: {missing_cols}. "
                f"Columns found: {df.columns.tolist()}"
            )
            continue

        df = df[required_cols].copy()

        df = df.rename(
            columns={
                "date": "trade_date",
                "open": "open_price",
                "high": "high_price",
                "low": "low_price",
                "close": "close_price",
                "volume": "volume",
            }
        )

        df["ticker"] = ticker_name

        df["trade_date"] = pd.to_datetime(
            df["trade_date"],
            format="mixed",
            errors="coerce",
        )

        # Simpan sebagai date bersih, bukan timestamp aneh
        df["trade_date"] = df["trade_date"].dt.tz_localize(None)
        df["trade_date"] = df["trade_date"].dt.normalize()

        numeric_cols = [
            "open_price",
            "high_price",
            "low_price",
            "close_price",
            "volume",
        ]

        for col in numeric_cols:
            df[col] = pd.to_numeric(df[col], errors="coerce")

        df = df.dropna(
            subset=[
                "trade_date",
                "ticker",
                "open_price",
                "high_price",
                "low_price",
                "close_price",
            ]
        ).copy()

        df = df[
            [
                "trade_date",
                "ticker",
                "open_price",
                "high_price",
                "low_price",
                "close_price",
                "volume",
            ]
        ]

        all_data.append(df)

        latest_row = df.sort_values("trade_date").tail(1).iloc[0]

        print(
            f"  latest: {latest_row['trade_date'].date()} "
            f"close={latest_row['close_price']} "
            f"volume={latest_row['volume']}"
        )

    except Exception as e:
        print(f"ERROR download {ticker_name}: {e}")
        continue


# ======================
# COMBINE DATA
# ======================

if not all_data:
    raise RuntimeError("Tidak ada data berhasil didownload dari yfinance.")

final_df = pd.concat(
    all_data,
    ignore_index=True,
)

final_df = final_df.drop_duplicates(
    subset=["ticker", "trade_date"],
    keep="last",
)

final_df = final_df.sort_values(
    ["ticker", "trade_date"]
).reset_index(drop=True)


# ======================
# CALCULATE INDICATORS
# ======================

result = []

for ticker_name, df in final_df.groupby("ticker"):
    df = df.sort_values("trade_date").copy()

    df["ma20"] = (
        df["close_price"]
        .rolling(20)
        .mean()
    )

    df["ma50"] = (
        df["close_price"]
        .rolling(50)
        .mean()
    )

    df["avg_volume"] = (
        df["volume"]
        .rolling(20)
        .mean()
    )

    try:
        df["rsi"] = ta.momentum.RSIIndicator(
            close=df["close_price"],
            window=14,
        ).rsi()
    except Exception:
        df["rsi"] = None

    result.append(df)

final_df = pd.concat(
    result,
    ignore_index=True,
)

final_df = final_df.sort_values(
    ["ticker", "trade_date"]
).reset_index(drop=True)


# ======================
# SAVE DAILY PRICES
# ======================

print("")
print("=" * 80)
print("SAVE daily_prices")
print("=" * 80)

# ========================================================
# 🚀 MODIFIKASI: SAVE INTELLIGENTLY (ANTI WIPE OUT) - FIXED TIMESTAMP
# ========================================================
if is_turbo_mode:
    print("🔄 Menggabungkan data kilat ke database daily_prices yang sudah ada...")
    with engine.begin() as conn:
        # Hapus data tanggal hari ini untuk emiten yang di-update agar tidak duplikat
        formatted_tickers = ", ".join([f"'{t}'" for t in tickers])
        trade_dates_to_clean = final_df["trade_date"].dt.strftime("%Y-%m-%d %H:%M:%S").unique()
        
        for d_str in trade_dates_to_clean:
            conn.execute(
                text(f"DELETE FROM daily_prices WHERE ticker IN ({formatted_tickers}) AND trade_date = :d_str"),
                {"d_str": d_str}
            )
    
    # Masukkan data baru dengan mode 'append' (ditambah ke bawahnya, bukan ditimpa)
    final_df.to_sql(
        "daily_prices",
        engine,
        if_exists="append",
        index=False,
    )
    
    # 🔥 FIX: Baca ulang seluruh database untuk keperluan kalkulasi 'latest_snapshot'
    final_df = pd.read_sql("SELECT * FROM daily_prices", engine)
    
    # Kembalikan kolom trade_date ke bentuk STRING/TEXT bersih agar tidak crash saat save snapshot
    final_df["trade_date"] = pd.to_datetime(final_df["trade_date"])
    # (Setelah dikalkulasi di proses groupby bawah, tipe data ini aman, tapi kita jaga-jaga 
    # agar saat to_sql dia otomatis berupa text format standar database lo)
else:
    # Jika dijalankan regular/manual tanpa argumen, biarkan replace total seperti aslinya
    # Namun pastikan tipenya string bersih saat masuk ke SQLite
    final_df_copy = final_df.copy()
    final_df_copy["trade_date"] = final_df_copy["trade_date"].dt.strftime("%Y-%m-%d %H:%M:%S.%f")
    final_df_copy.to_sql(
        "daily_prices",
        engine,
        if_exists="replace",
        index=False,
    )
# =========================================================

print(f"daily_prices rows saved: {len(final_df):,}")


# ======================
# BUILD LATEST SNAPSHOT
# ======================

latest_snapshot = (
    final_df
    .sort_values("trade_date")
    .groupby("ticker", as_index=False)
    .tail(1)
    .copy()
)

latest_snapshot["ma_distance"] = (
    (
        latest_snapshot["close_price"]
        - latest_snapshot["ma20"]
    )
    /
    latest_snapshot["ma20"]
) * 100

latest_snapshot["is_bullish"] = (
    latest_snapshot["close_price"]
    > latest_snapshot["ma50"]
)

latest_snapshot["is_oversold"] = (
    latest_snapshot["rsi"]
    < 30
)

latest_snapshot["is_golden_cross"] = (
    latest_snapshot["ma20"]
    > latest_snapshot["ma50"]
)

latest_snapshot["is_volume_spike"] = (
    latest_snapshot["volume"]
    > latest_snapshot["avg_volume"] * 2
)


# ======================
# SAVE LATEST SNAPSHOT
# ======================

# ========================================================
# 🚀 MODIFIKASI: UPDATE LATEST SNAPSHOT SECARA AMAN
# ========================================================
if is_turbo_mode:
    print("🔄 Memperbarui tabel latest_snapshot khusus emiten aktif...")
    # Ambit snapshot lama dari DB
    try:
        old_snapshot = pd.read_sql("SELECT * FROM latest_snapshot", engine)
        # Buang emiten yang baru saja di-update dari snapshot lama
        old_snapshot = old_snapshot[~old_snapshot["ticker"].isin(tickers)]
        # Gabungkan dengan snapshot tergres hasil download kita
        latest_snapshot = pd.concat([old_snapshot, latest_snapshot], ignore_index=True)
    except Exception:
        pass

# Paksa kolom trade_date di latest_snapshot menjadi string bersih sebelum masuk .to_sql
latest_snapshot["trade_date"] = pd.to_datetime(latest_snapshot["trade_date"]).dt.strftime("%Y-%m-%d %H:%M:%S.%f")

# ========================================================
# 🚀 MODIFIKASI: UPDATE LATEST SNAPSHOT SECARA AMAN
# ========================================================
if is_turbo_mode:
    print("🔄 Memperbarui tabel latest_snapshot khusus emiten aktif...")
    try:
        old_snapshot = pd.read_sql("SELECT * FROM latest_snapshot", engine)
        old_snapshot = old_snapshot[~old_snapshot["ticker"].isin(tickers)]
        latest_snapshot = pd.concat([old_snapshot, latest_snapshot], ignore_index=True)
    except Exception:
        pass

latest_snapshot.to_sql(
    "latest_snapshot",
    engine,
    if_exists="replace",
    index=False,
)
# =========================================================

# Tulis ulang snapshot gabungan yang utuh ke database
latest_snapshot.to_sql(
    "latest_snapshot",
    engine,
    if_exists="replace",
    index=False,
)
# ===========================================================

print(f"latest_snapshot rows saved: {len(latest_snapshot):,}")


# ======================
# INDEX SQLITE
# ======================

with engine.begin() as conn:
    conn.execute(
        text("""
        CREATE INDEX IF NOT EXISTS idx_daily_prices_ticker
        ON daily_prices(ticker)
        """)
    )

    conn.execute(
        text("""
        CREATE INDEX IF NOT EXISTS idx_daily_prices_trade_date
        ON daily_prices(trade_date)
        """)
    )

    conn.execute(
        text("""
        CREATE INDEX IF NOT EXISTS idx_daily_prices_ticker_trade_date
        ON daily_prices(ticker, trade_date)
        """)
    )


# ======================
# FINAL CHECK
# ======================

watchlist_check = [
    "HRTA.JK",
    "ANTM.JK",
    "MDKA.JK",
    "BRMS.JK",
    "EMAS.JK",
    "ADRO.JK",
    "PTBA.JK",
    "ITMG.JK",
    "HRUM.JK",
    "BYAN.JK",
    "BUMI.JK",
    "INCO.JK",
    "NCKL.JK",
    "ARCI.JK",
    "MBMA.JK"
]

check_df = latest_snapshot[
    latest_snapshot["ticker"].isin(watchlist_check)
].copy()

check_df = check_df[
    [
        "ticker",
        "trade_date",
        "close_price",
        "volume",
        "ma20",
        "ma50",
        "rsi",
    ]
].sort_values("ticker")

print("")
print("=" * 80)
print("LATEST SNAPSHOT CHECK")
print("=" * 80)
print(check_df.to_string(index=False))

print("")
print("UPDATE DATA DONE.")