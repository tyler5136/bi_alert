# alert_helper.py
import os
import json
import time
import subprocess
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional, Any
from PIL import Image
import cv2


class ArtifactManager:
    """Manages the artifact.json file for persisting state between runs."""
    
    def __init__(self, artifact_path: Path):
        self.artifact_path = artifact_path
    
    def load(self) -> Dict[str, Any]:
        """Load artifact data, creating default if missing."""
        if not self.artifact_path.exists():
            default = {
                "session": "<placeholder>",
                "Alert": "@1896798668",
                "Camera": "FrontYardDW",
                "Timestamp": "8/8/2025 4:07:00PM",
            }
            self.save(default)
            return default
        
        with open(self.artifact_path, "r", encoding="utf-8") as f:
            return json.load(f)
    
    def save(self, updates: Dict[str, Any]) -> None:
        """Merge updates into the artifact and atomically write to disk."""
        data = {}
        if self.artifact_path.exists():
            try:
                with open(self.artifact_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
            except Exception:
                data = {}
        
        data.update(updates)
        tmp = self.artifact_path.with_suffix(".json.tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        tmp.replace(self.artifact_path)


class OnePasswordHelper:
    """Helper for 1Password CLI operations."""
    
    @staticmethod
    def get_item_json(vault: str, item: str) -> Dict[str, Any]:
        """
        Call: op item get <item> --vault <vault> --format json
        Requires OP_SERVICE_ACCOUNT_TOKEN in the environment (service account).
        """
        if not os.getenv("OP_SERVICE_ACCOUNT_TOKEN"):
            raise RuntimeError("OP_SERVICE_ACCOUNT_TOKEN not set; 1Password CLI will prompt (not desired).")
        
        try:
            out = subprocess.check_output(
                ["op", "item", "get", item, "--vault", vault, "--format", "json"],
                text=True,
                env=os.environ.copy(),
                stderr=subprocess.STDOUT,
            )
            return json.loads(out)
        except subprocess.CalledProcessError as e:
            raise RuntimeError(f"1Password CLI failed: {e.output.strip()}") from e
    
    @staticmethod
    def get_field(item_json: Dict[str, Any], name: str, default=None) -> Any:
        """Extract a field by label or id from the 1Password item JSON."""
        for f in item_json.get("fields", []) or []:
            if f.get("label") == name or f.get("id") == name:
                return f.get("value")
        
        # Some items also store values in sections; try a broader scan:
        for sec in item_json.get("sections", []) or []:
            for f in sec.get("fields", []) or []:
                if f.get("t") == name or f.get("id") == name:
                    return f.get("v")
        
        return default
    
    @staticmethod
    def read_secret(ref: str) -> str:
        """Call op read <ref> to get a secret value."""
        env = os.environ.copy()
        out = subprocess.check_output(["op", "read", ref], env=env, text=True).strip()
        return out


class VideoProcessor:
    """Handles video processing operations like MP4 to GIF conversion and frame extraction."""
    
    @staticmethod
    def convert_mp4_to_gif(
        mp4_path: str, 
        gif_path: str, 
        duration_seconds: int, 
        fps: int,
        log_func=print
    ) -> Optional[str]:
        """Convert MP4 to GIF with specified duration and fps."""
        try:
            os.makedirs(os.path.dirname(gif_path), exist_ok=True)
            if not os.path.exists(mp4_path):
                raise Exception(f"Input file not found: {mp4_path}")

            cap = cv2.VideoCapture(mp4_path)
            if not cap.isOpened():
                raise Exception(f"Could not open video file: {mp4_path}")

            original_fps = cap.get(cv2.CAP_PROP_FPS)
            total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
            width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

            frames_to_extract = duration_seconds * fps
            frame_step = max(1, int(total_frames / frames_to_extract))

            frames = []
            frame_count = 0
            while len(frames) < frames_to_extract:
                ret, frame = cap.read()
                if not ret:
                    break
                if frame_count % frame_step == 0:
                    frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                    if width > 720:
                        new_width = 720
                        new_height = int(height * (new_width / width))
                        frame_rgb = cv2.resize(frame_rgb, (new_width, new_height))
                    frames.append(Image.fromarray(frame_rgb))
                frame_count += 1

            cap.release()
            if not frames:
                raise Exception("No frames extracted from video")

            duration_per_frame = int(1000 / fps)
            frames[0].save(
                gif_path,
                save_all=True,
                append_images=frames[1:],
                duration=duration_per_frame,
                loop=0,
                optimize=True
            )

            log_func(f"✅ GIF created: {gif_path} ({len(frames)} frames)")
            return gif_path
        except Exception as e:
            log_func(f"❌ GIF conversion failed: {e}")
            return None
    
    @staticmethod
    def extract_midframe_jpeg(
        mp4_path: str, 
        jpeg_save_dir: str, 
        camera_name: str,
        log_func=print
    ) -> Optional[str]:
        """Extract a single JPEG from the middle of the video."""
        try:
            os.makedirs(jpeg_save_dir, exist_ok=True)
            if not os.path.exists(mp4_path):
                raise Exception(f"MP4 not found: {mp4_path}")

            cap = cv2.VideoCapture(mp4_path)
            if not cap.isOpened():
                raise Exception(f"Could not open MP4: {mp4_path}")

            total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
            if total_frames <= 0:
                raise Exception("Total frames reported as 0")

            mid_frame = max(0, total_frames // 2)
            cap.set(cv2.CAP_PROP_POS_FRAMES, mid_frame)
            ret, frame = cap.read()
            cap.release()

            if not ret or frame is None:
                raise Exception("Failed to read middle frame")

            ts_str = datetime.now().strftime("%m%d%y_%H%M%S")
            jpeg_name = f"{camera_name}_{ts_str}_mid.jpg"
            jpeg_path = os.path.join(jpeg_save_dir, jpeg_name)

            ok = cv2.imwrite(jpeg_path, frame, [cv2.IMWRITE_JPEG_QUALITY, 95])
            if not ok:
                raise Exception("cv2.imwrite returned False")

            log_func(f"✅ Extracted middle-frame JPEG: {jpeg_path}")
            return jpeg_path
        except Exception as e:
            log_func(f"❌ Mid-frame JPEG extraction failed: {e}")
            return None
    
    @staticmethod
    def extract_alert_jpegs(
        mp4_path: str, 
        jpeg_save_dir: str, 
        camera_name: str,
        log_func=print
    ) -> List[str]:
        """Extract multiple JPEG frames from video at various time intervals."""
        try:
            os.makedirs(jpeg_save_dir, exist_ok=True)
            if not os.path.exists(mp4_path):
                raise Exception(f"MP4 not found: {mp4_path}")

            cap = cv2.VideoCapture(mp4_path)
            if not cap.isOpened():
                raise Exception(f"Could not open MP4: {mp4_path}")

            fps = cap.get(cv2.CAP_PROP_FPS)
            total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
            duration_seconds = total_frames / fps

            extraction_times = []
            if duration_seconds > 2:
                extraction_times.append(2.0)
            if duration_seconds > 3:
                t = duration_seconds - 3.0
                if t > 0:
                    extraction_times.append(t)
            t = 0.0
            while t < duration_seconds:
                extraction_times.append(t)
                t += 5.0

            extraction_times = sorted(set(extraction_times))
            extracted = []
            ts_str = datetime.now().strftime('%m%d%y_%H%M%S')

            for i, t in enumerate(extraction_times, 1):
                frame_number = int(t * fps)
                cap.set(cv2.CAP_PROP_POS_FRAMES, frame_number)
                ret, frame = cap.read()
                if not ret:
                    continue
                name = f"{camera_name}_{ts_str}_frame_{i:02d}_{t:.1f}s.jpg"
                path = os.path.join(jpeg_save_dir, name)
                ok = cv2.imwrite(path, frame, [cv2.IMWRITE_JPEG_QUALITY, 95])
                if ok:
                    extracted.append(path)

            cap.release()
            log_func(f"✅ Extracted {len(extracted)} JPEG frames")
            return extracted
        except Exception as e:
            log_func(f"❌ JPEG extraction failed: {e}")
            return []


class FileWaiter:
    """Handles waiting for exported files to be ready."""
    
    @staticmethod
    def wait_for_exported_file(
        export_response: Dict[str, Any], 
        export_dir: str,
        timeout_seconds: int = 60,
        log_func=print
    ) -> str:
        """Wait for an exported file to be available and stable."""
        uri = export_response.get("data", {}).get("uri", "")
        if not uri:
            raise Exception("No URI in export response")
        
        cleaned = uri.replace("Clipboard\\", "").replace("\\", os.sep)
        expected = os.path.join(export_dir, cleaned)

        if not os.path.exists(export_dir):
            os.makedirs(export_dir, exist_ok=True)

        timeout = time.time() + timeout_seconds
        while time.time() < timeout:
            if os.path.exists(expected):
                initial = os.path.getsize(expected)
                time.sleep(2)
                final = os.path.getsize(expected)
                if initial == final and final > 0:
                    return expected
            time.sleep(3)

        raise Exception(f"Timeout waiting for exported file: {os.path.basename(expected)}")


class SessionValidator:
    """Handles Blue Iris session validation."""
    
    @staticmethod
    def validate_session(
        bi_client, 
        session: str, 
        alert_name: Optional[str], 
        camera: Optional[str]
    ) -> bool:
        """
        Try a cheap API call using the provided session to validate it.
        Returns True if the call succeeds, else False.
        """
        try:
            # Temporarily inject the session into the client
            original_session = bi_client.cfg.session
            bi_client.cfg.session = session

            if alert_name and alert_name != "@-1":
                # Try clipstats - this will raise an exception if session is invalid
                bi_client.clipstats(alert_name)
                return True
            elif camera:
                # Try minimal alertlist - this will raise an exception if session is invalid
                bi_client.alertlist(camera=camera, startdate_epoch=int(time.time()) - 1)
                return True
            else:
                # Nothing to validate against, assume session is good
                return True
        except Exception as e:
            # Any exception means the session is invalid
            return False
        finally:
            # Restore original session
            bi_client.cfg.session = original_session


class Logger:
    """Centralized logging functionality."""
    
    def __init__(self, log_path: str, debug_enabled: bool = False):
        self.log_path = log_path
        self.debug_enabled = debug_enabled
    
    def debug(self, msg: str) -> None:
        """Log debug message if debug mode is enabled."""
        if self.debug_enabled:
            ts = datetime.now()
            out = f"[DEBUG {ts}] {msg}"
            self._write_and_print(out)
    
    def log(self, msg: str) -> None:
        """Log regular message."""
        ts = datetime.now()
        out = f"[{ts}] {msg}"
        self._write_and_print(out)
    
    def _write_and_print(self, message: str) -> None:
        """Write to file and print to console."""
        try:
            os.makedirs(os.path.dirname(self.log_path), exist_ok=True)
            with open(self.log_path, "a", encoding="utf-8") as f:
                f.write(message + "\n")
        finally:
            print(message)


class AlertConfiguration:
    """Manages alert configuration and constants."""
    
    def __init__(self):
        # Default configuration values
        self.CLIP_DURATION_MS = 60000
        self.AI_OBJECT = "person"
        self.CONFIDENCE_LEVEL = 60
        self.ALERT_SEARCH_TIME = 60
        self.DEBUG_ALERT_SEARCH_TIME = 17400
        
        # Paths
        self.EXPORT_DIR = r"C:\Blue Iris\New\Clipboard"
        self.GIF_SAVE_DIR = r"C:\bi_alerts"
        
        # File processing settings
        self.GIF_DURATION_SECONDS = 6
        self.GIF_FPS = 5
    
    def get_export_duration(self, alert_msec: int) -> int:
        """Decide export duration based on alert duration."""
        return alert_msec if (alert_msec > 0 and alert_msec <= 60000) else self.CLIP_DURATION_MS
    
    def get_gif_filename(self, camera: str) -> str:
        """Generate GIF filename with timestamp."""
        return f"{camera}_{datetime.now().strftime('%m%d%y_%H%M%S')}.gif"