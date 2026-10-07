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
                created_at TEXT
            )
        """)
        cur.execute("CREATE INDEX IF NOT EXISTS idx_queue_status ON recording_queue(status)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_queue_start ON recording_queue(start_iso)")
        conn.commit()
        conn.close()

    def add_recording(self, title: str, channel: str, start_iso: str, duration_iso: str, lead_time_mins: int = 5) -> int:
        # Calculate end_iso and local display time
        try:
            dt_start = datetime.fromisoformat(start_iso)
            h, m, s = map(int, duration_iso.split(":"))
            dt_end = dt_start + timedelta(hours=h, minutes=m, seconds=s)
            end_iso = dt_end.strftime("%Y-%m-%dT%H:%M:%S")
            start_display = dt_start.strftime("%Y-%m-%d %I:%M %p")
        except Exception:
            end_iso = start_iso
            start_display = start_iso

        conn = sqlite3.connect(str(self.db_path))
        cur = conn.cursor()

        # Check for duplicates
        cur.execute("""
            SELECT id FROM recording_queue 
            WHERE channel = ? AND start_iso = ? AND status IN ('QUEUED', 'ARMED', 'RECORDING')
        """, (channel, start_iso))
        existing = cur.fetchone()
        if existing:
            conn.close()
            return existing[0]

        now_str = datetime.now().isoformat()
        cur.execute("""
            INSERT INTO recording_queue (
                title, channel, start_iso, duration_iso, start_time_local,
                end_iso, lead_time_mins, status, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, 'QUEUED', ?)
        """, (title, channel, start_iso, duration_iso, start_display, end_iso, lead_time_mins, now_str))
        new_id = cur.lastrowid
        conn.commit()
        conn.close()
        return new_id

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

    def update_statuses(self, active_kaffeine_keys: List[int]):
        """
        Transitions ARMED -> RECORDING -> COMPLETED based on current time and Kaffeine state.
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
                    cur.execute("UPDATE recording_queue SET status = 'COMPLETED' WHERE id = ?", (qid,))
                elif now >= start_dt:
                    cur.execute("UPDATE recording_queue SET status = 'RECORDING' WHERE id = ?", (qid,))
            except Exception:
                pass

        conn.commit()
        conn.close()
