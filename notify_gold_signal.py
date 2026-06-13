import os
import json
import urllib.parse
import urllib.request
import html
from pathlib import Path

import pandas as pd

# ======================
# CONFIG
# ======================

DRIVER = "GOLD"
LOOKBACK = 10
THRESHOLD = 5.0
COOLDOWN_DAYS = 20

DRIVER_CSV = "data/driver_prices.csv"
STATE_FILE = "data/gold_signal_state.json"

TARGET_TICKER = "HRTA.JK"
WATCHLIST = ["HRTA.JK", "MDKA.JK", "BRMS.JK", "ANTM.JK", "EMAS.JK"]


# ======================
# TELEGRAM
# ======================

def send_telegram(message):
    bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")

    if not bot_token:
        raise ValueError("TELEGRAM_BOT_TOKEN belum diset.")

    if not chat_id:
        raise ValueError("TELEGRAM_CHAT_ID belum diset.")

    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"

    payload = urllib.parse.urlencode({
        "chat_id": chat_id,
        "text": message,
        "parse_mode": "HTML",
    }).encode("utf-8")

    request = urllib.request.Request(
        url,
        data=payload,
        method="POST"
    )

    with urllib.request.urlopen(request) as response:
        return response.read().decode("utf-8")

def build_hrta_confidence_block():
    path = "data/processed/gold_hrta_confidence_signal.csv"

    if not os.path.exists(path):
        return "\n\n<b>HRTA Gold Confidence</b>:\nData belum tersedia."

    try:
        df = pd.read_csv(path)

        if df.empty:
            return "\n\n<b>HRTA Gold Confidence</b>:\nData kosong."

        row = df.iloc[-1]

        signal_status = row.get("signal_status", "N/A")
        confidence = row.get("confidence_level", "N/A")
        action = row.get("recommended_action", "N/A")
        size = row.get("position_size_hint", "N/A")
        reason = html.escape(str(row.get("reason", "N/A")))

        entry_rsi = row.get("entry_rsi", None)
        entry_dist_ma20 = row.get("entry_dist_ma20_pct", None)
        entry_ret20 = row.get("entry_hrta_ret20_pct", None)

        def fmt_pct(value):
            if pd.isna(value):
                return "N/A"
            return f"{float(value):.2f}%"

        def fmt_num(value):
            if pd.isna(value):
                return "N/A"
            return f"{float(value):.2f}"

        return f"""

<b>HRTA Gold Confidence</b>
Status: {signal_status}
Confidence: {confidence}
Action: {action}
Size: {size}

Entry HRTA ret20D: {fmt_pct(entry_ret20)}
Entry RSI: {fmt_num(entry_rsi)}
Entry dist MA20: {fmt_pct(entry_dist_ma20)}

Reason:
{reason}
""".rstrip()

    except Exception as e:
        return f"\n\n<b>HRTA Gold Confidence</b>:\nGagal baca data: {html.escape(str(e))}"
    
# ======================
# STATE
# ======================

def load_state():
    path = Path(STATE_FILE)

    if not path.exists():
        return {}

    try:
        return json.loads(path.read_text())
    except Exception:
        return {}


def save_state(state):
    path = Path(STATE_FILE)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2))


# ======================
# MAIN
# ======================

def main():
    if not Path(DRIVER_CSV).exists():
        raise FileNotFoundError(f"File tidak ditemukan: {DRIVER_CSV}")

    df = pd.read_csv(DRIVER_CSV)

    df.columns = df.columns.str.strip().str.lower()

    df["driver_date"] = pd.to_datetime(
        df["driver_date"],
        format="mixed",
        errors="coerce"
    )

    df["value"] = pd.to_numeric(
        df["value"],
        errors="coerce"
    )

    gold = df[df["driver"].str.upper() == DRIVER].copy()

    gold = gold.dropna(
        subset=["driver_date", "value"]
    ).copy()

    gold = gold.sort_values(
        "driver_date"
    ).reset_index(drop=True)

    gold["gold_10d_change_pct"] = (
        gold["value"].pct_change(LOOKBACK) * 100
    )

    latest = gold.dropna(
        subset=["gold_10d_change_pct"]
    ).tail(1)

    if latest.empty:
        print("Data GOLD belum cukup.")
        return

    latest_row = latest.iloc[0]

    latest_date = latest_row["driver_date"]
    latest_value = latest_row["value"]
    latest_change = latest_row["gold_10d_change_pct"]

    # ======================
    # BUILD VALID EVENTS WITH COOLDOWN
    # ======================

    events = gold[
        gold["gold_10d_change_pct"] >= THRESHOLD
    ].copy()

    events = events.rename(
        columns={"driver_date": "event_date"}
    )

    events = events.sort_values(
        "event_date"
    ).reset_index(drop=True)

    events["prev_event_date"] = events["event_date"].shift(1)

    events["days_since_prev"] = (
        events["event_date"]
        - events["prev_event_date"]
    ).dt.days

    events = events[
        events["days_since_prev"].isna()
        | (events["days_since_prev"] > COOLDOWN_DAYS)
    ].copy()

    if events.empty:
        print("Belum ada valid GOLD signal.")
        return

    last_event = events.tail(1).iloc[0]

    last_event_date = last_event["event_date"]
    last_event_change = last_event["gold_10d_change_pct"]

    state = load_state()
    last_notified_event_date = state.get("last_notified_event_date")

    last_event_date_str = last_event_date.strftime("%Y-%m-%d")
    latest_date_str = latest_date.strftime("%Y-%m-%d")

    # hanya notif kalau event valid terakhir adalah data terbaru
    is_new_signal_today = last_event_date_str == latest_date_str

    already_notified = (
        last_notified_event_date == last_event_date_str
    )

    print("Latest GOLD date:", latest_date_str)
    print("Latest GOLD value:", round(latest_value, 2))
    print("Latest GOLD 10D change:", round(latest_change, 2))
    print("Last valid event:", last_event_date_str)
    print("Already notified:", already_notified)

    if not is_new_signal_today:
        print("Tidak ada signal baru hari ini.")
        return

    if already_notified:
        print("Signal sudah pernah dikirim. Skip.")
        return

    hrta_block = build_hrta_confidence_block()

    message = f"""
🚨 <b>GOLD SIGNAL ACTIVE</b>

<b>Driver</b>: GOLD
<b>Date</b>: {last_event_date_str}
<b>GOLD Price</b>: {latest_value:,.2f}
<b>GOLD 10D Change</b>: +{last_event_change:.2f}%

<b>Rule</b>:
GOLD naik &gt;= +{THRESHOLD}% dalam {LOOKBACK} hari
Cooldown: {COOLDOWN_DAYS} hari
Hold: 10 trading days

<b>Primary Target</b>:
{TARGET_TICKER}

<b>Gold Watchlist</b>:
{", ".join(WATCHLIST)}
{hrta_block}
""".strip()

    send_telegram(message)

    state["last_notified_event_date"] = last_event_date_str
    state["last_gold_value"] = float(latest_value)
    state["last_gold_10d_change_pct"] = round(float(last_event_change), 2)

    save_state(state)

    print("Telegram notification sent.")


if __name__ == "__main__":
    main()