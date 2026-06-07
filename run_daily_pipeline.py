import subprocess
import sys
import sqlite3
from pathlib import Path


SCRIPTS = [
    "update_data.py",
    "update_gold_watchlist_latest.py",
    "update_drivers.py",
    "backtest_gold.py",
    "notify_gold_signal.py",
]


def check_database(label):
    db_path = Path("data/market.db")

    print()
    print("=" * 60)
    print(f"DATABASE CHECK: {label}")
    print("=" * 60)

    if not db_path.exists():
        print("ERROR: data/market.db tidak ditemukan.")
        return False

    print(f"DB path: {db_path}")
    print(f"DB size: {db_path.stat().st_size} bytes")

    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    cur.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    )

    tables = [row[0] for row in cur.fetchall()]

    print("Tables:")
    for table in tables:
        print(f"- {table}")

    if "daily_prices" not in tables:
        print("ERROR: table daily_prices tidak ada.")
        conn.close()
        return False

    cur.execute("SELECT COUNT(*) FROM daily_prices")
    print("daily_prices rows:", cur.fetchone()[0])

    if "latest_snapshot" in tables:
        cur.execute("SELECT COUNT(*) FROM latest_snapshot")
        print("latest_snapshot rows:", cur.fetchone()[0])
    else:
        print("WARNING: latest_snapshot tidak ada.")

    conn.close()
    return True


def run_script(script_name):
    path = Path(script_name)

    if not path.exists():
        print(f"SKIP: {script_name} tidak ditemukan.")
        return True

    print()
    print("=" * 60)
    print(f"RUNNING: {script_name}")
    print("=" * 60)

    result = subprocess.run(
        [sys.executable, script_name],
        capture_output=False,
        text=True
    )

    if result.returncode != 0:
        print()
        print(f"ERROR: {script_name} gagal.")
        print(f"Return code: {result.returncode}")
        return False

    print(f"DONE: {script_name}")
    return True


def main():
    failed_scripts = []

    check_database("BEFORE PIPELINE")

    for script in SCRIPTS:
        success = run_script(script)

        if script == "update_data.py":
            db_ok = check_database("AFTER update_data.py")

            if not db_ok:
                failed_scripts.append("database_check_after_update_data")
                break

        if not success:
            failed_scripts.append(script)

    print()
    print("=" * 60)
    print("PIPELINE SUMMARY")
    print("=" * 60)

    if failed_scripts:
        print("FAILED:")
        for script in failed_scripts:
            print(f"- {script}")

        sys.exit(1)

    print("All pipeline steps completed successfully.")


if __name__ == "__main__":
    main()