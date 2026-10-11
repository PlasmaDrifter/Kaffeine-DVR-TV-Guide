import os
import time
import subprocess
from datetime import datetime, timedelta
from typing import Optional
from .dbus_client import KaffeineDbusClient
from .queue_manager import QueueManager
from .config import ConfigManager
from .storage_manager import StorageManager

def send_desktop_notification(title: str, channel: str, start_display: str, lead_mins: int = 0):
    """
    Send a persistent desktop notification via notify-send.
    -t 0 specifies zero timeout, persisting in the notification center until dismissed.
    """
    try:
        if lead_mins > 0:
            summary = f"Recording Starting Soon: {title}"
            body = f"Channel: {channel}\nAirtime: {start_display}\nScheduled recording starts in {lead_mins} minute(s)."
        else:
            summary = f"Recording Starting: {title}"
            body = f"Channel: {channel}\nAirtime: {start_display}\nScheduled recording is starting."
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

    def stop_lingering_buffers_for_upcoming_shows(self):
        """
        If an active recording is past its scheduled base end time (currently recording post-roll buffer)
        and another show on a different channel is due to record, stop the buffer recording immediately
        to release the hardware tuner.
        """
        active_recordings = self.queue_mgr.list_queue(include_completed=False)
        now = datetime.now()

        currently_recording = [r for r in active_recordings if r.get("status") == "RECORDING"]
        if not currently_recording:
            return

        upcoming = [
            r for r in active_recordings
            if r.get("status") in ("QUEUED", "ARMED")
            and (datetime.fromisoformat(r["start_iso"]) <= now + timedelta(minutes=2))
        ]
        if not upcoming:
            return

        for rec_a in currently_recording:
            try:
                start_dt = datetime.fromisoformat(rec_a["start_iso"])
                h, m, s = map(int, rec_a["duration_iso"].split(":"))
                total_secs = h * 3600 + m * 60 + s
                buf_mins = int(rec_a.get("buffer_mins") or 0)
                base_secs = max(0, total_secs - (buf_mins * 60))
                base_end_dt = start_dt + timedelta(seconds=base_secs)

                if now >= base_end_dt:
                    for rec_b in upcoming:
                        if rec_a.get("channel", "").strip().lower() != rec_b.get("channel", "").strip().lower():
                            k_key = rec_a.get("kaffeine_key")
                            if k_key:
                                now_str = now.strftime('%Y-%m-%d %H:%M:%S')
                                print(
                                    f"[{now_str}] Releasing tuner: Stopping buffer on '{rec_a.get('title')}' "
                                    f"({rec_a.get('channel')}) so '{rec_b.get('title')}' ({rec_b.get('channel')}) can record.",
                                    flush=True
                                )
                                self.dbus_client.cancel_recording(
                                    key=k_key,
                                    channel=rec_a.get("channel"),
                                    title=rec_a.get("title")
                                )
                                self.queue_mgr.archive_to_history(rec_a["id"])
                            break
            except Exception as e:
                print(f"Error checking lingering buffers: {e}", flush=True)

    def check_and_dispatch(self, notify: bool = True) -> int:
        self.reap_children()
        # Resolve any back-to-back buffer conflicts across different channels before arming
        self.queue_mgr.resolve_consecutive_buffer_conflicts(dbus_client=self.dbus_client)
        # Release tuner if any active recording has reached base end time and is lingering in buffer
        self.stop_lingering_buffers_for_upcoming_shows()
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
                elif cfg.launch_mode in ("taskbar", "tray") or cfg.launch_minimized:
                    self.dbus_client.minimize_kaffeine(mode=cfg.launch_mode)
                key = self.dbus_client.schedule_recording(title, channel, start_iso, duration_iso, 0)
                if key and key > 0:
                    self.queue_mgr.mark_armed(rec_id, key)
                    if cfg.launch_mode in ("taskbar", "tray") or cfg.launch_minimized:
                        self.dbus_client.minimize_kaffeine(mode=cfg.launch_mode)
                    print(f"[{now_str}] Successfully armed recording in Kaffeine (D-Bus Key: {key}).", flush=True)
                    armed_count += 1
                else:
                    print(f"[{now_str}] Warning: schedule_recording returned invalid key {key} for '{title}'.", flush=True)

            except Exception as e:
                print(f"[{now_str}] Error arming recording '{title}': {e}", flush=True)

        # Check and dispatch desktop notifications when recording is due to start
        if notify and cfg.enable_desktop_notifications:
            lead_mins = getattr(cfg, "notification_lead_time_mins", 0)
            notify_due = self.queue_mgr.get_due_for_notification(lead_time_mins=lead_mins)
            for nrec in notify_due:
                n_title = nrec["title"]
                n_channel = nrec["channel"]
                n_start_local = nrec.get("start_time_local", nrec["start_iso"])
                send_desktop_notification(n_title, n_channel, n_start_local, lead_mins=lead_mins)
                self.queue_mgr.mark_notified(nrec["id"])
                now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                print(f"[{now_str}] Desktop notification sent for '{n_title}' on {n_channel} (lead: {lead_mins}m).", flush=True)

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
