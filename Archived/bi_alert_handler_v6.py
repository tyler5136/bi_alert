import requests
import hashlib
import time
import sys
import os
from datetime import datetime
from PIL import Image
import cv2

# === CONFIG ===
BI_HOST = "http://127.0.0.1:8191"
BI_USER = "Tyler"
BI_PASS = "Jasper-0518"
CLIP_DURATION_MS = 10000
LOG_PATH = r"C:\scripts\event_summary_log.txt"
EXPORT_DIR = r"C:\Blue Iris\New\Clipboard"
GIF_SAVE_DIR = r"C:\bi_alerts"
WEBHOOK_URL = "https://n8n.tsmithit.net/webhook/blue-iris-alert"
AUTH_HEADER = {
    "Authorization": "Basic d2ViaG9vazpNaWxuZXItU21hbGxlci0xNDI="
}
debugging = True
if debugging 
# === GLOBAL VARIABLES ===
camera_arg = None
timestamp_arg = None

def log(msg):
    ts = datetime.now()
    with open(LOG_PATH, "a", encoding="utf-8") as f:
        f.write(f"[{ts}] {msg}\n")
    print(f"[{ts}] {msg}")

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

def convert_mp4_to_gif(mp4_path, gif_path, duration_seconds=3, fps=10):
    """Convert MP4 to GIF with specified duration and fps"""
    try:
        # Create output directory if it doesn't exist
        os.makedirs(os.path.dirname(gif_path), exist_ok=True)
        
        # Open video
        cap = cv2.VideoCapture(mp4_path)
        if not cap.isOpened():
            raise Exception(f"Could not open video file: {mp4_path}")
        
        # Get video properties
        original_fps = cap.get(cv2.CAP_PROP_FPS)
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        
        # Calculate frame sampling
        frames_to_extract = duration_seconds * fps
        frame_step = max(1, int(total_frames / frames_to_extract))
        
        frames = []
        frame_count = 0
        
        while len(frames) < frames_to_extract:
            ret, frame = cap.read()
            if not ret:
                break
                
            if frame_count % frame_step == 0:
                # Convert BGR to RGB
                frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                # Resize to reduce file size (optional)
                height, width = frame_rgb.shape[:2]
                if width > 640:
                    new_width = 640
                    new_height = int(height * (new_width / width))
                    frame_rgb = cv2.resize(frame_rgb, (new_width, new_height))
                
                frames.append(Image.fromarray(frame_rgb))
            
            frame_count += 1
        
        cap.release()
        
        if not frames:
            raise Exception("No frames extracted from video")
        
        # Save as GIF
        duration_per_frame = int(1000 / fps)  # milliseconds
        frames[0].save(
            gif_path,
            save_all=True,
            append_images=frames[1:],
            duration=duration_per_frame,
            loop=0,
            optimize=True
        )
        
        log(f"✅ GIF created: {gif_path} ({len(frames)} frames)")
        return gif_path
        
    except Exception as e:
        log(f"❌ GIF conversion failed: {e}")
        return None

def wait_for_exported_file():
    """Wait for the exported MP4 file to appear"""
    global camera_arg
    
    expected_filename_prefix = f"{camera_arg}.{datetime.now().strftime('%Y%m%d')}_"
    timeout = time.time() + 30  # 30 seconds max
    
    while time.time() < timeout:
        try:
            matching_files = [
                f for f in os.listdir(EXPORT_DIR)
                if f.startswith(expected_filename_prefix) and f.endswith(".mp4")
            ]
            if matching_files:
                latest_file = max(
                    matching_files,
                    key=lambda x: os.path.getctime(os.path.join(EXPORT_DIR, x))
                )
                return os.path.join(EXPORT_DIR, latest_file)
        except FileNotFoundError:
            log(f"❌ Export directory not found: {EXPORT_DIR}")
            break
        except Exception as e:
            log(f"⚠️ Error checking for files: {e}")
        
        time.sleep(1)
    
    raise Exception("❌ Failed to locate exported .mp4 within timeout")

def send_webhook(mp4_path, gif_path=None):
    """Send files to n8n webhook"""
    global camera_arg, timestamp_arg
    
    try:
        files = {}
        data = {"camera": camera_arg, "timestamp": timestamp_arg}
        
        # Always send MP4
        with open(mp4_path, "rb") as f:
            files["clip"] = f
            
            # Optionally send GIF if it exists
            if gif_path and os.path.exists(gif_path):
                with open(gif_path, "rb") as gif_f:
                    files["gif"] = gif_f
                    data["has_gif"] = "true"
                    
                    resp = requests.post(
                        WEBHOOK_URL,
                        files=files,
                        data=data,
                        headers=AUTH_HEADER
                    )
            else:
                resp = requests.post(
                    WEBHOOK_URL,
                    files=files,
                    data=data,
                    headers=AUTH_HEADER
                )
        
        log(f"📨 Files sent to n8n: {resp.status_code} - {resp.text}")
        return resp
        
    except Exception as e:
        log(f"❌ Webhook failed: {e}")
        raise

def main():
    global camera_arg, timestamp_arg
    
    if len(sys.argv) < 4:
        log("❌ Not enough args: expecting clip name, camera name, and timestamp")
        sys.exit(1)

    clip_name_arg = sys.argv[1]
    camera_arg = sys.argv[2]
    timestamp_arg = sys.argv[3]
    
    log(f"📩 Received alert:\n ├─ Clip: {clip_name_arg}\n ├─ Camera: {camera_arg}\n └─ Timestamp: {timestamp_arg}")

    try:
        session = login()
        log(f"✅ Logged in: {session}")

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
        
        # Wait for exported file
        exported_mp4_path = wait_for_exported_file()
        log(f"✅ Found exported file: {exported_mp4_path}")
        
        # Create GIF with proper naming format
        gif_filename = f"{camera_arg}_{datetime.now().strftime('%m%d%y_%H%M%S')}.gif"
        gif_path = os.path.join(GIF_SAVE_DIR, gif_filename)
        
        log("🎬 Converting MP4 to GIF...")
        converted_gif_path = convert_mp4_to_gif(exported_mp4_path, gif_path)
        
        # Send webhook
        send_webhook(exported_mp4_path, converted_gif_path)
        
        log("✅ Process completed successfully!")

    except Exception as e:
        log(f"❌ Failed: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()