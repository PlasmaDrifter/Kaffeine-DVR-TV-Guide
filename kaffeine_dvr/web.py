"""
Lightweight, dependency-free HTTP Server & Remote Web Companion for Kaffeine DVR.

Provides:
- Mobile & tablet-friendly web interface for TV Guide browsing and scheduling.
- Active Schedule & Completed Recordings management.
- Video streaming with RFC 7233 HTTP Range header chunking for instant HTML5 scrubbing.
- Salted SHA-256 session token authentication for Tailscale / LAN access.
"""

import http.server
import json
import mimetypes
import secrets
import shutil
import threading
import time
import urllib.parse
from pathlib import Path
from typing import Any, Dict, Optional

from .config import ConfigManager
from .guide_service import GuideService
from .queue_manager import QueueManager
from .storage_manager import StorageManager
from .web_ui import WEB_HTML_TEMPLATE


class KaffeineWebRequestHandler(http.server.BaseHTTPRequestHandler):
    """Handles HTTP requests for Kaffeine DVR Web Companion."""

    server_version = "KaffeineDVR-Web/1.0"

    @property
    def server_obj(self) -> Optional["KaffeineWebServer"]:
        return getattr(self.server, "owner", None)

    def log_message(self, fmt, *args):
        # Quiet standard logging to keep stdout clean
        pass

    def _send_json(self, data: Any, status: int = 200):
        body = json.dumps(data).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
        self.end_headers()
        self.wfile.write(body)

    def _send_html(self, html_text: str, status: int = 200):
        body = html_text.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(body)

    def _is_authenticated(self) -> bool:
        if not self.server_obj or not self.server_obj.config_mgr.has_web_password:
            return True

        # 1. Bearer Token in Authorization header
        auth_hdr = self.headers.get("Authorization", "")
        if auth_hdr.startswith("Bearer "):
            token = auth_hdr[7:].strip()
            if self.server_obj.is_valid_token(token):
                return True

        # 2. Token in Query Parameter (used by <video src="/api/stream/..">)
        parsed = urllib.parse.urlparse(self.path)
        qs = urllib.parse.parse_qs(parsed.query)
        q_token = qs.get("token", [""])[0]
        if q_token and self.server_obj.is_valid_token(q_token):
            return True

        return False

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path

        content_len = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_len).decode("utf-8") if content_len > 0 else ""

        # Login endpoint: POST /api/login
        if path == "/api/login":
            try:
                data = json.loads(body) if body else {}
                pw = data.get("password", "")
                if self.server_obj.config_mgr.verify_web_password(pw):
                    token = self.server_obj.create_session_token()
                    self._send_json({"token": token, "status": "ok"})
                    return
                time.sleep(0.5)  # Anti-brute-force delay
                self._send_json({"error": "Invalid password"}, status=401)
                return
            except Exception as e:
                self._send_json({"error": str(e)}, status=400)
                return

        # Enforce authentication for all other mutating endpoints
        if not self._is_authenticated():
            self._send_json({"error": "Unauthorized"}, status=401)
            return

        # Schedule show: POST /api/schedule
        if path == "/api/schedule":
            try:
                data = json.loads(body)
                title = data.get("title", "").strip()
                ch = data.get("channel", "").strip()
                start_iso = data.get("start_iso", "").strip()
                dur_iso = data.get("duration_iso", "00:30:00").strip()

                if not title or not ch or not start_iso:
                    self._send_json({"error": "Missing required fields"}, status=400)
                    return

                qid = self.server_obj.queue_mgr.add_recording(
                    title=title,
                    channel=ch,
                    start_iso=start_iso,
                    duration_iso=dur_iso
                )
                self._send_json({"id": qid, "status": "scheduled"})
                return
            except Exception as e:
                self._send_json({"error": str(e)}, status=500)
                return

        self._send_json({"error": "Not Found"}, status=404)

    def do_DELETE(self):
        if not self._is_authenticated():
            self._send_json({"error": "Unauthorized"}, status=401)
            return

        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path

        # Cancel schedule: DELETE /api/schedule/<id>
        if path.startswith("/api/schedule/"):
            try:
                qid = int(path.split("/")[-1])
                self.server_obj.queue_mgr.remove_recording(qid)
                self._send_json({"status": "cancelled", "id": qid})
                return
            except Exception as e:
                self._send_json({"error": str(e)}, status=400)
                return

        self._send_json({"error": "Not Found"}, status=404)

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path

        # Root route: Serve frontend SPA HTML
        if path in ("/", "/index.html"):
            self._send_html(WEB_HTML_TEMPLATE)
            return

        # All API endpoints require authentication (except status probe which returns 401 if unauthed)
        if path.startswith("/api/"):
            if not self._is_authenticated():
                self._send_json({"error": "Unauthorized"}, status=401)
                return

        # System status: GET /api/status
        if path == "/api/status":
            try:
                active_recs = len(self.server_obj.queue_mgr.list_queue())
                folder = self.server_obj.storage_mgr.get_recording_folder()
                free_gb = 0
                if folder and folder.exists():
                    _, _, free = shutil.disk_usage(str(folder))
                    free_gb = round(free / (1024 ** 3), 1)
                self._send_json({
                    "status": "online",
                    "free_disk_gb": free_gb,
                    "active_recordings": active_recs,
                    "server_port": self.server_obj.port
                })
                return
            except Exception as e:
                self._send_json({"error": str(e)}, status=500)
                return

        # TV Guide listings: GET /api/guide?date=YYYY-MM-DD
        if path == "/api/guide":
            try:
                qs = urllib.parse.parse_qs(parsed.query)
                target_date = qs.get("date", [""])[0] or time.strftime("%Y-%m-%d")
                programs = self.server_obj.guide_svc.search_programs(
                    airdate=target_date,
                    trim_ended=False,
                    include_overhang=True
                )

                # Cross-reference with scheduled map
                scheduled_map = self.server_obj.queue_mgr.get_active_scheduled_map()

                out = []
                for p in programs:
                    ch_name = p.get("kaffeine_channel") or p.get("channel") or ""
                    ch_key = ch_name.strip().lower()
                    iso_key = (p.get("start_iso") or "")[:16]
                    is_sched = (ch_key, iso_key) in scheduled_map
                    out.append({
                        "id": p.get("id"),
                        "title": p.get("show_title") or p.get("title") or "Untitled",
                        "episode_title": p.get("episode_title") or "",
                        "channel": ch_name,
                        "start_iso": p.get("start_iso"),
                        "duration_iso": p.get("duration_iso"),
                        "category": p.get("_category") or "",
                        "is_scheduled": is_sched
                    })
                self._send_json(out)
                return
            except Exception as e:
                self._send_json({"error": str(e)}, status=500)
                return

        # Recordings list: GET /api/recordings
        if path == "/api/recordings":
            try:
                active = self.server_obj.queue_mgr.list_queue()
                hist = self.server_obj.queue_mgr.list_history()

                active_out = []
                for a in active:
                    active_out.append({
                        "id": a.get("id"),
                        "title": a.get("title"),
                        "channel": a.get("channel"),
                        "start_iso": a.get("start_iso"),
                        "duration_iso": a.get("duration_iso"),
                        "status": a.get("status"),
                        "file_available": False,
                        "stream_url": ""
                    })

                hist_out = []
                for h in hist:
                    hid = h.get("id")
                    is_avail, _, sz_bytes = self.server_obj.storage_mgr.check_history_file_availability(h)
                    size_str = f"{round(sz_bytes / (1024 ** 3), 2)} GB" if sz_bytes > 0 else ""
                    hist_out.append({
                        "id": hid,
                        "title": h.get("title"),
                        "channel": h.get("channel"),
                        "start_iso": h.get("start_iso"),
                        "completed_at": h.get("completed_at"),
                        "duration_iso": h.get("duration_iso"),
                        "status": "COMPLETED",
                        "size_str": size_str,
                        "file_available": is_avail,
                        "stream_url": f"/api/stream/{hid}" if is_avail else ""
                    })

                self._send_json({"active": active_out, "history": hist_out})
                return
            except Exception as e:
                self._send_json({"error": str(e)}, status=500)
                return

        # Stream recording with RFC 7233 byte-range support: GET /api/stream/<id>
        if path.startswith("/api/stream/"):
            try:
                hid = int(path.split("/")[-1])
                import sqlite3
                conn = self.server_obj.queue_mgr._get_connection()
                conn.row_factory = sqlite3.Row
                cur = conn.cursor()
                cur.execute("SELECT * FROM recording_history WHERE id = ?", (hid,))
                row = cur.fetchone()
                conn.close()

                if not row:
                    self._send_json({"error": "Recording not found"}, status=404)
                    return

                h_dict = dict(row)
                is_avail, found, _ = self.server_obj.storage_mgr.check_history_file_availability(h_dict)
                if not is_avail or not found or not found.exists():
                    self._send_json({"error": "Video file not found on disk"}, status=404)
                    return

                # Security check: Ensure file resides strictly inside recording folder
                rec_folder = self.server_obj.storage_mgr.get_recording_folder().resolve()
                resolved_target = found.resolve()
                if not str(resolved_target).startswith(str(rec_folder)):
                    self._send_json({"error": "Access denied"}, status=403)
                    return

                self._stream_file_with_range(resolved_target)
                return
            except Exception as e:
                self._send_json({"error": str(e)}, status=500)
                return

        self._send_json({"error": "Not Found"}, status=404)

    def _stream_file_with_range(self, file_path: Path):
        """Streams a media file supporting HTTP Range headers for seeking/scrubbing."""
        total_size = file_path.stat().st_size
        range_header = self.headers.get("Range")

        mime_type, _ = mimetypes.guess_type(str(file_path))
        if not mime_type:
            mime_type = "video/mp2t" if file_path.suffix.lower() in (".m2t", ".ts") else "video/mp4"

        start = 0
        end = total_size - 1

        if range_header and range_header.startswith("bytes="):
            parts = range_header[6:].split("-")
            if parts[0]:
                start = int(parts[0])
            if len(parts) > 1 and parts[1]:
                end = int(parts[1])

        if start >= total_size:
            self.send_response(416)
            self.send_header("Content-Range", f"bytes */{total_size}")
            self.end_headers()
            return

        end = min(end, total_size - 1)
        chunk_len = end - start + 1

        if range_header:
            self.send_response(206)
            self.send_header("Content-Range", f"bytes {start}-{end}/{total_size}")
        else:
            self.send_response(200)

        self.send_header("Content-Type", mime_type)
        self.send_header("Content-Length", str(chunk_len))
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()

        # Stream chunk
        chunk_size = 64 * 1024
        with open(file_path, "rb") as f:
            f.seek(start)
            bytes_left = chunk_len
            while bytes_left > 0:
                read_sz = min(chunk_size, bytes_left)
                data = f.read(read_sz)
                if not data:
                    break
                try:
                    self.wfile.write(data)
                    bytes_left -= len(data)
                except (BrokenPipeError, ConnectionResetError):
                    break


class ThreadedHTTPServer(http.server.ThreadingHTTPServer):
    """Threading HTTPServer with immediate address reuse and owner reference."""
    allow_reuse_address = True
    daemon_threads = True

    def __init__(self, server_address, RequestHandlerClass, owner: "KaffeineWebServer"):
        self.owner = owner
        super().__init__(server_address, RequestHandlerClass)


class KaffeineWebServer:
    """Manages the background HTTP web server thread and active sessions."""

    def __init__(
        self,
        config_mgr: ConfigManager,
        queue_mgr: QueueManager,
        guide_svc: GuideService,
        storage_mgr: StorageManager
    ):
        self.config_mgr = config_mgr
        self.queue_mgr = queue_mgr
        self.guide_svc = guide_svc
        self.storage_mgr = storage_mgr

        self.port = self.config_mgr.web_server_port
        self.bind_addr = self.config_mgr.web_server_bind
        self.server: Optional[ThreadedHTTPServer] = None
        self.thread: Optional[threading.Thread] = None
        self.active_tokens: Dict[str, float] = {}
        self._lock = threading.Lock()

    def create_session_token(self) -> str:
        with self._lock:
            token = secrets.token_hex(24)
            # 7-day token expiration
            self.active_tokens[token] = time.time() + (7 * 86400)
            return token

    def is_valid_token(self, token: str) -> bool:
        with self._lock:
            exp = self.active_tokens.get(token)
            if exp and time.time() < exp:
                return True
            if exp:
                del self.active_tokens[token]
            return False

    def is_running(self) -> bool:
        return self.server is not None and self.thread is not None and self.thread.is_alive()

    def start(self) -> bool:
        """Starts the background web server thread."""
        if self.is_running():
            return True

        self.port = self.config_mgr.web_server_port
        self.bind_addr = self.config_mgr.web_server_bind

        try:
            addr = (self.bind_addr, self.port)
            self.server = ThreadedHTTPServer(addr, KaffeineWebRequestHandler, owner=self)
            self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
            self.thread.start()
            print(f"Kaffeine DVR Web Companion listening on http://{self.bind_addr}:{self.port}/", flush=True)
            return True
        except Exception as e:
            print(f"Failed to start Kaffeine DVR Web Server on port {self.port}: {e}", flush=True)
            self.server = None
            self.thread = None
            return False

    def stop(self):
        """Shuts down the background web server."""
        if self.server:
            try:
                self.server.shutdown()
                self.server.server_close()
            except Exception:
                pass
            self.server = None
        if self.thread:
            self.thread.join(timeout=1.0)
            self.thread = None
        print("Kaffeine DVR Web Companion stopped.", flush=True)
