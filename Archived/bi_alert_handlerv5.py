import requests
import hashlib
import time
import sys
import os
from datetime import datetime
import time


# === CONFIG ===
BI_HOST = "http://127.0.0.1:8191"
BI_USER = "Tyler"
BI_PASS = "Jasper-0518"
CLIP_DURATION_MS = 10000
LOG_PATH = r"C:\scripts\event_summary_log.txt"
EXPORT_DIR = r"C:\Blue Iris\New\Clipboard"
WEBHOOK_URL = "https://n8n.tsmithit.net/webhook/blue-iris-alert"
AUTH_HEADER = {
    "Authorization": "Basic d2ViaG9vazpNaWxuZXItU21hbGxlci0xNDI="
}
expected_filename_prefix = f"{camera_arg}.{datetime.now().strftime('%Y%m%d')}_"
latest_file = None
timeout = time.time() + 30  # 30 seconds max

# === START ===
def log(msg):
    ts = datetime.now()
    with open(LOG_PATH, "a", encoding="utf-8") as f:
        f.write(f"[{ts}] {msg}\n")
    print(f"[{ts}] {msg}")

# clip_name_arg = "@1464623813.bvr"
# camera_arg = "FrontYardDW"
# timestamp_arg = "12:18:43 PM"


def login():
    r1 = requests.post(f"{BI_HOST}/json", json={"cmd": "login"})
    session = r1.json()["session"]
    rhash = hashlib.md5(f"{BI_USER}:{session}:{BI_PASS}".encode()).hexdigest()
    r2 = requests.post(f"{BI_HOST}/json", json={
        "cmd": "login",
        "session": session,
        "response": rhash
    })
    if r2.json().get("result") != "success":
        raise Exception("Login failed")
    return session

def get_clip_from_cliplist(session, camera):
    r = requests.post(f"{BI_HOST}/json", json={
        "cmd": "cliplist",
        "session": session,
        "camera": camera,
        "startdate": int(time.time()) - 7200
    })
    data = r.json().get("data", [])
    if not data:
        raise Exception(f"No clips found for camera {camera}")
    return data[0]  # most recent

def export_clip(session, path, msec):
    startms = msec - CLIP_DURATION_MS if msec > CLIP_DURATION_MS else 0
    r = requests.post(f"{BI_HOST}/json", json={
        "cmd": "export",
        "session": session,
        "path": path,
        "startms": startms,
        "msec": CLIP_DURATION_MS,
        "timelapse": "3.0@30.0"
    })
    return r.json()

def main():
    if len(sys.argv) < 3:
        log("❌ Not enough args: expecting clip name and camera name")
        sys.exit(1)

    clip_name_arg = sys.argv[1]
    camera_arg = sys.argv[2]
    timestamp_arg = sys.argv[3]
    log(f"📩 Received alert:\n ├─ Clip: {clip_name_arg}\n └─ Camera: {camera_arg}\n └─ Timestamp: {timestamp_arg}")

    session = login()
    log(f"✅ Logged in: {session}")

    try:
        if clip_name_arg == "@-1" and camera_arg:
            # Prefer lookup by camera if macro is generic
            clip = get_clip_from_cliplist(session, camera_arg)
            log("🔁 Used cliplist fallback due to forced macro (@-1)")
        else:
            log(f"✅ Using provided clip path without lookup: {clip_name_arg}")
            clip = {
                "path": clip_name_arg,
                "camera": camera_arg,
                "msec": 0  # Duration unknown unless retrieved later
            }

        clip_path = clip["path"]
        clip_msec = int(clip["msec"])
        log(f"📸 Clip: {clip_path} ({clip_msec}ms)")

        exp_resp = export_clip(session, clip_path, clip_msec)
        log(f"📤 Export started: {exp_resp}")

    except Exception as e:
        log(f"❌ Failed: {e}")
        sys.exit(1)

def webhook():
    while time.time() < timeout:
        matching_files = [
            f for f in os.listdir(EXPORT_DIR)
            if f.startswith(expected_filename_prefix) and f.endswith(".mp4")
        ]
        if matching_files:
            latest_file = max(
                matching_files,
                key=lambda x: os.path.getctime(os.path.join(EXPORT_DIR, x))
            )
            break
        time.sleep(1)

    if not latest_file:
        raise Exception("❌ Failed to locate exported .mp4")

    # Send to n8n
    full_path = os.path.join(EXPORT_DIR, latest_file)
    with open(full_path, "rb") as f:
        resp = requests.post(
            WEBHOOK_URL,
            files={"clip": f},
            data={"camera": camera_arg, "timestamp": timestamp_arg},
            headers=AUTH_HEADER
        )

    print(f"📨 Clip sent to n8n: {resp.status_code} - {resp.text}")
    
if __name__ == "__main__":
    main()
    webhook()