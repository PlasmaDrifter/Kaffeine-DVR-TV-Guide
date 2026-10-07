import os
import re
import shutil
import configparser
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Any

class StorageManager:
    """
    Manages DVR recording storage directory, disk space monitoring,
    and automatic retention cleanup (age-based and disk space threshold-based).
    """

    VIDEO_EXTENSIONS = {".m2t", ".ts", ".mp4", ".mkv"}
    SIDECAR_EXTENSIONS = {".txt", ".log", ".info"}

    def __init__(self, config_mgr=None, queue_mgr=None):
        from .config import ConfigManager
        from .queue_manager import QueueManager
        self.config_mgr = config_mgr or ConfigManager()
        self.queue_mgr = queue_mgr or QueueManager()

    def get_recording_folder(self) -> Path:
        """
        Determines the recording directory:
        1. Checks custom_recording_folder override in config.json.
        2. Checks ~/.config/kaffeinerc under [DVB] -> RecordingFolder.
        3. Falls back to Path.home() / 'Videos'.
        """
        custom = self.config_mgr.custom_recording_folder
        if custom and custom.strip():
            p = Path(os.path.expanduser(custom.strip()))
            if p.exists() and p.is_dir():
                return p

        kaffeinerc = Path.home() / ".config" / "kaffeinerc"
        if kaffeinerc.exists():
            # Try 1: read line by line under [DVB]
            try:
                in_dvb = False
                with open(kaffeinerc, "r", encoding="utf-8", errors="replace") as f:
                    for line in f:
                        line_str = line.strip()
                        if line_str.startswith("[") and line_str.endswith("]"):
                            in_dvb = (line_str == "[DVB]")
                            continue
                        if in_dvb and line_str.startswith("RecordingFolder="):
                            rf = line_str.split("=", 1)[1].strip()
                            if rf:
                                p = Path(os.path.expanduser(rf))
                                if p.exists() and p.is_dir():
                                    return p
            except Exception as e:
                print(f"Error reading kaffeinerc directly: {e}")

            # Try 2: kreadconfig6
            try:
                res = subprocess.run(
                    ["kreadconfig6", "--file", "kaffeinerc", "--group", "DVB", "--key", "RecordingFolder"],
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
                )
                if res.returncode == 0 and res.stdout.strip():
                    p = Path(os.path.expanduser(res.stdout.strip()))
                    if p.exists() and p.is_dir():
                        return p
            except Exception:
                pass

        fallback = Path.home() / "Videos"
        return fallback

    def get_disk_usage(self, folder: Optional[Path] = None) -> Dict[str, Any]:
        """
        Returns total, used, free disk bytes and free percentage for the recording filesystem.
        """
        target = folder or self.get_recording_folder()
        if not target.exists():
            target = Path.home()

        try:
            usage = shutil.disk_usage(str(target))
            total_gb = usage.total / (1024 ** 3)
            used_gb = usage.used / (1024 ** 3)
            free_gb = usage.free / (1024 ** 3)
            free_pct = (usage.free / usage.total) * 100 if usage.total > 0 else 0.0

            return {
                "folder": str(target),
                "total_bytes": usage.total,
                "used_bytes": usage.used,
                "free_bytes": usage.free,
                "total_gb": round(total_gb, 2),
                "used_gb": round(used_gb, 2),
                "free_gb": round(free_gb, 2),
                "free_percent": round(free_pct, 1)
            }
        except Exception as e:
            return {
                "folder": str(target),
                "total_bytes": 0,
                "used_bytes": 0,
                "free_bytes": 0,
                "total_gb": 0.0,
                "used_gb": 0.0,
                "free_gb": 0.0,
                "free_percent": 0.0,
                "error": str(e)
            }

    def find_recorded_files(self, folder: Optional[Path] = None) -> List[Dict[str, Any]]:
        """
        Scans recording folder for recorded video files, sorted oldest to newest by mtime.
        """
        target = folder or self.get_recording_folder()
        if not target.exists():
            return []

        files = []
        try:
            for entry in target.iterdir():
                if entry.is_file() and entry.suffix.lower() in self.VIDEO_EXTENSIONS:
                    stat = entry.stat()
                    files.append({
                        "path": entry,
                        "name": entry.name,
                        "size_bytes": stat.st_size,
                        "size_gb": round(stat.st_size / (1024 ** 3), 2),
                        "mtime": stat.st_mtime,
                        "mtime_dt": datetime.fromtimestamp(stat.st_mtime)
                    })
        except Exception as e:
            print(f"Error scanning recording folder {target}: {e}")

        files.sort(key=lambda x: x["mtime"])
        return files

    def is_file_active_recording(self, file_path: Path) -> bool:
        """
        Checks if a file is currently being recorded or actively written.
        Protects against deleting in-progress broadcasts.
        """
        # 1. Check if modified within the last 120 seconds
        try:
            mtime = file_path.stat().st_mtime
            if (datetime.now().timestamp() - mtime) < 120:
                return True
        except Exception:
            return True

        # 2. Check active queue entries (ARMED or RECORDING)
        try:
            active_recs = self.queue_mgr.list_queue(include_completed=False)
            now = datetime.now()
            for rec in active_recs:
                if rec.get("status") in ("ARMED", "RECORDING"):
                    # Check if airtime window is currently active
                    end_dt = datetime.fromisoformat(rec["end_iso"])
                    if now <= end_dt + timedelta(minutes=10):
                        clean_title = re.sub(r'[^a-zA-Z0-9]', '', rec.get("title", "")).lower()
                        clean_fname = re.sub(r'[^a-zA-Z0-9]', '', file_path.name).lower()
                        if clean_title and clean_title in clean_fname:
                            return True
        except Exception as e:
            print(f"Error checking active queue during retention check: {e}")

        return False

    def delete_recording(self, file_path: Path) -> bool:
        """
        Safely deletes a video file and any associated sidecars (.txt, .log, .info).
        """
        try:
            if not file_path.exists():
                return False

            base_stem = file_path.stem
            parent = file_path.parent

            file_path.unlink()
            print(f"StorageManager: Deleted recorded video {file_path.name}")

            for ext in self.SIDECAR_EXTENSIONS:
                sidecar = parent / f"{base_stem}{ext}"
                if sidecar.exists():
                    try:
                        sidecar.unlink()
                        print(f"StorageManager: Deleted sidecar {sidecar.name}")
                    except Exception:
                        pass

            self.queue_mgr.mark_file_purged(str(file_path))
            return True
        except Exception as e:
            print(f"Error deleting recording {file_path}: {e}")
            return False

    def run_cleanup_cycle(self) -> Dict[str, Any]:
        """
        Executes retention policy:
        1. Age-based cleanup (if retention_days > 0).
        2. Disk space threshold cleanup (if min_free_disk_gb > 0 and free space < threshold).
        Returns a summary report of actions taken.
        """
        if not self.config_mgr.auto_cleanup_enabled:
            return {"enabled": False, "deleted_count": 0, "freed_gb": 0.0}

        retention_days = self.config_mgr.retention_days
        min_free_gb = self.config_mgr.min_free_disk_gb
        folder = self.get_recording_folder()

        deleted_files = []
        total_freed_bytes = 0

        protected_paths = self.queue_mgr.get_protected_paths()

        # Step 1: Age-based retention
        if retention_days > 0:
            now_dt = datetime.now()
            cutoff = now_dt - timedelta(days=retention_days)
            all_files = self.find_recorded_files(folder)

            for item in all_files:
                fpath = item["path"]
                if str(fpath) in protected_paths:
                    continue
                if self.is_file_active_recording(fpath):
                    continue

                if item["mtime_dt"] < cutoff:
                    sz = item["size_bytes"]
                    if self.delete_recording(fpath):
                        deleted_files.append(item["name"])
                        total_freed_bytes += sz

        # Step 2: Disk space threshold retention
        if min_free_gb > 0:
            usage = self.get_disk_usage(folder)
            current_free_gb = usage["free_gb"]

            if current_free_gb < min_free_gb:
                needed_bytes = int((min_free_gb - current_free_gb) * (1024 ** 3))
                freed_for_threshold = 0

                remaining_files = self.find_recorded_files(folder)
                for item in remaining_files:
                    if freed_for_threshold >= needed_bytes:
                        break

                    fpath = item["path"]
                    if str(fpath) in protected_paths:
                        continue
                    if self.is_file_active_recording(fpath):
                        continue

                    sz = item["size_bytes"]
                    if self.delete_recording(fpath):
                        deleted_files.append(item["name"])
                        total_freed_bytes += sz
                        freed_for_threshold += sz

        freed_gb = round(total_freed_bytes / (1024 ** 3), 2)
        return {
            "enabled": True,
            "deleted_count": len(deleted_files),
            "deleted_files": deleted_files,
            "freed_gb": freed_gb,
            "folder": str(folder)
        }
