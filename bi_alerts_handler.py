# main.py - Refactored version with simple database logging
import sys
import os
from pathlib import Path
from datetime import datetime
from dotenv import load_dotenv

# Local imports
from api_clients import BlueIrisAPI, BlueIrisConfig, MinioStorage, MinioConfig, WebhookNotifier, WebhookConfig
from alert_helper import (
    ArtifactManager, OnePasswordHelper, VideoProcessor, FileWaiter, 
    SessionValidator, Logger, AlertConfiguration
)
from database_helper import DatabaseLogger, DatabaseConfig


class BlueIrisAlertHandler:
    """Main handler class for Blue Iris alerts."""
    
    def __init__(self, debug_mode: bool = False, testing_mode: bool = False):
        self.debug_mode = debug_mode
        self.testing_mode = testing_mode
        self.script_start_time = datetime.now()
        
        # Initialize configuration
        self.config = AlertConfiguration()
        if debug_mode:
            self.config.ALERT_SEARCH_TIME = self.config.DEBUG_ALERT_SEARCH_TIME
        
        # Initialize paths and logging
        self._setup_paths()
        self._setup_logging()
        
        # Initialize artifact manager
        self.artifact_manager = ArtifactManager(self.artifact_path)
        self.artifact = self.artifact_manager.load()
        
        # Initialize API clients (will be set up in main)
        self.bi_client = None
        self.storage_client = None
        self.notifier_client = None
        self.db_logger = None
        
        # Runtime variables
        self.camera_arg = None
        self.timestamp_arg = None
        self.alert_name_arg = None
    
    def _setup_paths(self):
        """Setup file paths."""
        load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), ".env"))
        self.artifact_path = Path(__file__).with_name("artifact.json")
        
        # Use a project-relative path for logs
        log_dir = Path(__file__).parent / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)

        today = datetime.now().strftime("%Y-%m-%d")
        self.log_path = log_dir / f"log{today}.txt"
    
    def _setup_logging(self):
        """Setup logging."""
        self.logger = Logger(self.log_path, self.debug_mode)
        if self.debug_mode:
            self.logger.debug("🐛 ========== SCRIPT EXECUTION START ==========")
            self.logger.log("🐛 DEBUG MODE ENABLED")
    
    def _load_secrets(self):
        """Load secrets from 1Password."""
        try:
            secrets = OnePasswordHelper.get_item_json("SecretsMGMT", "bi_alert_handler_secrets")
            
            return {
                'bi_host': OnePasswordHelper.get_field(secrets, "BI_HOST"),
                'bi_user': OnePasswordHelper.get_field(secrets, "BI_USER"),
                'bi_pass': OnePasswordHelper.get_field(secrets, "BI_PASS"),
                'minio_endpoint': OnePasswordHelper.get_field(secrets, "MINIO_ENDPOINT"),
                'minio_access_key': OnePasswordHelper.get_field(secrets, "MINIO_ACCESS_KEY"),
                'minio_secret_key': OnePasswordHelper.get_field(secrets, "MINIO_SECRET_KEY"),
                'webhook_url': OnePasswordHelper.get_field(secrets, "N8N_WEBHOOK_URL"),
                'webhook_auth': OnePasswordHelper.get_field(secrets, "N8N_AUTH_HEADER"),
                # Database credentials
                'db_host': OnePasswordHelper.get_field(secrets, "DB_HOST"),
                'db_database': OnePasswordHelper.get_field(secrets, "DB_DATABASE"),
                'db_username': OnePasswordHelper.get_field(secrets, "DB_USERNAME"),
                'db_password': OnePasswordHelper.get_field(secrets, "DB_PASSWORD"),
                'db_port': OnePasswordHelper.get_field(secrets, "DB_PORT", "5432"),
            }
        except Exception as e:
            self.logger.log(f"❌ Failed to load secrets: {e}")
            raise
    
    def _setup_api_clients(self, secrets):
        """Initialize API clients with loaded secrets."""
        # Blue Iris client
        bi_config = BlueIrisConfig(
            host=secrets['bi_host'],
            username=secrets['bi_user'],
            password=secrets['bi_pass']
        )
        self.bi_client = BlueIrisAPI(bi_config, debug_log=self.logger.debug)
        
        # MinIO client
        minio_config = MinioConfig(
            endpoint=secrets['minio_endpoint'],
            access_key=secrets['minio_access_key'],
            secret_key=secrets['minio_secret_key'],
            bucket="bialerts",
            secure=True
        )
        self.storage_client = MinioStorage(minio_config, debug_log=self.logger.debug, log=self.logger.log)
        
        # Webhook client
        webhook_config = WebhookConfig(
            url=secrets['webhook_url'],
            headers={"Authorization": secrets['webhook_auth']},
            timeout=30,
            retries=3
        )
        self.notifier_client = WebhookNotifier(webhook_config, debug_log=self.logger.debug, log=self.logger.log)
        
        # Database client (optional - don't crash if database isn't configured)
        try:
            db_config = DatabaseConfig(
                host=secrets['db_host'],
                port=int(secrets['db_port']),
                database=secrets['db_database'],
                username=secrets['db_username'],
                password=secrets['db_password']
            )
            self.db_logger = DatabaseLogger(db_config, debug_log=self.logger.debug, log=self.logger.log)
            self.logger.debug("Database logger initialized")
        except Exception as e:
            self.logger.log(f"⚠️ Database logging disabled: {e}")
            self.db_logger = None
    
    def _parse_arguments(self):
        """Parse command line arguments or use debug/test values."""
        if self.debug_mode:
            # Debug mode - use artifact values
            self.alert_name_arg = self.artifact.get("Alert", "@-1")
            self.camera_arg = self.artifact.get("Camera", "FrontYardDW")
            self.timestamp_arg = self.artifact.get("Timestamp", datetime.now().strftime("%I:%M:%S %p"))
        else:
            # Normal mode - require CLI args
            if len(sys.argv) < 4:
                self.logger.log("❌ Not enough args: expecting alert handle, camera name, and timestamp")
                sys.exit(1)
            
            self.alert_name_arg = sys.argv[1]
            self.camera_arg = sys.argv[2]
            self.timestamp_arg = sys.argv[3]
        
        self.logger.log(f"📩 Received alert:\n ├─ Alert Handle: {self.alert_name_arg}\n ├─ Camera: {self.camera_arg}\n └─ Timestamp: {self.timestamp_arg}")
        self.artifact_manager.save({"Alert": self.alert_name_arg})
    
    def _handle_session_management(self):
        """Handle Blue Iris session login and caching."""
        # Try to reuse cached session
        cached_session = self.artifact.get("session")
        session_is_valid = False
        
        if cached_session and cached_session != "<placeholder>":
            self.logger.debug(f"Testing cached session: {cached_session}")
            if SessionValidator.validate_session(
                self.bi_client, cached_session, self.alert_name_arg, self.camera_arg
            ):
                self.bi_client.cfg.session = cached_session
                session_is_valid = True
                self.logger.log("🔄 Reusing cached Blue Iris session from artifact.json")
            else:
                self.logger.log("♻️ Cached session invalid; will perform fresh login")
        
        # If we didn't successfully reuse a session, do a real login
        if not session_is_valid:
            session = self.bi_client.login()
            self.logger.log(f"✅ Logged in with new session: {session}")
            self.artifact_manager.save({"session": session})
    
    def _get_alert_clip(self):
        """Get alert clip data, using provided handle or fallback to recent AI alert."""
        alert_clip = None
        used_fallback = False
        
        if self.alert_name_arg != "@-1":
            data = self.bi_client.clipstats(self.alert_name_arg)
            candidate = {
                "path": data.get("path", ""),
                "camera": self.camera_arg,
                "offset": data.get("triggeroffset", 0),
                "msec": data.get("alertmsec", 0),
            }
            if candidate["path"]:
                alert_clip = candidate
                self.logger.log(f"✅ Using provided alert handle: {self.alert_name_arg}")
            else:
                used_fallback = True
                self.artifact_manager.save({"Alert": self.alert_name_arg})
        else:
            used_fallback = True
        
        if used_fallback or alert_clip is None:
            alert_clip = self.bi_client.get_recent_ai_alert(
                camera=self.camera_arg,
                lookback_seconds=self.config.ALERT_SEARCH_TIME,
                ai_object=self.config.AI_OBJECT,
                min_confidence=self.config.CONFIDENCE_LEVEL,
            )
            self.logger.log("🔁 Used alertlist fallback to find recent AI-filtered alert")
            self.artifact_manager.save({"Alert": alert_clip.get("path", self.alert_name_arg)})
        
        return alert_clip
    
    def _export_video(self, alert_clip):
        """Export video clip from Blue Iris."""
        alert_path = alert_clip["path"]
        alert_offset = int(alert_clip.get("offset", 0))
        alert_msec = int(alert_clip.get("msec", 0))
        
        self.logger.log(f"📸 Final alert clip: {alert_path} (Starts {alert_offset}ms for {alert_msec}ms)")
        
        # Decide export duration
        export_msec = self.config.get_export_duration(alert_msec)
        
        exp_resp = self.bi_client.export(path=alert_path, startms=alert_offset, msec=export_msec)
        if exp_resp.get("result") != "success":
            raise Exception(f"Export failed: {exp_resp.get('data', {}).get('status', 'Unknown error')}")
        
        self.logger.log("📤 Export started")
        
        exported_mp4_path = FileWaiter.wait_for_exported_file(
            exp_resp, self.config.EXPORT_DIR, log_func=self.logger.log
        )
        self.logger.log(f"✅ Found exported file: {exported_mp4_path}")
        
        return exported_mp4_path
    
    def _process_video(self, exported_mp4_path):
        """Process exported video - convert to GIF and extract frames."""
        # Convert to GIF
        gif_filename = self.config.get_gif_filename(self.camera_arg)
        gif_path = os.path.join(self.config.GIF_SAVE_DIR, gif_filename)
        
        self.logger.log("🎬 Converting MP4 to GIF...")
        converted_gif_path = VideoProcessor.convert_mp4_to_gif(
            exported_mp4_path, 
            gif_path, 
            self.config.GIF_DURATION_SECONDS, 
            self.config.GIF_FPS,
            log_func=self.logger.log
        )
        
        if not converted_gif_path:
            raise Exception("GIF conversion failed, aborting webhook")
        
        # Extract mid-frame JPEG
        jpeg_dir = os.path.join(self.config.GIF_SAVE_DIR, "frames")
        self.logger.log("📸 Extracting single mid-frame JPEG...")
        mid_jpeg_local = VideoProcessor.extract_midframe_jpeg(
            exported_mp4_path, jpeg_dir, self.camera_arg, log_func=self.logger.log
        )
        
        return converted_gif_path, mid_jpeg_local
    
    def _upload_and_notify(self, converted_gif_path, mid_jpeg_local):
        """Upload files to MinIO and send webhook notification."""
        # Upload main GIF
        self.logger.log("📤 Uploading main GIF to MinIO...")
        gif_minio_url = self.storage_client.upload_file(converted_gif_path, object_prefix="alerts")
        self.logger.log(f"✅ Main GIF uploaded: {gif_minio_url}")
        
        # Upload JPEG if available
        jpeg_minio_urls = []
        if mid_jpeg_local:
            self.logger.log("📤 Uploading mid-frame JPEG to MinIO...")
            mid_jpeg_url = self.storage_client.upload_file(mid_jpeg_local, object_prefix="alert_frames")
            jpeg_minio_urls = [mid_jpeg_url]
            self.logger.log(f"✅ Mid-frame JPEG uploaded: {mid_jpeg_url}")
        else:
            self.logger.log("⚠️ No mid-frame JPEG produced; webhook will include GIF only")
        
        # Send webhook
        self.logger.log("📨 Sending webhook...")
        self.notifier_client.send_alert(
            camera=self.camera_arg,
            timestamp=self.timestamp_arg,
            gif_url=gif_minio_url,
            jpeg_urls=jpeg_minio_urls if jpeg_minio_urls else None,
        )
        
        # Log to database - this is the key addition
        if self.db_logger:
            try:
                self.db_logger.log_alert(
                    camera=self.camera_arg,
                    timestamp=self.timestamp_arg,
                    alert_handle=self.alert_name_arg,
                    gif_url=gif_minio_url,
                    jpeg_urls=jpeg_minio_urls,
                    success=True,
                    debug_mode=self.debug_mode
                )
                self.logger.log("✅ Alert logged to database")
            except Exception as e:
                self.logger.log(f"⚠️ Failed to log to database: {e}")
        else:
            self.logger.debug("Database logging skipped (not configured)")
        
        return jpeg_minio_urls
    
    def _finalize(self, exported_mp4_path, converted_gif_path, jpeg_minio_urls):
        """Finalize processing and update artifact."""
        self.artifact_manager.save({
            "Camera": self.camera_arg,
            "Timestamp": self.timestamp_arg
        })
        self.logger.log("🗂  artifact.json updated: session, Alert, Camera, Timestamp")
        
        self.logger.log("✅ Process completed")
        self.logger.log("📊 Summary:")
        total_time = datetime.now() - self.script_start_time
        self.logger.log(f"  ├─ ⏱ Total execution time: {total_time}")
        self.logger.log(f"  ├─ MP4 exported: {os.path.basename(exported_mp4_path)}")
        self.logger.log(f"  ├─ Main GIF: {os.path.basename(converted_gif_path)}")
        if jpeg_minio_urls:
            self.logger.log(f"  └─ JPEG frames: {len(jpeg_minio_urls)} uploaded")
    
    def run(self):
        """Main execution method."""
        try:
            # Setup
            secrets = self._load_secrets()
            self._setup_api_clients(secrets)
            self._parse_arguments()
            
            # Initialize database and ensure table exists (if available)
            if self.db_logger:
                try:
                    self.db_logger.ensure_table_exists()
                    self.logger.debug("Database table verified")
                except Exception as e:
                    self.logger.log(f"⚠️ Database table setup failed: {e}")
                    self.db_logger = None  # Disable database logging
            
            # Blue Iris operations
            self._handle_session_management()
            alert_clip = self._get_alert_clip()
            exported_mp4_path = self._export_video(alert_clip)
            
            # Video processing
            converted_gif_path, mid_jpeg_local = self._process_video(exported_mp4_path)
            
            # Upload and notify (includes database logging)
            jpeg_minio_urls = self._upload_and_notify(converted_gif_path, mid_jpeg_local)
            
            # Finalize
            self._finalize(exported_mp4_path, converted_gif_path, jpeg_minio_urls)
            
        except Exception as e:
            self.logger.log(f"❌ Failed: {e}")
            
            # Log failure to database if we have the required info
            if self.db_logger and hasattr(self, 'camera_arg') and self.camera_arg:
                try:
                    self.db_logger.log_alert(
                        camera=self.camera_arg,
                        timestamp=getattr(self, 'timestamp_arg', ''),
                        alert_handle=getattr(self, 'alert_name_arg', ''),
                        gif_url="",
                        jpeg_urls=[],
                        success=False,
                        error_message=str(e),
                        debug_mode=self.debug_mode
                    )
                except:
                    pass  # Don't let database logging errors crash the error handling
                
            sys.exit(1)
        finally:
            # Clean up database connection
            if self.db_logger:
                self.db_logger.disconnect()


def main():
    """Entry point for the script."""
    # Load .env file first
    load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), ".env"))
    
    # Determine mode based on environment or arguments
    debug_mode = os.getenv("DEBUG_MODE", "false").lower() == "true"
    testing_mode = os.getenv("TESTING_MODE", "false").lower() == "true"
    
    # Create and run handler
    handler = BlueIrisAlertHandler(debug_mode=debug_mode, testing_mode=testing_mode)
    handler.run()


if __name__ == "__main__":
    main()