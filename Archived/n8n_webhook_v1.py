import requests
import os
import time
from datetime import datetime

# === CONFIG ===
GIF_SAVE_DIR = r"C:\bi_alerts"
WEBHOOK_URL = "https://n8n.tsmithit.net/webhook-test/blue-iris-alert"
LOG_PATH = r"C:\scripts\event_summary_log.txt"
AUTH_HEADER = {}

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

def send_webhook_test(gif_path):
    """Send GIF and test metadata to n8n webhook"""
    debug_log("🐛 Starting webhook test")
    debug_log(f"🐛 GIF path: {gif_path}")
    debug_log(f"🐛 Webhook URL: {WEBHOOK_URL}")
    
    max_retries = 3
    timeout_seconds = 30
    
    for attempt in range(max_retries):
        try:
            debug_log(f"🐛 Webhook attempt {attempt + 1}/{max_retries}")
            
            files = {}
            data = {"camera": test_camera, "timestamp": test_timestamp}
            debug_log(f"🐛 Webhook data: {data}")
            
            if gif_path and os.path.exists(gif_path):
                gif_size = os.path.getsize(gif_path)
                debug_log(f"🐛 Including GIF file, size: {gif_size} bytes ({gif_size/1024/1024:.1f}MB)")
                
                with open(gif_path, "rb") as gif_f:
                    files["gif"] = gif_f
                    data["has_gif"] = "true"
                    
                    debug_log("🐛 Sending webhook with GIF and test metadata...")
                    resp = requests.post(
                        WEBHOOK_URL,
                        files=files,
                        data=data,
                        headers=AUTH_HEADER,
                        timeout=timeout_seconds
                    )
            else:
                debug_log("🐛 ❌ GIF file doesn't exist!")
                return None
            
            debug_log(f"🐛 Webhook response: {resp.status_code}")
            debug_log(f"🐛 Webhook response text: {resp.text}")
            
            log(f"📨 Test data sent to n8n: {resp.status_code} - {resp.text}")
            return resp
            
        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as e:
            debug_log(f"🐛 ❌ Webhook attempt {attempt + 1} failed: {e}")
            if attempt < max_retries - 1:
                wait_time = (attempt + 1) * 2  # 2, 4, 6 seconds
                debug_log(f"🐛 Retrying in {wait_time} seconds...")
                time.sleep(wait_time)
            else:
                debug_log("🐛 ❌ All webhook attempts failed")
                log(f"❌ Webhook test failed after {max_retries} attempts: {e}")
                raise
        except Exception as e:
            debug_log(f"🐛 ❌ Webhook exception: {e}")
            log(f"❌ Webhook test failed: {e}")
            raise

def main():
    debug_log("🐛 ========== GIF WEBHOOK TEST START ==========")
    log("🧪 Starting GIF webhook test...")
    
    try:
        # Find most recent GIF
        gif_path = find_most_recent_gif()
        
        # Send webhook
        debug_log("🐛 Sending test webhook...")
        send_webhook_test(gif_path)
        
        log("✅ GIF webhook test completed successfully!")
        debug_log("🐛 ========== GIF WEBHOOK TEST END ==========")
        
    except Exception as e:
        debug_log(f"🐛 ❌ Test failed: {e}")
        log(f"❌ GIF webhook test failed: {e}")

if __name__ == "__main__":
    main()