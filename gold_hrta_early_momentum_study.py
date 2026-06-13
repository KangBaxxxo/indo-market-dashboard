from pathlib import Path
import sqlite3
import pandas as pd
import numpy as np


# =====================================================
# CONFIG
# =====================================================
DB_PATH = Path("data/market.db")
DRIVER_PATH = Path("data/driver_prices.csv")

OUTPUT_DIR = Path("data/output")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

OUTPUT_PATH = OUTPUT_DIR / "gold_hrta_early_momentum_results.csv"
TRADE_PATH = OUTPUT_DIR / "gold_hrta_early_momentum_trades.csv"

START_DATE = "2012-01-01"

TICKER = "HRTA.JK"
DRIVER = "GOLD"

# Old rule reference
OLD_GOLD_LOOKBACK = 10
OLD_GOLD_THRESHOLD = 5
OLD_HOLD = 10
OLD_COOLDOWN = 20

# Early momentum grid
HRTA_RET20_THRESHOLDS = [10, 15, 20, 25, 30]
GOLD_RET10_MIN_LIST = [0, 2, 5, 8]
GOLD_RET20_MIN_LIST = [-999, 0, 5, 10]
HOLDS = [5, 10, 20]
COOLDOWNS = [10, 20, 30]

MIN_TRADES = 10


# =====================================================
# LOAD DATA
# =====================================================
def safe_dt(s):
    return pd.to_datetime(s, format="mixed", errors="coerce")


def safe_num(s):
    return pd.to_numeric(s, errors="coerce")


def load_gold():
    df = pd.read_csv(DRIVER_PATH)
    df.columns = df.columns.str.strip().str.lower()

    df["driver"] = df["driver"].astype(str).str.upper().str.strip()
    df["driver_date"] = safe_dt(df["driver_date"])
    df["value"] = safe_num(df["value"])

    df = df[df["driver"] == DRIVER].copy()
    df = df.dropna(subset=["driver_date", "value"])
    df = df.sort_values("driver_date").reset_index(drop=True)

    df = df[df["driver_date"] >= pd.to_datetime(START_DATE)].copy()
    df = df.reset_index(drop=True)

    for n in [5, 10, 20, 30, 60]:
        df[f"gold_ret_{n}d"] = df["value"].pct_change(n) * 100

    return df


def load_hrta():
    query = """
        SELECT trade_date, ticker, close_price, volume, ma20, ma50, rsi
        FROM daily_prices
        WHERE ticker = ?
        ORDER BY DATE(trade_date)
    """

    with sqlite3.connect(DB_PATH) as con:
        df = pd.read_sql(query, con, params=(TICKER,))

    df["trade_date"] = safe_dt(df["trade_date"])
    df["close_price"] = safe_num(df["close_price"])
    df["volume"] = safe_num(df["volume"])
    df["ma20"] = safe_num(df["ma20"])
    df["ma50"] = safe_num(df["ma50"])
    df["rsi"] = safe_num(df["rsi"])

    df = df.dropna(subset=["trade_date", "close_price"])
    df = df.sort_values("trade_date").reset_index(drop=True)

    df = df[df["trade_date"] >= pd.to_datetime(START_DATE)].copy()
    df = df.reset_index(drop=True)

    for n in [5, 10, 20, 30, 60]:
        df[f"hrta_ret_{n}d"] = df["close_price"].pct_change(n) * 100

    df["dist_ma20_pct"] = (df["close_price"] / df["ma20"] - 1) * 100
    df["dist_ma50_pct"] = (df["close_price"] / df["ma50"] - 1) * 100

    return df


def build_base(hrta, gold):
    gold_cols = [
        "driver_date",
        "value",
        "gold_ret_5d",
        "gold_ret_10d",
        "gold_ret_20d",
        "gold_ret_30d",
        "gold_ret_60d",
    ]

    g = gold[gold_cols].copy()
    g = g.rename(columns={"value": "gold_close"})

    base = pd.merge_asof(
        hrta.sort_values("trade_date"),
        g.sort_values("driver_date"),
        left_on="trade_date",
        right_on="driver_date",
        direction="backward",
    )

    return base.sort_values("trade_date").reset_index(drop=True)


# =====================================================
# BACKTEST HELPERS
# =====================================================
def apply_cooldown_by_index(signal_df, date_col, cooldown_days):
    filtered_dates = []
    cooldown_until_idx = -1

    signal_df = signal_df.sort_values(date_col).copy()

    for idx, row in signal_df.iterrows():
        if idx <= cooldown_until_idx:
            continue

        filtered_dates.append(row[date_col])
        cooldown_until_idx = idx + cooldown_days

    return filtered_dates


def get_entry_exit(signal_date, stock_dates, hold_days):
    signal_date = pd.to_datetime(signal_date).normalize()

    future = stock_dates[stock_dates > signal_date]

    if len(future) == 0:
        return pd.NaT, pd.NaT

    entry_date = future.iloc[0]
    valid_exit = stock_dates[stock_dates >= entry_date]

    if len(valid_exit) < hold_days:
        return entry_date, pd.NaT

    exit_date = valid_exit.iloc[hold_days - 1]

    return entry_date, exit_date


def backtest_signal_dates(base, signal_dates, hold_days, rule_name, meta):
    stock_dates = base["trade_date"].dt.normalize().drop_duplicates().reset_index(drop=True)

    price_map = (
        base.drop_duplicates("trade_date", keep="last")
        .set_index(base["trade_date"].dt.normalize())["close_price"]
        .to_dict()
    )

    feature_map = (
        base.drop_duplicates("trade_date", keep="last")
        .set_index(base["trade_date"].dt.normalize())
        .to_dict("index")
    )

    rows = []

    for signal_date in signal_dates:
        entry_date, exit_date = get_entry_exit(signal_date, stock_dates, hold_days)

        if pd.isna(entry_date) or pd.isna(exit_date):
            continue

        entry_price = price_map.get(entry_date)
        exit_price = price_map.get(exit_date)

        if entry_price is None or exit_price is None or entry_price <= 0:
            continue

        ret = exit_price / entry_price - 1

        entry_feat = feature_map.get(entry_date, {})

        rows.append({
            "ticker": TICKER,
            "rule_name": rule_name,
            "signal_date": signal_date,
            "entry_date": entry_date,
            "exit_date": exit_date,
            "entry_price": entry_price,
            "exit_price": exit_price,
            "return_pct": ret * 100,
            "return_decimal": ret,

            "entry_hrta_ret_5d": entry_feat.get("hrta_ret_5d"),
            "entry_hrta_ret_10d": entry_feat.get("hrta_ret_10d"),
            "entry_hrta_ret_20d": entry_feat.get("hrta_ret_20d"),
            "entry_rsi": entry_feat.get("rsi"),
            "entry_dist_ma20_pct": entry_feat.get("dist_ma20_pct"),
            "entry_gold_ret_10d": entry_feat.get("gold_ret_10d"),
            "entry_gold_ret_20d": entry_feat.get("gold_ret_20d"),

            **meta,
        })

    return pd.DataFrame(rows)


def calc_profit_factor(returns):
    wins = returns[returns > 0].sum()
    losses = returns[returns <= 0].sum()

    if losses == 0:
        return 999.0 if wins > 0 else np.nan

    return wins / abs(losses)


def summarize(trades):
    rows = []

    group_cols = [
        "rule_name",
        "hrta_ret20_trigger",
        "gold_ret10_min",
        "gold_ret20_min",
        "hold_days",
        "cooldown_days",
    ]

    for keys, g in trades.groupby(group_cols):
        returns = g["return_decimal"].dropna()
        total = len(returns)

        if total == 0:
            continue

        wins = int((returns > 0).sum())
        losses = int((returns <= 0).sum())

        win_rate = wins / total * 100
        avg = returns.mean() * 100
        med = returns.median() * 100
        best = returns.max() * 100
        worst = returns.min() * 100
        simple_total = g["return_pct"].sum()
        compound = ((1 + returns).prod() - 1) * 100
        pf = calc_profit_factor(returns)

        rule_name, hrta_thr, gold10, gold20, hold, cooldown = keys

        score = (
            0.30 * (win_rate / 100)
            + 0.25 * (med / 100)
            + 0.20 * (avg / 100)
            + 0.15 * min(pf, 10) / 10
            + 0.10 * min(total, 50) / 50
        )

        if worst <= -20:
            score -= 0.08
        elif worst <= -15:
            score -= 0.04

        if total < MIN_TRADES:
            score -= 0.15

        rows.append({
            "rule_name": rule_name,
            "hrta_ret20_trigger": hrta_thr,
            "gold_ret10_min": gold10,
            "gold_ret20_min": gold20,
            "hold_days": hold,
            "cooldown_days": cooldown,

            "total_trades": total,
            "wins": wins,
            "losses": losses,
            "win_rate": round(win_rate, 2),
            "avg_return_pct": round(avg, 2),
            "median_return_pct": round(med, 2),
            "best_return_pct": round(best, 2),
            "worst_return_pct": round(worst, 2),
            "simple_total_pct": round(simple_total, 2),
            "compound_return_pct": round(compound, 2),
            "profit_factor": round(pf, 4),
            "score": round(score, 6),
        })

    return pd.DataFrame(rows)


# =====================================================
# SIGNAL BUILDERS
# =====================================================
def build_old_gold_signals(gold):
    g = gold.copy()
    signal_df = g[g[f"gold_ret_{OLD_GOLD_LOOKBACK}d"] >= OLD_GOLD_THRESHOLD].copy()
    return apply_cooldown_by_index(signal_df, "driver_date", OLD_COOLDOWN)


def build_early_momentum_signals(base, hrta_ret20_trigger, gold_ret10_min, gold_ret20_min):
    b = base.copy()

    b["prev_hrta_ret20"] = b["hrta_ret_20d"].shift(1)

    cross_up = (
        (b["hrta_ret_20d"] >= hrta_ret20_trigger)
        & (b["prev_hrta_ret20"] < hrta_ret20_trigger)
    )

    gold_filter = (
        (b["gold_ret_10d"] >= gold_ret10_min)
        & (b["gold_ret_20d"] >= gold_ret20_min)
    )

    signal_df = b[cross_up & gold_filter].copy()

    return signal_df["trade_date"].tolist()


def print_old_signal_diagnostic(base, old_signals):
    print("\n=== OLD GOLD SIGNAL DIAGNOSTIC 2026 ===")

    b = base.copy()
    b["date_norm"] = b["trade_date"].dt.normalize()

    rows = []

    for signal_date in old_signals:
        if signal_date < pd.to_datetime("2026-01-01") or signal_date > pd.to_datetime("2026-04-30"):
            continue

        signal_date = pd.to_datetime(signal_date).normalize()

        asof = b[b["date_norm"] <= signal_date].tail(1)

        stock_dates = b["date_norm"].drop_duplicates().reset_index(drop=True)
        entry_date, exit_date = get_entry_exit(signal_date, stock_dates, OLD_HOLD)

        entry = b[b["date_norm"] == entry_date].tail(1)

        if asof.empty or entry.empty:
            continue

        a = asof.iloc[0]
        e = entry.iloc[0]

        rows.append({
            "signal_date": signal_date.date(),
            "entry_date": entry_date.date(),
            "gold_ret_10d_signal": a["gold_ret_10d"],
            "gold_ret_20d_signal": a["gold_ret_20d"],
            "hrta_ret_20d_signal": a["hrta_ret_20d"],
            "hrta_ret_20d_entry": e["hrta_ret_20d"],
            "hrta_ret_10d_entry": e["hrta_ret_10d"],
            "rsi_entry": e["rsi"],
            "dist_ma20_entry": e["dist_ma20_pct"],
        })

    if rows:
        print(pd.DataFrame(rows).round(2).to_string(index=False))
    else:
        print("NO OLD SIGNALS 2026")


# =====================================================
# MAIN
# =====================================================
def main():
    print("LOAD GOLD")
    gold = load_gold()

    print("LOAD HRTA")
    hrta = load_hrta()

    print("BUILD BASE")
    base = build_base(hrta, gold)

    old_signals = build_old_gold_signals(gold)
    print_old_signal_diagnostic(base, old_signals)

    all_trades = []

    # Reference old rule
    old_trades = backtest_signal_dates(
        base=base,
        signal_dates=old_signals,
        hold_days=OLD_HOLD,
        rule_name="OLD_GOLD_10D_5_NEXTDAY_HOLD10_CD20",
        meta={
            "hrta_ret20_trigger": np.nan,
            "gold_ret10_min": OLD_GOLD_THRESHOLD,
            "gold_ret20_min": np.nan,
            "hold_days": OLD_HOLD,
            "cooldown_days": OLD_COOLDOWN,
        },
    )

    if not old_trades.empty:
        all_trades.append(old_trades)

    # Early HRTA momentum + gold confirmation grid
    for hrta_thr in HRTA_RET20_THRESHOLDS:
        for gold10 in GOLD_RET10_MIN_LIST:
            for gold20 in GOLD_RET20_MIN_LIST:
                raw_signals = build_early_momentum_signals(
                    base=base,
                    hrta_ret20_trigger=hrta_thr,
                    gold_ret10_min=gold10,
                    gold_ret20_min=gold20,
                )

                for cooldown in COOLDOWNS:
                    raw_signal_df = base[base["trade_date"].isin(raw_signals)].copy()
                    signal_dates = apply_cooldown_by_index(raw_signal_df, "trade_date", cooldown)

                    for hold in HOLDS:
                        rule_name = (
                            f"HRTA_RET20_CROSS_{hrta_thr}_"
                            f"GOLD10_MIN_{gold10}_"
                            f"GOLD20_MIN_{gold20}_"
                            f"HOLD_{hold}_CD_{cooldown}"
                        )

                        trades = backtest_signal_dates(
                            base=base,
                            signal_dates=signal_dates,
                            hold_days=hold,
                            rule_name=rule_name,
                            meta={
                                "hrta_ret20_trigger": hrta_thr,
                                "gold_ret10_min": gold10,
                                "gold_ret20_min": gold20,
                                "hold_days": hold,
                                "cooldown_days": cooldown,
                            },
                        )

                        if not trades.empty:
                            all_trades.append(trades)

    trade_df = pd.concat(all_trades, ignore_index=True)

    for c in ["signal_date", "entry_date", "exit_date"]:
        trade_df[c] = pd.to_datetime(trade_df[c]).dt.strftime("%Y-%m-%d")

    summary = summarize(trade_df)
    summary = summary.sort_values("score", ascending=False).reset_index(drop=True)

    trade_df.to_csv(TRADE_PATH, index=False)
    summary.to_csv(OUTPUT_PATH, index=False)

    print(f"\nSUCCESS CREATE {OUTPUT_PATH}")
    print(f"SUCCESS CREATE {TRADE_PATH}")

    show_cols = [
        "rule_name",
        "hrta_ret20_trigger",
        "gold_ret10_min",
        "gold_ret20_min",
        "hold_days",
        "cooldown_days",
        "total_trades",
        "win_rate",
        "avg_return_pct",
        "median_return_pct",
        "worst_return_pct",
        "simple_total_pct",
        "compound_return_pct",
        "profit_factor",
        "score",
    ]

    print("\n=== TOP 30 EARLY MOMENTUM RULES ===")
    top = summary[summary["rule_name"] != "OLD_GOLD_10D_5_NEXTDAY_HOLD10_CD20"].head(30)
    print(top[show_cols].to_string(index=False))

    print("\n=== OLD RULE SUMMARY ===")
    old = summary[summary["rule_name"] == "OLD_GOLD_10D_5_NEXTDAY_HOLD10_CD20"]
    print(old[show_cols].to_string(index=False))

    print("\n=== TOP RULE 2026 TRADES ===")
    if not top.empty:
        top_rule = top.iloc[0]["rule_name"]
        t = trade_df[trade_df["rule_name"] == top_rule].copy()
        t2026 = t[t["entry_date"].astype(str).str.startswith("2026")].copy()

        print("TOP RULE:", top_rule)
        print(t2026[[
            "signal_date",
            "entry_date",
            "exit_date",
            "entry_price",
            "exit_price",
            "return_pct",
            "entry_hrta_ret_20d",
            "entry_gold_ret_10d",
            "entry_gold_ret_20d",
        ]].round(2).to_string(index=False))


if __name__ == "__main__":
    main()
