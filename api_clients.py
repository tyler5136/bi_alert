# api_clients.py
from __future__ import annotations
import hashlib
import re
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

import requests
from minio import Minio
from minio.error import S3Error

# ---------- Blue Iris ----------

@dataclass
class BlueIrisConfig:
    host: str               # e.g. "http://127.0.0.1:8191"
    username: str
    password: str
    timeout: int = 30       # seconds
    session: Optional[str] = None

class BlueIrisAPI:
    def __init__(self, cfg: BlueIrisConfig, debug_log=lambda *_: None):
        self.cfg = cfg
        self._debug = debug_log

    def _post(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        url = f"{self.cfg.host}/json"
        self._debug(f"BI POST {url} :: {payload.get('cmd')}")
        r = requests.post(url, json=payload, timeout=self.cfg.timeout)
        self._debug(f"BI RESP {r.status_code}: {r.text[:400]}")
        r.raise_for_status()
        return r.json()

    def login(self) -> str:
        """Obtain and cache a BI session token."""
        r1 = self._post({"cmd": "login"})
        session = r1["session"]
        rhash = hashlib.md5(f"{self.cfg.username}:{session}:{self.cfg.password}".encode()).hexdigest()
        r2 = self._post({"cmd": "login", "session": session, "response": rhash})
        if r2.get("result") != "success":
            raise RuntimeError("Blue Iris login failed")
        self.cfg.session = session
        return session

    def ensure_session(self) -> str:
        return self.cfg.session or self.login()

    def clipstats(self, path: str) -> Dict[str, Any]:
        session = self.ensure_session()
        response = self._post({"cmd": "clipstats", "session": session, "path": path})
        if response.get("result") != "success":
            raise RuntimeError(f"clipstats failed: {response.get('data', {}).get('reason', 'Unknown error')}")
        return response.get("data", {})

    def alertlist(self, camera: str, startdate_epoch: int) -> List[Dict[str, Any]]:
        session = self.ensure_session()
        data = self._post({"cmd": "alertlist", "session": session, "camera": camera, "startdate": startdate_epoch})
        if data.get("result") != "success":
            raise RuntimeError(f"alertlist failed: {data}")
        return data.get("data", [])

    def export(self, path: str, startms: int, msec: int) -> Dict[str, Any]:
        session = self.ensure_session()
        return self._post({"cmd": "export", "session": session, "path": path, "startms": startms, "msec": msec})

    # ---------- helpers specific to your logic (still API-focused) ----------

    @staticmethod
    def parse_memo_for_ai_detection(memo: str, target_object: str, min_confidence: int) -> Tuple[bool, int]:
        """Return (meets_threshold, confidence)."""
        if not memo:
            return False, 0
        m = re.search(rf"{re.escape(target_object)}:(\d+)%", memo, re.IGNORECASE)
        if not m:
            return False, 0
        conf = int(m.group(1))
        return (conf >= min_confidence, conf)

    def get_recent_ai_alert(
        self,
        camera: str,
        lookback_seconds: int,
        ai_object: str,
        min_confidence: int,
    ) -> Dict[str, Any]:
        """Returns your normalized 'alert_clip' dict for the most recent alert that matches the AI threshold."""
        start_date = int(time.time()) - lookback_seconds
        alerts = self.alertlist(camera=camera, startdate_epoch=start_date)

        valid_alerts: List[Dict[str, Any]] = []
        for a in alerts:
            ok, conf = self.parse_memo_for_ai_detection(a.get("memo", ""), ai_object, min_confidence)
            if ok:
                a["ai_confidence"] = conf
                valid_alerts.append(a)

        if not valid_alerts:
            raise RuntimeError(f"No alerts found with {ai_object} >= {min_confidence}% in last {lookback_seconds}s")

        valid_alerts.sort(key=lambda x: x.get("date", 0), reverse=True)
        sel = valid_alerts[0]

        # Normalize to the structure your main expects
        return {
            "path": sel.get("clip", ""),
            "camera": sel.get("camera", camera),
            "offset": sel.get("offset", 0),
            "msec": sel.get("msec", 0),
            "date": sel.get("date", 0),
            "ai_confidence": sel.get("ai_confidence", 0),
        }

# ---------- MinIO ----------

@dataclass
class MinioConfig:
    endpoint: str            # e.g. "minio.tsmithit.net"
    access_key: str
    secret_key: str
    bucket: str
    secure: bool = True

class MinioStorage:
    def __init__(self, cfg: MinioConfig, debug_log=lambda *_: None, log=lambda *_: None):
        self.cfg = cfg
        self._debug = debug_log
        self._log = log
        self.client = Minio(
            cfg.endpoint,
            access_key=cfg.access_key,
            secret_key=cfg.secret_key,
            secure=cfg.secure
        )

    def ensure_bucket(self):
        if not self.client.bucket_exists(self.cfg.bucket):
            self.client.make_bucket(self.cfg.bucket)

    def upload_file(self, local_path: str, object_prefix: str = "alerts", content_type: Optional[str]=None) -> str:
        """Uploads a single file and returns a URL."""
        from pathlib import Path
        self.ensure_bucket()
        name = Path(local_path).name
        object_name = f"{object_prefix}/{name}"

        # basic content-type inference
        if content_type is None:
            ext = Path(local_path).suffix.lower()
            ct_map = {'.gif': 'image/gif', '.mp4': 'video/mp4', '.avi': 'video/avi', '.mov': 'video/quicktime', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg'}
            content_type = ct_map.get(ext, 'application/octet-stream')

        self._debug(f"MinIO fput_object {self.cfg.bucket}/{object_name} ({content_type})")
        result = self.client.fput_object(self.cfg.bucket, object_name, local_path, content_type=content_type)
        url = f"{'https' if self.cfg.secure else 'http'}://{self.cfg.endpoint}/{self.cfg.bucket}/{object_name}"
        self._log(f"✅ Uploaded to MinIO: {object_name}")
        return url

    def upload_many(self, local_paths: List[str], object_prefix: str = "alert_frames") -> List[str]:
        urls: List[str] = []
        for p in local_paths:
            try:
                urls.append(self.upload_file(p, object_prefix=object_prefix))
            except Exception as e:
                self._log(f"❌ Failed to upload {p}: {e}")
        return urls

# ---------- Webhook ----------

@dataclass
class WebhookConfig:
    url: str
    headers: Optional[Dict[str, str]] = None
    timeout: int = 30
    retries: int = 3

class WebhookNotifier:
    def __init__(self, cfg: WebhookConfig, debug_log=lambda *_: None, log=lambda *_: None):
        self.cfg = cfg
        self._debug = debug_log
        self._log = log

    def send_alert(
        self,
        camera: str,
        timestamp: str,
        gif_url: str,
        jpeg_urls: Optional[List[str]] = None,
    ) -> requests.Response:
        data = {
            "camera": camera,
            "timestamp": timestamp,
            "has_gif": "true",
            "minio_url": gif_url,
            "gif_source": "minio",
        }
        if jpeg_urls:
            data["has_jpegs"] = "true"
            data["jpeg_count"] = str(len(jpeg_urls))
            data["jpeg_urls"] = ",".join(jpeg_urls)

        last_exc: Optional[Exception] = None
        for attempt in range(1, self.cfg.retries + 1):
            try:
                self._debug(f"Webhook attempt {attempt}: {self.cfg.url}")
                resp = requests.post(
                    self.cfg.url,
                    data=data,
                    headers=self.cfg.headers or {},
                    timeout=self.cfg.timeout
                )
                self._debug(f"Webhook {resp.status_code}: {resp.text[:400]}")
                self._log(f"📨 Webhook sent: {resp.status_code}")
                return resp
            except (requests.ConnectionError, requests.Timeout) as e:
                last_exc = e
                self._debug(f"Webhook failed attempt {attempt}: {e}")
                if attempt < self.cfg.retries:
                    time.sleep(attempt * 2)
        # exhausted retries
        raise RuntimeError(f"Webhook failed after {self.cfg.retries} attempts") from last_exc

# ---------- CodeProject.AI ----------

@dataclass
class CodeProjectAIConfig:
    host: str  # e.g., "http://localhost:32168"
    timeout: int = 60

class CodeProjectAIClient:
    def __init__(self, cfg: CodeProjectAIConfig, debug_log=lambda *_: None, log=lambda *_: None):
        self.cfg = cfg
        self._debug = debug_log
        self._log = log

    def detect_objects(self, image_path: str, min_confidence: float = 0.5) -> List[Dict[str, Any]]:
        """
        Call CodeProject.AI to perform object detection on an image.
        """
        endpoint = f"{self.cfg.host}/v1/vision/detection"
        self._debug(f"AI POST {endpoint}")

        try:
            with open(image_path, "rb") as f:
                files = {"image": f}
                data = {"min_confidence": min_confidence}
                response = requests.post(endpoint, files=files, data=data, timeout=self.cfg.timeout)

            response.raise_for_status()
            result = response.json()
            self._debug(f"AI RESP {response.status_code}: {result}")

            if not result.get("success"):
                raise RuntimeError(f"CodeProject.AI detection failed: {result.get('error', 'Unknown error')}")

            return result.get("predictions", [])

        except requests.exceptions.RequestException as e:
            self._log(f"❌ CodeProject.AI API request failed: {e}")
            raise RuntimeError(f"Could not connect to CodeProject.AI at {self.cfg.host}") from e
        except Exception as e:
            self._log(f"❌ An unexpected error occurred during AI detection: {e}")
            raise
