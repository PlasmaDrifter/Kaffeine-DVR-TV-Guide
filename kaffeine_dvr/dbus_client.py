import os
import sqlite3
import subprocess
from pathlib import Path
from typing import List, Dict, Any, Optional
from datetime import datetime

class KaffeineDbusClient:
    def __init__(self, kaffeine_db_path: Optional[Path] = None):
        self.kaffeine_db_path = kaffeine_db_path or (Path.home() / ".local" / "share" / "kaffeine" / "sqlite.db")
        self.service_name = "org.mpris.kaffeine"
        self.object_path = "/Television"
        self.interface_name = "org.freedesktop.MediaPlayer"

    def is_running(self) -> bool:
        """Check if Kaffeine is active on the D-Bus session bus."""
        try:
            import dbus
            bus = dbus.SessionBus()
            return bool(bus.name_has_owner(self.service_name))
        except Exception:
            # Fallback to pgrep check
            res = subprocess.run(["pgrep", "-x", "kaffeine"], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            return res.returncode == 0

    def _get_display_env(self) -> Dict[str, str]:
        """Ensure WAYLAND_DISPLAY and DISPLAY exist when launched from background services."""
        env = os.environ.copy()
        if not env.get("WAYLAND_DISPLAY") and not env.get("DISPLAY"):
            runtime_dir = os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}"
            wayland_sockets = list(Path(runtime_dir).glob("wayland-*"))
            if wayland_sockets:
                env["WAYLAND_DISPLAY"] = wayland_sockets[0].name
            if not env.get("DISPLAY"):
                env["DISPLAY"] = ":0"
        return env

    def launch_kaffeine(self, mode: str = "taskbar", minimized: Optional[bool] = None) -> bool:
        """
        Start Kaffeine with the specified launch mode:
        - 'taskbar': start normal window and minimize to taskbar via window manager (kdotool/xdotool)
        - 'tray': start in minimal mode (-m) to dock into the system tray
        - 'normal': start normal visible application window
        """
        if self.is_running():
            return True
        if minimized is not None:
            mode = "taskbar" if minimized else "normal"
        try:
            env = self._get_display_env()
            cmd = ["kaffeine", "-m"] if mode == "tray" else ["kaffeine"]
            subprocess.Popen(cmd, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            if mode == "taskbar":
                import threading
                threading.Thread(target=self._minimize_window_async, daemon=True).start()

            # Wait up to 5 seconds for Kaffeine to register on D-Bus
            import time
            for _ in range(20):
                time.sleep(0.25)
                if self.is_running():
                    return True
            return True
        except Exception as e:
            print(f"Error launching kaffeine: {e}")
            return False

    def _minimize_window_async(self, timeout_sec: float = 6.0):
        """Poll briefly for Kaffeine's window to appear and minimize it to the taskbar."""
        import shutil
        import time

        kdotool_bin = shutil.which("kdotool")
        xdotool_bin = shutil.which("xdotool")

        if not kdotool_bin and not xdotool_bin:
            return

        start_time = time.time()
        while time.time() - start_time < timeout_sec:
            time.sleep(0.25)
            try:
                if kdotool_bin:
                    res = subprocess.run(
                        [kdotool_bin, "search", "--class", "kaffeine"],
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        text=True,
                        timeout=1.0
                    )
                    if res.stdout.strip():
                        subprocess.run(
                            [kdotool_bin, "search", "--class", "kaffeine", "windowminimize"],
                            stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL,
                            timeout=1.0
                        )
                        break
                elif xdotool_bin:
                    res = subprocess.run(
                        [xdotool_bin, "search", "--class", "kaffeine"],
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        text=True,
                        timeout=1.0
                    )
                    if res.stdout.strip():
                        wid = res.stdout.strip().split()[0]
                        subprocess.run(
                            [xdotool_bin, "windowminimize", wid],
                            stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL,
                            timeout=1.0
                        )
                        break
            except Exception:
                break


    def list_scheduled_recordings(self) -> List[Dict[str, Any]]:
        """
        List scheduled recordings. If Kaffeine is running, query via D-Bus.
        Otherwise, query directly from sqlite.db.
        """
        if self.is_running():
            try:
                return self._list_via_dbus()
            except Exception as e:
                print(f"D-Bus query failed, falling back to SQLite: {e}")

        return self._list_via_sqlite()

    def _list_via_dbus(self) -> List[Dict[str, Any]]:
        import dbus
        bus = dbus.SessionBus()
        proxy = bus.get_object(self.service_name, self.object_path)
        
        # Call ListProgramSchedule
        # Try through interface or direct method call
        try:
            iface = dbus.Interface(proxy, dbus_interface=self.interface_name)
            raw_entries = iface.ListProgramSchedule()
        except Exception:
            raw_entries = proxy.ListProgramSchedule()

        recordings = []
        for entry in raw_entries:
            # entry structure: (key, name, channel, begin, duration, repeat, isRunning)
            try:
                rec_id = int(entry[0])
                name = str(entry[1])
                channel = str(entry[2])
                begin = str(entry[3])
                duration = str(entry[4])
                repeat = int(entry[5])
                is_running = bool(entry[6])
                recordings.append({
                    "id": rec_id,
                    "name": name,
                    "channel": channel,
                    "begin": begin,
                    "duration": duration,
                    "repeat": repeat,
                    "is_running": is_running,
                    "disabled": False,
                    "source": "dbus"
                })
            except Exception as err:
                print(f"Error parsing D-Bus schedule entry: {err}")
        return recordings

    def _list_via_sqlite(self) -> List[Dict[str, Any]]:
        if not self.kaffeine_db_path.exists():
            return []
        recordings = []
        try:
            conn = sqlite3.connect(str(self.kaffeine_db_path))
            cur = conn.cursor()
            cur.execute("""
                SELECT Id, Name, Channel, Begin, Duration, Repeat, Disabled, Subheading, Details 
                FROM RecordingSchedule ORDER BY Begin ASC
            """)
            rows = cur.fetchall()
            for row in rows:
                rec_id, name, channel, begin, duration, repeat, disabled, sub, details = row
                recordings.append({
                    "id": rec_id,
                    "name": name or "Unknown",
                    "channel": channel or "",
                    "begin": begin or "",
                    "duration": duration or "",
                    "repeat": repeat or 0,
                    "is_running": False,
                    "disabled": bool(disabled),
                    "subheading": sub or "",
                    "details": details or "",
                    "source": "sqlite"
                })
            conn.close()
        except Exception as e:
            print(f"Error reading SQLite schedule: {e}")
        return recordings

    def schedule_recording(self, name: str, channel: str, begin_iso: str, duration_iso: str, repeat: int = 0) -> int:
        """
        Schedule a recording via D-Bus (if running) or direct SQLite insertion (if offline).
        begin_iso: e.g. '2026-10-07T20:00:00'
        duration_iso: e.g. '01:00:00'
        repeat: 0 for once, bitmask for recurring days
        Returns the new recording ID.
        """
        if self.is_running():
            # Try dbus-python call
            try:
                import dbus
                bus = dbus.SessionBus()
                proxy = bus.get_object(self.service_name, self.object_path)
                try:
                    iface = dbus.Interface(proxy, dbus_interface=self.interface_name)
                    key = iface.ScheduleProgram(name, channel, begin_iso, duration_iso, dbus.Int32(repeat))
                except Exception:
                    key = proxy.ScheduleProgram(name, channel, begin_iso, duration_iso, repeat)
                return int(key)
            except Exception as e:
                # Fallback to qdbus CLI
                cmd = [
                    "qdbus",
                    self.service_name,
                    self.object_path,
                    "ScheduleProgram",
                    name,
                    channel,
                    begin_iso,
                    duration_iso,
                    str(repeat)
                ]
                res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                if res.returncode == 0 and res.stdout.strip().isdigit():
                    return int(res.stdout.strip())
                print(f"D-Bus schedule call failed ({e}), attempting SQLite insertion fallback...")

        # Kaffeine is offline: direct SQLite insertion
        return self._schedule_via_sqlite(name, channel, begin_iso, duration_iso, repeat)

    def _schedule_via_sqlite(self, name: str, channel: str, begin_iso: str, duration_iso: str, repeat: int = 0) -> int:
        if not self.kaffeine_db_path.exists():
            raise FileNotFoundError(f"Kaffeine database not found at {self.kaffeine_db_path}")

        # Parse begin_iso and calculate UTC and end times
        try:
            from datetime import datetime, timedelta, timezone
            # parse local time
            dt_local = datetime.fromisoformat(begin_iso)
            dt_utc = dt_local.astimezone(timezone.utc)
            begin_utc_str = dt_utc.strftime("%Y-%m-%dT%H:%M:%SZ")

            # parse duration
            h, m, s = map(int, duration_iso.split(":"))
            dur_delta = timedelta(hours=h, minutes=m, seconds=s)
            end_local = dt_local + dur_delta
            end_local_str = end_local.strftime("%Y-%m-%dT%H:%M:%S")
            begin_local_str = dt_local.strftime("%Y-%m-%dT%H:%M:%S")
        except Exception:
            begin_utc_str = begin_iso + "Z" if not begin_iso.endswith("Z") else begin_iso
            begin_local_str = begin_iso
            end_local_str = begin_iso

        conn = sqlite3.connect(str(self.kaffeine_db_path))
        cur = conn.cursor()
        cur.execute("SELECT COALESCE(MAX(Id), 0) + 1 FROM RecordingSchedule")
        new_id = cur.fetchone()[0]

        cur.execute("""
            INSERT INTO RecordingSchedule (
                Id, Name, Channel, Begin, Duration, Repeat,
                Subheading, Details, beginEPG, endEPG, durationEPG, Priority, Disabled
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            new_id, name, channel, begin_utc_str, duration_iso, repeat,
            "", "", begin_local_str, end_local_str, duration_iso, 0, 0
        ))
        conn.commit()
        conn.close()
        return new_id


    def remove_recording(self, key: int) -> bool:
        """Cancel/remove a scheduled recording."""
        if not self.is_running():
            # If offline, remove directly from SQLite
            try:
                conn = sqlite3.connect(str(self.kaffeine_db_path))
                cur = conn.cursor()
                cur.execute("DELETE FROM RecordingSchedule WHERE Id = ?", (key,))
                conn.commit()
                conn.close()
                return True
            except Exception as e:
                print(f"Failed to delete recording from SQLite: {e}")
                return False

        try:
            import dbus
            bus = dbus.SessionBus()
            proxy = bus.get_object(self.service_name, self.object_path)
            try:
                iface = dbus.Interface(proxy, dbus_interface=self.interface_name)
                iface.RemoveProgram(dbus.UInt32(key))
            except Exception:
                proxy.RemoveProgram(key)
            return True
        except Exception as e:
            # Fallback to qdbus CLI
            res = subprocess.run(["qdbus", self.service_name, self.object_path, "RemoveProgram", str(key)],
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            return res.returncode == 0
