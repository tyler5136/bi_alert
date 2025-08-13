import os
import sys
import subprocess
import requests
from datetime import datetime

# === Config ===
temp_dir = r"C:\bi_alerts"
log_path = r"C:\scripts\event_summary_log.txt"
WEBHOOK_URL = "https://n8n.tsmithit.net/webhook/blue-iris-alert-result"
AUTH_HEADER = { "Authorization": "Basic d2ViaG9vazpNaWxuZXItU21hbGxlci0xNDI=" }

# === Logging helper ===
def log(msg):
    timestamp = datetime.now()
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(f"[{timestamp}] {msg}\n")
    print(f"[{timestamp}] {msg}")

try:
    # === Input validation ===
    log("Starting script execution.")
    log(f"Raw sys.argv: {sys.argv}")
    
    if len(sys.argv) < 3:
        log("Not enough arguments provided. Expected: camera and timestamp.")
        sys.exit(1)

    camera = sys.argv[1]
    timestamp = sys.argv[2]
    base_name = f"{camera}_{timestamp.replace(':', '-').replace(' ', '_')}"
    gif_path = os.path.join(temp_dir, f"{base_name}.gif")
    bvr_dir = rf"C:\Blue Iris\New\{camera}"  # Adjust this path if needed

    log(f"Camera: {camera}")
    log(f"Timestamp: {timestamp}")
    log(f"Temp Dir: {temp_dir}")
    log(f"Clip Dir: {bvr_dir}")
    log(f"GIF Path: {gif_path}")

    os.makedirs(temp_dir, exist_ok=True)

    # === Find most recent .bvr file ===
    log("Searching for .bvr files...")
    bvr_files = [f for f in os.listdir(bvr_dir) if f.endswith(".bvr")]
    bvr_files.sort(key=lambda f: os.path.getmtime(os.path.join(bvr_dir, f)), reverse=True)

    if not bvr_files:
        log("No .bvr files found in the directory.")
        sys.exit(1)

    latest_bvr = os.path.join(bvr_dir, bvr_files[0])
    log(f"Found latest .bvr file: {latest_bvr}")

    # === Generate GIF from .bvr file ===
    log("Generating GIF using ffmpeg...")
    ffmpeg_cmd = [
        "ffmpeg", "-y",
        "-i", latest_bvr,
        "-ss", "00:00:00",
        "-t", "00:00:08",
        "-vf", "fps=3,scale=320:-1:flags=lanczos",
        "-loop", "0",
        gif_path
    ]

    log(f"🛠️ Running command: {' '.join(ffmpeg_cmd)}")
    result = subprocess.run(ffmpeg_cmd, capture_output=True, text=True)

    if result.returncode != 0:
        log(f"ffmpeg failed: {result.stderr.strip()}")
        sys.exit(1)

    log(f"GIF created at: {gif_path}")

    # === Send to webhook ===
    log("Sending GIF to webhook...")
    with open(gif_path, "rb") as f:
        resp = requests.post(
            WEBHOOK_URL,
            files={"gif": f},
            data={
                "camera": camera,
                "timestamp": timestamp
            },
            headers=AUTH_HEADER,
            timeout=10
        )
        log(f"Webhook response: {resp.status_code} {resp.text.strip()}")

except Exception as e:
    log(f"Unhandled exception occurred: {str(e)}")
    sys.exit(1)
