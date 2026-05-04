#!/usr/bin/env python3
"""
JKT48 Ticket Monitor — Railway.app Version (Final Fix v4)
- Interval cek: 10 detik
- Fetch lebih tahan error: retry cepat tanpa delay panjang
- Jika fetch gagal, langsung coba lagi di siklus berikutnya
- Notif langsung saat startup jika ada tiket tersedia
- Header browser tanpa Accept-Encoding
- Heartbeat setiap 6 jam
"""

import requests
import os
import time
from datetime import datetime, timezone, timedelta

# ─────────────────────────────────────────────
#  KONFIGURASI
# ─────────────────────────────────────────────

API_URL        = "https://jkt48.com/api/v1/exclusives/EX579E/bonus?lang=id"
EXCLUSIVE_CODE = "EX579E"

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID   = os.environ.get("TELEGRAM_CHAT_ID", "")

CHECK_INTERVAL        = 10   # detik — dipercepat dari 30 → 10
HEARTBEAT_EVERY_HOURS = 6
MAX_FAIL_ALERT        = 10   # dinaikkan karena interval lebih cepat

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
#  FETCH API
#  - Timeout 8 detik (lebih pendek dari interval)
#  - Retry 2x dengan jeda singkat (3 detik)
#  - Tanpa Accept-Encoding agar tidak dapat
#    respons terkompresi
# ─────────────────────────────────────────────

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "id-ID,id;q=0.9,en-US;q=0.8",
    "Referer": "https://jkt48.com/",
    "Origin": "https://jkt48.com",
    "Connection": "keep-alive",
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "same-origin",
}

def fetch_tickets(retries: int = 2) -> list | None:
    for attempt in range(1, retries + 1):
        try:
            r = requests.get(API_URL, headers=HEADERS, timeout=8)
            r.raise_for_status()

            text = r.content.decode("utf-8", errors="replace").strip()
            if not text:
                raise ValueError("Respons kosong")
            if not text.startswith("{") and not text.startswith("["):
                raise ValueError(f"Bukan JSON: {text[:60]!r}")

            data = r.json()
            if data.get("status") and "data" in data:
                return data["data"]
            print(f"  ⚠ Respons tidak terduga: {data.get('message')}")
            return None

        except Exception as e:
            if attempt < retries:
                # Jeda singkat 3 detik lalu langsung retry
                # agar tidak buang waktu terlalu lama
                print(f"  ⚠ Attempt {attempt}/{retries} gagal, retry 3s: {e}")
                time.sleep(3)
            else:
                print(f"  ❌ Gagal fetch: {e}")
                return None

# ─────────────────────────────────────────────
#  EXTRACT QUOTA
# ─────────────────────────────────────────────

def extract_quota(sessions: list) -> dict:
    result = {}
    for sesi in sessions:
        for member in sesi.get("session_members", []):
            detail_id = str(member.get("session_detail_id", ""))
            result[detail_id] = member.get("quota", 0)
    return result

# ─────────────────────────────────────────────
#  HEARTBEAT
# ─────────────────────────────────────────────

def should_send_heartbeat(last_hb) -> bool:
    if last_hb is None:
        return True
    return (now_wib() - last_hb).total_seconds() >= HEARTBEAT_EVERY_HOURS * 3600

def send_heartbeat(sessions: list, run_count: int, fail_total: int) -> datetime:
    now         = now_wib()
    total_slots = sum(len(s.get("session_members", [])) for s in sessions)
    available   = sum(
        1 for s in sessions
        for m in s.get("session_members", [])
        if m.get("quota", 0) > 0
    )
    next_hb = now + timedelta(hours=HEARTBEAT_EVERY_HOURS)
    status  = "😴 Semua slot masih sold out" if available == 0 \
              else f"🎉 {available} slot tersedia!"
    send_telegram(
        f"💓 <b>Laporan Berkala — JKT48 Monitor</b>\n\n"
        f"✅ Sistem berjalan normal\n"
        f"🕐 Waktu: {now.strftime('%Y-%m-%d %H:%M WIB')}\n"
        f"⚡ Interval cek: setiap {CHECK_INTERVAL} detik\n\n"
        f"📊 <b>Status tiket:</b>\n"
        f"   • Total slot dipantau: {total_slots}\n"
        f"   • Sold out: {total_slots - available}\n"
        f"   • Tersedia: {available}\n\n"
        f"{status}\n\n"
        f"📈 Total pengecekan: {run_count:,}x\n"
        f"⚠️ Total gagal fetch: {fail_total}x\n"
        f"🔁 Laporan berikutnya: {next_hb.strftime('%H:%M WIB')}"
    )
    print("  💓 Heartbeat terkirim")
    return now

# ─────────────────────────────────────────────
#  STARTUP
# ─────────────────────────────────────────────

def init_and_notify() -> tuple:
    print("🔄 Inisialisasi — mengambil data awal dari API...")
    while True:
        sessions = fetch_tickets()
        if sessions is not None:
            break
        print("  ⚠ API belum merespons, retry dalam 5 detik...")
        time.sleep(5)

    quota        = extract_quota(sessions)
    total        = len(quota)
    tersedia     = sum(1 for v in quota.values() if v > 0)
    purchase_url = f"https://jkt48.com/purchase/exclusive?code={EXCLUSIVE_CODE}"

    print(f"  ✅ Data awal: {total} slot, {tersedia} tersedia, {total - tersedia} sold out")

    if tersedia > 0:
        print(f"  🎉 {tersedia} slot tersedia saat startup — mengirim notif...")
        for sesi in sessions:
            sesi_label = sesi.get("label", "?")
            sesi_time  = sesi.get("start_time", "")[:5]
            for member in sesi.get("session_members", []):
                name      = member.get("member_name", "")
                jalur     = member.get("label", "")
                quota_val = member.get("quota", 0)
                price     = member.get("price", 0)
                if WATCH_MEMBERS and name not in WATCH_MEMBERS:
                    continue
                if quota_val > 0:
                    send_telegram(
                        f"🎉 <b>TIKET TERSEDIA!</b>\n"
                        f"<i>(terdeteksi saat sistem restart)</i>\n\n"
                        f"👤 <b>Member:</b> {name}\n"
                        f"📋 <b>Sesi:</b> {sesi_label} ({sesi_time} WIB)\n"
                        f"🚪 <b>Jalur:</b> {jalur}\n"
                        f"🎟 <b>Quota:</b> {quota_val} tiket\n"
                        f"💰 <b>Harga:</b> Rp{price:,}\n"
                        f"🕐 <b>Terdeteksi:</b> {now_str()}\n\n"
                        f"🔗 <a href='{purchase_url}'>Beli sekarang →</a>"
                    )
    else:
        print("  😴 Tidak ada slot tersedia saat startup")

    return quota, sessions

# ─────────────────────────────────────────────
#  MAIN LOOP
# ─────────────────────────────────────────────

def main():
    print("=" * 55)
    print("JKT48 Ticket Monitor — Railway.app (Final Fix v4)")
    print(f"Interval : {CHECK_INTERVAL} detik")
    print(f"Heartbeat: setiap {HEARTBEAT_EVERY_HOURS} jam")
    print(f"Member   : {'semua' if not WATCH_MEMBERS else ', '.join(WATCH_MEMBERS)}")
    print("=" * 55)

    prev_quota, _ = init_and_notify()

    send_telegram(
        f"✅ <b>JKT48 Monitor aktif!</b>\n\n"
        f"⚡ Cek tiket setiap <b>{CHECK_INTERVAL} detik</b>\n"
        f"🎯 Member: {'semua' if not WATCH_MEMBERS else ', '.join(WATCH_MEMBERS)}\n"
        f"🕐 Mulai: {now_str()}"
    )

    run_count      = 0
    fail_count     = 0
    fail_total     = 0
    last_heartbeat = now_wib()
    last_sessions  = []

    while True:
        time.sleep(CHECK_INTERVAL)
        run_count += 1
        ts = now_wib().strftime("%H:%M:%S")
        print(f"[{ts}] Cek #{run_count}...", end=" ", flush=True)

        sessions = fetch_tickets()

        if sessions is None:
            fail_count += 1
            fail_total += 1
            print(f"gagal ({fail_count}x berturut-turut)")
            if fail_count == MAX_FAIL_ALERT:
                send_telegram(
                    f"⚠️ <b>JKT48 Monitor — API Bermasalah</b>\n\n"
                    f"Gagal mengakses API JKT48 sebanyak {MAX_FAIL_ALERT}x berturut-turut (~{MAX_FAIL_ALERT * CHECK_INTERVAL} detik).\n"
                    f"🕐 {now_str()}\n\n"
                    f"Monitor tetap mencoba setiap {CHECK_INTERVAL} detik."
                )
            continue

        fail_count    = 0
        last_sessions = sessions
        new_quota     = extract_quota(sessions)
        notif_count   = 0
        purchase_url  = f"https://jkt48.com/purchase/exclusive?code={EXCLUSIVE_CODE}"

        for sesi in sessions:
            sesi_label = sesi.get("label", "?")
            sesi_time  = sesi.get("start_time", "")[:5]

            for member in sesi.get("session_members", []):
                name      = member.get("member_name", "")
                jalur     = member.get("label", "")
                quota     = member.get("quota", 0)
                price     = member.get("price", 0)
                detail_id = str(member.get("session_detail_id", ""))

                if WATCH_MEMBERS and name not in WATCH_MEMBERS:
                    continue

                prev = prev_quota.get(detail_id, 0)

                # Sold out → Tersedia
                if quota > 0 and prev == 0:
                    print(f"\n  🎉 TERSEDIA: {name} | {sesi_label} ({sesi_time}) | {jalur} | quota={quota}")
                    send_telegram(
                        f"🎉 <b>TIKET TERSEDIA!</b>\n\n"
                        f"👤 <b>Member:</b> {name}\n"
                        f"📋 <b>Sesi:</b> {sesi_label} ({sesi_time} WIB)\n"
                        f"🚪 <b>Jalur:</b> {jalur}\n"
                        f"🎟 <b>Quota:</b> {quota} tiket\n"
                        f"💰 <b>Harga:</b> Rp{price:,}\n"
                        f"🕐 <b>Terdeteksi:</b> {now_str()}\n\n"
                        f"🔗 <a href='{purchase_url}'>Beli sekarang →</a>"
                    )
                    notif_count += 1

                # Tersedia → Sold out
                elif quota == 0 and prev > 0:
                    print(f"\n  ❌ Sold out: {name} | {sesi_label} | {jalur}")

        prev_quota = new_quota

        if should_send_heartbeat(last_heartbeat):
            last_heartbeat = send_heartbeat(sessions, run_count, fail_total)

        if notif_count > 0:
            print(f"  📨 {notif_count} notifikasi dikirim")
        else:
            print("OK" if run_count % 20 != 0 else f"OK (total {run_count}x cek)")

if __name__ == "__main__":
    main()
