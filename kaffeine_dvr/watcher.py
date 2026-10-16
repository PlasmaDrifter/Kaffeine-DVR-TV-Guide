"""
Background daemon watcher for Kaffeine DVR.

Periodically monitors the recording queue, dispatches just-in-time recordings
to Kaffeine over D-Bus before airtime, manages back-to-back channel handover,
and triggers automatic background guide sync and storage retention cycles.
"""

import os
import re
import subprocess
import time
from datetime import datetime, timedelta
from typing import Optional

from .config import ConfigManager
from .dbus_client import KaffeineDbusClient
from .queue_manager import QueueManager
from .storage_manager import StorageManager


def send_desktop_notification(title: str, channel: str, start_display: str, lead_mins: int = 0, persistent: bool = False):
    """
    Send a desktop notification via notify-send.
    If persistent is True, specifies -t 0 (zero timeout), persisting in the notification center until dismissed.
    If persistent is False, follows the OS default notification expiration/dismissal behavior.
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
        ]
        if persistent:
            cmd.extend(["-t", "0"])
        cmd.extend([summary, body])
        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception as e:
        print(f"Error sending desktop notification: {e}", flush=True)

class Watcher:
    def __init__(
        self,
        dbus_client: Optional[KaffeineDbusClient] = None,
        queue_mgr: Optional[QueueManager] = None,
        storage_mgr: Optional[StorageManager] = None,
        config_mgr: Optional[ConfigManager] = None,
    ):
        self.config_mgr = config_mgr or ConfigManager()
        self.dbus_client = dbus_client or KaffeineDbusClient()
        self.queue_mgr = queue_mgr or QueueManager()
        self.storage_mgr = storage_mgr or StorageManager(config_mgr=self.config_mgr, queue_mgr=self.queue_mgr)
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
        Releases the hardware tuner when consecutive recordings on different channels
        are scheduled.
        1. If an active recording has reached its target end time (e.g. 10s early cutoff or post-roll buffer)
           and another show on a different channel is starting soon, stops the active recording.
        2. Queries Kaffeine via D-Bus: if an upcoming show on a different channel starts within 20s,
           ensures any running stream on a different channel is stopped immediately.
        """
        active_recordings = self.queue_mgr.list_queue(include_completed=False)
        now = datetime.now()

        upcoming = []
        for r in active_recordings:
            if r.get("status") in ("QUEUED", "ARMED"):
                try:
                    s_dt = datetime.fromisoformat(r["start_iso"])
                    if s_dt <= now + timedelta(minutes=2):
                        upcoming.append((r, s_dt))
                except Exception:
                    continue

        if not upcoming:
            return

        currently_recording = [r for r in active_recordings if r.get("status") == "RECORDING"]

        for rec_a in currently_recording:
            try:
                ch_a = rec_a.get("channel", "").strip().lower()
                end_a_dt = datetime.fromisoformat(rec_a["end_iso"])

                for rec_b, s_b_dt in upcoming:
                    ch_b = rec_b.get("channel", "").strip().lower()
                    if ch_a != ch_b:
                        diff = (s_b_dt - end_a_dt).total_seconds()
                        if -60 <= diff <= 90 and now >= end_a_dt:
                            k_key = rec_a.get("kaffeine_key")
                            now_str = now.strftime('%Y-%m-%d %H:%M:%S')
                            print(
                                f"[{now_str}] Releasing tuner (handover): Stopping '{rec_a.get('title')}' "
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

        # Safeguard via D-Bus: if an upcoming show starts in <= 5 seconds,
        # ensure no active stream is running on another channel in Kaffeine
        for rec_b, s_b_dt in upcoming:
            secs_until_b = (s_b_dt - now).total_seconds()
            if 0 <= secs_until_b <= 5:
                ch_b = rec_b.get("channel", "").strip().lower()
                try:
                    active_dbus = self.dbus_client._list_via_dbus()
                    for entry in active_dbus:
                        if entry.get("is_running"):
                            e_ch = (entry.get("channel") or "").strip().lower()
                            if e_ch and e_ch != ch_b:
                                now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                                print(
                                    f"[{now_str}] Releasing tuner (D-Bus guard): Stopping running stream '{entry.get('name')}' "
                                    f"({entry.get('channel')}) {secs_until_b:.0f}s before '{rec_b.get('title')}' ({rec_b.get('channel')}) starts.",
                                    flush=True
                                )
                                self.dbus_client.cancel_recording(
                                    key=entry.get("id"),
                                    channel=entry.get("channel"),
                                    title=entry.get("name")
                                )
                except Exception as e:
                    print(f"Error checking D-Bus running streams: {e}", flush=True)

    def enforce_stale_recording_cleanup(self):
        """
        Watchdog that prevents runaway recordings from holding the tuner.
        1. If Kaffeine is running, queries active D-Bus schedule entries (is_running == True).
        2. If a running stream has exceeded its scheduled end time by more than 15s (or is already
           archived in history / cancelled from the queue), actively halts it via D-Bus to free the tuner.
        """
        if not self.dbus_client.is_running():
            return

        try:
            active_dbus = self.dbus_client._list_via_dbus()
        except Exception as e:
            print(f"Notice: Failed to query D-Bus schedule for stale cleanup: {e}", flush=True)
            return

        running_streams = [e for e in active_dbus if e.get("is_running")]
        if not running_streams:
            return

        now = datetime.now()
        active_queue = self.queue_mgr.list_queue(include_completed=False)

        for stream in running_streams:
            s_name = (stream.get("name") or "").strip().lower()
            s_ch = (stream.get("channel") or "").strip().lower()
            s_id = stream.get("id")

            # Check if this stream corresponds to an active recording in the queue
            matching_rec = None
            for rec in active_queue:
                r_ch = (rec.get("channel") or "").strip().lower()
                r_title = (rec.get("title") or "").strip().lower()
                r_key = rec.get("kaffeine_key")
                if (r_key and int(r_key) == int(s_id)) or (r_ch == s_ch and (r_title in s_name or s_name in r_title)):
                    matching_rec = rec
                    break

            if matching_rec:
                try:
                    end_dt = datetime.fromisoformat(matching_rec["end_iso"])
                    # If overdue by more than 15 seconds, actively halt it
                    if now > end_dt + timedelta(seconds=15):
                        now_str = now.strftime('%Y-%m-%d %H:%M:%S')
                        print(
                            f"[{now_str}] Stale Recording Watchdog: Halting overdue recording '{matching_rec['title']}' "
                            f"({matching_rec['channel']}) (ended at {matching_rec['end_iso']}) to free tuner.",
                            flush=True
                        )
                        self.dbus_client.cancel_recording(
                            key=s_id,
                            channel=matching_rec["channel"],
                            title=matching_rec["title"]
                        )
                        self.queue_mgr.archive_to_history(matching_rec["id"])
                except Exception as e:
                    print(f"Error evaluating stale queue recording: {e}", flush=True)
            else:
                # Not in active queue! Check if it was recently completed/archived to history in the last 2 hours
                try:
                    history = self.queue_mgr.list_history(limit=20)
                    for hist in history:
                        h_ch = (hist.get("channel") or "").strip().lower()
                        h_title = (hist.get("title") or "").strip().lower()
                        if h_ch == s_ch and (h_title in s_name or s_name in h_title):
                            now_str = now.strftime('%Y-%m-%d %H:%M:%S')
                            print(
                                f"[{now_str}] Stale Recording Watchdog: Halting completed history recording "
                                f"'{hist['title']}' ({hist['channel']}) still lingering on tuner.",
                                flush=True
                            )
                            self.dbus_client.cancel_recording(
                                key=s_id,
                                channel=hist["channel"],
                                title=hist["title"]
                            )
                            break
                except Exception as e:
                    print(f"Error evaluating stale history recording: {e}", flush=True)

    def enforce_zero_byte_recording_cleanup(self):
        """
        Watchdog that checks in-progress recordings (status == 'RECORDING').
        If a recording has been active for more than zero_byte_recording_timeout_secs
        (default 45s) and has received NO broadcast data (file is missing or <= 16KB),
        it cancels the dead recording in Kaffeine, cleans up the queue and stalled files,
        and immediately frees the hardware tuner.
        """
        if not self.dbus_client.is_running():
            return

        cfg = self.config_mgr
        timeout_threshold = getattr(cfg, "zero_byte_recording_timeout_secs", 8)
        now = datetime.now()
        active_queue = self.queue_mgr.list_queue(include_completed=False)
        rec_folder = self.storage_mgr.get_recording_folder()

        for rec in active_queue:
            if rec.get("status") != "RECORDING":
                continue

            try:
                start_dt = datetime.fromisoformat(rec["start_iso"])
                created_dt = datetime.fromisoformat(rec["created_at"]) if rec.get("created_at") else start_dt
                effective_start = max(start_dt, created_dt)
                elapsed = (now - effective_start).total_seconds()
            except Exception:
                continue

            if elapsed < timeout_threshold:
                continue

            title = rec.get("title", "")
            channel = rec.get("channel", "")
            qid = rec.get("id")
            k_key = rec.get("kaffeine_key")

            # Check if valid file exists and has written stream data (> 16 KB)
            has_data = False
            active_file = (
                self.storage_mgr.find_active_or_recent_recording_file(title, max_age_seconds=int(elapsed + 120), min_size_bytes=16384)
            )
            if active_file and active_file.exists():
                try:
                    if active_file.stat().st_size > 16384:
                        has_data = True
                except Exception:
                    pass

            # Fallback: scan recording folder for any recent video file modified since effective_start - 30s
            if not has_data and rec_folder and rec_folder.exists():
                try:
                    clean_title = re.sub(r'[^a-zA-Z0-9]', '', title).lower()
                    for ext in StorageManager.VIDEO_EXTENSIONS:
                        for vf in rec_folder.glob(f"*{ext}"):
                            try:
                                st = vf.stat()
                                if st.st_mtime >= (effective_start.timestamp() - 30):
                                    clean_stem = re.sub(r'[^a-zA-Z0-9]', '', vf.stem).lower()
                                    if clean_title in clean_stem or clean_stem in clean_title:
                                        if st.st_size > 16384:
                                            has_data = True
                                            break
                            except Exception:
                                pass
                        if has_data:
                            break
                except Exception:
                    pass

            if not has_data:
                now_str = now.strftime('%Y-%m-%d %H:%M:%S')
                print(
                    f"[{now_str}] Zero-Byte Watchdog: Recording '{title}' on channel {channel} "
                    f"has received 0 bytes of stream data after {int(elapsed)}s (weak/dead signal). "
                    f"Halting dead recording and removing from queue to free tuner.",
                    flush=True
                )

                # 1. Cancel in Kaffeine via D-Bus
                try:
                    self.dbus_client.cancel_recording(key=k_key, channel=channel, title=title)
                except Exception as e:
                    print(f"Error cancelling dead recording via D-Bus: {e}", flush=True)

                # 2. Remove from queue manager to release tuner reservation
                try:
                    self.queue_mgr.remove_recording(qid)
                except Exception as e:
                    print(f"Error removing dead recording from queue: {e}", flush=True)

                # 3. Clean up any 0-byte or corrupted header orphan files
                if rec_folder and rec_folder.exists():
                    try:
                        clean_title = re.sub(r'[^a-zA-Z0-9]', '', title).lower()
                        for ext in StorageManager.VIDEO_EXTENSIONS:
                            for vf in rec_folder.glob(f"*{ext}"):
                                try:
                                    st = vf.stat()
                                    if (now.timestamp() - st.st_mtime) < (elapsed + 60) and st.st_size <= 16384:
                                        clean_stem = re.sub(r'[^a-zA-Z0-9]', '', vf.stem).lower()
                                        if clean_title in clean_stem or clean_stem in clean_title:
                                            vf.unlink(missing_ok=True)
                                except Exception:
                                    pass
                    except Exception:
                        pass

                # 4. Send desktop notification if enabled
                if cfg.enable_desktop_notifications:
                    try:
                        send_desktop_notification(
                            title=f"Recording Aborted: {title}",
                            channel=channel,
                            start_display="No signal received (0 bytes). Tuner released.",
                            lead_mins=0,
                            persistent=False
                        )
                    except Exception:
                        pass

    def check_and_dispatch(self, notify: bool = True) -> int:
        self.reap_children()
        # Resolve any back-to-back buffer conflicts across different channels before arming
        self.queue_mgr.resolve_consecutive_buffer_conflicts(dbus_client=self.dbus_client)
        # Release tuner if any active recording has reached base end time and is lingering in buffer
        self.stop_lingering_buffers_for_upcoming_shows()
        # Enforce watchdog to clean up any stale running streams holding the tuner past end time
        self.enforce_stale_recording_cleanup()
        # Enforce watchdog to abort dead recordings receiving 0 bytes of data to free tuner
        self.enforce_zero_byte_recording_cleanup()
        due = self.queue_mgr.get_due_to_arm()
        armed_count = 0
        cfg = ConfigManager()

        for rec in due:
            title = rec["title"]
            channel = rec["channel"]
            start_iso = rec["start_iso"]
            rec_id = rec["id"]

            # Compute effective dispatch parameters (2s delayed start cheat for consecutive recordings on different channels)
            dispatch_start_iso, dispatch_dur_iso = self.queue_mgr.get_effective_dispatch_params(rec)
            if dispatch_start_iso != start_iso:
                now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                print(
                    f"[{now_str}] Tuner Handover Cheat: Offsetting start of '{title}' ({channel}) "
                    f"by +2s to {dispatch_start_iso} (dur: {dispatch_dur_iso}) to ensure preceding channel releases tuner.",
                    flush=True
                )

            now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            print(f"[{now_str}] Program due: '{title}' on {channel} at {dispatch_start_iso}. Arming into Kaffeine...", flush=True)
            try:
                # Ensure Kaffeine is running (launches if closed) and schedules via D-Bus
                if not self.dbus_client.is_running():
                    self.dbus_client.launch_kaffeine(mode=cfg.launch_mode)
                    for _ in range(20):
                        if self.dbus_client.is_running():
                            break
                        time.sleep(0.25)
                elif cfg.launch_mode in ("taskbar", "tray") or cfg.launch_minimized:
                    self.dbus_client.minimize_kaffeine(mode=cfg.launch_mode)
                kaff_channel = cfg.resolve_channel(channel)
                key = self.dbus_client.schedule_recording(title, kaff_channel, dispatch_start_iso, dispatch_dur_iso, 0)
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
            persistent = getattr(cfg, "persistent_desktop_notifications", False)
            notify_due = self.queue_mgr.get_due_for_notification(lead_time_mins=lead_mins)
            for nrec in notify_due:
                n_title = nrec["title"]
                n_channel = nrec["channel"]
                n_start_local = nrec.get("start_time_local", nrec["start_iso"])
                send_desktop_notification(n_title, n_channel, n_start_local, lead_mins=lead_mins, persistent=persistent)
                self.queue_mgr.mark_notified(nrec["id"])
                now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                print(f"[{now_str}] Desktop notification sent for '{n_title}' on {n_channel} (lead: {lead_mins}m, persistent: {persistent}).", flush=True)

        # Update in-progress and completed statuses (archive finished to history and actively halt in Kaffeine)
        status_res = self.queue_mgr.update_statuses([], max_history=cfg.max_history_entries, dbus_client=self.dbus_client)

        # Enforce internal background minimization if configured (tray or taskbar)
        if cfg.launch_mode in ("taskbar", "tray") or getattr(cfg, "launch_minimized", False):
            # 1. If any recording transitioned to RECORDING right now, Kaffeine's internal playDvb()
            # invokes QWidget::showNormal(). Start a short async monitor to immediately re-dock it.
            if status_res and status_res.get("started", 0) > 0:
                import threading
                threading.Thread(
                    target=self.dbus_client._minimize_window_async,
                    args=(cfg.launch_mode, 6.0, 2.5),
                    daemon=True
                ).start()

            # 2. If any recording is currently active (RECORDING) or armed (ARMED), ensure
            # Kaffeine remains minimized/docked in the tray so it never pops up on the desktop.
            try:
                active_recs = [
                    r for r in self.queue_mgr.list_queue(include_completed=False)
                    if r.get("status") in ("ARMED", "RECORDING")
                ]
                if active_recs and self.dbus_client.is_running():
                    self.dbus_client.minimize_kaffeine(mode=cfg.launch_mode)
            except Exception as e:
                print(f"Error asserting background minimization: {e}", flush=True)

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

    def _calculate_sleep_interval(self, default_interval: int) -> int:
        """
        Dynamically adjusts sleep interval:
        - If any recording is currently RECORDING or an upcoming show is due within 3 minutes:
          sleep 5 seconds for responsive tuner handover, buffer trimming, and prompt dispatch.
        - Otherwise, sleep the configured default interval.
        """
        try:
            active = self.queue_mgr.list_queue(include_completed=False)
            now = datetime.now()
            if any(r.get("status") == "RECORDING" for r in active):
                return 2
            for r in active:
                if r.get("status") in ("QUEUED", "ARMED"):
                    try:
                        s_dt = datetime.fromisoformat(r["start_iso"])
                        if s_dt <= now + timedelta(minutes=3):
                            return 5
                    except (KeyError, ValueError):
                        continue
        except Exception as e:
            print(f"Error calculating watcher sleep interval: {e}", flush=True)
        return max(5, default_interval)

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

            sleep_time = self._calculate_sleep_interval(interval_seconds)
            for _ in range(int(sleep_time)):
                if not self.running:
                    break
                time.sleep(1)
