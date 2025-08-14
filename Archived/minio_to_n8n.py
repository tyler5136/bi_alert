import requests
import os
import time
from datetime import datetime
from minio import Minio
from minio.error import S3Error

# === CONFIG ===
GIF_SAVE_DIR = r"C:\bi_alerts"
WEBHOOK_URL = "https://n8n.tsmithit.net/webhook-test/blue-iris-alert"
LOG_PATH = r"C:\scripts\event_summary_log.txt"
AUTH_HEADER = {}

# === MINIO CONFIG ===
MINIO_ENDPOINT = "minio.tsmithit.net"  # Change to your MinIO server
MINIO_ACCESS_KEY = "6MJ0YHHLAMEMNPC50TYW"
MINIO_SECRET_KEY = "vQBxNdSQWR3N3wHb99dm10oMHYEkUR5PsF5d4cKZ"
MINIO_BUCKET = "bialerts"
MINIO_SECURE = True  # Set to True if using HTTPS

# === TEST VALUES ===
test_camera = "FrontYardDW"
test_timestamp = "2:30:45 PM"

def debug_log(msg):
    """Enhanced logging for debug mode"""
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

def find_most_recent_gif():
    """Find the most recent GIF file in the GIF directory"""
    debug_log("🐛 Starting GIF file search")
    debug_log(f"🐛 Looking in directory: {GIF_SAVE_DIR}")
    
    try:
        if not os.path.exists(GIF_SAVE_DIR):
            debug_log(f"🐛 ❌ GIF directory does not exist: {GIF_SAVE_DIR}")
            raise Exception(f"GIF directory not found: {GIF_SAVE_DIR}")
        
        all_files = os.listdir(GIF_SAVE_DIR)
        debug_log(f"🐛 Found {len(all_files)} total files in directory")
        
        gif_files = [f for f in all_files if f.endswith('.gif')]
        debug_log(f"🐛 Found {len(gif_files)} GIF files: {gif_files}")
        
        if not gif_files:
            debug_log("🐛 ❌ No GIF files found!")
            raise Exception("No GIF files found in directory")
        
        # Find most recent by creation time
        most_recent = max(
            gif_files,
            key=lambda x: os.path.getctime(os.path.join(GIF_SAVE_DIR, x))
        )
        
        full_path = os.path.join(GIF_SAVE_DIR, most_recent)
        file_size = os.path.getsize(full_path)
        creation_time = datetime.fromtimestamp(os.path.getctime(full_path))
        
        debug_log(f"🐛 Most recent GIF: {most_recent}")
        debug_log(f"🐛 Full path: {full_path}")
        debug_log(f"🐛 File size: {file_size} bytes ({file_size/1024/1024:.1f}MB)")
        debug_log(f"🐛 Created: {creation_time}")
        
        log(f"✅ Found most recent GIF: {most_recent} ({file_size} bytes)")
        return full_path
        
    except Exception as e:
        debug_log(f"🐛 ❌ GIF search failed: {e}")
        raise

def upload_gif_to_minio(gif_path):
    """Upload GIF to MinIO and return the URL"""
    debug_log("🐛 Starting MinIO upload")
    debug_log(f"🐛 GIF path: {gif_path}")
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
        
        # Test connection
        debug_log("🐛 Testing MinIO connection...")
        if not client.bucket_exists(MINIO_BUCKET):
            debug_log(f"🐛 Creating bucket '{MINIO_BUCKET}'...")
            client.make_bucket(MINIO_BUCKET)
            debug_log(f"🐛 ✅ Created bucket '{MINIO_BUCKET}'")
        else:
            debug_log(f"🐛 ✅ Bucket '{MINIO_BUCKET}' exists")
        
        # Generate object name from original filename
        original_filename = os.path.basename(gif_path)
        object_name = f"alerts/{original_filename}"
        
        gif_size = os.path.getsize(gif_path)
        debug_log(f"🐛 Uploading {original_filename} ({gif_size} bytes) to MinIO...")
        debug_log(f"🐛 Object name: {object_name}")
        
        # Upload file
        result = client.fput_object(
            MINIO_BUCKET,
            object_name,
            gif_path,
            content_type="image/gif"
        )
        
        debug_log(f"🐛 ✅ MinIO upload successful!")
        debug_log(f"🐛 Object name: {result.object_name}")
        debug_log(f"🐛 ETag: {result.etag}")
        
        # Generate MinIO URL
        minio_url = f"{'https' if MINIO_SECURE else 'http'}://{MINIO_ENDPOINT}/{MINIO_BUCKET}/{object_name}"
        debug_log(f"🐛 MinIO URL: {minio_url}")
        
        log(f"✅ Uploaded to MinIO: {object_name} ({gif_size} bytes)")
        log(f"✅ MinIO URL: {minio_url}")
        
        return minio_url
        
    except S3Error as e:
        debug_log(f"🐛 ❌ MinIO S3 Error: {e}")
        log(f"❌ MinIO upload failed (S3): {e}")
        raise
    except Exception as e:
        debug_log(f"🐛 ❌ MinIO upload failed: {e}")
        log(f"❌ MinIO upload failed: {e}")
        raise

def send_webhook_with_minio_url(minio_url):
    """Send webhook with MinIO URL instead of binary data"""
    debug_log("🐛 Starting webhook send with MinIO URL")
    debug_log(f"🐛 MinIO URL: {minio_url}")
    debug_log(f"🐛 Webhook URL: {WEBHOOK_URL}")
    
    max_retries = 3
    timeout_seconds = 30
    
    for attempt in range(max_retries):
        try:
            debug_log(f"🐛 Webhook attempt {attempt + 1}/{max_retries}")
            
            data = {
                "camera": test_camera, 
                "timestamp": test_timestamp,
                "has_gif": "true",
                "minio_url": minio_url,
                "gif_source": "minio"
            }
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
    debug_log("🐛 ========== MinIO + N8N WEBHOOK TEST START ==========")
    log("🧪 Starting MinIO upload + n8n webhook test...")
    
    try:
        # Step 1: Find most recent GIF
        debug_log("🐛 Step 1: Finding most recent GIF...")
        gif_path = find_most_recent_gif()
        
        # Step 2: Upload to MinIO
        debug_log("🐛 Step 2: Uploading to MinIO...")
        log("📤 Uploading GIF to MinIO...")
        minio_url = upload_gif_to_minio(gif_path)
        
        # Step 3: Wait a moment to ensure upload is complete
        debug_log("🐛 Step 3: Waiting for upload to complete...")
        time.sleep(2)
        
        # Step 4: Send webhook with MinIO URL
        debug_log("🐛 Step 4: Sending webhook with MinIO URL...")
        log("📨 Sending webhook with MinIO URL...")
        send_webhook_with_minio_url(minio_url)
        
        log("✅ MinIO + n8n webhook test completed successfully!")
        debug_log("🐛 ========== MinIO + N8N WEBHOOK TEST END ==========")
        
    except Exception as e:
        debug_log(f"🐛 ❌ Test failed: {e}")
        log(f"❌ MinIO + n8n webhook test failed: {e}")

if __name__ == "__main__":
    main()