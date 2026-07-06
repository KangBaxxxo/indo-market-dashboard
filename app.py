import sqlite3
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import yfinance as yf
from datetime import datetime

def fetch_and_sync_today_data(config):
    """
    Versi Super Tanker: Mengatasi error kolom CSV out of range dengan fallback kolom terakhir,
    dan mengatasi format tanggal SQLite bertipe datetime timestamp dengan format='mixed'.
    """
    import yfinance as yf
    from datetime import datetime
    from pathlib import Path
    import pandas as pd
    import sqlite3
    import streamlit as st
    
    today_str = datetime.now().strftime("%Y-%m-%d")
    driver_symbol = config["driver_symbol"]
    watchlist_tickers = config["tickers"]
    
    yf_driver_mapping = {"GOLD": "GC=F", "COAL": "MTF=F", "NICKEL": "NICKEL=F"}
    yf_driver_symbol = yf_driver_mapping.get(driver_symbol.upper(), driver_symbol)
    
    success_count = 0
    log_messages = []

    # ==========================================
    # 1. LIVE DRIVER SYNC (CSV) - ANTI COLUMNS ERROR
    # ==========================================
    try:
        driver_ticker = yf.Ticker(yf_driver_symbol)
        df_driver_live = driver_ticker.history(period="5d")
        
        if not df_driver_live.empty:
            if df_driver_live.index.tz is not None:
                df_driver_live.index = df_driver_live.index.tz_localize(None)
                
            live_close = float(df_driver_live.iloc[-1]["Close"])
            live_date = df_driver_live.index[-1].strftime("%Y-%m-%d")
            
            csv_path = Path("data/driver_prices.csv")
            if csv_path.exists():
                df_csv = pd.read_csv(csv_path)
                
                # DETEKSI KOLOM SECARA SUPER AMAN (FALLBACK KOTAK TERAKHIR)
                date_cols = [col for col in df_csv.columns if "date" in col.lower() or "tgl" in col.lower()]
                date_col = date_cols[0] if date_cols else df_csv.columns[0]
                
                sym_cols = [col for col in df_csv.columns if "symbol" in col.lower() or "ticker" in col.lower()]
                sym_col = sym_cols[0] if sym_cols else df_csv.columns[1]
                
                close_cols = [col for col in df_csv.columns if "close" in col.lower() or "price" in col.lower() or "val" in col.lower() or "harga" in col.lower()]
                close_col = close_cols[0] if close_cols else df_csv.columns[-1] # Fallback kolom paling kanan
                
                # Bersihkan tanggal CSV lama dengan format mixed agar kebal timestamp
                df_csv[date_col] = pd.to_datetime(df_csv[date_col], format='mixed').dt.strftime("%Y-%m-%d")
                
                # Hapus baris lama biar ga double
                df_csv = df_csv[~((df_csv[date_col] == live_date) & (df_csv[sym_col].astype(str).str.upper() == driver_symbol.upper()))]
                
                # Tambah baris snapshot baru
                new_row = {col: None for col in df_csv.columns}
                new_row[date_col] = live_date
                new_row[sym_col] = driver_symbol
                new_row[close_col] = live_close
                df_csv = pd.concat([df_csv, pd.DataFrame([new_row])], ignore_index=True)
                
                # Urutkan kronologis
                df_csv[date_col] = pd.to_datetime(df_csv[date_col], format='mixed')
                df_csv = df_csv.sort_values(by=date_col).reset_index(drop=True)
                df_csv[date_col] = df_csv[date_col].dt.strftime("%Y-%m-%d")
                
                df_csv.to_csv(csv_path, index=False)
                log_messages.append(f"🚀 Driver CSV OK per {live_date}")
                success_count += 1
    except Exception as e:
        log_messages.append(f"❌ Snapshot Driver Error: {str(e)}")

    # ==========================================
    # 2. LIVE STOCK WATCHLIST SYNC (SQLITE) - MIXED TIMESTAMP FIXED
    # ==========================================
    if Path(DB_PATH).exists():
        try:
            con = sqlite3.connect(DB_PATH)
            cursor = con.cursor()
            
            for ticker in watchlist_tickers:
                stock_ticker = yf.Ticker(ticker)
                df_stock_live = stock_ticker.history(period="5d")
                
                if not df_stock_live.empty:
                    if df_stock_live.index.tz is not None:
                        df_stock_live.index = df_stock_live.index.tz_localize(None)
                        
                    live_close_stock = float(df_stock_live.iloc[-1]["Close"])
                    live_date_stock = df_stock_live.index[-1].strftime("%Y-%m-%d")
                    
                    df_hist = pd.read_sql(
                        "SELECT trade_date, close_price FROM daily_prices WHERE ticker = ? ORDER BY DATE(trade_date) DESC LIMIT 60",
                        con, params=(ticker,)
                    )
                    
                    if not df_hist.empty:
                        # 💡 SOLUSI ERROMU: Gunakan format='mixed' dan potong jadi Date murni (.dt.date)
                        df_hist["trade_date"] = pd.to_datetime(df_hist["trade_date"], format='mixed').dt.strftime("%Y-%m-%d")
                        df_hist = df_hist[df_hist["trade_date"] != live_date_stock]
                        
                        new_stock_row = pd.DataFrame([{"trade_date": live_date_stock, "close_price": live_close_stock}])
                        df_hist = pd.concat([new_stock_row, df_hist], ignore_index=True)
                        df_hist = df_hist.iloc[::-1].reset_index(drop=True)
                        
                        computed_ma20 = float(df_hist["close_price"].rolling(20).mean().iloc[-1]) if len(df_hist) >= 20 else live_close_stock
                        computed_ma50 = float(df_hist["close_price"].rolling(50).mean().iloc[-1]) if len(df_hist) >= 50 else live_close_stock
                        computed_rsi = 50.0 
                    else:
                        computed_ma20, computed_ma50, computed_rsi = live_close_stock, live_close_stock, 50.0
                    
                    # Agar seragam dengan database aslimu yang bertipe timestamp, simpan dengan buntut jamnya
                    db_save_date = f"{live_date_stock} 00:00:00.000000"
                    
                    # Eksekusi dengan toleransi format timestamp lama
                    cursor.execute("DELETE FROM daily_prices WHERE (trade_date = ? OR trade_date = ?) AND ticker = ?", (live_date_stock, db_save_date, ticker))
                    cursor.execute(
                        """
                        INSERT INTO daily_prices (trade_date, ticker, close_price, ma20, ma50, rsi)
                        VALUES (?, ?, ?, ?, ?, ?)
                        """,
                        (db_save_date, ticker, live_close_stock, computed_ma20, computed_ma50, computed_rsi)
                    )
            
            con.commit()
            con.close()
            success_count += 1
            log_messages.append("✅ SQLite Stock Sync Berhasil Tanpa Crash.")
        except Exception as e:
            log_messages.append(f"❌ Snapshot SQLite Error: {str(e)}")

    # Sapu bersih semua model cache Streamlit
    st.cache_data.clear()
    st.cache_resource.clear()
    
    return success_count > 0, log_messages

# ======================
# PAGE CONFIG
# ======================

st.set_page_config(
    page_title="Indonesia Market Dashboard",
    layout="wide",
)

# ======================
# PATHS
# ======================

DB_PATH = "data/market.db"
DRIVER_CSV_PATH = "data/driver_prices.csv"
PROCESSED_DIR = Path("data/processed")
LATEST_SIGNAL_PATH = PROCESSED_DIR / "latest_driver_signals.csv"


# ======================
# DRIVER CONFIG
# ======================

DRIVER_CONFIG = {
    "Gold Driver": {
        "driver_group": "GOLD",
        "driver_symbol": "GOLD",
        "title": "Gold Driver",
        "description": "Gold momentum signal untuk saham terkait emas Indonesia.",
        "source_label": "Gold price driver from data/driver_prices.csv",
        # Research universe. EMAS.JK is included as study candidate / not yet validated.
        "tickers": [
            "HRTA.JK",
            "ANTM.JK",
            "MDKA.JK",
            "BRMS.JK",
            "ARCI.JK",
            "EMAS.JK",
        ],
        "roles": {
            "HRTA.JK": "Primary Target",
            "ANTM.JK": "Cyclical Watchlist",
            "MDKA.JK": "Secondary Watchlist",
            "BRMS.JK": "High Beta Watchlist",
            "ARCI.JK": "Study Candidate / Not Validated",
            "EMAS.JK": "Study Candidate / Not Validated",
        },
        "primary_ticker": "HRTA.JK",
        "lookback_days": 10,
        "threshold_pct": 5.0,
        "hold_days": 10,
        "cooldown_days": 20,
        "rule_text": "GOLD naik >= +5% dalam 10 trading days | Entry next trading day | Hold 10D | Cooldown 20D",
        "summary_source": "csv",
        "summary_file": PROCESSED_DIR / "gold_backtest_summary.csv",
        "yearly_source": "computed_from_trades",
        "trade_source": "csv",
        "trade_file": PROCESSED_DIR / "gold_trade_details.csv",
        },

    "Coal Driver": {
        "driver_group": "COAL",
        "driver_symbol": "COAL",
        "title": "Coal Driver",
        "description": "Newcastle Coal momentum signal untuk saham coal Indonesia.",
        "source_label": "Newcastle Coal Futures / NCFMc1 from data/driver_prices.csv",
        # Research universe. BUMI.JK is included as study candidate / not yet validated.
        "tickers": [
            "ADRO.JK",
            "PTBA.JK",
            "ITMG.JK",
            "HRUM.JK",
            "BYAN.JK",
            "BUMI.JK",
        ],
        "roles": {
            "ADRO.JK": "Primary Target",
            "PTBA.JK": "Secondary Candidate",
            "ITMG.JK": "High Return / Higher Risk",
            "HRUM.JK": "Aggressive Watchlist",
            "BYAN.JK": "Speculative Watchlist",
            "BUMI.JK": "Study Candidate / Not Validated",
        },
        "primary_ticker": "ADRO.JK",
        "lookback_days": 10,
        "threshold_pct": 10.0,
        "hold_days": 10,
        "cooldown_days": 30,
        "rule_text": "COAL naik >= +10% dalam 10 trading days | Entry next trading day | Hold 10D | Cooldown 30D",
        "summary_source": "csv",
        "summary_file": PROCESSED_DIR / "coal_backtest_results.csv",
        "yearly_source": "computed_from_trades",
        "trade_source": "csv",
        "trade_file": PROCESSED_DIR / "coal_trade_details.csv",
    },

    "Nickel Driver": {
        "driver_group": "NICKEL",
        "driver_symbol": "NICKEL",
        "title": "Nickel Driver",
        "description": "Nickel momentum signal untuk saham nickel Indonesia. Research source memakai Nickel Futures Investing; production proxy memakai ^SPGSIK dari Yahoo Finance.",
        "source_label": "S&P GSCI Nickel Index (^SPGSIK) from data/driver_prices.csv | validated vs Investing Nickel Futures: 60D corr 0.9983",
        "tickers": [
            "INCO.JK",
            "ANTM.JK",
            "NCKL.JK",
            "MBMA.JK",
        ],
        "roles": {
            "INCO.JK": "Primary Target / Nickel Champion",
            "ANTM.JK": "Secondary Watchlist / Outlier Risk",
            "NCKL.JK": "Low Sample / Study Candidate",
            "MBMA.JK": "Low Sample / Study Candidate",
        },
        "primary_ticker": "INCO.JK",
        "lookback_days": 60,
        "threshold_pct": 9.0,
        "hold_days": 60,
        "cooldown_days": 60,
        "rule_text": "NICKEL naik >= +9% dalam 60 trading days | Entry next trading day | Hold 60D | Cooldown 60D",
        "summary_source": "csv",
        "summary_file": PROCESSED_DIR / "nickel_backtest_summary.csv",
        "yearly_source": "computed_from_trades",
        "trade_source": "csv",
        "trade_file": PROCESSED_DIR / "nickel_trade_details.csv",
    },
}


# ======================
# GENERAL HELPERS
# ======================

def normalize_ticker(value):
    value = str(value).strip().upper()
    if value and not value.endswith(".JK"):
        value = f"{value}.JK"
    return value


def safe_to_datetime(series):
    return pd.to_datetime(series, format="mixed", errors="coerce")


def safe_numeric(series):
    return pd.to_numeric(series, errors="coerce")


def format_date(value):
    if pd.isna(value):
        return "-"
    return pd.to_datetime(value).strftime("%Y-%m-%d")


def format_pct(value):
    if pd.isna(value):
        return "-"
    return f"{float(value):.2f}%"


def format_number(value):
    if pd.isna(value):
        return "-"
    return f"{float(value):,.2f}"


def table_exists(table_name):
    if not Path(DB_PATH).exists():
        return False

    with sqlite3.connect(DB_PATH) as con:
        result = pd.read_sql(
            """
            SELECT name
            FROM sqlite_master
            WHERE type = 'table'
              AND name = ?
            """,
            con,
            params=(table_name,),
        )

    return not result.empty


def read_sql_table(table_name):
    if not table_exists(table_name):
        return pd.DataFrame()

    with sqlite3.connect(DB_PATH) as con:
        return pd.read_sql(f"SELECT * FROM {table_name}", con)


# ======================
# TRADE DATE / SCHEDULE HELPERS
# ======================

@st.cache_data
def load_ticker_trade_calendar(ticker):
    """
    Actual trading calendar from daily_prices only.

    No manual holiday assumption. If a date has no stock price row, it is treated as
    non-trading / unavailable. This makes countdown follow real available data.
    """
    ticker = normalize_ticker(ticker)

    if not Path(DB_PATH).exists():
        return []

    with sqlite3.connect(DB_PATH) as con:
        df = pd.read_sql(
            """
            SELECT trade_date
            FROM daily_prices
            WHERE ticker = ?
            ORDER BY DATE(trade_date)
            """,
            con,
            params=(ticker,),
        )

    if df.empty:
        return []

    dates = safe_to_datetime(df["trade_date"]).dropna().dt.normalize().drop_duplicates()
    return dates.tolist()


def next_actual_trading_day_after(trigger_date, calendar_dates):
    """Return next available stock-price date after driver trigger date."""
    if pd.isna(trigger_date):
        return pd.NaT

    trigger = pd.to_datetime(trigger_date).normalize()
    future_dates = [d for d in calendar_dates if d > trigger]

    if not future_dates:
        return pd.NaT

    return future_dates[0]


def count_available_trading_days_from_entry(entry_date, ref_date, calendar_dates):
    """
    Count actual available stock rows from entry date through latest stock date.

    User-facing operational convention:
    - entry date is counted as day 1
    - example: entry 2026-06-05, data exists for 2026-06-05 and 2026-06-08
      => elapsed = 2, countdown for hold 10 = 8
    """
    if pd.isna(entry_date) or pd.isna(ref_date):
        return 0

    entry = pd.to_datetime(entry_date).normalize()
    ref = pd.to_datetime(ref_date).normalize()

    if ref < entry:
        return 0

    return int(sum(entry <= d <= ref for d in calendar_dates))


def nth_available_trading_day_from_entry(entry_date, hold_days, calendar_dates):
    """
    Return the actual sell date only when the hold window already exists in data.
    Entry date is day 1, so sell date is the hold_days-th available stock row.
    """
    if pd.isna(entry_date):
        return pd.NaT

    entry = pd.to_datetime(entry_date).normalize()
    dates = [d for d in calendar_dates if d >= entry]

    if len(dates) < hold_days:
        return pd.NaT

    return dates[hold_days - 1]


def build_signal_trade_schedule(row, config):
    status = str(row.get("signal_status", "")).upper()
    hold_days = int(config.get("hold_days", 10))

    if status not in ["ACTIVE_ACTIONABLE", "ACTIVE_BUT_COOLDOWN"]:
        return {
            "model_trigger_date": pd.NaT,
            "model_entry_date": pd.NaT,
            "model_sell_date": pd.NaT,
            "actual_trading_days_elapsed": 0,
            "sell_countdown_trading_days": None,
            "trade_phase": "NO_ACTIVE_TRADE",
        }

    # For a fresh actionable signal, latest driver date is the trigger.
    # For cooldown / active trade, last_signal_date is the first trigger date.
    if status == "ACTIVE_ACTIONABLE":
        trigger_date = row.get("driver_latest_date")
    else:
        trigger_date = row.get("last_signal_date")

    if pd.isna(trigger_date):
        return {
            "model_trigger_date": pd.NaT,
            "model_entry_date": pd.NaT,
            "model_sell_date": pd.NaT,
            "actual_trading_days_elapsed": 0,
            "sell_countdown_trading_days": None,
            "trade_phase": "NO_TRIGGER_DATE",
        }

    ticker = str(row.get("target_ticker", config.get("primary_ticker"))).upper().strip()
    calendar_dates = load_ticker_trade_calendar(ticker)

    entry_date = next_actual_trading_day_after(trigger_date, calendar_dates)

    ref_date = row.get("stock_latest_date")
    if pd.isna(ref_date) and calendar_dates:
        ref_date = max(calendar_dates)
    elif not pd.isna(ref_date):
        ref_date = pd.to_datetime(ref_date).normalize()

    elapsed = count_available_trading_days_from_entry(entry_date, ref_date, calendar_dates)
    countdown = max(hold_days - elapsed, 0)

    # Only show actual sell date once the 10th available stock-price row exists.
    sell_date = nth_available_trading_day_from_entry(entry_date, hold_days, calendar_dates)

    if pd.isna(entry_date):
        trade_phase = "WAITING_FOR_ENTRY_DATA"
    elif elapsed == 0:
        trade_phase = "ENTRY_PENDING"
    elif countdown > 0:
        trade_phase = "IN_HOLD"
    else:
        trade_phase = "SELL_DUE_OR_PAST"

    return {
        "model_trigger_date": trigger_date,
        "model_entry_date": entry_date,
        "model_sell_date": sell_date,
        "actual_trading_days_elapsed": elapsed,
        "sell_countdown_trading_days": countdown,
        "trade_phase": trade_phase,
    }


# ======================
# DATA LOADERS
# ======================

@st.cache_data
def load_driver_prices():
    path = Path(DRIVER_CSV_PATH)

    if not path.exists():
        return pd.DataFrame(columns=["driver", "driver_date", "value"])

    df = pd.read_csv(path)
    df.columns = df.columns.str.strip().str.lower()

    required_cols = {"driver", "driver_date", "value"}
    missing_cols = required_cols - set(df.columns)

    if missing_cols:
        st.error(f"Kolom driver_prices.csv kurang: {sorted(missing_cols)}")
        return pd.DataFrame(columns=["driver", "driver_date", "value"])

    df["driver"] = df["driver"].astype(str).str.upper().str.strip()
    df["driver_date"] = safe_to_datetime(df["driver_date"])
    df["value"] = safe_numeric(df["value"])

    df = df.dropna(subset=["driver", "driver_date", "value"])
    df = df.sort_values(["driver", "driver_date"]).reset_index(drop=True)

    return df


@st.cache_data
def load_stock_prices(tickers, start_date, end_date):
    tickers = tuple(normalize_ticker(t) for t in tickers)

    if not Path(DB_PATH).exists() or not tickers:
        return pd.DataFrame()

    placeholders = ",".join(["?"] * len(tickers))

    query = f"""
        SELECT *
        FROM daily_prices
        WHERE ticker IN ({placeholders})
          AND DATE(trade_date) BETWEEN DATE(?) AND DATE(?)
        ORDER BY ticker, DATE(trade_date)
    """

    params = (*tickers, str(start_date), str(end_date))

    with sqlite3.connect(DB_PATH) as con:
        df = pd.read_sql(query, con, params=params)

    if df.empty:
        return df

    df["ticker"] = df["ticker"].astype(str).str.upper().str.strip()
    df["trade_date"] = safe_to_datetime(df["trade_date"])

    numeric_cols = [
        "open_price",
        "high_price",
        "low_price",
        "close_price",
        "volume",
        "ma20",
        "ma50",
        "rsi",
        "ma_distance",
    ]

    for col in numeric_cols:
        if col in df.columns:
            df[col] = safe_numeric(df[col])

    df = df.dropna(subset=["ticker", "trade_date", "close_price"])
    df = df.sort_values(["ticker", "trade_date"]).reset_index(drop=True)

    return df


@st.cache_data
def load_latest_stock_rows(tickers):
    tickers = tuple(normalize_ticker(t) for t in tickers)

    if not Path(DB_PATH).exists() or not tickers:
        return pd.DataFrame()

    placeholders = ",".join(["?"] * len(tickers))

    query = f"""
        SELECT trade_date, ticker, close_price, volume
        FROM daily_prices
        WHERE ticker IN ({placeholders})
        ORDER BY ticker, DATE(trade_date)
    """

    with sqlite3.connect(DB_PATH) as con:
        df = pd.read_sql(query, con, params=tickers)

    if df.empty:
        return df

    df["ticker"] = df["ticker"].astype(str).str.upper().str.strip()
    df["trade_date"] = safe_to_datetime(df["trade_date"])
    df["close_price"] = safe_numeric(df["close_price"])
    df["volume"] = safe_numeric(df["volume"])

    df = df.dropna(subset=["ticker", "trade_date", "close_price"])
    df = df.sort_values(["ticker", "trade_date"]).reset_index(drop=True)

    df["prev_close"] = df.groupby("ticker")["close_price"].shift(1)
    df["prev_close_date"] = df.groupby("ticker")["trade_date"].shift(1)
    df["change_pct"] = (df["close_price"] / df["prev_close"] - 1) * 100

    latest = df.groupby("ticker").tail(1).copy()

    return latest


@st.cache_data
def load_latest_driver_signals():
    if not LATEST_SIGNAL_PATH.exists():
        return pd.DataFrame()

    df = pd.read_csv(LATEST_SIGNAL_PATH)
    df.columns = df.columns.str.strip()

    date_cols = [
        "driver_latest_date",
        "driver_prev_date",
        "last_signal_date",
        "stock_latest_date",
    ]

    for col in date_cols:
        if col in df.columns:
            df[col] = safe_to_datetime(df[col])

    if "driver_group" in df.columns:
        df["driver_group"] = df["driver_group"].astype(str).str.upper().str.strip()

    if "driver_symbol" in df.columns:
        df["driver_symbol"] = df["driver_symbol"].astype(str).str.upper().str.strip()

    if "target_ticker" in df.columns:
        df["target_ticker"] = df["target_ticker"].astype(str).str.upper().str.strip()

    return df


@st.cache_data
def load_summary(config):
    if config.get("summary_source") == "db":
        return read_sql_table(config.get("summary_table"))

    if config.get("summary_source") == "csv":
        path = Path(config.get("summary_file"))
        if path.exists():
            return pd.read_csv(path)

    return pd.DataFrame()


@st.cache_data
def load_yearly(config):
    if config.get("yearly_source") == "db":
        return read_sql_table(config.get("yearly_table"))

    return pd.DataFrame()


@st.cache_data
def load_trades(config):
    if config.get("trade_source") == "db":
        return read_sql_table(config.get("trade_table"))

    if config.get("trade_source") == "csv":
        path = Path(config.get("trade_file"))
        if path.exists():
            return pd.read_csv(path)

    return pd.DataFrame()


@st.cache_data
def get_available_date_range(tickers):
    tickers = tuple(normalize_ticker(t) for t in tickers)

    if not Path(DB_PATH).exists() or not tickers:
        today = pd.Timestamp.today().date()
        return today, today

    placeholders = ",".join(["?"] * len(tickers))

    query = f"""
        SELECT MIN(trade_date) AS min_date,
               MAX(trade_date) AS max_date
        FROM daily_prices
        WHERE ticker IN ({placeholders})
    """

    with sqlite3.connect(DB_PATH) as con:
        result = pd.read_sql(query, con, params=tickers)

    min_date = safe_to_datetime(result["min_date"]).iloc[0]
    max_date = safe_to_datetime(result["max_date"]).iloc[0]

    if pd.isna(min_date) or pd.isna(max_date):
        today = pd.Timestamp.today().date()
        return today, today

    return min_date.date(), max_date.date()


# ======================
# DISPLAY HELPERS
# ======================

def get_range_dates(range_option, max_date, page_key):
    max_ts = pd.Timestamp(max_date)

    if range_option == "1D":
        return max_date, max_date

    if range_option == "1W":
        return (max_ts - pd.DateOffset(weeks=1)).date(), max_date

    if range_option == "3M":
        return (max_ts - pd.DateOffset(months=3)).date(), max_date

    if range_option == "1Y":
        return (max_ts - pd.DateOffset(years=1)).date(), max_date

    start_date = st.sidebar.date_input(
        "From",
        value=(max_ts - pd.DateOffset(years=1)).date(),
        key=f"{page_key}_custom_start",
    )

    end_date = st.sidebar.date_input(
        "To",
        value=max_date,
        key=f"{page_key}_custom_end",
    )

    return start_date, end_date


def show_signal_status(config, driver_prices=None):
    st.subheader("Signal Status")

    latest_signals = load_latest_driver_signals()

    if latest_signals.empty:
        st.warning(
            "File latest signal belum tersedia. Jalankan `python latest_driver_signals.py` dulu."
        )
        return

    driver_group = config["driver_group"]

    signal_df = latest_signals[
        latest_signals["driver_group"].astype(str).str.upper() == driver_group
    ].copy()

    if signal_df.empty:
        st.warning(f"Belum ada latest signal untuk {driver_group}.")
        return

    row = signal_df.iloc[0].copy()

    # Use cooldown-debounced valid signal history as the source of truth.
    # latest_driver_signals.csv can show NO_SIGNAL when today's driver return
    # is below threshold, but the latest valid event can still be inside
    # the model hold/cooldown window.
    latest_valid_event = None

    if driver_prices is not None and not driver_prices.empty:
        valid_events = build_valid_signal_events(driver_prices, config)

        if not valid_events.empty:
            valid_events_for_calc = valid_events.copy()
            valid_events_for_calc["signal_date_dt"] = safe_to_datetime(
                valid_events_for_calc["signal_date"]
            )

            driver_latest_date = row.get("driver_latest_date")
            if not pd.isna(driver_latest_date):
                driver_latest_date = pd.to_datetime(driver_latest_date).normalize()
                valid_events_for_calc = valid_events_for_calc[
                    valid_events_for_calc["signal_date_dt"] <= driver_latest_date
                ].copy()

            if not valid_events_for_calc.empty:
                latest_valid_event = valid_events_for_calc.sort_values(
                    "signal_date_dt"
                ).iloc[-1]

                row["last_signal_date"] = latest_valid_event["signal_date_dt"]
                row["last_signal_return_pct"] = latest_valid_event.get(
                    "driver_return_pct"
                )

    schedule = build_signal_trade_schedule(row, config)

    # Keep the visible detail table aligned with the corrected row.
    for base_key in ["last_signal_date", "last_signal_return_pct"]:
        if base_key in signal_df.columns:
            signal_df[base_key] = row.get(base_key)

    for key, value in schedule.items():
        signal_df[key] = value
        row[key] = value
        
    # Recalculate visible signal status from the latest valid event schedule.
    # This prevents the dashboard from showing NO_SIGNAL while a previous
    # valid trigger is still inside hold period.
    if latest_valid_event is not None:
        elapsed_td = pd.to_numeric(
            row.get("actual_trading_days_elapsed"),
            errors="coerce",
        )
        cooldown_remaining = pd.to_numeric(
            row.get("cooldown_remaining_days"),
            errors="coerce",
        )
        hold_days = int(config.get("hold_days", 0))

        if pd.notna(elapsed_td):
            if elapsed_td < 1:
                row["signal_status"] = "WAIT_ENTRY"
            elif hold_days > 0 and elapsed_td <= hold_days:
                row["signal_status"] = "ACTIVE_ACTIONABLE"
            elif pd.notna(cooldown_remaining) and cooldown_remaining > 0:
                row["signal_status"] = "ACTIVE_BUT_COOLDOWN"
            else:
                row["signal_status"] = "NO_SIGNAL"

            if "signal_status" in signal_df.columns:
                signal_df["signal_status"] = row["signal_status"]
    
    col1, col2, col3, col4 = st.columns(4)

    col1.metric(
        "Driver Date",
        format_date(row.get("driver_latest_date")),
    )

    col2.metric(
        f"{config['driver_symbol']} {config['lookback_days']}D",
        format_pct(row.get("driver_return_pct")),
    )

    col3.metric(
        "Threshold",
        format_pct(row.get("threshold_pct")),
    )

    col4.metric(
        "Status",
        str(row.get("signal_status", "-")),
    )

    status = str(row.get("signal_status", "")).upper()

    if status == "ACTIVE_ACTIONABLE":
        st.success(
            f"Signal aktif dan actionable untuk {row.get('target_ticker', config['primary_ticker'])}. "
            f"Model entry: {format_date(row.get('model_entry_date'))}. "
            f"Elapsed: {row.get('actual_trading_days_elapsed', '-')} trading days. "
            f"Countdown to sell: {row.get('sell_countdown_trading_days', '-')} trading days."
        )
    elif status == "ACTIVE_BUT_COOLDOWN":
        st.warning(
            "Threshold hit, tapi masih dalam cooldown / active trade window. "
            f"First trigger: {format_date(row.get('last_signal_date'))}. "
            f"Model entry: {format_date(row.get('model_entry_date'))}. "
            f"Elapsed: {row.get('actual_trading_days_elapsed', '-')} trading days. "
            f"Sisa menuju sell: {row.get('sell_countdown_trading_days', '-')} trading days."
        )
    else:
        st.info(f"Belum ada signal aktif untuk {driver_group}.")

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Trigger", format_date(row.get("model_trigger_date")))
    c2.metric("Entry", format_date(row.get("model_entry_date")))
    c3.metric("Elapsed TD", row.get("actual_trading_days_elapsed", "-"))
    c4.metric("Sell Countdown", row.get("sell_countdown_trading_days", "-"))
    c5.metric("Sell Date", format_date(row.get("model_sell_date")))

    detail_cols = [
        "driver_group",
        "driver_symbol",
        "target_ticker",
        "driver_latest_date",
        "driver_return_pct",
        "threshold_pct",
        "threshold_hit",
        "signal_status",
        "model_trigger_date",
        "model_entry_date",
        "model_sell_date",
        "actual_trading_days_elapsed",
        "sell_countdown_trading_days",
        "trade_phase",
        "last_signal_date",
        "last_signal_return_pct",
        "cooldown_remaining_days",
        "stock_latest_date",
        "stock_latest_close",
    ]

    detail_cols = [c for c in detail_cols if c in signal_df.columns]

    with st.expander("Signal Detail", expanded=False):
        st.caption(
            "Countdown memakai actual available trading rows di daily_prices. "
            "Entry date dihitung sebagai day 1. Sell date baru terisi kalau row trading day ke-N sudah tersedia."
        )
        st.dataframe(signal_df[detail_cols], use_container_width=True, hide_index=True)

    with st.expander("Signal Detail", expanded=False):
        st.caption(
            "Countdown memakai actual available trading rows di daily_prices. "
            "Entry date dihitung sebagai day 1. Sell date baru terisi kalau row trading day ke-N sudah tersedia."
        )
        st.dataframe(signal_df[detail_cols], use_container_width=True, hide_index=True)


def show_watchlist_confidence_signal(config, current_driver_return, selected_ticker):
    st.subheader(f"📊 Technical Confidence Signal — {selected_ticker}")
    
    if not Path(DB_PATH).exists():
        st.warning("Database tidak ditemukan.")
        return

    with sqlite3.connect(DB_PATH) as con:
        stock_data = pd.read_sql(
            """
            SELECT trade_date, ticker, close_price, ma20, ma50, rsi
            FROM daily_prices
            WHERE ticker = ?
            ORDER BY DATE(trade_date) DESC
            LIMIT 1
            """,
            con,
            params=(selected_ticker,),
        )
        
    if stock_data.empty:
        st.info(f"Belum ada data teknikal di database untuk menghitung kustom confidence pada saham {selected_ticker}.")
        return

    row = stock_data.iloc[0]
    close_p = float(row.get("close_price", 0))
    ma20_v = float(row.get("ma20", 0))
    
    if ma20_v > 0:
        calculated_ma_dist = ((close_p - ma20_v) / ma20_v) * 100
    else:
        calculated_ma_dist = 0.0
        
    stock_data["ma_distance"] = calculated_ma_dist
    conf_result = compute_dynamic_confidence(stock_data, current_driver_return)
    
    # ─── HACK CSS UNTUK MENGECILKAN FONT METRIC KANVAS DASHBOARD ───
    st.markdown(
        """
        <style>
        div[data-testid="stMetricValue"] {
            font-size: 18px !important;  /* Kecilin ukuran font value biar ga kepotong */
            white-space: normal !important; /* Biar teks panjang otomatis turun ke bawah klo ga muat */
            line-height: 1.2 !important;
        }
        div[data-testid="stMetricLabel"] {
            font-size: 13px !important;  /* Kecilin sedikit font judul metriknya */
        }
        </style>
        """,
        unsafe_allow_html=True
    )
    
    # Render komponen UI bursa dengan font baru yang lebih bersahabat
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Confidence Level", conf_result["confidence_level"])
    col2.metric("Action Model", conf_result["recommended_action"])
    col3.metric("Position Size Hint", conf_result["position_size_hint"])
    col4.metric("RSI Terkini", f"{row.get('rsi', 0):.2f}")
    
    if conf_result["confidence_level"] == "HIGH":
        st.success(f"**Analisis Struktur:** {conf_result['reason']}")
    elif conf_result["confidence_level"] == "MEDIUM":
        st.warning(f"**Analisis Struktur:** {conf_result['reason']}")
    else:
        st.error(f"**Analisis Struktur:** {conf_result['reason']}")
        

def show_rule_card(config):
    st.subheader("Final Rule")

    rule_df = pd.DataFrame(
        [
            {"item": "Driver", "value": config["driver_symbol"]},
            {"item": "Primary Target", "value": config["primary_ticker"]},
            {
                "item": "Trigger",
                "value": f"{config['driver_symbol']} >= +{config['threshold_pct']}% dalam {config['lookback_days']} trading days",
            },
            {"item": "Entry", "value": "Next trading day setelah signal"},
            {"item": "Holding Period", "value": f"{config['hold_days']} trading days"},
            {"item": "Cooldown", "value": f"{config['cooldown_days']} trading days"},
            {"item": "Source", "value": config["source_label"]},
        ]
    )

    st.dataframe(rule_df, use_container_width=True, hide_index=True)
    st.caption(config["rule_text"])


def show_driver_today(config, driver_prices):
    st.subheader(f"{config['driver_symbol']} Today")

    driver_df = driver_prices[
        driver_prices["driver"] == config["driver_symbol"]
    ].copy()

    if driver_df.empty:
        st.warning(f"Belum ada data driver {config['driver_symbol']} di {DRIVER_CSV_PATH}.")
        return

    driver_df = driver_df.sort_values("driver_date").reset_index(drop=True)
    lookback = config["lookback_days"]

    driver_df["prev_value"] = driver_df["value"].shift(1)
    driver_df["today_change_pct"] = (driver_df["value"] / driver_df["prev_value"] - 1) * 100
    driver_df["lookback_change_pct"] = driver_df["value"].pct_change(lookback) * 100

    latest = driver_df.dropna(subset=["value", "lookback_change_pct"]).tail(1)

    if latest.empty:
        st.warning(f"Data {config['driver_symbol']} belum cukup untuk hitung lookback.")
        return

    row = latest.iloc[0]

    col1, col2, col3, col4 = st.columns(4)

    col1.metric("Date", format_date(row["driver_date"]))
    col2.metric("Value", format_number(row["value"]))
    col3.metric("Daily Change", format_pct(row["today_change_pct"]))
    col4.metric(f"{lookback}D Change", format_pct(row["lookback_change_pct"]))


def show_watchlist(config):
    st.subheader(f"{config['driver_symbol']} Related Watchlist")

    latest = load_latest_stock_rows(tuple(config["tickers"]))

    if latest.empty:
        st.warning("Belum ada data harga untuk watchlist ini.")
        return

    latest["role"] = latest["ticker"].map(config.get("roles", {})).fillna("Watchlist")
    latest["last_close_date"] = latest["trade_date"].dt.strftime("%Y-%m-%d")
    latest["prev_close_date"] = latest["prev_close_date"].dt.strftime("%Y-%m-%d")
    latest["change_pct"] = latest["change_pct"].round(2)

    latest["status"] = latest["change_pct"].apply(
        lambda x: "Up" if x > 0 else "Down" if x < 0 else "Flat"
    )

    show_cols = [
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

    show_cols = [c for c in show_cols if c in latest.columns]

    st.dataframe(latest[show_cols], use_container_width=True, hide_index=True)


def plot_driver_chart(config, driver_prices, start_date, end_date):
    driver_df = driver_prices[
        (driver_prices["driver"] == config["driver_symbol"])
        & (driver_prices["driver_date"] >= pd.to_datetime(start_date))
        & (driver_prices["driver_date"] <= pd.to_datetime(end_date))
    ].copy()

    st.subheader(f"{config['driver_symbol']} Driver Chart")

    if driver_df.empty:
        st.warning("Data driver kosong pada range ini.")
        return

    fig = go.Figure()

    fig.add_trace(
        go.Scatter(
            x=driver_df["driver_date"],
            y=driver_df["value"],
            mode="lines",
            name=config["driver_symbol"],
        )
    )

    fig.update_layout(
        height=360,
        xaxis_title="Date",
        yaxis_title="Driver Price",
    )

    st.plotly_chart(fig, use_container_width=True)


def plot_stock_chart(price_df, selected_ticker):
    st.subheader(f"Price Chart - {selected_ticker}")

    data = price_df[price_df["ticker"] == selected_ticker].copy()

    if data.empty:
        st.warning("Data harga kosong untuk ticker/range ini.")
        return

    fig = go.Figure()

    candle_cols = {"open_price", "high_price", "low_price", "close_price"}

    if candle_cols.issubset(data.columns):
        fig.add_trace(
            go.Candlestick(
                x=data["trade_date"],
                open=data["open_price"],
                high=data["high_price"],
                low=data["low_price"],
                close=data["close_price"],
                name="Price",
                increasing_line_color="#59CD90",
                decreasing_line_color="#EE6352",
            )
        )
    else:
        fig.add_trace(
            go.Scatter(
                x=data["trade_date"],
                y=data["close_price"],
                mode="lines",
                name="Close Price",
            )
        )

    if "ma20" in data.columns and data["ma20"].notna().any():
        fig.add_trace(
            go.Scatter(
                x=data["trade_date"],
                y=data["ma20"],
                mode="lines",
                name="MA20",
                line=dict(color="#3FA7D6"),
            )
        )

    if "ma50" in data.columns and data["ma50"].notna().any():
        fig.add_trace(
            go.Scatter(
                x=data["trade_date"],
                y=data["ma50"],
                mode="lines",
                name="MA50",
                line=dict(color="#FAC05E"),
            )
        )

    fig.update_layout(
        height=560,
        xaxis_rangeslider_visible=False,
        xaxis_title="Date",
        yaxis_title="Price",
    )

    st.plotly_chart(fig, use_container_width=True)
    

# ======================
# GENERAL HELPERS
# ======================

def compute_dynamic_confidence(stock_latest_row, driver_return_pct):
    """
    Menghitung Confidence Signal secara dinamis berdasarkan data teknikal terkini
    dari database untuk ticker apa pun di dalam watchlist.
    """
    if stock_latest_row.empty:
        return {
            "signal_status": "NO_DATA", "confidence_level": "N/A",
            "recommended_action": "WAIT", "position_size_hint": "0%",
            "reason": "Tidak ada data teknikal terkini di database."
        }
        
    row = stock_latest_row.iloc[0]
    rsi = row.get("rsi", 50)
    ma_dist = row.get("ma_distance", 0)  # Biasanya % jarak ke MA20 atau MA50
    close_price = row.get("close_price", 0)
    ma20 = row.get("ma20", 0)
    ma50 = row.get("ma50", 0)
    
    # Skor Awal
    score = 0
    reasons = []
    
    # 1. Evaluasi Tren (MA)
    if close_price > ma20 and ma20 > ma50:
        score += 2
        reasons.append("Tren Bullish Kuat (Price > MA20 > MA50)")
    elif close_price > ma20:
        score += 1
        reasons.append("Tren Bullish Transisi (Price > MA20)")
    else:
        reasons.append("Tren Lemah (Price < MA20)")
        
    # 2. Evaluasi Momentum (RSI)
    if 45 <= rsi <= 65:
        score += 2
        reasons.append(f"RSI Ideal ({rsi:.1f})")
    elif rsi > 65:
        score += 1
        reasons.append(f"RSI Overbought Alert ({rsi:.1f})")
    else:
        reasons.append(f"RSI Lemah/Bearish ({rsi:.1f})")
        
    # 3. Jarak ke MA (Mencegah beli di pucuk)
    if ma_dist > 12.0:
        score -= 1
        reasons.append(f"Harga terlalu jauh di atas MA20 ({ma_dist:.1f}%), rawan profit taking")

    # Tentukan Tingkat Keyakinan & Action
    if score >= 3 and driver_return_pct >= 0:
        confidence = "HIGH"
        action = "AGGRESSIVE BUY / ACCUMULATE"
        size = "100% Alokasi Sektor"
    elif score >= 1 and driver_return_pct >= 0:
        confidence = "MEDIUM"
        action = "SELECTive BUY / PYRAMIDING"
        size = "50% Alokasi Sektor"
    else:
        confidence = "LOW"
        action = "HOLD / WAIT FOR RETRACEMENT"
        size = "0% - 25% Alokasi"

    return {
        "signal_status": "ACTIVE" if driver_return_pct > 0 else "STANDBY",
        "confidence_level": confidence,
        "recommended_action": action,
        "position_size_hint": size,
        "reason": " | ".join(reasons)
    }
    
def normalize_summary_for_display(summary):
    if summary.empty:
        return summary

    df = summary.copy()

    rename_map = {
        "win_rate_pct": "win_rate",
        "avg_return_pct": "avg_trade_return_pct",
        "best_return_pct": "best_trade_pct",
        "worst_return_pct": "worst_trade_pct",
    }

    df = df.rename(columns={k: v for k, v in rename_map.items() if k in df.columns})

    return df


def show_backtest_summary(config, selected_ticker):
    st.subheader("Backtest Summary")

    summary = load_summary(config)

    if summary.empty:
        st.warning("Backtest summary belum tersedia.")
        return pd.DataFrame()

    summary = normalize_summary_for_display(summary)

    if "ticker" in summary.columns:
        summary["ticker"] = summary["ticker"].astype(str).str.upper().str.strip()
        summary = summary[summary["ticker"].isin(config["tickers"])].copy()

    if summary.empty:
        st.warning("Backtest summary kosong untuk driver ini.")
        return summary

    sort_cols = [c for c in ["score", "profit_factor", "compound_return_pct"] if c in summary.columns]
    if sort_cols:
        summary = summary.sort_values(sort_cols, ascending=False)

    metric_row = None

    if "ticker" in summary.columns:
        selected_rows = summary[summary["ticker"] == selected_ticker].copy()
        if not selected_rows.empty:
            metric_row = selected_rows.iloc[0]
        else:
            st.info(
                f"{selected_ticker} masih study candidate / belum ada hasil backtest valid di file summary saat ini."
            )

    if metric_row is None:
        metric_row = summary.iloc[0]

    m1, m2, m3, m4 = st.columns(4)

    if "compound_return_pct" in metric_row.index:
        m1.metric("Compound Return", format_pct(metric_row["compound_return_pct"]))
    else:
        m1.metric("Compound Return", "-")

    if "win_rate" in metric_row.index:
        m2.metric("Win Rate", format_pct(metric_row["win_rate"]))
    else:
        m2.metric("Win Rate", "-")

    if "profit_factor" in metric_row.index:
        m3.metric("Profit Factor", format_number(metric_row["profit_factor"]))
    else:
        m3.metric("Profit Factor", "-")

    if "total_trades" in metric_row.index:
        m4.metric("Total Trades", int(metric_row["total_trades"]))
    else:
        m4.metric("Total Trades", "-")

    show_cols = [
        "driver",
        "ticker",
        "rule",
        "total_trades",
        "wins",
        "losses",
        "win_rate",
        "profit_factor",
        "compound_return_pct",
        "avg_trade_return_pct",
        "median_trade_return_pct",
        "best_trade_pct",
        "worst_trade_pct",
        "max_drawdown_pct",
        "score",
    ]

    show_cols = [c for c in show_cols if c in summary.columns]

    st.dataframe(summary[show_cols].head(30), use_container_width=True, hide_index=True)

    return summary


def get_best_rule_for_ticker(summary, selected_ticker):
    if summary.empty or "ticker" not in summary.columns:
        return {}

    df = normalize_summary_for_display(summary)
    df["ticker"] = df["ticker"].astype(str).str.upper().str.strip()
    df = df[df["ticker"] == selected_ticker].copy()

    if df.empty:
        return {}

    sort_cols = [c for c in ["score", "profit_factor", "compound_return_pct"] if c in df.columns]
    if sort_cols:
        df = df.sort_values(sort_cols, ascending=False)

    return df.iloc[0].to_dict()


def filter_trades_by_best_rule(trades, config, selected_ticker, best_rule):
    if trades.empty:
        return trades

    df = trades.copy()

    if "ticker" in df.columns:
        df["ticker"] = df["ticker"].astype(str).str.upper().str.strip()
        df = df[df["ticker"] == selected_ticker].copy()

    # Coal generic backtest columns
    rule_filters = {
        "driver_symbol": best_rule.get("driver_symbol", config.get("driver_symbol")),
        "lookback_days": best_rule.get("lookback_days", config.get("lookback_days")),
        "threshold_pct": best_rule.get("threshold_pct", config.get("threshold_pct")),
        "hold_days": best_rule.get("hold_days", config.get("hold_days")),
        "cooldown_days": best_rule.get("cooldown_days", config.get("cooldown_days")),
    }

    for col, value in rule_filters.items():
        if col in df.columns and value is not None:
            if col == "driver_symbol":
                df = df[df[col].astype(str).str.upper().str.strip() == str(value).upper()].copy()
            else:
                df = df[pd.to_numeric(df[col], errors="coerce") == float(value)].copy()

    return df


def show_yearly_and_trades(config, selected_ticker, summary):
    trades = load_trades(config)
    yearly = load_yearly(config)
    best_rule = get_best_rule_for_ticker(summary, selected_ticker)

    st.subheader(f"{selected_ticker} Year-by-Year Attribution")

    if config.get("yearly_source") == "db" and not yearly.empty:
        df_yearly = yearly.copy()

        if "ticker" in df_yearly.columns:
            df_yearly["ticker"] = df_yearly["ticker"].astype(str).str.upper().str.strip()
            df_yearly = df_yearly[df_yearly["ticker"] == selected_ticker].copy()

        if df_yearly.empty:
            st.info("Yearly attribution belum tersedia untuk ticker ini.")
        else:
            st.dataframe(df_yearly, use_container_width=True, hide_index=True)

            y_col = None
            for candidate in ["annual_return_pct", "total_simple_return_pct", "return_pct"]:
                if candidate in df_yearly.columns:
                    y_col = candidate
                    break

            if "year" in df_yearly.columns and y_col is not None:
                fig = go.Figure()
                fig.add_trace(
                    go.Bar(
                        x=df_yearly["year"],
                        y=df_yearly[y_col],
                        name=y_col,
                    )
                )
                fig.update_layout(
                    height=420,
                    xaxis_title="Year",
                    yaxis_title=y_col,
                )
                st.plotly_chart(fig, use_container_width=True)

    elif config.get("yearly_source") == "computed_from_trades" and not trades.empty:
        trade_filtered = filter_trades_by_best_rule(trades, config, selected_ticker, best_rule)

        date_col = "entry_date" if "entry_date" in trade_filtered.columns else "buy_date" if "buy_date" in trade_filtered.columns else None

        if trade_filtered.empty or date_col is None or "return_pct" not in trade_filtered.columns:
            st.info("Trade detail belum cukup untuk hitung yearly attribution.")
        else:
            trade_filtered[date_col] = safe_to_datetime(trade_filtered[date_col])
            trade_filtered["return_pct"] = safe_numeric(trade_filtered["return_pct"])
            trade_filtered = trade_filtered.dropna(subset=[date_col, "return_pct"])
            trade_filtered["year"] = trade_filtered[date_col].dt.year

            yearly_calc = trade_filtered.groupby("year").agg(
                trades=("return_pct", "count"),
                wins=("return_pct", lambda x: (x > 0).sum()),
                losses=("return_pct", lambda x: (x <= 0).sum()),
                avg_return_pct=("return_pct", "mean"),
                total_simple_return_pct=("return_pct", "sum"),
                best_trade_pct=("return_pct", "max"),
                worst_trade_pct=("return_pct", "min"),
            ).reset_index()

            yearly_calc["win_rate"] = yearly_calc["wins"] / yearly_calc["trades"] * 100
            yearly_calc = yearly_calc.round(2)

            st.dataframe(yearly_calc, use_container_width=True, hide_index=True)

            fig = go.Figure()
            fig.add_trace(
                go.Bar(
                    x=yearly_calc["year"],
                    y=yearly_calc["total_simple_return_pct"],
                    name="Total Simple Return %",
                )
            )
            fig.update_layout(
                height=420,
                xaxis_title="Year",
                yaxis_title="Total Simple Return %",
            )
            st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("Yearly attribution belum tersedia.")

    st.subheader(f"{selected_ticker} Trade Detail")

    if trades.empty:
        st.warning("Trade detail belum tersedia.")
        return

    trade_filtered = filter_trades_by_best_rule(trades, config, selected_ticker, best_rule)

    if trade_filtered.empty:
        st.info("Trade detail kosong untuk ticker/rule ini.")
        return

    for col in ["event_date", "signal_date", "buy_date", "sell_date", "entry_date", "exit_date"]:
        if col in trade_filtered.columns:
            trade_filtered[col] = safe_to_datetime(trade_filtered[col])

    show_cols = [
        "signal_date",
        "event_date",
        "driver_return_pct",
        "driver_change_pct",
        "entry_date",
        "buy_date",
        "exit_date",
        "sell_date",
        "entry_price",
        "buy_price",
        "exit_price",
        "sell_price",
        "return_pct",
        "profit_rp",
        "ending_value",
    ]

    show_cols = [c for c in show_cols if c in trade_filtered.columns]

    sort_col = None
    for candidate in ["entry_date", "buy_date", "signal_date", "event_date"]:
        if candidate in trade_filtered.columns:
            sort_col = candidate
            break

    if sort_col:
        trade_filtered = trade_filtered.sort_values(sort_col)

    st.dataframe(trade_filtered[show_cols], use_container_width=True, hide_index=True)

def build_valid_signal_events(driver_prices, config):
    driver_symbol = str(config["driver_symbol"]).upper().strip()
    lookback_days = int(config["lookback_days"])
    threshold_pct = float(config["threshold_pct"])
    cooldown_days = int(config["cooldown_days"])

    if driver_prices.empty:
        return pd.DataFrame()

    d = driver_prices.copy()
    d.columns = d.columns.str.strip().str.lower()

    if "driver" not in d.columns or "driver_date" not in d.columns or "value" not in d.columns:
        return pd.DataFrame()

    d["driver"] = d["driver"].astype(str).str.upper().str.strip()
    d["driver_date"] = safe_to_datetime(d["driver_date"])
    d["value"] = safe_numeric(d["value"])

    d = d[
        d["driver"] == driver_symbol
    ].dropna(subset=["driver_date", "value"]).copy()

    d = d.sort_values("driver_date").reset_index(drop=True)

    if d.empty or len(d) <= lookback_days:
        return pd.DataFrame()

    d["driver_return_pct"] = (
        d["value"].pct_change(lookback_days) * 100
    )

    events = []
    cooldown_until_idx = -1

    for i, row in d.iterrows():
        if i <= cooldown_until_idx:
            continue

        if pd.notna(row["driver_return_pct"]) and row["driver_return_pct"] >= threshold_pct:
            cooldown_end_idx = min(i + cooldown_days, len(d) - 1)
            cooldown_end_date = d.loc[cooldown_end_idx, "driver_date"]

            events.append({
                "signal_date": row["driver_date"],
                "driver_symbol": driver_symbol,
                "driver_close": row["value"],
                "driver_return_pct": row["driver_return_pct"],
                "lookback_days": lookback_days,
                "threshold_pct": threshold_pct,
                "cooldown_days": cooldown_days,
                "cooldown_until_est_date": cooldown_end_date,
            })

            cooldown_until_idx = i + cooldown_days

    events_df = pd.DataFrame(events)

    if events_df.empty:
        return events_df

    events_df["signal_date"] = pd.to_datetime(
        events_df["signal_date"],
        format="mixed",
        errors="coerce"
    ).dt.strftime("%Y-%m-%d")

    events_df["cooldown_until_est_date"] = pd.to_datetime(
        events_df["cooldown_until_est_date"],
        format="mixed",
        errors="coerce"
    ).dt.strftime("%Y-%m-%d")

    events_df["driver_close"] = safe_numeric(events_df["driver_close"]).round(2)
    events_df["driver_return_pct"] = safe_numeric(events_df["driver_return_pct"]).round(2)

    return events_df


def show_valid_signal_history(driver_prices, config):
    st.subheader("Valid Signal History")

    valid_events = build_valid_signal_events(
        driver_prices=driver_prices,
        config=config,
    )

    if valid_events.empty:
        st.info("Belum ada valid signal event.")
        return

    show_cols = [
        "signal_date",
        "driver_symbol",
        "driver_close",
        "driver_return_pct",
        "lookback_days",
        "threshold_pct",
        "cooldown_days",
        "cooldown_until_est_date",
    ]

    show_cols = [c for c in show_cols if c in valid_events.columns]

    st.caption(
        "Tabel ini hanya menampilkan valid signal pertama setelah cooldown. "
        "Raw threshold-hit harian selama cooldown tidak dihitung sebagai signal baru."
    )

    st.dataframe(
        valid_events.sort_values("signal_date", ascending=False)[show_cols].head(30),
        use_container_width=True,
        hide_index=True,
    )

def compute_realtime_driver_signal(config):
    """
    Menghitung sinyal tren driver secara real-time dari CSV.
    Versi Super Kebal: Dilengkapi auto-fallback jika nama kolom close tidak standar.
    """
    import pandas as pd
    from pathlib import Path
    
    driver_symbol = config["driver_symbol"]
    lookback_days = config["lookback_days"]
    threshold_pct = config["threshold_pct"]
    
    csv_path = Path("data/driver_prices.csv")
    if not csv_path.exists():
        return 0.0, "STANDBY", "File data/driver_prices.csv tidak ditemukan."
        
    try:
        df_all_drivers = pd.read_csv(csv_path)
        
        # Filter berdasarkan simbol driver
        if "driver_symbol" in df_all_drivers.columns:
            df_driver = df_all_drivers[df_all_drivers["driver_symbol"].astype(str).str.upper() == driver_symbol.upper()].copy()
        elif "ticker" in df_all_drivers.columns:
            df_driver = df_all_drivers[df_all_drivers["ticker"].astype(str).str.upper() == driver_symbol.upper()].copy()
        else:
            first_col = df_all_drivers.columns[0]
            df_driver = df_all_drivers[df_all_drivers[first_col].astype(str).str.upper() == driver_symbol.upper()].copy()
            
    except Exception as e:
        return 0.0, "ERROR", f"Gagal membaca file CSV driver: {str(e)}"

    if df_driver.empty:
        return 0.0, "STANDBY", f"Data untuk driver '{driver_symbol}' tidak ditemukan di file CSV."

    # 🔍 DETEKSI KOLOM TANGGAL SECARA AMAN
    date_cols = [col for col in df_driver.columns if "date" in col.lower()]
    date_col = date_cols[0] if date_cols else df_driver.columns[0]
    
    # 🔍 DETEKSI KOLOM HARGA SECARA AMAN
    close_cols = [col for col in df_driver.columns if "close" in col.lower() or "price" in col.lower() or "val" in col.lower()]
    close_col = close_cols[0] if close_cols else df_driver.columns[-1]
    
    # Ubah ke datetime asli dan urutkan kronologis murni
    df_driver[date_col] = pd.to_datetime(df_driver[date_col], format='mixed')
    df_driver = df_driver.sort_values(by=date_col).reset_index(drop=True)
    
    if len(df_driver) < 2:
        return 0.0, "STANDBY", f"Data '{driver_symbol}' di CSV terlalu sedikit."

    # 🎯 AMBIL BARIS PALING AKHIR (Terbaru)
    latest_row = df_driver.iloc[-1]
    latest_price = float(latest_row[close_col])
    latest_date_str = latest_row[date_col].strftime("%Y-%m-%d")
    
    # Ambil harga acuan masa lalu berdasarkan lookback_days
    base_idx = max(0, len(df_driver) - 1 - lookback_days)
    base_price = float(df_driver.iloc[base_idx][close_col])
    
    if base_price == 0:
        return 0.0, "STANDBY", "Harga acuan masa lalu bernilai 0."
        
    # Hitung % return live komoditas
    driver_return_pct = ((latest_price - base_price) / base_price) * 100
    
    # Klasifikasi Sinyal
    if driver_return_pct >= threshold_pct:
        signal_status = "BUY"
        reason = f"Driver {driver_symbol} menguat +{driver_return_pct:.2f}% (>= +{threshold_pct}%) per {latest_date_str}."
    elif driver_return_pct <= -threshold_pct:
        signal_status = "SHORT/SELL"
        reason = f"Driver {driver_symbol} melemah {driver_return_pct:.2f}% (<= -{threshold_pct}%) per {latest_date_str}."
    else:
        signal_status = "STANDBY"
        reason = f"Driver {driver_symbol} konsolidasi ({driver_return_pct:.2f}%) di dalam threshold (per {latest_date_str})."
        
    return driver_return_pct, signal_status, reason


# ======================
# MAIN APP
# ======================

st.sidebar.title("Indonesia Market Dashboard")

page = st.sidebar.selectbox(
    "Menu",
    [
        "Gold Driver",
        "Coal Driver",
        "Nickel Driver",
    ],
)

# ========================================================
# 1. ENGINE PENDUKUNG: REALTIME SIGNAL CALCULATOR
# ========================================================
def compute_realtime_driver_signal(config):
    """
    Menghitung sinyal tren driver secara real-time dari CSV.
    Versi Super Kebal: Dilengkapi auto-fallback jika nama kolom close tidak standar.
    """
    import pandas as pd
    from pathlib import Path
    
    driver_symbol = config["driver_symbol"]
    lookback_days = config["lookback_days"]
    threshold_pct = config["threshold_pct"]
    
    csv_path = Path("data/driver_prices.csv")
    if not csv_path.exists():
        return 0.0, "STANDBY", "File data/driver_prices.csv tidak ditemukan."
        
    try:
        df_all_drivers = pd.read_csv(csv_path)
        
        if "driver_symbol" in df_all_drivers.columns:
            df_driver = df_all_drivers[df_all_drivers["driver_symbol"].astype(str).str.upper() == driver_symbol.upper()].copy()
        elif "ticker" in df_all_drivers.columns:
            df_driver = df_all_drivers[df_all_drivers["ticker"].astype(str).str.upper() == driver_symbol.upper()].copy()
        else:
            first_col = df_all_drivers.columns[0]
            df_driver = df_all_drivers[df_all_drivers[first_col].astype(str).str.upper() == driver_symbol.upper()].copy()
            
    except Exception as e:
        return 0.0, "ERROR", f"Gagal membaca file CSV driver: {str(e)}"

    if df_driver.empty:
        return 0.0, "STANDBY", f"Data untuk driver '{driver_symbol}' tidak ditemukan di file CSV."

    date_cols = [col for col in df_driver.columns if "date" in col.lower()]
    date_col = date_cols[0] if date_cols else df_driver.columns[0]
    
    close_cols = [col for col in df_driver.columns if "close" in col.lower() or "price" in col.lower() or "val" in col.lower()]
    close_col = close_cols[0] if close_cols else df_driver.columns[-1]
    
    df_driver[date_col] = pd.to_datetime(df_driver[date_col], format='mixed')
    df_driver = df_driver.sort_values(by=date_col).reset_index(drop=True)
    
    if len(df_driver) < 2:
        return 0.0, "STANDBY", f"Data '{driver_symbol}' di CSV terlalu sedikit."

    latest_row = df_driver.iloc[-1]
    latest_price = float(latest_row[close_col])
    latest_date_str = latest_row[date_col].strftime("%Y-%m-%d")
    
    base_idx = max(0, len(df_driver) - 1 - lookback_days)
    base_price = float(df_driver.iloc[base_idx][close_col])
    
    if base_price == 0:
        return 0.0, "STANDBY", "Harga acuan masa lalu bernilai 0."
        
    driver_return_pct = ((latest_price - base_price) / base_price) * 100
    
    if driver_return_pct >= threshold_pct:
        signal_status = "BUY"
        reason = f"Driver {driver_symbol} menguat +{driver_return_pct:.2f}% (>= +{threshold_pct}%) per {latest_date_str}."
    elif driver_return_pct <= -threshold_pct:
        signal_status = "SHORT/SELL"
        reason = f"Driver {driver_symbol} melemah {driver_return_pct:.2f}% (<= -{threshold_pct}%) per {latest_date_str}."
    else:
        signal_status = "STANDBY"
        reason = f"Driver {driver_symbol} konsolidasi ({driver_return_pct:.2f}%) di dalam threshold (per {latest_date_str})."
        
    return driver_return_pct, signal_status, reason


# ========================================================
# 2. FUNGSI UTAMA: RENDER DRIVER PAGE (WITH INJECTION)
# ========================================================
def render_driver_page(page_name):
    import pandas as pd
    
    config = DRIVER_CONFIG[page_name]

    st.title(config["title"])
    st.caption(config["description"])

    min_date, max_date = get_available_date_range(tuple(config["tickers"]))

    st.sidebar.subheader(f"{config['title']} Settings")

    selected_ticker = st.sidebar.selectbox(
        "Pilih Saham",
        config["tickers"],
        index=config["tickers"].index(config["primary_ticker"]),
        key=f"{page_name}_ticker",
    )

    range_option = st.sidebar.radio(
        "Range",
        ["1D", "1W", "3M", "1Y", "Custom"],
        horizontal=True,
        key=f"{page_name}_range",
    )
    
    start_date, end_date = get_range_dates(range_option, max_date, page_name)

    if pd.to_datetime(start_date) > pd.to_datetime(end_date):
        st.error("Tanggal From tidak boleh lebih besar dari To.")
        st.stop()

    st.sidebar.caption(f"Range aktif: {start_date} s/d {end_date}")

    # --- SIDEBAR COMPONENT: LIVE MARKET SYNC ---
    st.sidebar.markdown("---")
    st.sidebar.subheader("🔄 Live Market Sync")
    st.sidebar.caption("Tarik harga snapshot hari ini langsung dari Yahoo Finance API ke lokal dashboard.")
    
    if st.sidebar.button("⚡ Refresh Data Today", use_container_width=True):
        with st.sidebar.spinner("Fetching data dari yfinance..."):
            success, logs = fetch_and_sync_today_data(config)
            if success:
                st.sidebar.success("Data Today Berhasil Disinkronkan!")
                st.rerun()
            else:
                st.sidebar.error("Gagal sinkronisasi data.")
                for log in logs:
                    st.sidebar.caption(log)
    st.sidebar.markdown("---")

    # --- LIVE SIGNAL GENERATOR ENGINE ---
    current_driver_ret, live_signal, live_reason = compute_realtime_driver_signal(config)
    
    if live_signal == "BUY":
        st.success(f"🚀 **LIVE DRIVER SIGNAL: BUY** | {live_reason}")
    elif live_signal == "SHORT/SELL":
        st.error(f"⚠️ **LIVE DRIVER SIGNAL: BEARISH ALERT** | {live_reason}")
    else:
        st.info(f"💤 **LIVE DRIVER SIGNAL: STANDBY** | {live_reason}")
        
    st.markdown("---")

    # --- DATA LOADING & INJECTION ---
    driver_prices = load_driver_prices()
    stock_prices = load_stock_prices(tuple(config["tickers"]), start_date, end_date)

    if current_driver_ret is not None:
        try:
            live_date_detected = live_reason.split("per ")[-1].replace(".", "").strip()
        except:
            live_date_detected = "2026-07-06"
            
        mock_row = pd.DataFrame([{
            "date": live_date_detected,
            "driver_date": live_date_detected,
            "trade_date": live_date_detected,
            "driver_latest_date": f"{live_date_detected} 00:00:00",
            "driver_symbol": config["driver_symbol"],
            "ticker": config["driver_symbol"],
            "close": 4174.70,
            "driver_return_pct": current_driver_ret,
            "threshold_pct": config["threshold_pct"],
            "signal_status": live_signal,
            "status": "WAIT_ENTRY" if live_signal == "STANDBY" else live_signal
        }])
        
        driver_prices = pd.concat([driver_prices, mock_row], ignore_index=True)

    # --- RENDERING UI COMPONENT ---
    show_signal_status(config, driver_prices)
    show_watchlist_confidence_signal(config, current_driver_ret, selected_ticker)
        
    show_valid_signal_history(driver_prices, config)
    show_rule_card(config)
    show_driver_today(config, driver_prices)
    show_watchlist(config)
    plot_driver_chart(config, driver_prices, start_date, end_date)
    plot_stock_chart(stock_prices, selected_ticker)

    summary = show_backtest_summary(config, selected_ticker)
    show_yearly_and_trades(config, selected_ticker, summary)
    
render_driver_page(page)
