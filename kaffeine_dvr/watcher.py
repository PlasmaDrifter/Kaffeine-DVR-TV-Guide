import os
import time
import subprocess
from datetime import datetime
from typing import Optional
from .dbus_client import KaffeineDbusClient
from .queue_manager import QueueManager
from .config import ConfigManager
from .storage_manager import StorageManager

def send_desktop_notification(title: str, channel: str, start_display: str):
    """
    Send a persistent desktop notification via notify-send.
    -t 0 specifies zero timeout, persisting in the notification center until dismissed.
    """
    try:
        summary = f"Kaffeine Recording Armed: {title}"
        body = f"Channel: {channel}\nAirtime: {start_display}\nKaffeine launched and recording timer armed."
        cmd = [
            "notify-send",
            "-a", "Kaffeine DVR",
            "-i", "kaffeine",
            "-u", "normal",
            "-t", "0",
            summary,
            body
        ]
        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception as e:
        print(f"Error sending desktop notification: {e}", flush=True)

class Watcher:
    def __init__(self, dbus_client: Optional[KaffeineDbusClient] = None, queue_mgr: Optional[QueueManager] = None):
        self.dbus_client = dbus_client or KaffeineDbusClient()
        self.queue_mgr = queue_mgr or QueueManager()
        self.storage_mgr = StorageManager(queue_mgr=self.queue_mgr)
        self.running = True
        self.last_sync_time = 0.0

    def reap_children(self):
        """Reap any terminated child processes to prevent zombie (<defunct>) processes."""
        while True:
            try:
                pid, _ = os.waitpid(-1, os.WNOHANG)
                if pid <= 0:
                    break
            except (ChildProcessError, OSError):
                break

    def check_and_dispatch(self, notify: bool = True) -> int:
        self.reap_children()
        due = self.queue_mgr.get_due_to_arm()
        armed_count = 0
        cfg = ConfigManager()

        for rec in due:
            title = rec["title"]
            channel = rec["channel"]
            start_iso = rec["start_iso"]
            duration_iso = rec["duration_iso"]
            start_local = rec.get("start_time_local", start_iso)
            rec_id = rec["id"]
            
            now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            print(f"[{now_str}] Program due: '{title}' on {channel} at {start_iso}. Arming into Kaffeine...", flush=True)
            try:
                # Ensure Kaffeine is running (launches if closed) and schedules via D-Bus
                if not self.dbus_client.is_running():
                    self.dbus_client.launch_kaffeine(mode=cfg.launch_mode)
                    time.sleep(1)
                key = self.dbus_client.schedule_recording(title, channel, start_iso, duration_iso, 0)
                if key and key > 0:
                    self.queue_mgr.mark_armed(rec_id, key)
                    print(f"[{now_str}] Successfully armed recording in Kaffeine (D-Bus Key: {key}).", flush=True)
                    armed_count += 1

                    # Send persistent desktop notification if enabled and not triggered manually
                    if notify and cfg.enable_desktop_notifications:
                        send_desktop_notification(title, channel, start_local)
                else:
                    print(f"[{now_str}] Warning: schedule_recording returned invalid key {key} for '{title}'.", flush=True)

            except Exception as e:
                print(f"[{now_str}] Error arming recording '{title}': {e}", flush=True)

        # Update in-progress and completed statuses (archive finished to history)
        self.queue_mgr.update_statuses([], max_history=cfg.max_history_entries)

        # Run storage retention & auto-cleanup if enabled
        try:
            cleanup_res = self.storage_mgr.run_cleanup_cycle()
            if cleanup_res.get("deleted_count", 0) > 0:
                now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                print(
                    f"[{now_str}] Auto-Cleanup completed: Purged {cleanup_res['deleted_count']} recording(s), "
                    f"freed {cleanup_res['freed_gb']} GB in {cleanup_res['folder']}.",
                    flush=True
                )
        except Exception as e:
            print(f"Error during storage cleanup cycle: {e}", flush=True)

        return armed_count

    def check_periodic_sync(self):
        """Periodically sync TV guide listings and evaluate series rules."""
        cfg = ConfigManager()
        interval_seconds = getattr(cfg, "auto_sync_interval_hours", 6) * 3600
        now = time.time()
        
        # If we haven't synced yet in this session or interval has elapsed
        if (now - self.last_sync_time) >= interval_seconds:
            self.last_sync_time = now
            now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            print(f"[{now_str}] Running periodic TV guide sync and series rules evaluation...", flush=True)
            try:
                from .guide_service import GuideService
                from .rules_engine import RulesEngine
                guide_svc = GuideService(channel_map=cfg.channel_map, config_mgr=cfg)
                synced_count = guide_svc.sync_guide(days=cfg.guide_days_ahead)
                print(f"[{now_str}] Guide sync completed: {synced_count} programs cached.", flush=True)
                
                rules_eng = RulesEngine(cfg, self.dbus_client, guide_svc)
                scheduled = rules_eng.evaluate_and_schedule()
                print(f"[{now_str}] Rule evaluation completed: {len(scheduled)} recordings scheduled.", flush=True)
            except Exception as e:
                print(f"[{now_str}] Error during periodic guide sync: {e}", flush=True)

    def run_loop(self, interval_seconds: int = 120):
        print(f"Kaffeine DVR Watcher running (check interval: {interval_seconds}s).", flush=True)
        # Run an initial guide & rules check on daemon startup
        self.check_periodic_sync()
        while self.running:
            try:
                self.reap_children()
                self.check_and_dispatch()
                self.check_periodic_sync()
            except Exception as e:
                print(f"Error in watcher cycle: {e}", flush=True)
            time.sleep(interval_seconds)
