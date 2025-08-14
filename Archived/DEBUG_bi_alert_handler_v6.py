import requests
import hashlib
import time
import sys
import os
from datetime import datetime
from PIL import Image
import cv2

# === DEBUG MODE ===
debugging = True

# === CONFIG ===
BI_HOST = "http://127.0.0.1:8191"
BI_USER = "Tyler"
BI_PASS = "Jasper-0518"
CLIP_DURATION_MS = 10000
LOG_PATH = r"C:\scripts\event_summary_log.txt"
EXPORT_DIR = r"C:\Blue Iris\New\Clipboard"
GIF_SAVE_DIR = r"C:\bi_alerts"
WEBHOOK_URL = "https://n8n.tsmithit.net/webhook-test/blue-iris-alert"
AUTH_HEADER = {
    "Authorization": "Basic d2ViaG9vazpNaWxuZXItU21hbGxlci0xNDI="
}

# === GLOBAL VARIABLES ===
if debugging:
    # Debug mode - use placeholder values
    camera_arg = "FrontYardDW"
    timestamp_arg = "2:30:45 PM"
    clip_name_arg = "@1517439888.bvr"
    print("🐛 DEBUG MODE ENABLED - Using placeholder arguments")
    print(f"🐛 Placeholder args: clip={clip_name_arg}, camera={camera_arg}, timestamp={timestamp_arg}")
else:
    camera_arg = None
    timestamp_arg = None
    clip_name_arg = None

def debug_log(msg):
    """Enhanced logging for debug mode"""
    if debugging:
        ts = datetime.now()
        debug_msg = f"[DEBUG {ts}] {msg}"
        try:
            with open(LOG_PATH, "a", encoding="utf-8") as f:
                f.write(f"{debug_msg}\n")
            print(debug_msg)
        except Exception as e:
            print(f"❌ Failed to write debug log: {e}")
            print(debug_msg)

def log(msg):
    """Standard logging"""
    ts = datetime.now()
    log_msg = f"[{ts}] {msg}"
    try:
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(f"{log_msg}\n")
        print(log_msg)
    except Exception as e:
        print(f"❌ Failed to write log: {e}")
        print(log_msg)

def login():
    debug_log("🐛 Starting login process...")
    debug_log(f"🐛 Connecting to BI_HOST: {BI_HOST}")
    debug_log(f"🐛 Using username: {BI_USER}")
    
    try:
        r1 = requests.post(f"{BI_HOST}/json", json={"cmd": "login"})
        debug_log(f"🐛 Initial login response: {r1.status_code}")
        debug_log(f"🐛 Response content: {r1.text}")
        
        session = r1.json()["session"]
        debug_log(f"🐛 Session received: {session}")
        
        rhash = hashlib.md5(f"{BI_USER}:{session}:{BI_PASS}".encode()).hexdigest()
        debug_log(f"🐛 Generated hash: {rhash}")
        
        r2 = requests.post(f"{BI_HOST}/json", json={
            "cmd": "login",
            "session": session,
            "response": rhash
        })
        debug_log(f"🐛 Final login response: {r2.status_code}")
        debug_log(f"🐛 Final response content: {r2.text}")
        
        if r2.json().get("result") != "success":
            debug_log("🐛 Login failed - result was not 'success'")
            raise Exception("Login failed")
            
        debug_log("🐛 Login successful!")
        return session
        
    except Exception as e:
        debug_log(f"🐛 Login exception: {e}")
        raise

def get_clip_from_cliplist(session, camera):
    debug_log(f"🐛 Getting clip list for camera: {camera}")
    debug_log(f"🐛 Using session: {session}")
    debug_log(f"🐛 Start date: {int(time.time()) - 7200}")
    
    try:
        r = requests.post(f"{BI_HOST}/json", json={
            "cmd": "cliplist",
            "session": session,
            "camera": camera,
            "startdate": int(time.time()) - 7200
        })
        debug_log(f"🐛 Cliplist response: {r.status_code}")
        debug_log(f"🐛 Cliplist content: {r.text}")
        
        data = r.json().get("data", [])
        debug_log(f"🐛 Found {len(data)} clips")
        
        if not data:
            debug_log("🐛 No clips found!")
            raise Exception(f"No clips found for camera {camera}")
            
        debug_log(f"🐛 Using most recent clip: {data[0]}")
        return data[0]  # most recent
        
    except Exception as e:
        debug_log(f"🐛 Cliplist exception: {e}")
        raise

def export_clip(session, path, msec):
    debug_log(f"🐛 Exporting clip: {path}")
    debug_log(f"🐛 Clip duration: {msec}ms")
    
    startms = msec - CLIP_DURATION_MS if msec > CLIP_DURATION_MS else 0
    debug_log(f"🐛 Start ms: {startms}, Duration: {CLIP_DURATION_MS}")
    
    try:
        r = requests.post(f"{BI_HOST}/json", json={
            "cmd": "export",
            "session": session,
            "path": path,
            "startms": startms,
            "msec": CLIP_DURATION_MS,
            "timelapse": "3.0@30.0"
        })
        debug_log(f"🐛 Export response: {r.status_code}")
        debug_log(f"🐛 Export content: {r.text}")
        
        return r.json()
        
    except Exception as e:
        debug_log(f"🐛 Export exception: {e}")
        raise

def convert_mp4_to_gif(mp4_path, gif_path, duration_seconds=3, fps=10):
    """Convert MP4 to GIF with specified duration and fps"""
    debug_log(f"🐛 Starting MP4 to GIF conversion")
    debug_log(f"🐛 Input: {mp4_path}")
    debug_log(f"🐛 Output: {gif_path}")
    debug_log(f"🐛 Duration: {duration_seconds}s, FPS: {fps}")
    
    try:
        # Create output directory if it doesn't exist
        debug_log(f"🐛 Creating directory: {os.path.dirname(gif_path)}")
        os.makedirs(os.path.dirname(gif_path), exist_ok=True)
        
        # Check if input file exists
        if not os.path.exists(mp4_path):
            debug_log(f"🐛 ❌ Input file does not exist: {mp4_path}")
            raise Exception(f"Input file not found: {mp4_path}")
        
        debug_log(f"🐛 Input file size: {os.path.getsize(mp4_path)} bytes")
        
        # Open video
        cap = cv2.VideoCapture(mp4_path)
        if not cap.isOpened():
            debug_log("🐛 ❌ Could not open video file")
            raise Exception(f"Could not open video file: {mp4_path}")
        
        # Get video properties
        original_fps = cap.get(cv2.CAP_PROP_FPS)
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        
        debug_log(f"🐛 Video properties: {width}x{height}, {original_fps}fps, {total_frames} frames")
        
        # Calculate frame sampling
        frames_to_extract = duration_seconds * fps
        frame_step = max(1, int(total_frames / frames_to_extract))
        debug_log(f"🐛 Extracting {frames_to_extract} frames, step: {frame_step}")
        
        frames = []
        frame_count = 0
        
        while len(frames) < frames_to_extract:
            ret, frame = cap.read()
            if not ret:
                debug_log(f"🐛 End of video reached at frame {frame_count}")
                break
                
            if frame_count % frame_step == 0:
                debug_log(f"🐛 Processing frame {frame_count}/{total_frames}")
                
                # Convert BGR to RGB
                frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                
                # Resize to reduce file size (optional)
                if width > 640:
                    new_width = 640
                    new_height = int(height * (new_width / width))
                    frame_rgb = cv2.resize(frame_rgb, (new_width, new_height))
                    debug_log(f"🐛 Resized frame to {new_width}x{new_height}")
                
                frames.append(Image.fromarray(frame_rgb))
            
            frame_count += 1
        
        cap.release()
        debug_log(f"🐛 Extracted {len(frames)} frames total")
        
        if not frames:
            debug_log("🐛 ❌ No frames extracted!")
            raise Exception("No frames extracted from video")
        
        # Save as GIF
        duration_per_frame = int(1000 / fps)  # milliseconds
        debug_log(f"🐛 Saving GIF with {duration_per_frame}ms per frame")
        
        frames[0].save(
            gif_path,
            save_all=True,
            append_images=frames[1:],
            duration=duration_per_frame,
            loop=0,
            optimize=True
        )
        
        debug_log(f"🐛 GIF saved: {gif_path}")
        debug_log(f"🐛 GIF file size: {os.path.getsize(gif_path)} bytes")
        
        log(f"✅ GIF created: {gif_path} ({len(frames)} frames)")
        return gif_path
        
    except Exception as e:
        debug_log(f"🐛 ❌ GIF conversion failed: {e}")
        log(f"❌ GIF conversion failed: {e}")
        return None

def wait_for_exported_file():
    """Wait for the exported MP4 file to appear"""
    global camera_arg
    
    debug_log("🐛 Starting file wait process")
    debug_log(f"🐛 Looking in directory: {EXPORT_DIR}")
    debug_log(f"🐛 Camera: {camera_arg}")
    
    # Check if export directory exists, create if it doesn't
    if not os.path.exists(EXPORT_DIR):
        debug_log(f"🐛 ⚠️ Export directory does not exist, creating: {EXPORT_DIR}")
        try:
            os.makedirs(EXPORT_DIR, exist_ok=True)
            debug_log(f"🐛 ✅ Created export directory: {EXPORT_DIR}")
        except Exception as e:
            debug_log(f"🐛 ❌ Failed to create export directory: {e}")
            raise Exception(f"Failed to create export directory: {EXPORT_DIR}")
    
    expected_filename_prefix = f"{camera_arg}.{datetime.now().strftime('%Y%m%d')}_"
    debug_log(f"🐛 Expected filename prefix: {expected_filename_prefix}")
    
    timeout = time.time() + 60  # Increased to 60 seconds for export processing
    debug_log(f"🐛 Timeout at: {datetime.fromtimestamp(timeout)}")
    
    attempt = 0
    while time.time() < timeout:
        attempt += 1
        debug_log(f"🐛 File check attempt #{attempt}")
        
        try:
            all_files = os.listdir(EXPORT_DIR)
            debug_log(f"🐛 Found {len(all_files)} total files in directory")
            
            matching_files = [
                f for f in all_files
                if f.startswith(expected_filename_prefix) and f.endswith(".mp4")
            ]
            debug_log(f"🐛 Found {len(matching_files)} matching files: {matching_files}")
            
            if matching_files:
                latest_file = max(
                    matching_files,
                    key=lambda x: os.path.getctime(os.path.join(EXPORT_DIR, x))
                )
                full_path = os.path.join(EXPORT_DIR, latest_file)
                
                # Check if file is still being written (size changing)
                debug_log(f"🐛 Checking if file is complete: {latest_file}")
                initial_size = os.path.getsize(full_path)
                time.sleep(2)  # Wait 2 seconds
                final_size = os.path.getsize(full_path)
                
                if initial_size == final_size and final_size > 0:
                    debug_log(f"🐛 ✅ Found complete file: {latest_file}")
                    debug_log(f"🐛 Full path: {full_path}")
                    debug_log(f"🐛 File size: {final_size} bytes")
                    return full_path
                else:
                    debug_log(f"🐛 ⚠️ File still being written: {initial_size} -> {final_size} bytes")
                
        except Exception as e:
            debug_log(f"🐛 ⚠️ Error checking for files: {e}")
        
        remaining_time = int(timeout - time.time())
        debug_log(f"🐛 Waiting 3 seconds... ({remaining_time}s remaining)")
        time.sleep(3)
    
    debug_log("🐛 ❌ File wait timeout reached")
    # List all files in directory for debugging
    try:
        all_files = os.listdir(EXPORT_DIR)
        debug_log(f"🐛 Final directory contents: {all_files}")
    except:
        debug_log("🐛 Could not list directory contents")
    
    raise Exception("❌ Failed to locate exported .mp4 within timeout")

def send_webhook(mp4_path, gif_path=None):
    """Send files to n8n webhook"""
    global camera_arg, timestamp_arg
    
    debug_log("🐛 Starting webhook send")
    debug_log(f"🐛 MP4 path: {mp4_path}")
    debug_log(f"🐛 GIF path: {gif_path}")
    debug_log(f"🐛 Webhook URL: {WEBHOOK_URL}")
    
    try:
        files = {}
        data = {"camera": camera_arg, "timestamp": timestamp_arg}
        debug_log(f"🐛 Webhook data: {data}")
        
        # Always send MP4
        debug_log(f"🐛 MP4 file size: {os.path.getsize(mp4_path)} bytes")
        with open(mp4_path, "rb") as f:
            files["clip"] = f
            
            # Optionally send GIF if it exists
            if gif_path and os.path.exists(gif_path):
                debug_log(f"🐛 Including GIF file, size: {os.path.getsize(gif_path)} bytes")
                with open(gif_path, "rb") as gif_f:
                    files["gif"] = gif_f
                    data["has_gif"] = "true"
                    
                    debug_log("🐛 Sending webhook with both MP4 and GIF...")
                    resp = requests.post(
                        WEBHOOK_URL,
                        files=files,
                        data=data,
                        headers=AUTH_HEADER
                    )
            else:
                debug_log("🐛 Sending webhook with MP4 only...")
                resp = requests.post(
                    WEBHOOK_URL,
                    files=files,
                    data=data,
                    headers=AUTH_HEADER
                )
        
        debug_log(f"🐛 Webhook response: {resp.status_code}")
        debug_log(f"🐛 Webhook response text: {resp.text}")
        
        log(f"📨 Files sent to n8n: {resp.status_code} - {resp.text}")
        return resp
        
    except Exception as e:
        debug_log(f"🐛 ❌ Webhook exception: {e}")
        log(f"❌ Webhook failed: {e}")
        raise

def main():
    global camera_arg, timestamp_arg, clip_name_arg
    
    debug_log("🐛 ========== MAIN FUNCTION START ==========")
    debug_log(f"🐛 Python version: {sys.version}")
    debug_log(f"🐛 Script arguments: {sys.argv}")
    debug_log(f"🐛 Current working directory: {os.getcwd()}")
    debug_log(f"🐛 Debug mode: {debugging}")
    
    if not debugging:
        if len(sys.argv) < 4:
            log("❌ Not enough args: expecting clip name, camera name, and timestamp")
            debug_log("🐛 ❌ Insufficient arguments provided")
            sys.exit(1)

        clip_name_arg = sys.argv[1]
        camera_arg = sys.argv[2]
        timestamp_arg = sys.argv[3]
        debug_log(f"🐛 Arguments from command line: {clip_name_arg}, {camera_arg}, {timestamp_arg}")
    else:
        debug_log("🐛 Using debug mode placeholder arguments")
    
    log(f"📩 Received alert:\n ├─ Clip: {clip_name_arg}\n ├─ Camera: {camera_arg}\n └─ Timestamp: {timestamp_arg}")

    try:
        debug_log("🐛 Starting login...")
        session = login()
        log(f"✅ Logged in: {session}")

        # Try to use provided clip first, with fallback to cliplist
        clip = None
        used_fallback = False
        
        if clip_name_arg != "@-1":
            debug_log("🐛 Attempting to use provided clip path directly")
            # Try the provided clip first
            test_clip = {
                "path": clip_name_arg,
                "camera": camera_arg,
                "msec": 0  # Duration unknown unless retrieved later
            }
            
            debug_log("🐛 Testing export with provided clip...")
            test_export = export_clip(session, test_clip["path"], test_clip["msec"])
            
            if test_export.get("result") == "success":
                debug_log("🐛 ✅ Provided clip export successful")
                clip = test_clip
                log(f"✅ Using provided clip path: {clip_name_arg}")
            else:
                debug_log(f"🐛 ❌ Provided clip export failed: {test_export}")
                debug_log("🐛 Falling back to cliplist search...")
                used_fallback = True
        else:
            debug_log("🐛 Clip name is @-1, using cliplist method directly")
            used_fallback = True
        
        # Use cliplist fallback if needed
        if used_fallback or clip is None:
            debug_log("🐛 Using cliplist fallback method")
            try:
                clip = get_clip_from_cliplist(session, camera_arg)
                log("🔁 Used cliplist fallback to find recent clip")
            except Exception as e:
                debug_log(f"🐛 ❌ Cliplist fallback also failed: {e}")
                raise Exception(f"Both direct clip access and cliplist fallback failed. Direct: {test_export if 'test_export' in locals() else 'N/A'}, Cliplist: {e}")

        clip_path = clip["path"]
        clip_msec = int(clip["msec"])
        debug_log(f"🐛 Final clip details: path={clip_path}, msec={clip_msec}")
        log(f"📸 Final clip: {clip_path} ({clip_msec}ms)")

        # Always export the final clip (the test export above was just for validation)
        debug_log("🐛 Starting export with final clip...")
        exp_resp = export_clip(session, clip_path, clip_msec)
        
        if exp_resp.get("result") != "success":
            debug_log(f"🐛 ❌ Final export failed: {exp_resp}")
            raise Exception(f"Export failed: {exp_resp.get('data', {}).get('status', 'Unknown error')}")
        
        log(f"📤 Export started: {exp_resp}")
        
        # Wait for exported file
        debug_log("🐛 Waiting for exported file...")
        exported_mp4_path = wait_for_exported_file()
        log(f"✅ Found exported file: {exported_mp4_path}")
        
        # Create GIF with proper naming format
        gif_filename = f"{camera_arg}_{datetime.now().strftime('%m%d%y_%H%M%S')}.gif"
        gif_path = os.path.join(GIF_SAVE_DIR, gif_filename)
        debug_log(f"🐛 GIF will be saved as: {gif_path}")
        
        log("🎬 Converting MP4 to GIF...")
        converted_gif_path = convert_mp4_to_gif(exported_mp4_path, gif_path)
        
        # Send webhook
        debug_log("🐛 Sending webhook...")
        send_webhook(exported_mp4_path, converted_gif_path)
        
        log("✅ Process completed successfully!")
        debug_log("🐛 ========== MAIN FUNCTION END ==========")

    except Exception as e:
        debug_log(f"🐛 ❌ Main function exception: {e}")
        log(f"❌ Failed: {e}")
        sys.exit(1)

if __name__ == "__main__":
    debug_log("🐛 ========== SCRIPT EXECUTION START ==========")
    main()