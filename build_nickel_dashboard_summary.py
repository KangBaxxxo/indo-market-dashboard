from pathlib import Path
import pandas as pd


# =====================================================
# CONFIG
# =====================================================
INPUT_PATH = Path("data/output/nickel_championship_results.csv")

OUTPUT_DIR = Path("data/processed")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

OUTPUT_PATH = OUTPUT_DIR / "nickel_backtest_summary.csv"


# =====================================================
# MAIN
# =====================================================
def main():
    if not INPUT_PATH.exists():
        raise FileNotFoundError(f"Input file tidak ketemu: {INPUT_PATH}")

    df = pd.read_csv(INPUT_PATH)

    required_cols = {
        "ticker",
        "signals",
        "win_rate",
        "avg_return",
        "median_return",
        "best_return",
        "worst_return",
        "score",
    }

    missing = required_cols - set(df.columns)
    if missing:
        raise ValueError(f"Kolom kurang di {INPUT_PATH}: {sorted(missing)}")

    out = pd.DataFrame()

    out["driver"] = "NICKEL"
    out["ticker"] = df["ticker"].astype(str).str.upper().str.strip()
    out["rule"] = "NICKEL >= +9% in 60D | Hold 60D | Cooldown 60D"

    out["driver_symbol"] = "NICKEL"
    out["lookback_days"] = 60
    out["threshold_pct"] = 9.0
    out["hold_days"] = 60
    out["cooldown_days"] = 60

    out["total_trades"] = df["signals"]

    # Convert decimal return to percent for dashboard display
    out["win_rate"] = df["win_rate"] * 100
    out["avg_trade_return_pct"] = df["avg_return"] * 100
    out["median_trade_return_pct"] = df["median_return"] * 100
    out["best_trade_pct"] = df["best_return"] * 100
    out["worst_trade_pct"] = df["worst_return"] * 100
    out["score"] = df["score"]

    # Optional columns supaya dashboard tetap compatible
    out["wins"] = None
    out["losses"] = None
    out["profit_factor"] = None
    out["compound_return_pct"] = None
    out["max_drawdown_pct"] = None

    # Safety-first sorting:
    # ticker dengan sample kecil jangan otomatis jadi champion.
    out["sample_flag"] = out["total_trades"].apply(
        lambda x: "LOW_SAMPLE" if x < 20 else "ROBUST"
    )

    out["ranking_score"] = out.apply(
        lambda r: -999 if r["sample_flag"] == "LOW_SAMPLE" else r["score"],
        axis=1,
    )

    out = out.sort_values(
        ["ranking_score", "win_rate", "median_trade_return_pct", "avg_trade_return_pct"],
        ascending=[False, False, False, False],
    )

    out = out.drop(columns=["ranking_score"])

    out.to_csv(OUTPUT_PATH, index=False)

    print(f"SUCCESS CREATE {OUTPUT_PATH}")
    print(out.to_string(index=False))


if __name__ == "__main__":
    main()
