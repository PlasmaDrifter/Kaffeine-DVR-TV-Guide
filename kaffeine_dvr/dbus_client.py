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

    @staticmethod
    def get_kaffeine_bin() -> str:
        """
        Locate the preferred Kaffeine executable:
        1. Custom path override if configured in config.json.
        2. Standard user installation ~/.local/bin/kaffeine (if present and executable).
        3. System PATH lookup via shutil.which("kaffeine").
        4. Standard distribution location /usr/bin/kaffeine.
        """
        import shutil
        try:
            from .config import ConfigManager
            cfg = ConfigManager()
            if cfg.custom_kaffeine_path:
                cpath = Path(cfg.custom_kaffeine_path)
                if cpath.is_file() and os.access(cpath, os.X_OK):
                    return str(cpath)
        except Exception:
            pass

        local_bin = Path.home() / ".local" / "bin" / "kaffeine"
        if local_bin.is_file() and os.access(local_bin, os.X_OK):
            return str(local_bin)

        which_bin = shutil.which("kaffeine")
        if which_bin:
            return which_bin

        return "/usr/bin/kaffeine"

    def is_running(self) -> bool:
        """Check if Kaffeine is active on the D-Bus session bus."""
        try:
            import dbus
            bus = dbus.SessionBus()
            if bool(bus.name_has_owner(self.service_name)):
                return True
        except Exception:
            pass

        # Fallback to checking active (non-zombie) kaffeine process
        try:
            res = subprocess.run(["pgrep", "-x", "kaffeine"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            if res.returncode != 0:
                return False
            pids = res.stdout.strip().split()
            for p in pids:
                try:
                    with open(f"/proc/{p}/status", "r") as f:
                        for line in f:
                            if line.startswith("State:"):
                                if "Z" not in line:  # Exclude zombie / defunct
                                    return True
                except (FileNotFoundError, ProcessLookupError, PermissionError):
                    continue
            return False
        except Exception:
            return False

    def _get_display_env(self) -> Dict[str, str]:
        """Ensure WAYLAND_DISPLAY, DISPLAY, XAUTHORITY, QT_QPA_PLATFORM, and KDE desktop environment variables exist."""
        env = os.environ.copy()
        runtime_dir_str = env.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}"
        runtime_dir = Path(runtime_dir_str)

        # Ensure PATH contains ~/.local/bin
        local_bin = str(Path.home() / ".local" / "bin")
        curr_path = env.get("PATH", "")
        if local_bin not in curr_path.split(os.pathsep):
            env["PATH"] = f"{local_bin}:{curr_path}" if curr_path else local_bin

        if not env.get("WAYLAND_DISPLAY"):
            wayland_sockets = list(runtime_dir.glob("wayland-*"))
            if wayland_sockets:
                env["WAYLAND_DISPLAY"] = wayland_sockets[0].name

        if not env.get("DISPLAY"):
            env["DISPLAY"] = ":0"

        if not env.get("XAUTHORITY"):
            xauth_files = sorted(runtime_dir.glob("xauth_*"), key=lambda p: p.stat().st_mtime, reverse=True)
            if xauth_files:
                env["XAUTHORITY"] = str(xauth_files[0])

        # Essential KDE / Qt desktop environment variables for theme inheritance
        if not env.get("XDG_CURRENT_DESKTOP"):
            env["XDG_CURRENT_DESKTOP"] = "KDE"
        if not env.get("KDE_FULL_SESSION"):
            env["KDE_FULL_SESSION"] = "true"
        if not env.get("KDE_SESSION_VERSION"):
            env["KDE_SESSION_VERSION"] = "6"
        if not env.get("DESKTOP_SESSION"):
            env["DESKTOP_SESSION"] = "plasma.desktop"
        if not env.get("XDG_SESSION_DESKTOP"):
            env["XDG_SESSION_DESKTOP"] = "KDE"

        config_defaults = str(Path.home() / ".config" / "kdedefaults")
        if not env.get("XDG_CONFIG_DIRS"):
            env["XDG_CONFIG_DIRS"] = f"{config_defaults}:/etc/xdg:/usr/share/kde-settings/kde-profile/default/xdg"

        # Kaffeine is configured in its desktop launcher with QT_QPA_PLATFORM=xcb,
        # which produces wmclass='kaffeine' (matching user KWin rules to place on the second monitor).
        # Native Wayland uses wmclass='org.kde.kaffeine' and bypasses those X11 window placement rules.
        env["QT_QPA_PLATFORM"] = "xcb"
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
            k_bin = self.get_kaffeine_bin()
            cmd = [k_bin, "-m"] if mode == "tray" else [k_bin]
            subprocess.Popen(cmd, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            if mode == "taskbar":
                import threading
                threading.Thread(target=self._minimize_window_async, daemon=True).start()

            # Wait up to 8 seconds for Kaffeine to register on D-Bus
            import time
            for _ in range(32):
                time.sleep(0.25)
                if self.is_running():
                    time.sleep(0.5)
                    return True
            return True
        except Exception as e:
            print(f"Error launching kaffeine: {e}")
            return False

    def minimize_kaffeine(self) -> bool:
        """Minimize Kaffeine window to the taskbar if running."""
        import shutil
        kdotool_bin = shutil.which("kdotool")
        xdotool_bin = shutil.which("xdotool")
        if not kdotool_bin and not xdotool_bin:
            return False
        env = self._get_display_env()
        try:
            if kdotool_bin:
                res = subprocess.run(
                    [kdotool_bin, "search", "--class", "^kaffeine$"],
                    env=env,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    timeout=1.5
                )
                wids = [w.strip() for w in res.stdout.strip().splitlines() if w.strip()]
                for wid in wids:
                    cls = subprocess.run([kdotool_bin, "getwindowclassname", wid], env=env, stdout=subprocess.PIPE, text=True, timeout=1.0).stdout.strip().lower()
                    if "dvr" in cls:
                        continue
                    subprocess.run([kdotool_bin, "windowminimize", wid], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=1.0)
                return bool(wids)
            elif xdotool_bin:
                res = subprocess.run(
                    [xdotool_bin, "search", "--class", "^kaffeine$"],
                    env=env,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    timeout=1.5
                )
                wids = [w.strip() for w in res.stdout.strip().splitlines() if w.strip()]
                for wid in wids:
                    cls = subprocess.run([xdotool_bin, "getwindowclassname", wid], env=env, stdout=subprocess.PIPE, text=True, timeout=1.0).stdout.strip().lower()
                    if "dvr" in cls:
                        continue
                    subprocess.run([xdotool_bin, "windowminimize", wid], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=1.0)
                return bool(wids)
        except Exception:
            pass
        return False

    def _minimize_window_async(self, timeout_sec: float = 6.0, post_match_duration: float = 2.5):
        """
        Poll for Kaffeine's window to appear and persist minimize commands across startup.
        Because KWin rules and Qt map events can un-minimize the window during initial creation,
        we continue asserting minimization for post_match_duration seconds after the window is first seen.
        Strictly targets Kaffeine itself, never the Kaffeine DVR TV Guide application window.
        """
        import shutil
        import time

        kdotool_bin = shutil.which("kdotool")
        xdotool_bin = shutil.which("xdotool")

        if not kdotool_bin and not xdotool_bin:
            return

        env = self._get_display_env()
        start_time = time.time()
        first_match_time = None

        while time.time() - start_time < timeout_sec:
            time.sleep(0.2)
            try:
                if kdotool_bin:
                    res = subprocess.run(
                        [kdotool_bin, "search", "--class", "^kaffeine$"],
                        env=env,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        text=True,
                        timeout=1.5
                    )
                    wids = [w.strip() for w in res.stdout.strip().splitlines() if w.strip()]
                    kaffeine_wids = []
                    for wid in wids:
                        cls = subprocess.run([kdotool_bin, "getwindowclassname", wid], env=env, stdout=subprocess.PIPE, text=True, timeout=1.0).stdout.strip().lower()
                        if "dvr" not in cls:
                            kaffeine_wids.append(wid)
                    if kaffeine_wids:
                        if first_match_time is None:
                            first_match_time = time.time()
                        for wid in kaffeine_wids:
                            subprocess.run(
                                [kdotool_bin, "windowminimize", wid],
                                env=env,
                                stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL,
                                timeout=1.0
                            )
                        if time.time() - first_match_time >= post_match_duration:
                            break
                elif xdotool_bin:
                    res = subprocess.run(
                        [xdotool_bin, "search", "--class", "^kaffeine$"],
                        env=env,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        text=True,
                        timeout=1.5
                    )
                    wids = [w.strip() for w in res.stdout.strip().splitlines() if w.strip()]
                    kaffeine_wids = []
                    for wid in wids:
                        cls = subprocess.run([xdotool_bin, "getwindowclassname", wid], env=env, stdout=subprocess.PIPE, text=True, timeout=1.0).stdout.strip().lower()
                        if "dvr" not in cls:
                            kaffeine_wids.append(wid)
                    if kaffeine_wids:
                        if first_match_time is None:
                            first_match_time = time.time()
                        for wid in kaffeine_wids:
                            subprocess.run(
                                [xdotool_bin, "windowminimize", wid],
                                env=env,
                                stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL,
                                timeout=1.0
                            )
                        if time.time() - first_match_time >= post_match_duration:
                            break
            except Exception:
                pass

    def tune_channel(self, channel: str, raise_window: bool = True, view_mode: Optional[str] = None) -> bool:
        """
        Tune Kaffeine to the specified TV channel name or number.
        view_mode options: 'minimal', 'minimal_alwaysontop', 'fullscreen', 'alwaysontop', 'normal'
        If Kaffeine is not running, launches it with view mode flags and tuned to the channel.
        If Kaffeine is already running, tunes via D-Bus and applies window mode if requested.
        """
        if not channel:
            return False

        if self.is_running():
            tuned = False
            # Method 1: Use org.kde.KDBusService CommandLine interface.
            # This activates the TV tab in Kaffeine, tunes the exact channel requested,
            # applies view mode flags (--minimal, --fullscreen, etc.), and activates/raises the window,
            # avoiding any number key simulation.
            try:
                import dbus
                bus = dbus.SessionBus()
                app_proxy = bus.get_object("org.kde.kaffeine", "/org/kde/kaffeine")
                app_iface = dbus.Interface(app_proxy, "org.kde.KDBusService")

                cmd_args = ["kaffeine"]
                if view_mode in ("minimal", "minimal_alwaysontop"):
                    cmd_args.append("--minimal")
                elif view_mode == "fullscreen":
                    cmd_args.append("--fullscreen")
                cmd_args.extend(["--channel", str(channel)])

                ret = app_iface.CommandLine(cmd_args, "", {})
                if ret == 0:
                    tuned = True
            except Exception:
                pass

            if not tuned:
                # Method 2: D-Bus PlayChannel fallback
                try:
                    import dbus
                    bus = dbus.SessionBus()
                    proxy = bus.get_object(self.service_name, self.object_path)
                    iface = dbus.Interface(proxy, dbus_interface=self.interface_name)
                    iface.PlayChannel(channel)
                    tuned = True
                except Exception:
                    # Method 3: Fallback to calling kaffeine CLI with --channel
                    env = self._get_display_env()
                    cmd = [self.get_kaffeine_bin()]
                    if view_mode in ("minimal", "minimal_alwaysontop"):
                        cmd.append("--minimal")
                    elif view_mode == "fullscreen":
                        cmd.append("--fullscreen")
                    cmd.extend(["--channel", str(channel)])
                    subprocess.Popen(cmd, env=env)
                    tuned = True

            always_on_top = view_mode in ("minimal_alwaysontop", "alwaysontop")
            if raise_window:
                self.raise_window(always_on_top=always_on_top)
            elif always_on_top:
                self.set_always_on_top(True)
            return tuned
        else:
            env = self._get_display_env()
            cmd = [self.get_kaffeine_bin()]
            if view_mode in ("minimal", "minimal_alwaysontop"):
                cmd.append("--minimal")
            elif view_mode == "fullscreen":
                cmd.append("--fullscreen")
            cmd.extend(["--channel", str(channel)])
            try:
                subprocess.Popen(cmd, env=env)
                if view_mode in ("minimal_alwaysontop", "alwaysontop"):
                    # Give Kaffeine a moment to map its window, then set always-on-top via window manager
                    def _delayed_ontop():
                        import time
                        time.sleep(1.0)
                        self.set_always_on_top(True)
                    import threading
                    threading.Thread(target=_delayed_ontop, daemon=True).start()
                return True
            except Exception as e:
                print(f"Error launching Kaffeine for channel {channel}: {e}")
                return False

    def switch_to_tv_view(self, view_mode: Optional[str] = None):
        """Switch view mode if needed without pressing numeric channel keys."""
        pass

    def set_always_on_top(self, enable: bool = True):
        """Toggle always-on-top on Kaffeine's top-level window via the window manager."""
        import shutil
        kdotool_bin = shutil.which("kdotool")
        xdotool_bin = shutil.which("xdotool")
        env = self._get_display_env()
        state_flag = "ABOVE" if enable else ""
        try:
            if kdotool_bin:
                action = "--add" if enable else "--remove"
                subprocess.run(
                    [kdotool_bin, "search", "--class", "kaffeine", "windowstate", action, "ABOVE"],
                    env=env,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=1.5
                )
            elif xdotool_bin:
                # Fallback using wmctrl or xdotool
                wmctrl_bin = shutil.which("wmctrl")
                if wmctrl_bin:
                    action = "add" if enable else "remove"
                    subprocess.run(
                        [wmctrl_bin, "-r", "kaffeine", "-b", f"{action},above"],
                        env=env,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        timeout=1.5
                    )
        except Exception:
            pass

    def raise_window(self, always_on_top: bool = False):
        """Unminimize and raise Kaffeine window to the foreground, optionally keeping it on top."""
        import shutil
        kdotool_bin = shutil.which("kdotool")
        xdotool_bin = shutil.which("xdotool")
        env = self._get_display_env()
        try:
            if kdotool_bin:
                res = subprocess.run(
                    [kdotool_bin, "search", "--class", "kaffeine"],
                    env=env,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL,
                    text=True,
                    timeout=1.5
                )
                wids = [w.strip() for w in res.stdout.strip().splitlines() if w.strip()]
                for wid in wids:
                    subprocess.run([kdotool_bin, "windowstate", "--remove", "MINIMIZED"], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=1.0)
                    if always_on_top:
                        subprocess.run([kdotool_bin, "windowstate", "--add", "ABOVE", wid], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=1.0)
                    subprocess.run([kdotool_bin, "windowactivate", wid], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=1.0)
            elif xdotool_bin:
                res = subprocess.run(
                    [xdotool_bin, "search", "--class", "kaffeine"],
                    env=env,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL,
                    text=True,
                    timeout=1.5
                )
                wids = [w.strip() for w in res.stdout.strip().splitlines() if w.strip()]
                for wid in wids:
                    subprocess.run([xdotool_bin, "windowactivate", wid], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=1.0)
                if always_on_top:
                    self.set_always_on_top(True)
        except Exception:
            pass

    def play_file(self, file_path: str) -> bool:
        """Play a recorded media file in Kaffeine or system default player."""
        if not file_path or not os.path.exists(file_path):
            return False
        env = self._get_display_env()
        try:
            subprocess.Popen([self.get_kaffeine_bin(), str(file_path)], env=env)
            return True
        except Exception:
            try:
                subprocess.Popen(["xdg-open", str(file_path)], env=env)
                return True
            except Exception as e:
                print(f"Error opening file {file_path}: {e}")
                return False


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
