# alert_service.py - A long-running service to handle Blue Iris alerts.
import os
import sys
import time
from pathlib import Path
from datetime import datetime
from flask import Flask, request, jsonify
from dotenv import load_dotenv
import requests

# Add modules directory to Python path for imports
sys.path.insert(0, str(Path(__file__).parent.resolve()))

from api_clients import (
    BlueIrisAPI, BlueIrisConfig,
    MinioStorage, MinioConfig,
    WebhookNotifier, WebhookConfig,
    CodeProjectAIClient, CodeProjectAIConfig
)
from alert_helper import (
    OnePasswordHelper, VideoProcessor, FileWaiter,
    SessionValidator, Logger, AlertConfiguration
)
from database_helper import DatabaseLogger, DatabaseConfig

class AlertServiceHandler:
    """
    A long-running handler for Blue Iris alerts, designed to be used with Flask.
    """
    def __init__(self):
        self.config = AlertConfiguration()
        self._setup_logging()
        self._load_and_setup_clients()

    def _setup_logging(self):
        log_dir = Path(__file__).parent / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        today = datetime.now().strftime("%Y-%m-%d")
        log_path = log_dir / f"alert_service_log_{today}.txt"
        self.logger = Logger(log_path, debug_enabled=True)
        self.logger.log("✅ Alert service handler initialized.")

    def _load_and_setup_clients(self):
        try:
            self.logger.log("🤫 Loading secrets and setting up API clients...")
            secrets = self._load_secrets()

            self.bi_client = BlueIrisAPI(BlueIrisConfig(host=secrets['bi_host'], username=secrets['bi_user'], password=secrets['bi_pass']), debug_log=self.logger.debug)
            self.storage_client = MinioStorage(MinioConfig(endpoint=secrets['minio_endpoint'], access_key=secrets['minio_access_key'], secret_key=secrets['minio_secret_key'], bucket="bialerts", secure=True), debug_log=self.logger.debug, log=self.logger.log)
            self.notifier_client = WebhookNotifier(WebhookConfig(url=secrets['webhook_url'], headers={"Authorization": secrets['webhook_auth']}, timeout=30, retries=3), debug_log=self.logger.debug, log=self.logger.log)
            self.ai_client = CodeProjectAIClient(CodeProjectAIConfig(host=secrets['ai_host']), debug_log=self.logger.debug, log=self.logger.log)

            db_config = DatabaseConfig(host=secrets['db_host'], port=int(secrets['db_port']), database=secrets['db_database'], username=secrets['db_username'], password=secrets['db_password'])
            self.db_logger = DatabaseLogger(db_config, debug_log=self.logger.debug, log=self.logger.log)
            self.db_logger.ensure_table_exists()

            self.logger.log("✅ All API clients initialized successfully.")
            self._handle_session_management() # Initial login
        except Exception as e:
            self.logger.log(f"❌ FATAL: Failed to initialize API clients: {e}")
            self.bi_client = self.storage_client = self.notifier_client = self.db_logger = self.ai_client = None

    def _load_secrets(self):
        secrets = OnePasswordHelper.get_item_json("SecretsMGMT", "bi_alert_handler_secrets")
        return {k: OnePasswordHelper.get_field(secrets, v) for k, v in {
            'bi_host': "BI_HOST", 'bi_user': "BI_USER", 'bi_pass': "BI_PASS",
            'minio_endpoint': "MINIO_ENDPOINT", 'minio_access_key': "MINIO_ACCESS_KEY", 'minio_secret_key': "MINIO_SECRET_KEY",
            'webhook_url': "N8N_WEBHOOK_URL", 'webhook_auth': "N8N_AUTH_HEADER",
            'db_host': "DB_HOST", 'db_database': "DB_DATABASE", 'db_username': "DB_USERNAME", 'db_password': "DB_PASSWORD",
            'ai_host': "CODEPROJECT_AI_HOST"
        }.items()} | {'db_port': OnePasswordHelper.get_field(secrets, "DB_PORT", "5432")}

    def _handle_session_management(self):
        try:
            if self.bi_client.cfg.session and self.bi_client.test_session():
                self.logger.log("🔄 Blue Iris session is still valid.")
                return
        except Exception as e:
            self.logger.log(f"⚠️ Session check failed: {e}. Attempting to re-login.")
        self.logger.log("♻️ Performing Blue Iris login...")
        session = self.bi_client.login()
        self.logger.log(f"✅ Logged in with new session: {session}")

    def process_alert(self, alert_data):
        camera = alert_data.get("camera")
        timestamp = alert_data.get("timestamp", datetime.now().strftime("%I:%M:%S %p"))
        alert_handle = alert_data.get("alert_handle", "@-1")

        if not camera: raise ValueError("Webhook data must include a 'camera' field.")
        self.logger.log(f"📩 Received alert: Camera={camera}, Timestamp={timestamp}, Handle={alert_handle}")

        try:
            self._handle_session_management()
            alert_clip = self._get_alert_clip(camera, alert_handle)
            exported_mp4 = self._export_video(alert_clip)

            # --- AI Intelligence Step ---
            jpeg_dir = os.path.join(self.config.GIF_SAVE_DIR, "frames")
            jpeg_path = VideoProcessor.extract_midframe_jpeg(exported_mp4, jpeg_dir, camera, log_func=self.logger.log)
            if not jpeg_path:
                raise Exception("Failed to extract JPEG frame for AI analysis.")

            self.logger.log(f"🤖 Sending frame to CodeProject.AI for analysis...")
            predictions = self.ai_client.detect_objects(jpeg_path)

            # Check for persons
            persons = [p for p in predictions if p.get("label") == "person" and p.get("confidence", 0) > 0.6]
            if not persons:
                self.logger.log(f"✅ AI analysis complete. No person detected with sufficient confidence. Ignoring alert.")
                # Optionally, log ignored alerts to the database with a specific status
                return # Stop processing

            self.logger.log(f"✅ Person detected! Confidence: {[p['confidence'] for p in persons]}. Proceeding with alert.")

            # --- Continue with normal processing ---
            gif_path = self._process_gif(exported_mp4, camera)
            self._upload_and_notify_and_log(gif_path, jpeg_path, camera, timestamp, alert_handle)
            self._finalize(exported_mp4, gif_path, jpeg_path)

        except Exception as e:
            self.logger.log(f"❌ Processing failed for camera {camera}: {e}")
            if self.db_logger:
                self.db_logger.log_alert(camera=camera, timestamp=timestamp, alert_handle=alert_handle, success=False, error_message=str(e))
            raise

    def _get_alert_clip(self, camera, alert_handle):
        if alert_handle != "@-1":
            data = self.bi_client.clipstats(alert_handle)
            if data.get("path"):
                self.logger.log(f"✅ Using provided alert handle: {alert_handle}")
                return {"path": data["path"], "camera": camera, "offset": data.get("triggeroffset", 0), "msec": data.get("alertmsec", 0)}
        self.logger.log("🔁 Using alertlist fallback to find recent AI-filtered alert")
        return self.bi_client.get_recent_ai_alert(camera=camera, lookback_seconds=self.config.ALERT_SEARCH_TIME)

    def _export_video(self, alert_clip):
        path, offset, msec = alert_clip["path"], int(alert_clip.get("offset", 0)), int(alert_clip.get("msec", 0))
        self.logger.log(f"📸 Final alert clip: {path} (Starts {offset}ms for {msec}ms)")
        export_msec = self.config.get_export_duration(msec)
        exp_resp = self.bi_client.export(path=path, startms=offset, msec=export_msec)
        if exp_resp.get("result") != "success": raise Exception(f"Export failed: {exp_resp.get('data', {}).get('status', 'Unknown error')}")
        self.logger.log("📤 Export started")
        return FileWaiter.wait_for_exported_file(exp_resp, self.config.EXPORT_DIR, log_func=self.logger.log)

    def _process_gif(self, mp4_path, camera):
        gif_path = os.path.join(self.config.GIF_SAVE_DIR, self.config.get_gif_filename(camera))
        self.logger.log("🎬 Converting MP4 to GIF...")
        gif = VideoProcessor.convert_mp4_to_gif(mp4_path, gif_path, self.config.GIF_DURATION_SECONDS, self.config.GIF_FPS, log_func=self.logger.log)
        if not gif: raise Exception("GIF conversion failed")
        return gif

    def _upload_and_notify_and_log(self, gif_path, jpeg_path, camera, timestamp, alert_handle):
        self.logger.log("📤 Uploading GIF to MinIO...")
        gif_url = self.storage_client.upload_file(gif_path, object_prefix="alerts")
        jpeg_urls = [self.storage_client.upload_file(jpeg_path, object_prefix="alert_frames")] if jpeg_path else []

        self.logger.log("📨 Sending webhook...")
        self.notifier_client.send_alert(camera=camera, timestamp=timestamp, gif_url=gif_url, jpeg_urls=jpeg_urls or None)

        if self.db_logger:
            self.logger.log("✍️ Logging alert to database...")
            self.db_logger.log_alert(camera=camera, timestamp=timestamp, alert_handle=alert_handle, gif_url=gif_url, jpeg_urls=jpeg_urls, success=True)
            try:
                requests.post("http://localhost:5050/api/notify", timeout=5)
                self.logger.log("✅ Notified web UI of new alert.")
            except Exception as e:
                self.logger.log(f"⚠️ Could not notify web UI: {e}")

    def _finalize(self, mp4_path, gif_path, jpeg_path):
        self.logger.log("✅ Process completed")
        try:
            if os.path.exists(mp4_path): os.remove(mp4_path)
            self.logger.log("🧹 Cleaned up local exported files.")
        except Exception as e:
            self.logger.log(f"⚠️ Could not clean up files: {e}")

# --- Flask App ---
app = Flask(__name__)
load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), ".env"))
handler = AlertServiceHandler()

@app.route('/webhook', methods=['POST'])
def webhook():
    if not handler.ai_client: return jsonify({"error": "Service is not properly configured. Check logs."}), 503
    data = request.json
    if not data: return jsonify({"error": "Invalid JSON payload"}), 400
    try:
        handler.process_alert(data)
        return jsonify({"status": "success"}), 200
    except Exception as e:
        handler.logger.log(f"❌ Unhandled error in webhook: {e}")
        return jsonify({"error": "Internal server error"}), 500

if __name__ == '__main__':
    port = int(os.environ.get("ALERT_SERVICE_PORT", 5051))
    print(f"🚀 Starting Alert Handler Service on http://0.0.0.0:{port}")
    # Use waitress or gunicorn in production
    app.run(host='0.0.0.0', port=port, debug=True)
