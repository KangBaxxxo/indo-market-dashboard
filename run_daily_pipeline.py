import subprocess
import sys
from pathlib import Path


SCRIPTS = [
    "update_data.py",
    "update_drivers.py",
    "backtest_gold.py",
    "notify_gold_signal.py",
]


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

    for script in SCRIPTS:
        success = run_script(script)

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