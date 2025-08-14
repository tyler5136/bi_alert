import os
import sys
import glob
import subprocess
import requests
from datetime import datetime


# === Input from BI ===
camera = sys.argv[1]
timestamp = sys.argv[2]

# === Config ===
WEBHOOK_URL = "https://n8n.tsmithit.net/webhook/blue-iris-alert-result"
AUTH_HEADER = { "Authorization": "Basic d2ViaG9vazpNaWxuZXItU21hbGxlci0xNDI=" }  # replace this

bi_command = r"C:\Program Files\Blue Iris 5\BlueIrisCommand.exe"
output_dir = r"C:\bi_alerts"

base_name = f"{camera}_{timestamp.replace(':', '-').replace(' ', '_')}"
output_dir = r"C:\bi_alerts"
os.makedirs(output_dir, exist_ok=True)

export_path = os.path.join(output_dir, f"{base_name}.mp4")

# === Export last 10s using BlueIrisCommand.exe ===
export_cmd = [
    bi_command,
    "/export",
    f"/camera={camera}",
    "/start=now-10",
    "/end=now",
    f"/file={export_path}"
]

try:
    subprocess.run(export_cmd, check=True)
    log(f"✅ Exported last 10s to: {export_path}")
except Exception as e:
    log(f"❌ Failed to export clip: {e}")
    sys.exit(1)


os.makedirs(OUTPUT_DIR, exist_ok=True)

# === Logging ===
def log(msg):
    with open("C:\\scripts\\event_summary_log.txt", "a") as f:
        f.write(f"[{datetime.now()}] {msg}\n")

log(f"Processing alert from {camera} at {timestamp}")

# === Step 1: Find Most Recent MP4 Clip for Camera ===
mp4_files = sorted(
    glob.glob(os.path.join(STORED_CLIP_DIR, "*.mp4")),
    key=os.path.getmtime,
    reverse=True
)

if not mp4_files:
    log(f"[ERROR] No clips found in {STORED_CLIP_DIR}")
    sys.exit(1)

latest_clip = mp4_files[0]
log(f"Latest clip: {latest_clip}")

# === Step 2: Determine Duration (via ffprobe) ===
cmd = [
    "ffprobe", "-v", "error", "-show_entries", "format=duration",
    "-of", "default=noprint_wrappers=1:nokey=1", latest_clip
]

try:
    result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True, text=True)
    duration = float(result.stdout.strip())
except Exception as e:
    log(f"[ERROR] Failed to get clip duration: {e}")
    sys.exit(1)

# === Step 3: Generate 10s GIF from end of clip ===
start_time = max(duration - 10, 0)
gif_path = os.path.join(OUTPUT_DIR, f"{camera}_{timestamp.replace(':', '-')}.gif")

ffmpeg_cmd = [
    "ffmpeg", "-y", "-ss", str(start_time), "-t", "10", "-i", latest_clip,
    "-vf", "fps=10,scale=320:-1:flags=lanczos", "-loop", "0", gif_path
]

try:
    subprocess.run(ffmpeg_cmd, check=True)
    log(f"Generated GIF: {gif_path}")
except Exception as e:
    log(f"[ERROR] ffmpeg failed: {e}")
    sys.exit(1)

# === Step 4: Send to n8n Webhook ===
with open(gif_path, "rb") as f:
    resp = requests.post(
        WEBHOOK_URL,
        files={"gif": f},
        data={
            "camera": camera,
            "timestamp": timestamp
        },
        headers=AUTH_HEADER
    )

log(f"Webhook status: {resp.status_code}")
