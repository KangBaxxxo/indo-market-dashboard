import argparse
import html
import json
import os
from pathlib import Path

import pandas as pd
import requests


LATEST_SIGNALS_PATH = Path("data/processed/latest_driver_signals.csv")
HRTA_CONF_PATH = Path("data/processed/gold_hrta_confidence_signal.csv")
STATE_PATH = Path("data/driver_signal_notify_state.json")

TARGET_DRIVERS = ["GOLD", "COAL", "NICKEL"]

WATCHLISTS = {
    "GOLD": ["HRTA.JK", "ANTM.JK", "MDKA.JK", "BRMS.JK", "EMAS.JK"],
    "COAL": ["ADRO.JK", "PTBA.JK", "BYAN.JK", "ITMG.JK", "HRUM.JK", "BUMI.JK"],
    "NICKEL": ["ANTM.JK", "INCO.JK", "NCKL.JK", "MBMA.JK"],
}

DRIVER_LABELS = {
    "GOLD": "Gold Driver",
    "COAL": "Coal Driver",
    "NICKEL": "Nickel Driver",
}

ACTIONABLE_STATUSES = {
    "ACTIVE_ACTIONABLE",
}

COOLDOWN_STATUSES = {
    "ACTIVE_BUT_COOLDOWN",
    "COOLDOWN_PERIOD",
}


def is_blank(value):
    if value is None:
        return True
    try:
        return pd.isna(value)
    except Exception:
        return False


def safe_str(value, default="N/A"):
    if is_blank(value):
        return default
    return str(value)


def safe_html(value, default="N/A"):
    return html.escape(safe_str(value, default=default))


def fmt_pct(value):
    if is_blank(value):
        return "N/A"
    try:
        return f"{float(value):+.2f}%"
    except Exception:
        return safe_html(value)


def fmt_num(value, decimals=2):
    if is_blank(value):
        return "N/A"
    try:
        return f"{float(value):,.{decimals}f}"
    except Exception:
        return safe_html(value)


def fmt_price(value):
    if is_blank(value):
        return "N/A"
    try:
        return f"{float(value):,.0f}"
    except Exception:
        return safe_html(value)


def fmt_date(value):
    if is_blank(value):
        return "N/A"

    try:
        dt = pd.to_datetime(value, errors="coerce")
        if pd.isna(dt):
            return safe_html(value)
        return dt.strftime("%Y-%m-%d")
    except Exception:
        return safe_html(value)


def truthy(value):
    if is_blank(value):
        return False

    if isinstance(value, bool):
        return value

    text = str(value).strip().lower()
    return text in {"true", "1", "yes", "y"}


def load_state():
    if not STATE_PATH.exists():
        return {}

    try:
        with STATE_PATH.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_state(state):
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with STATE_PATH.open("w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, sort_keys=True)


def send_telegram(message):
    bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")

    if not bot_token:
        raise ValueError("TELEGRAM_BOT_TOKEN belum diset.")

    if not chat_id:
        raise ValueError("TELEGRAM_CHAT_ID belum diset.")

    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"

    response = requests.post(
        url,
        json={
            "chat_id": chat_id,
            "text": message,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        },
        timeout=30,
    )

    print("Telegram response:", response.status_code, response.text)
    response.raise_for_status()


def get_trigger_date(row):
    for col in [
        "model_trigger_date",
        "last_signal_date",
        "driver_latest_date",
    ]:
        if col in row.index and not is_blank(row.get(col)):
            return fmt_date(row.get(col))

    return "N/A"


def build_notify_key(row):
    driver_group = safe_str(row.get("driver_group"), "UNKNOWN").upper()
    target_ticker = safe_str(row.get("target_ticker"), "UNKNOWN")
    signal_status = safe_str(row.get("signal_status"), "UNKNOWN").upper()
    trigger_date = get_trigger_date(row)

    return f"{driver_group}|{target_ticker}|{signal_status}|{trigger_date}"


def is_new_today(row):
    trigger_date = get_trigger_date(row)
    driver_latest_date = fmt_date(row.get("driver_latest_date"))

    return trigger_date != "N/A" and trigger_date == driver_latest_date


def build_hrta_confidence_block():
    if not HRTA_CONF_PATH.exists():
        return ""

    try:
        df = pd.read_csv(HRTA_CONF_PATH)

        if df.empty:
            return ""

        row = df.iloc[-1]

        return f"""

<b>HRTA Gold Confidence</b>
Status: {safe_html(row.get("signal_status"))}
Confidence: {safe_html(row.get("confidence_level"))}
Action: {safe_html(row.get("recommended_action"))}
Size: {safe_html(row.get("position_size_hint"))}

Entry HRTA ret20D: {fmt_pct(row.get("entry_hrta_ret20_pct"))}
Entry RSI: {fmt_num(row.get("entry_rsi"))}
Entry dist MA20: {fmt_pct(row.get("entry_dist_ma20_pct"))}

Reason:
{safe_html(row.get("reason"))}
""".rstrip()

    except Exception as e:
        return f"""

<b>HRTA Gold Confidence</b>
Gagal baca data: {html.escape(str(e))}
""".rstrip()


def build_driver_message(row):
    driver_group = safe_str(row.get("driver_group"), "UNKNOWN").upper()
    driver_symbol = safe_str(row.get("driver_symbol"), driver_group)
    target_ticker = safe_str(row.get("target_ticker"), "N/A")
    status = safe_str(row.get("signal_status"), "UNKNOWN").upper()

    label = DRIVER_LABELS.get(driver_group, f"{driver_group} Driver")
    watchlist = WATCHLISTS.get(driver_group, [])

    icon = "🚨"
    if driver_group == "GOLD":
        icon = "🥇"
    elif driver_group == "COAL":
        icon = "⛏️"
    elif driver_group == "NICKEL":
        icon = "🔩"

    message = f"""
{icon} <b>{html.escape(label)} SIGNAL</b>

<b>Driver</b>: {safe_html(driver_symbol)}
<b>Driver Date</b>: {fmt_date(row.get("driver_latest_date"))}
<b>Driver Return</b>: {fmt_pct(row.get("driver_return_pct"))}
<b>Threshold</b>: {fmt_pct(row.get("threshold_pct"))}
<b>Status</b>: {safe_html(status)}

<b>Target</b>: {safe_html(target_ticker)}
<b>Stock Date</b>: {fmt_date(row.get("stock_latest_date"))}
<b>Stock Close</b>: {fmt_price(row.get("stock_latest_close"))}

<b>Trigger Date</b>: {get_trigger_date(row)}
<b>Cooldown Remaining</b>: {safe_html(row.get("cooldown_remaining_days"))}

<b>Watchlist</b>:
{html.escape(", ".join(watchlist)) if watchlist else "N/A"}

<b>Notes</b>:
{safe_html(row.get("notes"))}
""".strip()

    if driver_group == "GOLD":
        hrta_block = build_hrta_confidence_block()
        if hrta_block:
            message = f"{message}\n{hrta_block}"

    return message


def load_latest_signals():
    if not LATEST_SIGNALS_PATH.exists():
        raise FileNotFoundError(f"{LATEST_SIGNALS_PATH} tidak ditemukan.")

    df = pd.read_csv(LATEST_SIGNALS_PATH)

    if df.empty:
        raise ValueError(f"{LATEST_SIGNALS_PATH} kosong.")

    if "driver_group" not in df.columns:
        raise ValueError("Kolom driver_group tidak ada di latest_driver_signals.csv.")

    df["driver_group"] = df["driver_group"].astype(str).str.upper()

    return df


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="Print message tanpa kirim Telegram.")
    parser.add_argument("--force", action="store_true", help="Kirim walaupun sudah pernah notify / bukan signal hari ini.")
    parser.add_argument("--include-cooldown", action="store_true", help="Ikut notify status cooldown.")
    parser.add_argument("--send-test", action="store_true", help="Kirim test message Telegram.")
    args = parser.parse_args()

    if args.send_test:
        message = """
🧪 <b>TEST TELEGRAM</b>

notify_driver_signals.py connected.

Gold: ready
Coal: ready
Nickel: ready
""".strip()

        if args.dry_run:
            print(message)
            return

        send_telegram(message)
        print("Test Telegram sent.")
        return

    df = load_latest_signals()
    state = load_state()

    notify_statuses = set(ACTIONABLE_STATUSES)
    if args.include_cooldown:
        notify_statuses |= COOLDOWN_STATUSES

    candidates = []

    for driver_group in TARGET_DRIVERS:
        driver_df = df[df["driver_group"] == driver_group].copy()

        if driver_df.empty:
            print(f"{driver_group}: no row in latest_driver_signals.csv")
            continue

        # Kalau ada beberapa row per driver, ambil semua yang status-nya relevan.
        for _, row in driver_df.iterrows():
            signal_status = safe_str(row.get("signal_status"), "UNKNOWN").upper()
            threshold_hit = truthy(row.get("threshold_hit", True))

            if not threshold_hit and not args.force:
                print(f"{driver_group}: skip, threshold_hit is false")
                continue

            if signal_status not in notify_statuses and not args.force:
                print(f"{driver_group}: skip, signal_status={signal_status}")
                continue

            if not is_new_today(row) and not args.force:
                print(
                    f"{driver_group}: skip, trigger date {get_trigger_date(row)} "
                    f"bukan driver latest date {fmt_date(row.get('driver_latest_date'))}"
                )
                continue

            notify_key = build_notify_key(row)

            if state.get(notify_key) and not args.force:
                print(f"{driver_group}: skip, already notified: {notify_key}")
                continue

            candidates.append((notify_key, row))

    if not candidates:
        print("No driver signal notification to send.")
        return

    messages = []
    notified_keys = []

    for notify_key, row in candidates:
        messages.append(build_driver_message(row))
        notified_keys.append(notify_key)

    final_message = "\n\n━━━━━━━━━━━━━━\n\n".join(messages)

    print("=== TELEGRAM MESSAGE PREVIEW ===")
    print(final_message)

    if args.dry_run:
        print("Dry run only. Telegram not sent.")
        return

    send_telegram(final_message)

    for notify_key in notified_keys:
        state[notify_key] = {
            "notified_at_driver_date": fmt_date(candidates[0][1].get("driver_latest_date")),
            "key": notify_key,
        }

    save_state(state)

    print("Driver signal notification sent.")
    print("Updated state:", STATE_PATH)


if __name__ == "__main__":
    main()
