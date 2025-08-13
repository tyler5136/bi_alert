import requests
import hashlib
import time
import sys
from datetime import datetime
import os
import json

# === CONFIGURATION ===
BI_HOST = "http://127.0.0.1:8191"
BI_USER = "Tyler"
BI_PASS = "Jasper-0518"
SESSION_FILE = os.path.join(os.path.dirname(__file__), ".bi_session")
EXPORT_DURATION_MS = 10000
LOG_PATH = r"C:\scripts\event_summary_log.txt"
OUTPUT_MP4 = r"C:\bi_alerts\latest_alert.mp4"
WEBHOOK_URL = "https://n8n.tsmithit.net/webhook/blue-iris-alert-result"
AUTH_HEADER = {
    "Authorization": "Basic d2ViaG9vazpNaWxuZXItU21hbGxlci0xNDI="
}
expected_filename_prefix = f"{camera_arg}.{datetime.now().strftime('%Y%m%d')}_"
latest_file = None
timeout = time.time() + 30  # 30 seconds max

def log(msg):
    ts = datetime.now()
    with open(LOG_PATH, "a", encoding="utf-8") as f:
        f.write(f"[{ts}] {msg}\n")
    print(f"[{ts}] {msg}")


def get_bi_session():
    # Try to load existing session
    if os.path.exists(SESSION_FILE):
        with open(SESSION_FILE, "r") as f:
            session = f.read().strip()
            # Test session
            test_resp = requests.post(f"{BI_HOST}/json", json={"cmd": "status", "session": session})
            if test_resp.ok and test_resp.json().get("result") != "fail":
                return session
            else:
                print("🔁 Session expired. Reauthenticating...")

    # No valid session — do full login
    login_resp = requests.post(f"{BI_HOST}/json", json={"cmd": "login"})
    session = login_resp.json()["session"]
    hashed = md5(f"{BI_USER}:{session}:{BI_PASS}".encode()).hexdigest()
    auth_resp = requests.post(f"{BI_HOST}/json", json={"cmd": "login", "session": session, "response": hashed})
    auth_data = auth_resp.json()

    if auth_data.get("result") == "success":
        session = auth_data["session"]
        with open(SESSION_FILE, "w") as f:
            f.write(session)
        return session
    else:
        raise Exception("❌ Blue Iris login failed")

# Use this in your alert handler
session = get_bi_session()


# === CLI ARGS ===
if len(sys.argv) < 4:
    log(f"❌ Error: Expected 3 arguments but got {len(sys.argv)}")
    sys.exit(1)

clip_name_arg = sys.argv[1]
camera_arg = sys.argv[2]
timestamp_arg = sys.argv[3]

log(f"📩 Received alert:\n ├─ Clip: {clip_name_arg}\n ├─ Camera: {camera_arg}\n └─ Timestamp: {timestamp_arg}")

def login():
    log("🔐 Attempting secure MD5 login...")
    # Step 1: Get session key
    r1 = requests.post(f"{BI_HOST}/json", json={"cmd": "login"})
    try:
        r1.raise_for_status()
        session = r1.json().get("session")
    except Exception as e:
        raise Exception(f"Failed to retrieve session: {e}")

    if not session:
        raise Exception("No session key received")

    # Step 2: Send MD5 hash response
    response = f"{BI_USER}:{session}:{BI_PASS}".encode()
    hash_response = hashlib.md5(response).hexdigest()

    r2 = requests.post(f"{BI_HOST}/json", json={
        "cmd": "login",
        "session": session,
        "response": hash_response
    })
    try:
        r2.raise_for_status()
        if r2.json().get("result") != "success":
            raise Exception(f"Login failed: {r2.json()}")
    except Exception as e:
        raise Exception(f"Failed to complete login: {e}")

    return session

def get_latest_clip_id(session):
    r = requests.post(f"{BI_HOST}/json", json={"cmd": "clips", "session": session})
    r.raise_for_status()
    resp_json = r.json()
    log(f"📥 Raw clips response: {resp_json}")
    clips = resp_json.get("data", [])
    if not isinstance(clips, list) or not clips:
        raise Exception("No valid clips list returned from Blue Iris")
    clip = clips[0]
    return clip["id"], clip["camera"], clip["start"]

def get_clip(session, clip_name_hint):
    if clip_name_hint.startswith("@") or len(clip_name_hint.strip()) < 5:
        log("⚠️ No valid clip name provided, falling back to latest clip...")
        return get_latest_clip_id(session)
    else:
        raise NotImplementedError("Named clip lookup not implemented yet")

def export_clip(session, clip_id):
    r = requests.post(f"{BI_HOST}/json", json={
        "cmd": "export",
        "session": session,
        "clipid": clip_id,
        "startms": 0,
        "msec": EXPORT_DURATION_MS
    })
    r.raise_for_status()
    return r.json().get("id")

def wait_for_export(session, export_id):
    while True:
        r = requests.post(f"{BI_HOST}/json", json={
            "cmd": "status",
            "session": session,
            "jobid": export_id
        })
        r.raise_for_status()
        data = r.json()
        if data.get("done"):
            return data["path"]
        time.sleep(0.5)

def download_clip(path):
    url = f"{BI_HOST}/clips/{path}"
    r = requests.get(url, stream=True)
    r.raise_for_status()
    with open(OUTPUT_MP4, "wb") as f:
        for chunk in r.iter_content(chunk_size=8192):
            f.write(chunk)

def send_to_n8n(camera="Unknown", timestamp=None):
    if not timestamp:
        timestamp = datetime.now().isoformat()
    with open(OUTPUT_MP4, "rb") as f:
        resp = requests.post(
            WEBHOOK_URL,
            files={"clip": f},
            data={"camera": camera, "timestamp": timestamp},
            headers=AUTH_HEADER
        )
    log(f"Sent to n8n: {resp.status_code} - {resp.text}")

def main():
    try:
        log("🚨 Starting BI alert handler")
        session = login()
        log(f"✅ Logged in with session: {session}")
        clip_id, camera, timestamp = get_clip(session, clip_name_arg)
        log(f"📸 Latest clip: ID={clip_id}, Camera={camera}, Timestamp={timestamp}")
        export_id = export_clip(session, clip_id)
        log(f"📤 Export job started: ID={export_id}")
        path = wait_for_export(session, export_id)
        log(f"📁 Export complete: Path={path}")
        download_clip(path)
        log("⬇️ Clip downloaded")
        send_to_n8n(camera, timestamp)
        log("📨 Clip sent to n8n")
    except requests.exceptions.RequestException as re:
        log(f"❌ HTTP Error: {re.response.status_code if re.response else 'No Response'} - {re}")
    except Exception as e:
        log(f"❌ General Error: {type(e).__name__} - {e}")

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

    full_path = os.path.join(EXPORT_DIR, latest_file)
    with open(full_path, "rb") as f:
        resp = requests.post(
            WEBHOOK_URL,
            files={"clip": f},
            data={"camera": camera_arg, "timestamp": timestamp_arg},
            headers=AUTH_HEADER
        )

    print(f"📨 Clip sent to n8n: {resp.status_code} - {resp.text}")

main()
