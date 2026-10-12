import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple

class QueueManager:
    def __init__(self, data_dir: Optional[Path] = None):
        self.data_dir = data_dir or (Path.home() / ".local" / "share" / "kaffeine-dvr")
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = self.data_dir / "recordings_queue.sqlite"
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), timeout=15.0)
        conn.execute("PRAGMA journal_mode = WAL;")
        conn.execute("PRAGMA busy_timeout = 15000;")
        return conn

    def _init_db(self):
        conn = self._get_connection()
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS recording_queue (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT,
                channel TEXT,
                start_iso TEXT,
                duration_iso TEXT,
                start_time_local TEXT,
                end_iso TEXT,
                lead_time_mins INTEGER DEFAULT 5,
                status TEXT DEFAULT 'QUEUED',
                kaffeine_key INTEGER,
                created_at TEXT,
                protected INTEGER DEFAULT 0,
                file_path TEXT,
                buffer_mins INTEGER DEFAULT 0,
                notified INTEGER DEFAULT 0
            )
        """)
        # Safe migration for existing databases
        cur.execute("PRAGMA table_info(recording_queue)")
        existing_cols = {col[1] for col in cur.fetchall()}
        if "protected" not in existing_cols:
            cur.execute("ALTER TABLE recording_queue ADD COLUMN protected INTEGER DEFAULT 0")
        if "file_path" not in existing_cols:
            cur.execute("ALTER TABLE recording_queue ADD COLUMN file_path TEXT")
        if "buffer_mins" not in existing_cols:
            cur.execute("ALTER TABLE recording_queue ADD COLUMN buffer_mins INTEGER DEFAULT 0")
        if "notified" not in existing_cols:
            cur.execute("ALTER TABLE recording_queue ADD COLUMN notified INTEGER DEFAULT 0")

        cur.execute("CREATE INDEX IF NOT EXISTS idx_queue_status ON recording_queue(status)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_queue_start ON recording_queue(start_iso)")

        # Recording History Table
        cur.execute("""
            CREATE TABLE IF NOT EXISTS recording_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT,
                channel TEXT,
                start_iso TEXT,
                duration_iso TEXT,
                start_time_local TEXT,
                completed_at TEXT
            )
        """)
        cur.execute("CREATE INDEX IF NOT EXISTS idx_hist_start ON recording_history(start_iso)")

        # Migrate any legacy COMPLETED or PURGED records from recording_queue into history
        cur.execute("SELECT id, title, channel, start_iso, duration_iso, start_time_local, end_iso FROM recording_queue WHERE status IN ('COMPLETED', 'PURGED')")
        legacy_done = cur.fetchall()
        for l_id, l_title, l_chan, l_start, l_dur, l_local, l_end in legacy_done:
            cur.execute("""
                INSERT INTO recording_history (title, channel, start_iso, duration_iso, start_time_local, completed_at)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (l_title, l_chan, l_start, l_dur, l_local, l_end or datetime.now().isoformat()))
            cur.execute("DELETE FROM recording_queue WHERE id = ?", (l_id,))

        conn.commit()
        conn.close()

    def add_recording(
        self,
        title: str,
        channel: str,
        start_iso: str,
        duration_iso: str,
        lead_time_mins: int = 5,
        buffer_mins: int = 0
    ) -> int:
        # Calculate end_iso and buffered duration
        try:
            dt_start = datetime.fromisoformat(start_iso)
            h, m, s = map(int, duration_iso.split(":"))
            total_seconds = h * 3600 + m * 60 + s + (buffer_mins * 60)
            bh = total_seconds // 3600
            bm = (total_seconds % 3600) // 60
            bs = total_seconds % 60
            effective_duration_iso = f"{bh:02d}:{bm:02d}:{bs:02d}"

            dt_end = dt_start + timedelta(seconds=total_seconds)
            end_iso = dt_end.strftime("%Y-%m-%dT%H:%M:%S")
            start_display = dt_start.strftime("%Y-%m-%d %I:%M %p")
        except Exception:
            effective_duration_iso = duration_iso
            end_iso = start_iso
            start_display = start_iso

        conn = self._get_connection()
        cur = conn.cursor()

        # If the show has already started or is currently airing, mark notified = 1
        # so background watcher service only sends desktop notifications for future scheduled shows.
        is_already_started = False
        try:
            if dt_start <= datetime.now():
                is_already_started = True
        except Exception:
            pass
        initial_notified = 1 if is_already_started else 0

        # Check for duplicates or update if still QUEUED
        cur.execute("""
            SELECT id, status, buffer_mins FROM recording_queue 
            WHERE channel = ? AND start_iso = ? AND status IN ('QUEUED', 'ARMED', 'RECORDING')
        """, (channel, start_iso))
        existing = cur.fetchone()
        if existing:
            existing_id, existing_status, existing_buf = existing
            if existing_status == 'QUEUED':
                cur.execute("""
                    UPDATE recording_queue
                    SET title = ?, duration_iso = ?, start_time_local = ?,
                        end_iso = ?, lead_time_mins = ?, buffer_mins = ?,
                        notified = CASE WHEN ? = 1 THEN 1 ELSE notified END
                    WHERE id = ?
                """, (title, effective_duration_iso, start_display, end_iso, lead_time_mins, buffer_mins, initial_notified, existing_id))
                conn.commit()
            elif is_already_started:
                cur.execute("UPDATE recording_queue SET notified = 1 WHERE id = ?", (existing_id,))
                conn.commit()
            conn.close()
            self.resolve_consecutive_buffer_conflicts()
            return existing_id

        now_str = datetime.now().isoformat()
        cur.execute("""
            INSERT INTO recording_queue (
                title, channel, start_iso, duration_iso, start_time_local,
                end_iso, lead_time_mins, status, created_at, buffer_mins, notified
            ) VALUES (?, ?, ?, ?, ?, ?, ?, 'QUEUED', ?, ?, ?)
        """, (title, channel, start_iso, effective_duration_iso, start_display, end_iso, lead_time_mins, now_str, buffer_mins, initial_notified))
        new_id = cur.lastrowid
        conn.commit()
        conn.close()
        self.resolve_consecutive_buffer_conflicts()
        return int(new_id) if new_id is not None else 0

    def resolve_consecutive_buffer_conflicts(self, dbus_client=None) -> List[Dict[str, Any]]:
        """
        Detects back-to-back or consecutive scheduled recordings on different channels
        where an earlier show's post-roll end buffer would collide with a subsequent
        show's scheduled start time.

        Automatically clamps the earlier show's end buffer to prevent tuner lock
        contentions on single-tuner systems, ensuring the subsequent show starts on time.
        """
        conn = self._get_connection()
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("""
            SELECT id, title, channel, start_iso, duration_iso, end_iso, buffer_mins, status, kaffeine_key
            FROM recording_queue
            WHERE status IN ('QUEUED', 'ARMED', 'RECORDING')
            ORDER BY start_iso ASC, id ASC
        """)
        rows = [dict(r) for r in cur.fetchall()]
        conn.close()

        if len(rows) < 2:
            return []

        # Parse schedule records
        parsed = []
        for r in rows:
            try:
                start_dt = datetime.fromisoformat(r["start_iso"])
                h, m, s = map(int, r["duration_iso"].split(":"))
                total_secs = h * 3600 + m * 60 + s
                buf_mins = int(r.get("buffer_mins") or 0)
                base_secs = max(0, total_secs - (buf_mins * 60))
                base_end_dt = start_dt + timedelta(seconds=base_secs)
                buffered_end_dt = start_dt + timedelta(seconds=total_secs)
                parsed.append({
                    "id": r["id"],
                    "title": r["title"],
                    "channel": r["channel"].strip(),
                    "status": r["status"],
                    "kaffeine_key": r["kaffeine_key"],
                    "start_dt": start_dt,
                    "start_iso": r["start_iso"],
                    "base_secs": base_secs,
                    "base_end_dt": base_end_dt,
                    "buf_mins": buf_mins,
                    "buffered_end_dt": buffered_end_dt
                })
            except Exception:
                continue

        modified = []

        for i in range(len(parsed)):
            rec_a = parsed[i]

            for j in range(i + 1, len(parsed)):
                rec_b = parsed[j]
                # If rec_b starts after rec_a's buffered end by more than 60s, no collision
                if rec_b["start_dt"] >= rec_a["buffered_end_dt"] + timedelta(seconds=60):
                    continue

                # Check if on different channels
                if rec_a["channel"].lower() != rec_b["channel"].lower():
                    gap_secs = (rec_b["start_dt"] - rec_a["base_end_dt"]).total_seconds()

                    # CASE 1: Back-to-back handover on different channels (|gap| <= 60s)
                    if abs(gap_secs) <= 60:
                        old_buf = rec_a["buf_mins"]
                        rec_a["buf_mins"] = 0

                        # Stop rec_a 5 seconds early (target end is rec_b["start_dt"] - 5s)
                        target_end_a = rec_b["start_dt"] - timedelta(seconds=5)
                        new_total_secs = max(30, int((target_end_a - rec_a["start_dt"]).total_seconds()))
                        rec_a["buffered_end_dt"] = target_end_a
                        rec_a["base_end_dt"] = target_end_a

                        bh = new_total_secs // 3600
                        bm = (new_total_secs % 3600) // 60
                        bs = new_total_secs % 60
                        new_dur_iso = f"{bh:02d}:{bm:02d}:{bs:02d}"
                        new_end_iso = target_end_a.strftime("%Y-%m-%dT%H:%M:%S")

                        # Persist to database if changed
                        if (rec_a.get("duration_iso") != new_dur_iso) or (old_buf != 0):
                            rec_a["duration_iso"] = new_dur_iso
                            rec_a["end_iso"] = new_end_iso

                            conn = self._get_connection()
                            c = conn.cursor()
                            c.execute("""
                                UPDATE recording_queue
                                SET duration_iso = ?, end_iso = ?, buffer_mins = 0
                                WHERE id = ?
                            """, (new_dur_iso, new_end_iso, rec_a["id"]))
                            conn.commit()
                            conn.close()

                            # If armed in Kaffeine, update the active Kaffeine timer
                            if rec_a["status"] == "ARMED" and rec_a["kaffeine_key"] and dbus_client:
                                try:
                                    dbus_client.remove_recording(rec_a["kaffeine_key"])
                                    new_key = dbus_client.schedule_recording(
                                        rec_a["title"], rec_a["channel"],
                                        rec_a["start_iso"], new_dur_iso, 0
                                    )
                                    if new_key and new_key > 0:
                                        conn = self._get_connection()
                                        c = conn.cursor()
                                        c.execute("UPDATE recording_queue SET kaffeine_key = ? WHERE id = ?", (new_key, rec_a["id"]))
                                        conn.commit()
                                        conn.close()
                                        rec_a["kaffeine_key"] = new_key
                                except Exception as e:
                                    print(f"Error updating Kaffeine timer for '{rec_a['title']}': {e}")

                            # If already in Kaffeine schedule, also sync new duration to Kaffeine's sqlite.db
                            if rec_a["kaffeine_key"]:
                                try:
                                    k_db = Path.home() / ".local" / "share" / "kaffeine" / "sqlite.db"
                                    if k_db.exists():
                                        k_conn = sqlite3.connect(str(k_db))
                                        k_cur = k_conn.cursor()
                                        k_cur.execute("UPDATE RecordingSchedule SET Duration = ? WHERE Id = ?", (new_dur_iso, rec_a["kaffeine_key"]))
                                        k_conn.commit()
                                        k_conn.close()
                                except Exception as e:
                                    print(f"Error syncing Duration to Kaffeine sqlite.db: {e}")

                            now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                            print(
                                f"[{now_str}] Back-to-Back Handover Tuned: Stopped '{rec_a['title']}' ({rec_a['channel']}) "
                                f"5s early at {new_end_iso} (dur: {new_dur_iso}, buffer: 0m) for consecutive show "
                                f"'{rec_b['title']}' ({rec_b['channel']}) starting at {rec_b['start_iso']}.",
                                flush=True
                            )
                            modified.append({
                                "id": rec_a["id"],
                                "title": rec_a["title"],
                                "channel": rec_a["channel"],
                                "old_buffer": old_buf,
                                "new_buffer": 0,
                                "next_title": rec_b["title"],
                                "next_channel": rec_b["channel"]
                            })

                    # CASE 2: Not back-to-back, but buffer of rec_a extends into rec_b
                    elif gap_secs > 60 and rec_b["start_dt"] < rec_a["buffered_end_dt"]:
                        allowed_buffer_secs = max(0, int((rec_b["start_dt"] - rec_a["base_end_dt"]).total_seconds()) - 5)
                        clamped_buf_mins = allowed_buffer_secs // 60

                        if clamped_buf_mins < rec_a["buf_mins"]:
                            old_buf = rec_a["buf_mins"]
                            rec_a["buf_mins"] = clamped_buf_mins
                            new_total_secs = rec_a["base_secs"] + (clamped_buf_mins * 60)
                            rec_a["buffered_end_dt"] = rec_a["start_dt"] + timedelta(seconds=new_total_secs)

                            bh = new_total_secs // 3600
                            bm = (new_total_secs % 3600) // 60
                            bs = new_total_secs % 60
                            new_dur_iso = f"{bh:02d}:{bm:02d}:{bs:02d}"
                            new_end_iso = rec_a["buffered_end_dt"].strftime("%Y-%m-%dT%H:%M:%S")

                            # Persist to database
                            conn = self._get_connection()
                            c = conn.cursor()
                            c.execute("""
                                UPDATE recording_queue
                                SET duration_iso = ?, end_iso = ?, buffer_mins = ?
                                WHERE id = ?
                            """, (new_dur_iso, new_end_iso, clamped_buf_mins, rec_a["id"]))
                            conn.commit()
                            conn.close()

                            # If armed in Kaffeine, update the active Kaffeine timer
                            if rec_a["status"] == "ARMED" and rec_a["kaffeine_key"] and dbus_client:
                                try:
                                    dbus_client.remove_recording(rec_a["kaffeine_key"])
                                    new_key = dbus_client.schedule_recording(
                                        rec_a["title"], rec_a["channel"],
                                        rec_a["start_iso"], new_dur_iso, 0
                                    )
                                    if new_key and new_key > 0:
                                        conn = self._get_connection()
                                        c = conn.cursor()
                                        c.execute("UPDATE recording_queue SET kaffeine_key = ? WHERE id = ?", (new_key, rec_a["id"]))
                                        conn.commit()
                                        conn.close()
                                        rec_a["kaffeine_key"] = new_key
                                except Exception as e:
                                    print(f"Error updating Kaffeine timer for '{rec_a['title']}': {e}")

                            # If already in Kaffeine schedule, also sync new duration to Kaffeine's sqlite.db
                            if rec_a["kaffeine_key"]:
                                try:
                                    k_db = Path.home() / ".local" / "share" / "kaffeine" / "sqlite.db"
                                    if k_db.exists():
                                        k_conn = sqlite3.connect(str(k_db))
                                        k_cur = k_conn.cursor()
                                        k_cur.execute("UPDATE RecordingSchedule SET Duration = ? WHERE Id = ?", (new_dur_iso, rec_a["kaffeine_key"]))
                                        k_conn.commit()
                                        k_conn.close()
                                except Exception as e:
                                    print(f"Error syncing Duration to Kaffeine sqlite.db: {e}")

                            now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                            print(
                                f"[{now_str}] Buffer Conflict Resolved: Clamped end buffer for '{rec_a['title']}' "
                                f"({rec_a['channel']}) from {old_buf}m to {clamped_buf_mins}m to allow consecutive show "
                                f"'{rec_b['title']}' ({rec_b['channel']}) to start on time at {rec_b['start_iso']}.",
                                flush=True
                            )
                            modified.append({
                                "id": rec_a["id"],
                                "title": rec_a["title"],
                                "channel": rec_a["channel"],
                                "old_buffer": old_buf,
                                "new_buffer": clamped_buf_mins,
                                "next_title": rec_b["title"],
                                "next_channel": rec_b["channel"]
                            })

        return modified

    def get_effective_dispatch_params(self, rec: Dict[str, Any]) -> Tuple[str, str]:
        """
        Determines the exact begin_iso and duration_iso to send to Kaffeine.
        If this recording is consecutive with an earlier recording on a different channel
        (predecessor finishes within 60s of this recording's start), applies a 2-second
        delayed start cheat (start + 2s, duration - 2s) to give the tuner hardware a
        guaranteed clear window to release and retune.
        """
        try:
            start_dt = datetime.fromisoformat(rec["start_iso"])
            h, m, s = map(int, rec["duration_iso"].split(":"))
            total_secs = h * 3600 + m * 60 + s
            ch = (rec.get("channel") or "").strip().lower()

            conn = self._get_connection()
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()
            cur.execute("""
                SELECT channel, end_iso, status FROM recording_queue
                WHERE id != ? AND status IN ('QUEUED', 'ARMED', 'RECORDING')
            """, (rec["id"],))
            rows = [dict(r) for r in cur.fetchall()]
            conn.close()

            for r in rows:
                r_ch = (r.get("channel") or "").strip().lower()
                if r_ch == ch:
                    continue
                try:
                    r_end = datetime.fromisoformat(r["end_iso"])
                    diff = (start_dt - r_end).total_seconds()
                    # If predecessor ends between 60s before and 60s after start_dt
                    if -60 <= diff <= 60:
                        adj_start = start_dt + timedelta(seconds=2)
                        adj_secs = max(30, total_secs - 2)
                        adj_start_iso = adj_start.strftime("%Y-%m-%dT%H:%M:%S")
                        ah = adj_secs // 3600
                        am = (adj_secs % 3600) // 60
                        as_sec = adj_secs % 60
                        adj_dur_iso = f"{ah:02d}:{am:02d}:{as_sec:02d}"
                        return adj_start_iso, adj_dur_iso
                except Exception:
                    continue
        except Exception as e:
            print(f"Error computing dispatch params: {e}")

        return rec["start_iso"], rec["duration_iso"]

    def update_recording_buffer(self, queue_id: int, new_buffer_mins: int) -> bool:
        """
        Updates the buffer_mins of an existing QUEUED recording and recalculates
        its duration_iso and end_iso.
        """
        conn = self._get_connection()
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("SELECT * FROM recording_queue WHERE id = ?", (queue_id,))
        row = cur.fetchone()
        if not row or row["status"] != "QUEUED":
            conn.close()
            return False

        try:
            start_iso = row["start_iso"]
            curr_dur_iso = row["duration_iso"]
            curr_buf = row["buffer_mins"] or 0

            # Compute original base duration seconds by subtracting current buffer
            h, m, s = map(int, curr_dur_iso.split(":"))
            total_current_secs = h * 3600 + m * 60 + s
            base_secs = max(0, total_current_secs - (curr_buf * 60))

            # Apply new buffer
            new_total_secs = base_secs + (new_buffer_mins * 60)
            bh = new_total_secs // 3600
            bm = (new_total_secs % 3600) // 60
            bs = new_total_secs % 60
            new_dur_iso = f"{bh:02d}:{bm:02d}:{bs:02d}"

            dt_start = datetime.fromisoformat(start_iso)
            dt_end = dt_start + timedelta(seconds=new_total_secs)
            new_end_iso = dt_end.strftime("%Y-%m-%dT%H:%M:%S")

            cur.execute("""
                UPDATE recording_queue
                SET duration_iso = ?, end_iso = ?, buffer_mins = ?
                WHERE id = ?
            """, (new_dur_iso, new_end_iso, new_buffer_mins, queue_id))
            conn.commit()
            conn.close()
            self.resolve_consecutive_buffer_conflicts()
            return True
        except Exception as e:
            print(f"Error updating buffer for recording {queue_id}: {e}")
            conn.close()
            return False

    def list_queue(self, include_completed: bool = False) -> List[Dict[str, Any]]:
        conn = self._get_connection()
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        if include_completed:
            cur.execute("SELECT * FROM recording_queue ORDER BY start_iso ASC")
        else:
            cur.execute("SELECT * FROM recording_queue WHERE status IN ('QUEUED', 'ARMED', 'RECORDING') ORDER BY start_iso ASC")
        rows = [dict(r) for r in cur.fetchall()]
        conn.close()
        return rows

    def get_active_scheduled_map(self) -> Dict[Any, Dict[str, Any]]:
        """
        Returns a mapping of (channel_lower, start_iso[:16]) -> recording_dict
        for all active recordings ('QUEUED', 'ARMED', 'RECORDING').
        """
        active = self.list_queue(include_completed=False)
        mapping = {}
        for r in active:
            ch = r.get("channel", "").strip().lower()
            start = r.get("start_iso", "")[:16]
            if ch and start:
                mapping[(ch, start)] = r
        return mapping

    def get_history_map(self, limit: int = 200) -> Dict[Any, Dict[str, Any]]:
        """
        Returns a mapping of (channel_lower, start_iso[:16]) -> history_dict
        for past completed recordings in recording_history.
        """
        history = self.list_history(limit=limit)
        mapping = {}
        for r in history:
            ch = r.get("channel", "").strip().lower()
            start = r.get("start_iso", "")[:16]
            if ch and start:
                mapping[(ch, start)] = r
        return mapping

    def remove_recording(self, queue_id: int) -> Optional[Dict[str, Any]]:
        """
        Removes/cancels a recording from queue. Returns the recording's details dictionary
        (including kaffeine_key, channel, title, start_iso) so Kaffeine timers can be purged.
        """
        conn = self._get_connection()
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("SELECT * FROM recording_queue WHERE id = ?", (queue_id,))
        row = cur.fetchone()
        if not row:
            conn.close()
            return None
        rec_data = dict(row)
        cur.execute("DELETE FROM recording_queue WHERE id = ?", (queue_id,))
        conn.commit()
        conn.close()
        return rec_data

    def get_due_to_arm(self) -> List[Dict[str, Any]]:
        """
        Returns recordings in 'QUEUED' status where current_time >= (start_time - lead_time_mins)
        and current_time < end_time.
        """
        conn = self._get_connection()
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("SELECT * FROM recording_queue WHERE status = 'QUEUED' ORDER BY start_iso ASC")
        queued = [dict(r) for r in cur.fetchall()]
        conn.close()

        now = datetime.now()
        due = []
        for rec in queued:
            try:
                start_dt = datetime.fromisoformat(rec["start_iso"])
                end_dt = datetime.fromisoformat(rec["end_iso"])
                lead = timedelta(minutes=rec.get("lead_time_mins", 5))
                # Arm if we are within the lead time window before start, or if already started but before end
                if (now >= start_dt - lead) and (now < end_dt):
                    due.append(rec)
            except Exception as e:
                print(f"Error parsing queue timestamps: {e}")
        return due

    def mark_armed(self, queue_id: int, kaffeine_key: int):
        conn = self._get_connection()
        cur = conn.cursor()
        cur.execute("UPDATE recording_queue SET status = 'ARMED', kaffeine_key = ? WHERE id = ?", (kaffeine_key, queue_id))
        conn.commit()
        conn.close()

    def get_due_for_notification(self, lead_time_mins: int = 0) -> List[Dict[str, Any]]:
        """
        Returns active recordings ('QUEUED', 'ARMED', 'RECORDING') where notified == 0,
        now >= (start_time - lead_time_mins), and now < end_time.
        """
        conn = self._get_connection()
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("""
            SELECT * FROM recording_queue
            WHERE (notified = 0 OR notified IS NULL)
              AND status IN ('QUEUED', 'ARMED', 'RECORDING')
            ORDER BY start_iso ASC
        """)
        items = [dict(r) for r in cur.fetchall()]
        conn.close()

        now = datetime.now()
        due = []
        for rec in items:
            try:
                start_dt = datetime.fromisoformat(rec["start_iso"])
                end_dt = datetime.fromisoformat(rec["end_iso"])
                lead = timedelta(minutes=max(0, lead_time_mins))
                if (now >= start_dt - lead) and (now < end_dt):
                    due.append(rec)
            except Exception as e:
                print(f"Error parsing timestamps for notification: {e}")
        return due

    def mark_notified(self, queue_id: int):
        """Marks a recording as notified so desktop notifications are only sent once."""
        conn = self._get_connection()
        cur = conn.cursor()
        cur.execute("UPDATE recording_queue SET notified = 1 WHERE id = ?", (queue_id,))
        conn.commit()
        conn.close()

    def archive_to_history(self, queue_id: int):
        """Immediately moves a completed or stopped recording into history."""
        conn = self._get_connection()
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("SELECT * FROM recording_queue WHERE id = ?", (queue_id,))
        rec = cur.fetchone()
        if rec:
            now_iso = datetime.now().isoformat()
            cur.execute("""
                INSERT INTO recording_history (title, channel, start_iso, duration_iso, start_time_local, completed_at)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (
                rec["title"], rec["channel"], rec["start_iso"],
                rec["duration_iso"], rec["start_time_local"], now_iso
            ))
            cur.execute("DELETE FROM recording_queue WHERE id = ?", (queue_id,))
            conn.commit()
        conn.close()

    def update_statuses(self, active_kaffeine_keys: List[int], max_history: int = 50):
        """
        Transitions ARMED -> RECORDING, and when finished (now >= end_dt),
        archives recording to recording_history and removes from active recording_queue.
        """
        conn = self._get_connection()
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("SELECT * FROM recording_queue WHERE status IN ('ARMED', 'RECORDING')")
        active = [dict(r) for r in cur.fetchall()]
        
        now = datetime.now()
        for rec in active:
            try:
                start_dt = datetime.fromisoformat(rec["start_iso"])
                end_dt = datetime.fromisoformat(rec["end_iso"])
                qid = rec["id"]

                if now >= end_dt:
                    # Archive to history
                    cur.execute("""
                        INSERT INTO recording_history (title, channel, start_iso, duration_iso, start_time_local, completed_at)
                        VALUES (?, ?, ?, ?, ?, ?)
                    """, (
                        rec.get("title", ""),
                        rec.get("channel", ""),
                        rec.get("start_iso", ""),
                        rec.get("duration_iso", ""),
                        rec.get("start_time_local", ""),
                        now.isoformat()
                    ))
                    # Remove from active queue
                    cur.execute("DELETE FROM recording_queue WHERE id = ?", (qid,))
                elif now >= start_dt:
                    cur.execute("UPDATE recording_queue SET status = 'RECORDING' WHERE id = ?", (qid,))
            except Exception as e:
                print(f"Error updating status for recording {rec.get('id')}: {e}")

        conn.commit()
        conn.close()

        # Prune history to max configured limit
        self.prune_history(max_history)

    def toggle_protected(self, queue_id: int) -> bool:
        """Toggles the protected status of a recording."""
        conn = self._get_connection()
        cur = conn.cursor()
        cur.execute("SELECT protected FROM recording_queue WHERE id = ?", (queue_id,))
        row = cur.fetchone()
        if not row:
            conn.close()
            return False
        new_val = 0 if row[0] else 1
        cur.execute("UPDATE recording_queue SET protected = ? WHERE id = ?", (new_val, queue_id))
        conn.commit()
        conn.close()
        return bool(new_val)

    def get_protected_paths(self) -> set:
        """Returns set of file_path strings that are protected."""
        conn = self._get_connection()
        cur = conn.cursor()
        cur.execute("SELECT file_path FROM recording_queue WHERE protected = 1 AND file_path IS NOT NULL")
        paths = {row[0] for row in cur.fetchall() if row[0]}
        conn.close()
        return paths

    def mark_file_purged(self, file_path_str: str):
        """
        When a recording file is deleted/purged, removes its listing from the schedule.
        """
        conn = self._get_connection()
        cur = conn.cursor()
        cur.execute("DELETE FROM recording_queue WHERE file_path = ?", (file_path_str,))
        conn.commit()
        conn.close()

    def set_recording_file(self, queue_id: int, file_path_str: str):
        """Links recorded file path to queue item."""
        conn = self._get_connection()
        cur = conn.cursor()
        cur.execute("UPDATE recording_queue SET file_path = ? WHERE id = ?", (file_path_str, queue_id))
        conn.commit()
        conn.close()

    # ------------------ RECORDING HISTORY METHODS ------------------

    def add_history_entry(
        self,
        title: str,
        channel: str,
        start_iso: str,
        duration_iso: str,
        start_time_local: str = "",
        completed_at: Optional[str] = None,
        max_entries: int = 50
    ) -> int:
        """Directly adds an entry into the recording history table."""
        comp = completed_at or datetime.now().isoformat()
        conn = self._get_connection()
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO recording_history (title, channel, start_iso, duration_iso, start_time_local, completed_at)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (title, channel, start_iso, duration_iso, start_time_local, comp))
        new_id = cur.lastrowid
        conn.commit()
        conn.close()

        self.prune_history(max_entries)
        return int(new_id) if new_id is not None else 0

    def list_history(self, limit: Optional[int] = None) -> List[Dict[str, Any]]:
        """Returns recorded history sorted newest first."""
        conn = self._get_connection()
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        if limit and limit > 0:
            cur.execute("SELECT * FROM recording_history ORDER BY id DESC LIMIT ?", (limit,))
        else:
            cur.execute("SELECT * FROM recording_history ORDER BY id DESC")
        rows = [dict(r) for r in cur.fetchall()]
        conn.close()
        return rows

    def delete_history_entry(self, history_id: int) -> bool:
        """Deletes a single history entry by ID."""
        conn = self._get_connection()
        cur = conn.cursor()
        cur.execute("DELETE FROM recording_history WHERE id = ?", (history_id,))
        deleted = cur.rowcount > 0
        conn.commit()
        conn.close()
        return deleted

    def clear_all_history(self) -> bool:
        """Clears all records in recording history."""
        conn = self._get_connection()
        cur = conn.cursor()
        cur.execute("DELETE FROM recording_history")
        conn.commit()
        conn.close()
        return True

    def prune_history(self, max_entries: int):
        """
        Retains only the newest `max_entries` records in recording_history,
        removing the oldest entries exceeding the threshold.
        """
        if max_entries <= 0:
            return
        conn = self._get_connection()
        cur = conn.cursor()
        # Delete entries where ID is not among the top max_entries
        cur.execute("""
            DELETE FROM recording_history
            WHERE id NOT IN (
                SELECT id FROM recording_history
                ORDER BY id DESC
                LIMIT ?
            )
        """, (max_entries,))
        conn.commit()
        conn.close()
