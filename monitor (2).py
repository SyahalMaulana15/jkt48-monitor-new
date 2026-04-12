#!/usr/bin/env python3
"""
JKT48 Ticket Monitor — Railway.app Version
Berjalan terus-menerus, cek tiket setiap 30 detik.
Kirim notifikasi Telegram saat quota > 0.
"""

import requests
import json
import os
import time
from datetime import datetime, timezone, timedelta

# ─────────────────────────────────────────────
#  KONFIGURASI
# ─────────────────────────────────────────────

API_URL        = "https://jkt48.com/api/v1/exclusives/EX579E/bonus?lang=id"
EXCLUSIVE_CODE = "EX579E"
STATE_FILE     = "/tmp/state.json"  # Railway pakai /tmp untuk file sementara

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID   = os.environ.get("TELEGRAM_CHAT_ID", "")

# Interval pengecekan (detik)
CHECK_INTERVAL = 30

# Interval heartbeat (jam)
HEARTBEAT_EVERY_HOURS = 6

# Kosongkan [] untuk pantau SEMUA member
# Contoh: WATCH_MEMBERS = ["Shabilqis Naila", "Freya Jayawardana"]
WATCH_MEMBERS = []

# ─────────────────────────────────────────────
#  WAKTU WIB
# ─────────────────────────────────────────────

def now_wib() -> datetime:
    return datetime.now(timezone(timedelta(hours=7)))

def now_str() -> str:
    return now_wib().strftime("%Y-%m-%d %H:%M:%S WIB")

# ─────────────────────────────────────────────
#  TELEGRAM
# ─────────────────────────────────────────────

def send_telegram(message: str) -> bool:
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("❌ TELEGRAM_BOT_TOKEN atau TELEGRAM_CHAT_ID belum diset!")
        return False
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    try:
        r = requests.post(url, json=payload, timeout=10)
        r.raise_for_status()
        print("  ✅ Telegram terkirim")
        return True
    except requests.RequestException as e:
        print(f"  ❌ Gagal kirim Telegram: {e}")
        return False

# ─────────────────────────────────────────────
#  STATE
# ─────────────────────────────────────────────

def load_state() -> dict:
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r") as f:
                return json.load(f)
        except Exception:
            pass
    return {}

def save_state(state: dict):
    try:
        with open(STATE_FILE, "w") as f:
            json.dump(state, f, indent=2)
    except Exception as e:
        print(f"  ⚠ Gagal simpan state: {e}")

# ─────────────────────────────────────────────
#  HEARTBEAT
# ─────────────────────────────────────────────

def should_send_heartbeat(state: dict) -> bool:
    last_hb = state.get("last_heartbeat")
    if not last_hb:
        return True
    try:
        last_dt = datetime.fromisoformat(last_hb)
        elapsed = now_wib() - last_dt
        return elapsed.total_seconds() >= HEARTBEAT_EVERY_HOURS * 3600
    except Exception:
        return True

def send_heartbeat(state: dict, sessions: list, total_slots: int):
    now = now_wib()
    available = sum(
        1 for s in sessions
        for m in s.get("session_members", [])
        if m.get("quota", 0) > 0
    )
    run_count = state.get("run_count", 0)
    next_hb   = now + timedelta(hours=HEARTBEAT_EVERY_HOURS)
    status_line = "😴 Semua slot masih sold out" if available == 0 \
        else f"🎉 {available} slot tersedia!"

    msg = (
        f"💓 <b>Laporan Berkala — JKT48 Monitor</b>\n\n"
        f"✅ Sistem berjalan normal\n"
        f"🕐 Waktu: {now.strftime('%Y-%m-%d %H:%M WIB')}\n"
        f"⚡ Interval cek: setiap {CHECK_INTERVAL} detik\n\n"
        f"📊 <b>Status tiket:</b>\n"
        f"   • Total slot dipantau: {total_slots}\n"
        f"   • Sold out: {total_slots - available}\n"
        f"   • Tersedia: {available}\n\n"
        f"{status_line}\n\n"
        f"🔁 Laporan berikutnya: {next_hb.strftime('%H:%M WIB')}\n"
        f"📈 Total pengecekan: {run_count:,}x"
    )
    print("  💓 Mengirim heartbeat...")
    send_telegram(msg)
    state["last_heartbeat"] = now.isoformat()

# ─────────────────────────────────────────────
#  FETCH API
# ─────────────────────────────────────────────

def fetch_tickets() -> list | None:
    try:
        r = requests.get(API_URL, timeout=10,
                         headers={"User-Agent": "Mozilla/5.0"})
        r.raise_for_status()
        data = r.json()
        if data.get("status") and "data" in data:
            return data["data"]
        print(f"  ⚠ Respons tidak terduga: {data.get('message')}")
        return None
    except Exception as e:
        print(f"  ❌ Gagal fetch API: {e}")
        return None

# ─────────────────────────────────────────────
#  SATU SIKLUS CEK
# ─────────────────────────────────────────────

def check_once(state: dict) -> dict:
    state["run_count"] = state.get("run_count", 0) + 1
    run = state["run_count"]

    sessions = fetch_tickets()
    if sessions is None:
        print(f"  ⚠ Skip cek #{run} — API tidak merespons")
        return state

    prev_quota  = state.get("quota", {})
    new_quota   = {}
    notif_count = 0
    total_slots = 0

    for sesi in sessions:
        sesi_label = sesi.get("label", "?")
        sesi_time  = sesi.get("start_time", "")[:5]

        for member in sesi.get("session_members", []):
            name      = member.get("member_name", "")
            jalur     = member.get("label", "")
            quota     = member.get("quota", 0)
            price     = member.get("price", 0)
            detail_id = str(member.get("session_detail_id", ""))
            total_slots += 1

            if WATCH_MEMBERS and name not in WATCH_MEMBERS:
                new_quota[detail_id] = quota
                continue

            prev = prev_quota.get(detail_id, 0)
            new_quota[detail_id] = quota

            # Sold out → Tersedia
            if quota > 0 and prev == 0:
                now = now_str()
                print(f"  🎉 TERSEDIA: {name} | {sesi_label} ({sesi_time}) | {jalur} | quota={quota}")
                purchase_url = f"https://jkt48.com/purchase/exclusive?code={EXCLUSIVE_CODE}"
                msg = (
                    f"🎉 <b>TIKET TERSEDIA!</b>\n\n"
                    f"👤 <b>Member:</b> {name}\n"
                    f"📋 <b>Sesi:</b> {sesi_label} ({sesi_time} WIB)\n"
                    f"🚪 <b>Jalur:</b> {jalur}\n"
                    f"🎟 <b>Quota:</b> {quota} tiket\n"
                    f"💰 <b>Harga:</b> Rp{price:,}\n"
                    f"🕐 <b>Terdeteksi:</b> {now}\n\n"
                    f"🔗 <a href='{purchase_url}'>Beli sekarang →</a>"
                )
                send_telegram(msg)
                notif_count += 1

            # Tersedia → Sold out
            elif quota == 0 and prev > 0:
                print(f"  ❌ Kembali sold out: {name} | {sesi_label} | {jalur}")

    state["quota"] = new_quota

    # Cek heartbeat
    if should_send_heartbeat(state):
        send_heartbeat(state, sessions, total_slots)

    if notif_count > 0:
        print(f"  📨 {notif_count} notifikasi dikirim")

    return state

# ─────────────────────────────────────────────
#  MAIN LOOP
# ─────────────────────────────────────────────

def main():
    print("=" * 50)
    print("JKT48 Ticket Monitor — Railway.app")
    print(f"Interval : {CHECK_INTERVAL} detik")
    print(f"Heartbeat: setiap {HEARTBEAT_EVERY_HOURS} jam")
    print(f"Member   : {'semua' if not WATCH_MEMBERS else ', '.join(WATCH_MEMBERS)}")
    print("=" * 50)

    # Pesan startup ke Telegram
    send_telegram(
        f"✅ <b>JKT48 Monitor aktif!</b>\n\n"
        f"⚡ Cek tiket setiap <b>{CHECK_INTERVAL} detik</b>\n"
        f"🎯 Member: {'semua' if not WATCH_MEMBERS else ', '.join(WATCH_MEMBERS)}\n"
        f"🕐 Mulai: {now_str()}"
    )

    state = load_state()

    while True:
        now = now_wib().strftime("%H:%M:%S")
        run_next = state.get("run_count", 0) + 1
        print(f"[{now}] Cek #{run_next}...", end=" ", flush=True)

        try:
            state = check_once(state)
            save_state(state)
            # Cetak ringkasan setiap 10 run
            if state["run_count"] % 10 == 0:
                print(f"\n  📊 Total {state['run_count']}x cek berjalan lancar")
            else:
                print("selesai")
        except Exception as e:
            print(f"\n  ❌ Error tidak terduga: {e}")

        time.sleep(CHECK_INTERVAL)

if __name__ == "__main__":
    main()
