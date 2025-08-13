import requests
import hashlib
import time
import sys
import os
from datetime import datetime
from PIL import Image
import cv2
from minio import Minio
from minio.error import S3Error

# === DEBUG MODE ===
debugging = False

# === AI FILTERING ===
ai_object = "person"
confidence_level = 60

# === CONFIG ===
BI_HOST = "http://127.0.0.1:8191"
BI_USER = "bialert_svc"
BI_PASS = "QWERahrjeykFGHZDFBVREGHSj"
CLIP_DURATION_MS = 60000
LOG_PATH = r"C:\scripts\event_summary_log.txt"
EXPORT_DIR = r"C:\Blue Iris\New\Clipboard"
GIF_SAVE_DIR = r"C:\bi_alerts"
WEBHOOK_URL = "https://n8n.tsmithit.net/webhook/blue-iris-alert"
AUTH_HEADER = {
    "Authorization": "Basic d2ViaG9vazpNaWxuZXItU21hbGxlci0xNDI="
}

# === MINIO CONFIG ===
MINIO_ENDPOINT = "minio.tsmithit.net"
MINIO_ACCESS_KEY = "6MJ0YHHLAMEMNPC50TYW"
MINIO_SECRET_KEY = "vQBxNdSQWR3N3wHb99dm10oMHYEkUR5PsF5d4cKZ"
MINIO_BUCKET = "bialerts"
MINIO_SECURE = True

# === GLOBAL VARIABLES ===
camera_arg = None
timestamp_arg = None
alert_name_arg = None
alert_search_time = 60  # Default for production

if debugging:
    # Debug mode - use placeholder values
    camera_arg = "FrontYardDW"
    timestamp_arg = datetime.now().strftime("%I:%M:%S %p")
    alert_name_arg = "@1557417957.bvr"
    alert_search_time = 17400
    print("🐛 DEBUG MODE ENABLED - Using placeholder arguments")
    print(f"🐛 Placeholder args: alert={alert_name_arg}, camera={camera_arg}, timestamp={timestamp_arg}")

    

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

def parse_memo_for_ai_detection(memo, target_object, min_confidence):
    """Parse Blue Iris memo field for AI detection confidence"""
    debug_log(f"🐛 Parsing memo: {memo}")
    debug_log(f"🐛 Looking for object: {target_object} with confidence >= {min_confidence}%")
    
    if not memo:
        debug_log("🐛 No memo found")
        return False, 0
    
    try:
        # Look for pattern like "person:87%" in the memo
        import re
        pattern = rf"{target_object}:(\d+)%"
        match = re.search(pattern, memo, re.IGNORECASE)
        
        if match:
            confidence = int(match.group(1))
            debug_log(f"🐛 Found {target_object} with {confidence}% confidence")
            
            if confidence >= min_confidence:
                debug_log(f"🐛 ✅ Confidence {confidence}% meets minimum {min_confidence}%")
                return True, confidence
            else:
                debug_log(f"🐛 ❌ Confidence {confidence}% below minimum {min_confidence}%")
                return False, confidence
        else:
            debug_log(f"🐛 ❌ No {target_object} detection found in memo")
            return False, 0
            
    except Exception as e:
        debug_log(f"🐛 ❌ Error parsing memo: {e}")
        return False, 0

def get_alert_from_alertlist(session, camera):
    debug_log(f"🐛 Getting alert list for camera: {camera}")
    debug_log(f"🐛 Using session: {session}")
    debug_log(f"🐛 AI Filter: {ai_object} >= {confidence_level}%")
    
    # Get alerts from the last alert_search_time seconds
    start_date = int(time.time()) - alert_search_time
    debug_log(f"🐛 Start date: {start_date} (last {alert_search_time} seconds)")
    debug_log(f"🐛 Start date readable: {datetime.fromtimestamp(start_date).strftime('%Y-%m-%d %H:%M:%S')}")
    
    try:
        r = requests.post(f"{BI_HOST}/json", json={
            "cmd": "alertlist",
            "session": session,
            "camera": camera,
            "startdate": start_date
        })
        debug_log(f"🐛 Alertlist response: {r.status_code}")
        debug_log(f"🐛 Alertlist content: {r.text}")
        
        response_data = r.json()
        if response_data.get("result") != "success":
            debug_log(f"🐛 ❌ Alertlist failed: {response_data}")
            raise Exception(f"Alertlist failed: {response_data}")
        
        alerts = response_data.get("data", [])
        debug_log(f"🐛 Found {len(alerts)} total alerts in the last 60 seconds")
        
        if not alerts:
            debug_log("🐛 No alerts found!")
            raise Exception(f"No alerts found for camera {camera} in the last {alert_search_time} seconds")
        
        # Filter alerts for AI detection with sufficient confidence
        valid_alerts = []
        for alert in alerts:
            memo = alert.get("memo", "")
            is_valid, confidence = parse_memo_for_ai_detection(memo, ai_object, confidence_level)
            
            if is_valid:
                alert["ai_confidence"] = confidence  # Store confidence for logging
                valid_alerts.append(alert)
                debug_log(f"🐛 ✅ Valid alert found: {ai_object} at {confidence}%")
            else:
                debug_log(f"🐛 ❌ Skipping alert - insufficient {ai_object} confidence")
        
        debug_log(f"🐛 Found {len(valid_alerts)} alerts matching AI criteria")
        
        if not valid_alerts:
            raise Exception(f"No alerts found with {ai_object} detection >= {confidence_level}% confidence")
        
        # Sort alerts by date (most recent first) to ensure we get the latest alert
        valid_alerts.sort(key=lambda x: x.get('date', 0), reverse=True)
        debug_log(f"🐛 Sorted alerts by date, most recent first")
        
        # Return most recent valid alert (first in sorted list)
        selected_alert = valid_alerts[0]
        debug_log(f"🐛 Selected most recent alert with date: {selected_alert.get('date', 0)}")
        debug_log(f"🐛 Alert timestamp: {datetime.fromtimestamp(selected_alert.get('date', 0)).strftime('%Y-%m-%d %H:%M:%S')}")
        debug_log(f"🐛 Using most recent valid alert: {selected_alert}")
        
        # Convert alert to clip format for compatibility - IMPORTANT: Use 'path' not 'clip'
        alert_clip = {
            "path": selected_alert.get("clip", ""),  # This is the ALERT segment, not the full clip
            "camera": selected_alert.get("camera", camera),
            "offset": selected_alert.get("offset", 0), #offset of the alert inside the 'clip'
            "msec": selected_alert.get("msec", 0),   # Duration of the alert segment
            "date": selected_alert.get("date", 0),
            "ai_confidence": selected_alert.get("ai_confidence", 0)
        }
        debug_log(f"🐛 Alert segment path: {alert_clip['path']}")
        debug_log(f"🐛 Alert segment offset: {alert_clip['offset']}")
        debug_log(f"🐛 Alert segment duration: {alert_clip['msec']}ms")
        debug_log(f"🐛 Full clip would be: {selected_alert.get('clip', 'N/A')}")
        debug_log(f"🐛 Converted alert to clip format: {alert_clip}")
        
        return alert_clip
        
    except Exception as e:
        debug_log(f"🐛 Alertlist exception: {e}")
        raise

def export_clip(session, path, offset, msec):
    debug_log(f"🐛 Exporting clip: {path}")
    debug_log(f"🐛 Starting at: {offset}ms")
    debug_log(f"🐛 Alert duration: {msec}ms")
    
    # Determine export duration - use alert duration if <= 60 seconds, otherwise use default 10 seconds
    if msec > 0 and msec <= 60000:  # 60 seconds in milliseconds
        export_duration = msec
        debug_log(f"🐛 Using alert duration: {export_duration}ms ({export_duration/1000:.1f} seconds)")
    else:
        export_duration = CLIP_DURATION_MS
        debug_log(f"🐛 Alert duration too long or invalid, using default: {export_duration}ms")
    
    # startms = msec - export_duration if msec > export_duration else 0 ##COmmenting out for testing
    startms = offset
    debug_log(f"🐛 Start ms: {startms}, Duration: {export_duration}")
    
    try:
        r = requests.post(f"{BI_HOST}/json", json={
            "cmd": "export",
            "session": session,
            "path": path,
            "startms": startms,
            "msec": export_duration
            # "timelapse": "3.0@30.0"
            #"reencode": "false"
        })
        debug_log(f"🐛 Export response: {r.status_code}")
        debug_log(f"🐛 Export content: {r.text}")
        
        return r.json()
        
    except Exception as e:
        debug_log(f"🐛 Export exception: {e}")
        raise

def convert_mp4_to_gif(mp4_path, gif_path, duration_seconds, fps):
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
                if width > 1080:
                    new_width = 1080
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

def wait_for_exported_file(export_response):
    """Wait for the specific exported MP4 file from the export response"""
    debug_log("🐛 Starting file wait process using export response")
    debug_log(f"🐛 Export response: {export_response}")
    
    # Extract the URI from the export response
    uri = export_response.get("data", {}).get("uri", "")
    if not uri:
        debug_log("🐛 ❌ No URI found in export response")
        raise Exception("No URI found in export response")
    
    # The URI is relative to the export directory
    # Remove leading "Clipboard\" from URI since EXPORT_DIR already includes it
    cleaned_uri = uri.replace("Clipboard\\", "").replace("\\", os.sep)
    expected_file_path = os.path.join(EXPORT_DIR, cleaned_uri)
    debug_log(f"🐛 Expected file path: {expected_file_path}")
    
    # Check if export directory exists, create if it doesn't
    if not os.path.exists(EXPORT_DIR):
        debug_log(f"🐛 ⚠️ Export directory does not exist, creating: {EXPORT_DIR}")
        try:
            os.makedirs(EXPORT_DIR, exist_ok=True)
            debug_log(f"🐛 ✅ Created export directory: {EXPORT_DIR}")
        except Exception as e:
            debug_log(f"🐛 ❌ Failed to create export directory: {e}")
            raise Exception(f"Failed to create export directory: {EXPORT_DIR}")
    
    timeout = time.time() + 60  # 60 seconds for export processing
    debug_log(f"🐛 Timeout at: {datetime.fromtimestamp(timeout)}")
    debug_log(f"🐛 Monitoring specific file: {os.path.basename(expected_file_path)}")
    
    attempt = 0
    while time.time() < timeout:
        attempt += 1
        debug_log(f"🐛 File check attempt #{attempt}")
        
        try:
            if os.path.exists(expected_file_path):
                debug_log(f"🐛 File exists, checking if complete...")
                
                # Check if file is still being written (size changing)
                initial_size = os.path.getsize(expected_file_path)
                time.sleep(2)  # Wait 2 seconds
                final_size = os.path.getsize(expected_file_path)
                
                if initial_size == final_size and final_size > 0:
                    debug_log(f"🐛 ✅ File is complete: {os.path.basename(expected_file_path)}")
                    debug_log(f"🐛 Full path: {expected_file_path}")
                    debug_log(f"🐛 File size: {final_size} bytes")
                    return expected_file_path
                else:
                    debug_log(f"🐛 ⚠️ File still being written: {initial_size} -> {final_size} bytes")
            else:
                debug_log(f"🐛 File not found yet: {os.path.basename(expected_file_path)}")
                
        except Exception as e:
            debug_log(f"🐛 ⚠️ Error checking for file: {e}")
        
        remaining_time = int(timeout - time.time())
        debug_log(f"🐛 Waiting 3 seconds... ({remaining_time}s remaining)")
        time.sleep(3)
    
    debug_log("🐛 ❌ File wait timeout reached")
    debug_log(f"🐛 Expected file: {expected_file_path}")
    
    # List directory contents for debugging
    try:
        if os.path.exists(EXPORT_DIR):
            all_files = os.listdir(EXPORT_DIR)
            debug_log(f"🐛 Directory contents: {all_files}")
    except:
        debug_log("🐛 Could not list directory contents")
    
    raise Exception(f"❌ Failed to locate exported file: {os.path.basename(expected_file_path)}")

def upload_to_minio(file_path, object_prefix="alerts"):
    """Upload file to MinIO and return the URL"""
    debug_log(f"🐛 Starting MinIO upload for: {file_path}")
    debug_log(f"🐛 MinIO endpoint: {MINIO_ENDPOINT}")
    debug_log(f"🐛 MinIO bucket: {MINIO_BUCKET}")
    
    try:
        # Initialize MinIO client
        debug_log("🐛 Initializing MinIO client...")
        client = Minio(
            MINIO_ENDPOINT,
            access_key=MINIO_ACCESS_KEY,
            secret_key=MINIO_SECRET_KEY,
            secure=MINIO_SECURE
        )
        
        # Test connection and create bucket if needed
        debug_log("🐛 Testing MinIO connection...")
        if not client.bucket_exists(MINIO_BUCKET):
            debug_log(f"🐛 Creating bucket '{MINIO_BUCKET}'...")
            client.make_bucket(MINIO_BUCKET)
            debug_log(f"🐛 ✅ Created bucket '{MINIO_BUCKET}'")
        else:
            debug_log(f"🐛 ✅ Bucket '{MINIO_BUCKET}' exists")
        
        # Generate object name
        original_filename = os.path.basename(file_path)
        object_name = f"{object_prefix}/{original_filename}"
        
        file_size = os.path.getsize(file_path)
        file_ext = os.path.splitext(file_path)[1].lower()
        
        # Set content type based on file extension
        content_type_map = {
            '.gif': 'image/gif',
            '.mp4': 'video/mp4',
            '.avi': 'video/avi',
            '.mov': 'video/quicktime'
        }
        content_type = content_type_map.get(file_ext, 'application/octet-stream')
        
        debug_log(f"🐛 Uploading {original_filename} ({file_size} bytes) to MinIO...")
        debug_log(f"🐛 Object name: {object_name}")
        debug_log(f"🐛 Content type: {content_type}")
        
        # Upload file
        result = client.fput_object(
            MINIO_BUCKET,
            object_name,
            file_path,
            content_type=content_type
        )
        
        debug_log(f"🐛 ✅ MinIO upload successful!")
        debug_log(f"🐛 Object name: {result.object_name}")
        debug_log(f"🐛 ETag: {result.etag}")
        
        # Generate MinIO URL
        minio_url = f"{'https' if MINIO_SECURE else 'http'}://{MINIO_ENDPOINT}/{MINIO_BUCKET}/{object_name}"
        debug_log(f"🐛 MinIO URL: {minio_url}")
        
        log(f"✅ Uploaded to MinIO: {object_name} ({file_size} bytes)")
        return minio_url
        
    except S3Error as e:
        debug_log(f"🐛 ❌ MinIO S3 Error: {e}")
        log(f"❌ MinIO upload failed (S3): {e}")
        raise
    except Exception as e:
        debug_log(f"🐛 ❌ MinIO upload failed: {e}")
        log(f"❌ MinIO upload failed: {e}")
        raise

    

def send_webhook(gif_minio_url, ai_review_gif_url=None):
    """Send webhook with MinIO URL - n8n handles the rest"""
    global camera_arg, timestamp_arg
    
    debug_log("🐛 Starting webhook send with MinIO URL")
    debug_log(f"🐛 Main GIF MinIO URL: {gif_minio_url}")
    debug_log(f"🐛 AI Review GIF MinIO URL: {ai_review_gif_url}")
    debug_log(f"🐛 Webhook URL: {WEBHOOK_URL}")
    
    max_retries = 3
    timeout_seconds = 30
    
    for attempt in range(max_retries):
        try:
            debug_log(f"🐛 Webhook attempt {attempt + 1}/{max_retries}")
            
            data = {
                "camera": camera_arg,
                "timestamp": timestamp_arg,
                "has_gif": "true",
                "minio_url": gif_minio_url,  # Keep original field name for compatibility
                "gif_source": "minio"
            }
            
            # Add AI review GIF if available
            if ai_review_gif_url:
                data["ai_review_gif_url"] = ai_review_gif_url
                data["has_ai_review_gif"] = "true"
            
            debug_log(f"🐛 Webhook data: {data}")
            
            debug_log("🐛 Sending webhook with MinIO URL...")
            resp = requests.post(
                WEBHOOK_URL,
                data=data,
                headers=AUTH_HEADER,
                timeout=timeout_seconds
            )
            
            debug_log(f"🐛 Webhook response: {resp.status_code}")
            debug_log(f"🐛 Webhook response text: {resp.text}")
            
            log(f"📨 Webhook sent successfully: {resp.status_code} - {resp.text}")
            return resp
            
        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as e:
            debug_log(f"🐛 ❌ Webhook attempt {attempt + 1} failed: {e}")
            if attempt < max_retries - 1:
                wait_time = (attempt + 1) * 2  # 2, 4, 6 seconds
                debug_log(f"🐛 Retrying in {wait_time} seconds...")
                time.sleep(wait_time)
            else:
                debug_log("🐛 ❌ All webhook attempts failed")
                log(f"❌ Webhook failed after {max_retries} attempts: {e}")
                raise
        except Exception as e:
            debug_log(f"🐛 ❌ Webhook exception: {e}")
            log(f"❌ Webhook failed: {e}")
            raise

def main():
    global camera_arg, timestamp_arg, alert_name_arg
    
    debug_log("🐛 ========== MAIN FUNCTION START ==========")
    debug_log(f"🐛 Python version: {sys.version}")
    debug_log(f"🐛 Script arguments: {sys.argv}")
    debug_log(f"🐛 Current working directory: {os.getcwd()}")
    debug_log(f"🐛 Debug mode: {debugging}")
    
    if not debugging:
        if len(sys.argv) < 4:
            log("❌ Not enough args: expecting alert handle, camera name, and timestamp")
            debug_log("🐛 ❌ Insufficient arguments provided")
            sys.exit(1)
        alert_name_arg = sys.argv[1]
        camera_arg = sys.argv[2]
        timestamp_arg = sys.argv[3]
        debug_log(f"🐛 Arguments from command line: {alert_name_arg}, {camera_arg}, {timestamp_arg}")
    else:
        debug_log("🐛 Using debug mode placeholder arguments")
    
    log(f"📩 Received alert:\n ├─ Alert Handle: {alert_name_arg}\n ├─ Camera: {camera_arg}\n └─ Timestamp: {timestamp_arg}")

    try:
        debug_log("🐛 Starting login...")
        session = login()
        log(f"✅ Logged in: {session}")

        # Try to use provided alert first, with fallback to alertlist
        alert_clip = None
        used_fallback = False
        
        if alert_name_arg != "@-1":
            debug_log("🐛 Attempting to use provided alert handle directly")

            # Get stats from provided clip
            cliptest = requests.post(f"{BI_HOST}/json", json={
                "cmd": "clipstats",
                "session": session,
                "path": alert_name_arg
            })
            debug_log(f"🐛 Provided @ClipTest Check: {cliptest.status_code}")
            debug_log(f"🐛 Provided Clip content: {cliptest.text}")

            clip_data = cliptest.json().get("data", {})

            test_alert_clip = {
                "path": clip_data.get("path", ""),
                "camera": camera_arg,
                "offset": clip_data.get("triggeroffset", 0),
                "msec": clip_data.get("alertmsec", 0)
            }

            if test_alert_clip["path"]:
                debug_log("🐛 ✅ Provided alert handle returned valid clip data")
                alert_clip = test_alert_clip
                log(f"✅ Using provided alert handle: {alert_name_arg}")
            else:
                debug_log("🐛 ❌ Provided alert handle did not return valid clip path")
                debug_log("🐛 Falling back to alertlist search...")
                used_fallback = True
        else:
            debug_log("🐛 Alert handle is @-1, using alertlist method directly")
            used_fallback = True
        
        # Use alertlist fallback if needed
        if used_fallback or alert_clip is None:
            debug_log("🐛 Using alertlist fallback method")
            try:
                alert_clip = get_alert_from_alertlist(session, camera_arg)
                log("🔁 Used alertlist fallback to find recent AI-filtered alert (last 60 seconds)")
            except Exception as e:
                debug_log(f"🐛 ❌ Alertlist fallback also failed: {e}")
                raise Exception(f"Both direct alert access and alertlist fallback failed. Direct: {test_export if 'test_export' in locals() else 'N/A'}, Alertlist: {e}")

        alert_path = alert_clip["path"]
        alert_offset = alert_clip["offset"]
        alert_msec = int(alert_clip["msec"])
        debug_log(f"🐛 Final alert details: path={alert_path}, offset={alert_offset}, msec={alert_msec}")
        log(f"📸 Final alert clip: {alert_path} (Starts at {alert_offset}ms) (for {alert_msec}ms)")

        # Always export the final alert clip (the test export above was just for validation)
        debug_log("🐛 Starting export with final alert clip...")
        exp_resp = export_clip(session, alert_path, alert_offset, alert_msec)

        if exp_resp.get("result") != "success":
            debug_log(f"🐛 ❌ Final export failed: {exp_resp}")
            raise Exception(f"Export failed: {exp_resp.get('data', {}).get('status', 'Unknown error')}")

        log(f"📤 Export started: {exp_resp}")
        
        # Wait for exported file using the export response
        debug_log("🐛 Waiting for exported file using export response...")
        exported_mp4_path = wait_for_exported_file(exp_resp)
        
        log(f"✅ Found exported file: {exported_mp4_path}")
        
        # Create GIF with proper naming format
        gif_filename = f"{camera_arg}_{datetime.now().strftime('%m%d%y_%H%M%S')}.gif"
        ai_review_gif_filename = f"{camera_arg}_{datetime.now().strftime('%m%d%y_%H%M%S')}_ai_review.gif"
        gif_path = os.path.join(GIF_SAVE_DIR, gif_filename)
        ai_review_gif_path_target = os.path.join(GIF_SAVE_DIR, ai_review_gif_filename)
        debug_log(f"🐛 Main GIF will be saved as: {gif_path}")
        debug_log(f"🐛 AI Review GIF will be saved as: {ai_review_gif_path_target}")
        
        log("🎬 Converting MP4 to GIF...")
        converted_gif_path = convert_mp4_to_gif(exported_mp4_path, gif_path, 6, 10)
        
        # Create AI review GIF with error handling
        ai_review_gif_path = None
        try:
            ai_review_gif_path = convert_mp4_to_gif(exported_mp4_path, ai_review_gif_path_target, 4, 6)
            if ai_review_gif_path:
                log(f"✅ AI Review GIF created: {os.path.basename(ai_review_gif_path)}")
        except Exception as e:
            debug_log(f"🐛 ⚠️ AI review GIF creation failed: {e}")
            log(f"⚠️ AI review GIF creation failed, continuing with main GIF only: {e}")

        if converted_gif_path:
            # Upload main GIF to MinIO
            debug_log("🐛 Uploading main GIF to MinIO...")
            log("📤 Uploading main GIF to MinIO...")
            gif_minio_url = upload_to_minio(converted_gif_path)
            log(f"✅ Main GIF uploaded to MinIO: {gif_minio_url}")
            
            # Upload AI review GIF if it was created successfully
            ai_review_minio_url = None
            if ai_review_gif_path:
                try:
                    debug_log("🐛 Uploading AI review GIF to MinIO...")
                    log("📤 Uploading AI review GIF to MinIO...")
                    ai_review_minio_url = upload_to_minio(ai_review_gif_path, "ai_review")
                    log(f"✅ AI Review GIF uploaded to MinIO: {ai_review_minio_url}")
                except Exception as e:
                    debug_log(f"🐛 ⚠️ AI review GIF upload failed: {e}")
                    log(f"⚠️ AI review GIF upload failed: {e}")
            
            # Log file sizes if both GIFs exist
            if ai_review_gif_path:
                try:
                    main_size = os.path.getsize(converted_gif_path)
                    ai_size = os.path.getsize(ai_review_gif_path)
                    log(f"📏 File sizes - Main: {main_size:,} bytes, AI Review: {ai_size:,} bytes")
                    log(f"📏 Size reduction: {((main_size - ai_size) / main_size * 100):.1f}%")
                except Exception as e:
                    debug_log(f"🐛 ⚠️ Could not compare file sizes: {e}")
            
            # Send webhook with both URLs
            debug_log("🐛 Sending webhook with MinIO URLs...")
            send_webhook(gif_minio_url, ai_review_minio_url)
            
            log("✅ Process completed successfully!")
            log(f"📊 Summary:")
            log(f"  ├─ MP4 exported: {os.path.basename(exported_mp4_path)}")
            log(f"  ├─ Main GIF created: {os.path.basename(converted_gif_path)}")
            if ai_review_gif_path:
                log(f"  ├─ AI Review GIF created: {os.path.basename(ai_review_gif_path)}")
            log(f"  └─ GIFs uploaded to MinIO and webhook sent")
        else:
            log("❌ GIF conversion failed - cannot proceed with webhook")
            raise Exception("GIF conversion failed")
        
        debug_log("🐛 ========== MAIN FUNCTION END ==========")

    except Exception as e:
        debug_log(f"🐛 ❌ Main function exception: {e}")
        log(f"❌ Failed: {e}")
        sys.exit(1)

if __name__ == "__main__":
    debug_log("🐛 ========== SCRIPT EXECUTION START ==========")
    main()