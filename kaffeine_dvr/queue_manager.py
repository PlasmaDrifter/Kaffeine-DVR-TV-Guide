import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Dict, Any, Optional

class QueueManager:
    def __init__(self, data_dir: Optional[Path] = None):
        self.data_dir = data_dir or (Path.home() / ".local" / "share" / "kaffeine-dvr")
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = self.data_dir / "recordings_queue.sqlite"
        self._init_db()

    def _init_db(self):
        conn = sqlite3.connect(str(self.db_path))
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
                buffer_mins INTEGER DEFAULT 0
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

        conn = sqlite3.connect(str(self.db_path))
        cur = conn.cursor()

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
                        end_iso = ?, lead_time_mins = ?, buffer_mins = ?
                    WHERE id = ?
                """, (title, effective_duration_iso, start_display, end_iso, lead_time_mins, buffer_mins, existing_id))
                conn.commit()
            conn.close()
            return existing_id

        now_str = datetime.now().isoformat()
        cur.execute("""
            INSERT INTO recording_queue (
                title, channel, start_iso, duration_iso, start_time_local,
                end_iso, lead_time_mins, status, created_at, buffer_mins
            ) VALUES (?, ?, ?, ?, ?, ?, ?, 'QUEUED', ?, ?)
        """, (title, channel, start_iso, effective_duration_iso, start_display, end_iso, lead_time_mins, now_str, buffer_mins))
        new_id = cur.lastrowid
        conn.commit()
        conn.close()
        return new_id

    def update_recording_buffer(self, queue_id: int, new_buffer_mins: int) -> bool:
        """
        Updates the buffer_mins of an existing QUEUED recording and recalculates
        its duration_iso and end_iso.
        """
        conn = sqlite3.connect(str(self.db_path))
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
            return True
        except Exception as e:
            print(f"Error updating buffer for recording {queue_id}: {e}")
            conn.close()
            return False

    def list_queue(self, include_completed: bool = False) -> List[Dict[str, Any]]:
        conn = sqlite3.connect(str(self.db_path))
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

    def remove_recording(self, queue_id: int) -> Optional[int]:
        """
        Removes/cancels from queue. Returns the kaffeine_key if it was armed.
        """
        conn = sqlite3.connect(str(self.db_path))
        cur = conn.cursor()
        cur.execute("SELECT kaffeine_key, status FROM recording_queue WHERE id = ?", (queue_id,))
        row = cur.fetchone()
        if not row:
            conn.close()
            return None
        k_key, status = row
        cur.execute("DELETE FROM recording_queue WHERE id = ?", (queue_id,))
        conn.commit()
        conn.close()
        return k_key if (k_key and status in ('ARMED', 'RECORDING')) else None

    def get_due_to_arm(self) -> List[Dict[str, Any]]:
        """
        Returns recordings in 'QUEUED' status where current_time >= (start_time - lead_time_mins)
        and current_time < end_time.
        """
        conn = sqlite3.connect(str(self.db_path))
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
        conn = sqlite3.connect(str(self.db_path))
        cur = conn.cursor()
        cur.execute("UPDATE recording_queue SET status = 'ARMED', kaffeine_key = ? WHERE id = ?", (kaffeine_key, queue_id))
        conn.commit()
        conn.close()

    def update_statuses(self, active_kaffeine_keys: List[int], max_history: int = 50):
        """
        Transitions ARMED -> RECORDING, and when finished (now >= end_dt),
        archives recording to recording_history and removes from active recording_queue.
        """
        conn = sqlite3.connect(str(self.db_path))
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
        conn = sqlite3.connect(str(self.db_path))
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
        conn = sqlite3.connect(str(self.db_path))
        cur = conn.cursor()
        cur.execute("SELECT file_path FROM recording_queue WHERE protected = 1 AND file_path IS NOT NULL")
        paths = {row[0] for row in cur.fetchall() if row[0]}
        conn.close()
        return paths

    def mark_file_purged(self, file_path_str: str):
        """
        When a recording file is deleted/purged, removes its listing from the schedule.
        """
        conn = sqlite3.connect(str(self.db_path))
        cur = conn.cursor()
        cur.execute("DELETE FROM recording_queue WHERE file_path = ?", (file_path_str,))
        conn.commit()
        conn.close()

    def set_recording_file(self, queue_id: int, file_path_str: str):
        """Links recorded file path to queue item."""
        conn = sqlite3.connect(str(self.db_path))
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
        conn = sqlite3.connect(str(self.db_path))
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO recording_history (title, channel, start_iso, duration_iso, start_time_local, completed_at)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (title, channel, start_iso, duration_iso, start_time_local, comp))
        new_id = cur.lastrowid
        conn.commit()
        conn.close()

        self.prune_history(max_entries)
        return new_id

    def list_history(self, limit: Optional[int] = None) -> List[Dict[str, Any]]:
        """Returns recorded history sorted newest first."""
        conn = sqlite3.connect(str(self.db_path))
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
        conn = sqlite3.connect(str(self.db_path))
        cur = conn.cursor()
        cur.execute("DELETE FROM recording_history WHERE id = ?", (history_id,))
        deleted = cur.rowcount > 0
        conn.commit()
        conn.close()
        return deleted

    def clear_all_history(self) -> bool:
        """Clears all records in recording history."""
        conn = sqlite3.connect(str(self.db_path))
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
        conn = sqlite3.connect(str(self.db_path))
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
