"""
D-Bus client and external player interface for Kaffeine DVB.

Handles IPC communication with Kaffeine via org.kde.kaffeine interface,
channel tuning, recording scheduling, and media player dispatching.
"""

import os
import shlex
import shutil
import sqlite3
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional

SUPPORTED_PLAYERS: Dict[str, Dict[str, Any]] = {
    "system": {
        "name": "System Default (xdg-open)",
        "binary": None,
        "flatpak_id": None,
    },
    "smplayer": {
        "name": "SMPlayer",
        "binary": "smplayer",
        "flatpak_id": "info.smplayer.SMPlayer",
    },
    "mpv": {
        "name": "mpv",
        "binary": "mpv",
        "flatpak_id": "io.mpv.Mpv",
    },
    "vlc": {
        "name": "VLC",
        "binary": "vlc",
        "flatpak_id": "org.videolan.VLC",
    },
    "mpc-qt": {
        "name": "MPC-QT",
        "binary": "mpc-qt",
        "flatpak_id": "io.github.mpc_qt.mpc-qt",
    },
    "celluloid": {
        "name": "Celluloid",
        "binary": "celluloid",
        "flatpak_id": "io.github.celluloid_player.Celluloid",
    },
    "haruna": {
        "name": "Haruna",
        "binary": "haruna",
        "flatpak_id": "org.kde.haruna",
    },
}


def detect_player_installation(player_key: str) -> str:
    """
    Detect how a media player is installed on the system.
    Returns:
    - 'native': found in system PATH or local user bin
    - 'flatpak': found via Flatpak app installation
    - '': not detected
    """
    info = SUPPORTED_PLAYERS.get(player_key)
    if not info:
        return ""

    bin_name = info.get("binary")
    if bin_name and shutil.which(bin_name):
        return "native"

    flatpak_id = info.get("flatpak_id")
    if flatpak_id:
        sys_fp = Path("/var/lib/flatpak/app") / flatpak_id
        user_fp = Path.home() / ".local" / "share" / "flatpak" / "app" / flatpak_id
        if sys_fp.is_dir() or user_fp.is_dir():
            return "flatpak"

    return ""


def resolve_system_default_player_command(file_path: str) -> Optional[List[str]]:
    """
    Resolve the actual binary and arguments for the user's default desktop media player
    via xdg-mime and .desktop files, rather than calling the transient xdg-open wrapper.
    """
    import shutil

    desktop_dirs = [
        Path.home() / ".local" / "share" / "applications",
        Path("/usr/local/share/applications"),
        Path("/usr/share/applications"),
        Path("/var/lib/flatpak/exports/share/applications"),
    ]
    desktop_file = None
    for mime in ("video/mp2t", "video/vnd.dlna.mpeg-tts", "video/mp4", "video/x-matroska", "video/quicktime"):
        try:
            out = subprocess.check_output(
                ["xdg-mime", "query", "default", mime],
                text=True,
                stderr=subprocess.DEVNULL
            ).strip()
            if out and out.endswith(".desktop"):
                desktop_file = out
                break
        except Exception:
            pass

    if not desktop_file:
        return None

    for d in desktop_dirs:
        p = d / desktop_file
        if p.exists():
            try:
                with open(p, "r", encoding="utf-8", errors="ignore") as f:
                    for line in f:
                        if line.startswith("Exec="):
                            exec_line = line.split("=", 1)[1].strip()
                            parts = shlex.split(exec_line)
                            filtered = []
                            has_field = False
                            for part in parts:
                                if part in ("%f", "%F", "%u", "%U"):
                                    filtered.append(str(file_path))
                                    has_field = True
                                elif not part.startswith("%"):
                                    filtered.append(part)
                            if not has_field:
                                filtered.append(str(file_path))
                            if filtered and (shutil.which(filtered[0]) or filtered[0] == "flatpak"):
                                return filtered
            except Exception:
                pass
    return None


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
        # Ensure Qt5 applications load the KDE platform theme so Kaffeine inherits Breeze Dark mode
        env["QT_QPA_PLATFORMTHEME"] = "kde"
        return env

    def launch_kaffeine(self, mode: str = "tray", minimized: Optional[bool] = None) -> bool:
        """
        Start Kaffeine with the specified launch mode:
        - 'tray': start offscreen and dock/minimize to the system tray
        - 'taskbar': start normal window and minimize to taskbar via window manager (kdotool/xdotool)
        - 'normal': start normal visible application window
        """
        if minimized is not None:
            mode = "tray" if minimized else "normal"

        if self.is_running():
            if mode == "normal":
                self.restore_kaffeine()
            elif mode in ("taskbar", "tray"):
                self.minimize_kaffeine(mode=mode)
            return True
        try:
            env = self._get_display_env()
            k_bin = self.get_kaffeine_bin()
            if mode in ("taskbar", "tray"):
                cmd = [k_bin, "--lastchannel", "--qwindowgeometry", "1x1+-3000+-3000"]
            else:
                cmd = [k_bin, "--lastchannel"]
            subprocess.Popen(cmd, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            if mode in ("taskbar", "tray"):
                import threading
                threading.Thread(target=self._minimize_window_async, args=(mode,), daemon=True).start()

            # Wait up to 10 seconds for Kaffeine to register on D-Bus
            import time
            for _ in range(40):
                time.sleep(0.25)
                if self.is_running():
                    time.sleep(0.5)
                    return True
            return self.is_running()
        except Exception as e:
            print(f"Error launching kaffeine: {e}")
            return False

    def _get_toplevel_kaffeine_wids(self, env: Dict[str, str]) -> List[str]:
        """
        Return only the top-level main application window IDs for Kaffeine.
        Uses _NET_CLIENT_LIST from the X11 root window to avoid matching internal Qt child sub-widgets.
        """
        kaffeine_wids = []
        try:
            out = subprocess.run(
                ["xprop", "-root", "_NET_CLIENT_LIST"],
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                timeout=1.5
            ).stdout
            if ":" in out:
                raw_wids = [x.strip().rstrip(".") for x in out.split(":", 1)[1].split(",")]
                for raw in raw_wids:
                    if not raw or not raw.startswith("0x"):
                        continue
                    try:
                        cls = subprocess.run(
                            ["xprop", "-id", raw, "WM_CLASS"],
                            env=env,
                            stdout=subprocess.PIPE,
                            stderr=subprocess.DEVNULL,
                            text=True,
                            timeout=1.0
                        ).stdout.lower()
                        if '"kaffeine"' in cls and '"kaffeine-dvr"' not in cls:
                            kaffeine_wids.append(raw)
                    except Exception:
                        pass
        except Exception:
            pass

        if not kaffeine_wids:
            xdotool_bin = shutil.which("xdotool")
            if xdotool_bin:
                try:
                    res = subprocess.run(
                        [xdotool_bin, "search", "--class", "^kaffeine$"],
                        env=env,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.DEVNULL,
                        text=True,
                        timeout=1.5
                    )
                    wids = [w.strip() for w in res.stdout.strip().splitlines() if w.strip()]
                    for wid in wids:
                        w_title = subprocess.run([xdotool_bin, "getwindowname", wid], env=env, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, timeout=1.0).stdout.strip().lower()
                        cls = subprocess.run([xdotool_bin, "getwindowclassname", wid], env=env, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, timeout=1.0).stdout.strip().lower()
                        if "dvr" in w_title or "tv guide" in w_title or "dvr" in cls:
                            continue
                        kaffeine_wids.append(wid)
                        break  # Take only the first (top-level) window to avoid corrupting child subwidgets
                except Exception:
                    pass
        return kaffeine_wids

    def restore_kaffeine(self, width: Optional[int] = None, height: Optional[int] = None, x: Optional[int] = None, y: Optional[int] = None) -> bool:
        """Restore Kaffeine window from minimized or hidden state, optionally resize and reposition it, and bring it to the front."""
        kdotool_bin = shutil.which("kdotool")
        xdotool_bin = shutil.which("xdotool")
        if not kdotool_bin and not xdotool_bin:
            return False
        env = self._get_display_env()
        try:
            if kdotool_bin:
                res = subprocess.run(
                    [kdotool_bin, "search", "--class", "kaffeine"],
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
                    if "dvr" in cls or "tv guide" in cls:
                        continue
                    w_title = subprocess.run([kdotool_bin, "getwindowname", wid], env=env, stdout=subprocess.PIPE, text=True, timeout=1.0).stdout.strip().lower()
                    if "dvr" in w_title or "tv guide" in w_title:
                        continue
                    kaffeine_wids.append(wid)
                    subprocess.run(
                        [kdotool_bin, "windowstate", "--remove", "MINIMIZED", "--remove", "SKIP_TASKBAR", "--remove", "SKIP_PAGER", wid],
                        env=env,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        timeout=1.0
                    )
                    if width is not None and height is not None:
                        subprocess.run([kdotool_bin, "windowsize", wid, str(width), str(height)], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=1.0)
                    if x is not None and y is not None:
                        subprocess.run([kdotool_bin, "windowmove", wid, str(x), str(y)], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=1.0)
                    subprocess.run([kdotool_bin, "windowraise", wid], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=1.0)
                    subprocess.run([kdotool_bin, "windowactivate", wid], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=1.0)
                return bool(kaffeine_wids)
            elif xdotool_bin:
                kaffeine_wids = self._get_toplevel_kaffeine_wids(env)
                for wid in kaffeine_wids:
                    subprocess.run([xdotool_bin, "windowmap", wid], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=1.0)
                    
                    if width is not None and height is not None:
                        # Unmaximize Kaffeine window via X11 _NET_WM_STATE_REMOVE so windowsize takes effect
                        try:
                            import ctypes
                            from ctypes import c_int, c_long, c_ulong, c_void_p, Structure
                            X11 = ctypes.cdll.LoadLibrary("libX11.so.6")
                            X11.XOpenDisplay.restype = c_void_p
                            X11.XDefaultRootWindow.restype = c_ulong
                            X11.XInternAtom.restype = c_ulong
                            X11.XSendEvent.restype = c_int

                            disp = X11.XOpenDisplay(env.get("DISPLAY", ":0").encode("utf-8"))
                            if disp:
                                wid_int = int(wid, 16) if isinstance(wid, str) and wid.startswith("0x") else int(wid)
                                root_w = X11.XDefaultRootWindow(disp)
                                net_state = X11.XInternAtom(disp, b"_NET_WM_STATE", False)
                                net_v = X11.XInternAtom(disp, b"_NET_WM_STATE_MAXIMIZED_VERT", False)
                                net_h = X11.XInternAtom(disp, b"_NET_WM_STATE_MAXIMIZED_HORZ", False)

                                class _XClientMsg(Structure):
                                    _fields_ = [
                                        ("type", c_int), ("serial", c_ulong), ("send_event", c_int),
                                        ("display", c_void_p), ("window", c_ulong), ("message_type", c_ulong),
                                        ("format", c_int), ("data", c_long * 5)
                                    ]
                                ev = _XClientMsg()
                                ev.type = 33
                                ev.serial = 0
                                ev.send_event = 1
                                ev.display = disp
                                ev.window = wid_int
                                ev.message_type = net_state
                                ev.format = 32
                                ev.data[0] = 0  # _NET_WM_STATE_REMOVE
                                ev.data[1] = net_v
                                ev.data[2] = net_h
                                ev.data[3] = 1
                                ev.data[4] = 0
                                mask = (1 << 20) | (1 << 19)
                                X11.XSendEvent(disp, root_w, False, mask, ctypes.byref(ev))
                                X11.XFlush(disp)
                                X11.XCloseDisplay(disp)
                        except Exception:
                            pass
                        subprocess.run([xdotool_bin, "windowsize", wid, str(width), str(height)], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=1.0)
                    if x is not None and y is not None:
                        subprocess.run([xdotool_bin, "windowmove", wid, str(x), str(y)], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=1.0)
                    subprocess.run([xdotool_bin, "windowraise", wid], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=1.0)
                    subprocess.run([xdotool_bin, "windowactivate", wid], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=1.0)
                return bool(kaffeine_wids)
        except Exception:
            pass
        return False

    def minimize_kaffeine(self, mode: str = "tray") -> bool:
        """Minimize Kaffeine window to the taskbar or system tray if running."""
        kdotool_bin = shutil.which("kdotool")
        xdotool_bin = shutil.which("xdotool")
        if not kdotool_bin and not xdotool_bin:
            return False
        env = self._get_display_env()
        try:
            if kdotool_bin:
                res = subprocess.run(
                    [kdotool_bin, "search", "--class", "kaffeine"],
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
                    if "dvr" in cls or "tv guide" in cls:
                        continue
                    w_title = subprocess.run([kdotool_bin, "getwindowname", wid], env=env, stdout=subprocess.PIPE, text=True, timeout=1.0).stdout.strip().lower()
                    if "dvr" in w_title or "tv guide" in w_title:
                        continue
                    kaffeine_wids.append(wid)
                    if mode == "tray":
                        subprocess.run(
                            [kdotool_bin, "windowstate", "--add", "MINIMIZED", "--add", "SKIP_TASKBAR", "--add", "SKIP_PAGER", wid],
                            env=env,
                            stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL,
                            timeout=1.0
                        )
                    subprocess.run([kdotool_bin, "windowminimize", wid], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=1.0)
                return bool(kaffeine_wids)
            elif xdotool_bin:
                kaffeine_wids = self._get_toplevel_kaffeine_wids(env)
                for wid in kaffeine_wids:
                    subprocess.run([xdotool_bin, "windowminimize", wid], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=1.0)
                return bool(kaffeine_wids)
        except Exception:
            pass
        return False

    def _minimize_window_async(self, mode: str = "tray", timeout_sec: float = 12.0, post_match_duration: float = 4.0):
        """
        Poll for Kaffeine's window to appear and persist minimize commands across startup.
        Because KWin rules and Qt map events can un-minimize the window during initial creation,
        we continue asserting minimization for post_match_duration seconds after the window is first seen.
        Strictly targets Kaffeine itself, never the Kaffeine DVR TV Guide application window.
        """
        import time

        kdotool_bin = shutil.which("kdotool")
        xdotool_bin = shutil.which("xdotool")

        if not kdotool_bin and not xdotool_bin:
            return

        env = self._get_display_env()
        start_time = time.time()
        first_match_time = None

        while time.time() - start_time < timeout_sec:
            time.sleep(0.15)
            try:
                if kdotool_bin:
                    res = subprocess.run(
                        [kdotool_bin, "search", "--class", "kaffeine"],
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
                        if "dvr" in cls or "tv guide" in cls:
                            continue
                        w_title = subprocess.run([kdotool_bin, "getwindowname", wid], env=env, stdout=subprocess.PIPE, text=True, timeout=1.0).stdout.strip().lower()
                        if "dvr" in w_title or "tv guide" in w_title:
                            continue
                        kaffeine_wids.append(wid)
                    if kaffeine_wids:
                        if first_match_time is None:
                            first_match_time = time.time()
                        for wid in kaffeine_wids:
                            if mode == "tray":
                                subprocess.run(
                                    [kdotool_bin, "windowstate", "--add", "MINIMIZED", "--add", "SKIP_TASKBAR", "--add", "SKIP_PAGER", wid],
                                    env=env,
                                    stdout=subprocess.DEVNULL,
                                    stderr=subprocess.DEVNULL,
                                    timeout=1.0
                                )
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
                    # Use exact class regex '^kaffeine$' so kaffeine-dvr GUI window is strictly excluded
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
                        w_title = subprocess.run([xdotool_bin, "getwindowname", wid], env=env, stdout=subprocess.PIPE, text=True, timeout=1.0).stdout.strip().lower()
                        if "dvr" in w_title or "tv guide" in w_title:
                            continue
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
        view_mode options: 'minimal', 'fullscreen', 'normal'
        If Kaffeine is not running, launches it with view mode flags and tuned to the channel.
        If Kaffeine is already running, tunes via D-Bus and applies window mode if requested.
        """
        if not channel:
            return False

        if self.is_running():
            tuned = False
            # Method 1: Use org.kde.KDBusService CommandLine interface.
            # This triggers Kaffeine's MainWindow::activateTab(DvbTabId) to switch tabs
            # away from the Start welcome screen directly into the Digital TV video view.
            try:
                import dbus
                bus = dbus.SessionBus()
                app_proxy = bus.get_object("org.kde.kaffeine", "/org/kde/kaffeine", introspect=False)
                app_iface = dbus.Interface(app_proxy, "org.kde.KDBusService")

                cmd_args = ["kaffeine"]
                if view_mode == "minimal":
                    cmd_args.append("--minimal")
                elif view_mode == "fullscreen":
                    cmd_args.append("--fullscreen")
                cmd_args.extend(["--channel", str(channel)])

                ret = app_iface.CommandLine(cmd_args, "", dbus.Dictionary({}, signature="sv"), timeout=2.0)
                if ret == 0:
                    tuned = True
            except Exception:
                pass

            if not tuned:
                # Method 2: D-Bus PlayChannel (Standard MPRIS /Television interface)
                try:
                    import dbus
                    bus = dbus.SessionBus()
                    proxy = bus.get_object(self.service_name, self.object_path, introspect=False)
                    iface = dbus.Interface(proxy, dbus_interface=self.interface_name)
                    iface.PlayChannel(channel, timeout=2.0)
                    tuned = True
                except Exception:
                    pass

            if raise_window:
                self.restore_kaffeine()
            return tuned
        else:
            env = self._get_display_env()
            cmd = [self.get_kaffeine_bin()]
            if view_mode == "minimal":
                cmd.append("--minimal")
            elif view_mode == "fullscreen":
                cmd.append("--fullscreen")
            cmd.extend(["--channel", str(channel)])
            try:
                subprocess.Popen(cmd, env=env)
                return True
            except Exception as e:
                print(f"Error launching Kaffeine for channel {channel}: {e}")
                return False

    def switch_to_tv_view(self, view_mode: Optional[str] = None):
        """Switch Kaffeine to the Digital Television tab."""
        if not self.is_running():
            self.launch_kaffeine(mode="normal")
            return
        try:
            import dbus
            bus = dbus.SessionBus()
            app_proxy = bus.get_object("org.kde.kaffeine", "/org/kde/kaffeine", introspect=False)
            app_iface = dbus.Interface(app_proxy, "org.kde.KDBusService")
            cmd_args = ["kaffeine"]
            if view_mode == "minimal":
                cmd_args.append("--minimal")
            elif view_mode == "fullscreen":
                cmd_args.append("--fullscreen")
            cmd_args.append("--lastchannel")
            app_iface.CommandLine(cmd_args, "", dbus.Dictionary({}, signature="sv"), timeout=2.0)
        except Exception:
            pass

    def raise_window(self):
        """Unminimize and raise Kaffeine window to the foreground."""
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
                    cls = subprocess.run([kdotool_bin, "getwindowclassname", wid], env=env, stdout=subprocess.PIPE, text=True, timeout=1.0).stdout.strip().lower()
                    if "dvr" in cls:
                        continue
                    subprocess.run(
                        [kdotool_bin, "windowstate", "--remove", "MINIMIZED", "--remove", "SKIP_TASKBAR", "--remove", "SKIP_PAGER", wid],
                        env=env,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        timeout=1.0
                    )
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
                    cls = subprocess.run([xdotool_bin, "getwindowclassname", wid], env=env, stdout=subprocess.PIPE, text=True, timeout=1.0).stdout.strip().lower()
                    if "dvr" in cls:
                        continue
                    subprocess.run([xdotool_bin, "windowactivate", wid], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=1.0)
        except Exception:
            pass

    def _prepare_standalone_smplayer_profile(self) -> Path:
        """
        Prepares a standalone SMPlayer configuration directory for live TV timeshifting.
        Inherits all user settings, skins, themes, iconsets, and GUI choices from ~/.config/smplayer/
        while ensuring single_instance_enabled=false so it never hijacks or affects other player windows.
        """
        import re

        base_user_dir = Path.home() / ".config" / "smplayer"
        target_dir = Path.home() / ".config" / "kaffeine-dvr" / "smplayer"
        target_dir.mkdir(parents=True, exist_ok=True)

        if base_user_dir.exists():
            for fname in ["smplayer.ini", "device_info.ini", "hdpi.ini", "styles.ass"]:
                src = base_user_dir / fname
                dst = target_dir / fname
                if src.exists():
                    if not dst.exists() or src.stat().st_mtime > dst.stat().st_mtime:
                        try:
                            shutil.copy2(src, dst)
                        except Exception:
                            pass
        try:
            (target_dir / "mpv.conf").unlink(missing_ok=True)
        except Exception:
            pass

        ini_path = target_dir / "smplayer.ini"
        if ini_path.exists():
            try:
                content = ini_path.read_text(encoding="utf-8", errors="ignore")
                if "[instances]" in content:
                    content = re.sub(
                        r"(?m)^\s*single_instance_enabled\s*=\s*true\b",
                        "single_instance_enabled=false",
                        content,
                        flags=re.IGNORECASE
                    )
                else:
                    content += "\n[instances]\nsingle_instance_enabled=false\n"
                ini_path.write_text(content, encoding="utf-8")
            except Exception:
                pass

        return target_dir

    def play_file(self, file_path: str, player: Optional[str] = None, custom_cmd: Optional[str] = None, standalone: bool = False) -> Any:
        """
        Play a recorded media file in the user's selected media player:
        - 'system': system default handler (xdg-open)
        - 'smplayer', 'mpv', 'vlc', 'mpc-qt', 'celluloid', 'haruna', 'kaffeine':
          launches native binary if available, or Flatpak container if installed.
        - 'custom': user-defined command template or command with file appended
        If standalone is True, passes isolation flags (e.g. dedicated config path for SMPlayer,
        --no-one-instance for VLC) to avoid hijacking or closing other running player windows.
        Returns the spawned subprocess.Popen instance on success, or None on failure.
        """
        if not file_path or not os.path.exists(file_path):
            return None
        env = self._get_display_env()
        player_mode = (player or "system").lower().strip()

        import shutil

        cmd = []
        if player_mode == "custom" and custom_cmd and custom_cmd.strip():
            cmd_str = custom_cmd.strip()
            if "{file}" in cmd_str:
                cmd = shlex.split(cmd_str.replace("{file}", str(file_path)))
            else:
                cmd = shlex.split(cmd_str) + [str(file_path)]
        elif player_mode in SUPPORTED_PLAYERS and player_mode != "system":
            info = SUPPORTED_PLAYERS[player_mode]
            bin_name = info.get("binary")
            flatpak_id = info.get("flatpak_id")

            bin_path = shutil.which(bin_name) if bin_name else None

            extra_args = []
            if standalone:
                if player_mode == "smplayer":
                    sm_profile = self._prepare_standalone_smplayer_profile()
                    extra_args = ["-config-path", str(sm_profile)]
                elif player_mode == "vlc":
                    extra_args = ["--no-one-instance"]

            if bin_path:
                cmd = [bin_path] + extra_args + [str(file_path)]
            elif flatpak_id and shutil.which("flatpak") and detect_player_installation(player_mode) == "flatpak":
                cmd = ["flatpak", "run", "--file-forwarding", flatpak_id] + extra_args + ["@@", str(file_path), "@@"]

        if not cmd:
            # When player_mode is 'system' or unresolved, resolve the real binary from desktop environment
            resolved_cmd = resolve_system_default_player_command(file_path)
            if resolved_cmd:
                cmd = resolved_cmd
            else:
                # If desktop association resolution fails, check for common native media players
                for candidate in ("smplayer", "mpv", "vlc", "celluloid", "haruna"):
                    if shutil.which(candidate):
                        extra_args = []
                        if standalone and candidate == "smplayer":
                            sm_profile = self._prepare_standalone_smplayer_profile()
                            extra_args = ["-config-path", str(sm_profile)]
                        elif standalone and candidate == "vlc":
                            extra_args = ["--no-one-instance"]
                        cmd = [candidate] + extra_args + [str(file_path)]
                        break

        is_xdg = False
        if not cmd:
            # Fallback to system default / xdg-open
            cmd = ["xdg-open", str(file_path)]
            is_xdg = True

        try:
            proc = subprocess.Popen(cmd, env=env)
            if is_xdg:
                setattr(proc, "_is_xdg_open", True)
            return proc
        except Exception as e:
            print(f"Error launching player ({cmd}): {e}")
            try:
                proc = subprocess.Popen(["xdg-open", str(file_path)], env=env)
                setattr(proc, "_is_xdg_open", True)
                return proc
            except Exception as e2:
                print(f"Fallback to xdg-open failed for {file_path}: {e2}")
                return None


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

    def list_recordings(self) -> List[Dict[str, Any]]:
        """Alias for list_scheduled_recordings."""
        return self.list_scheduled_recordings()

    def get_active_recordings(self) -> List[Dict[str, Any]]:
        """Returns currently recording entries (is_running == True)."""
        return [e for e in self.list_scheduled_recordings() if e.get("is_running")]

    def _list_via_dbus(self) -> List[Dict[str, Any]]:
        import dbus
        bus = dbus.SessionBus()
        proxy = bus.get_object(self.service_name, self.object_path, introspect=False)

        # Call ListProgramSchedule
        # Try through interface or direct method call
        try:
            iface = dbus.Interface(proxy, dbus_interface=self.interface_name)
            raw_entries = iface.ListProgramSchedule(timeout=3.0)
        except Exception:
            raw_entries = proxy.ListProgramSchedule(timeout=3.0)

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
        Prevents duplicate active timers in Kaffeine for the same show and channel.
        begin_iso: e.g. '2026-10-07T20:00:00'
        duration_iso: e.g. '01:00:00'
        repeat: 0 for once, bitmask for recurring days
        Returns the recording ID.
        """
        if not self.is_running():
            import time
            for _ in range(16):
                time.sleep(0.25)
                if self.is_running():
                    break

        if self.is_running():
            # Check for existing scheduled/active timers in Kaffeine to avoid duplicate recording files
            try:
                existing_entries = self._list_via_dbus()
                ch_target = (channel or "").strip().lower()
                name_target = (name or "").strip().lower()
                for entry in existing_entries:
                    e_ch = (entry.get("channel") or "").strip().lower()
                    e_name = (entry.get("name") or "").strip().lower()
                    if e_ch == ch_target and (e_name == name_target or name_target in e_name):
                        if entry.get("is_running"):
                            print(
                                f"Active recording already running in Kaffeine for '{name}' on {channel} "
                                f"(Key {entry['id']}). Reusing existing active timer.",
                                flush=True
                            )
                            return int(entry["id"])
                        elif entry.get("duration") == duration_iso and (not entry.get("begin") or entry.get("begin") == begin_iso):
                            return int(entry["id"])
                        else:
                            # Stale schedule parameters: remove old timer before adding updated one
                            self.remove_recording(int(entry["id"]))
            except Exception as e:
                print(f"Notice: Duplicate timer pre-check encountered: {e}", flush=True)

            # Try dbus-python call
            try:
                import dbus
                bus = dbus.SessionBus()
                proxy = bus.get_object(self.service_name, self.object_path, introspect=False)
                try:
                    iface = dbus.Interface(proxy, dbus_interface=self.interface_name)
                    key = iface.ScheduleProgram(name, channel, begin_iso, duration_iso, dbus.Int32(repeat), timeout=3.0)
                except Exception:
                    key = proxy.ScheduleProgram(name, channel, begin_iso, duration_iso, repeat, timeout=3.0)
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
        """Cancel/remove a scheduled recording by its Kaffeine numeric key."""
        if not key:
            return False
        try:
            key_int = int(key)
        except (ValueError, TypeError):
            return False

        if not self.is_running():
            # If offline, remove directly from SQLite
            try:
                conn = sqlite3.connect(str(self.kaffeine_db_path))
                cur = conn.cursor()
                cur.execute("DELETE FROM RecordingSchedule WHERE Id = ?", (key_int,))
                conn.commit()
                conn.close()
                return True
            except Exception as e:
                print(f"Failed to delete recording from SQLite: {e}")
                return False

        success = False
        try:
            import dbus
            bus = dbus.SessionBus()
            proxy = bus.get_object(self.service_name, self.object_path, introspect=False)
            try:
                iface = dbus.Interface(proxy, dbus_interface=self.interface_name)
                iface.RemoveProgram(dbus.UInt32(key_int), timeout=3.0)
            except Exception:
                proxy.RemoveProgram(key_int, timeout=3.0)
            success = True
        except Exception:
            # Fallback to qdbus CLI
            res = subprocess.run(
                ["qdbus", self.service_name, self.object_path, "RemoveProgram", str(key_int)],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
            )
            success = (res.returncode == 0)

        # Also purge from SQLite directly to guarantee clean state
        try:
            if self.kaffeine_db_path.exists():
                conn = sqlite3.connect(str(self.kaffeine_db_path))
                cur = conn.cursor()
                cur.execute("DELETE FROM RecordingSchedule WHERE Id = ?", (key_int,))
                conn.commit()
                conn.close()
        except Exception:
            pass

        return success

    def cancel_recording(
        self,
        key: Optional[int] = None,
        channel: Optional[str] = None,
        title: Optional[str] = None
    ) -> bool:
        """
        Thoroughly cancels and halts a recording in Kaffeine:
        1. Queries active and scheduled timers in Kaffeine via D-Bus; matches by channel
           and title (or verified key) before deleting to prevent canceling unrelated shows.
        2. Cleans matching records from Kaffeine's sqlite.db with strict channel guards.
        """
        removed_any = False
        ch_targets = set()
        if channel:
            ch_strip = str(channel).strip().lower()
            ch_targets.add(ch_strip)
            try:
                from .config import ConfigManager
                cfg = ConfigManager()
                if cfg.channel_map:
                    # If channel is a guide name, add tuned name
                    if channel in cfg.channel_map:
                        ch_targets.add(cfg.channel_map[channel].strip().lower())
                    # If channel is a tuned name, add guide name
                    for g_name, t_name in cfg.channel_map.items():
                        if t_name.strip().lower() == ch_strip or g_name.strip().lower() == ch_strip:
                            ch_targets.add(g_name.strip().lower())
                            ch_targets.add(t_name.strip().lower())
            except Exception:
                pass

        t_target = (title or "").strip().lower()

        # Step 1: Query active/scheduled timers in Kaffeine via D-Bus
        if self.is_running():
            try:
                active_entries = self._list_via_dbus()

                for entry in active_entries:
                    e_id = entry.get("id")
                    if not e_id:
                        continue

                    e_ch = (entry.get("channel") or "").strip().lower()
                    e_name = (entry.get("name") or "").strip().lower()

                    # Safety Guard: If a target channel is specified, NEVER remove an entry on a different channel!
                    # Kaffeine recycles small numeric IDs (1, 2, ...), so key collision across different channels occurs.
                    if ch_targets and e_ch not in ch_targets:
                        continue

                    match_show = False
                    if ch_targets and t_target:
                        match_show = (e_ch in ch_targets) and ((e_name == t_target) or (t_target in e_name) or (e_name in t_target))
                    elif ch_targets:
                        match_show = (e_ch in ch_targets)
                    elif t_target:
                        match_show = (e_name == t_target) or (t_target in e_name) or (e_name in t_target)
                    elif key is not None and int(key) == int(e_id):
                        match_show = True

                    if key is not None and int(key) == int(e_id):
                        match_show = True

                    if match_show:
                        if self.remove_recording(int(e_id)):
                            removed_any = True
            except Exception as e:
                print(f"Error checking Kaffeine schedule during cancellation: {e}", flush=True)

        # Step 2: Fallback to removing by key ONLY if no channel or title was specified
        if not removed_any and key is not None and not ch_targets and not t_target:
            try:
                k_int = int(key)
                if k_int > 0:
                    if self.remove_recording(k_int):
                        removed_any = True
            except (ValueError, TypeError):
                pass

        # Step 3: SQLite cleanup with strict channel guard
        if self.kaffeine_db_path.exists():
            try:
                conn = sqlite3.connect(str(self.kaffeine_db_path), timeout=10.0)
                cur = conn.cursor()
                for c_t in (ch_targets or [None]):
                    if c_t and t_target:
                        cur.execute(
                            "DELETE FROM RecordingSchedule WHERE LOWER(Channel) = LOWER(?) AND (LOWER(Name) = LOWER(?) OR Name LIKE ?)",
                            (c_t, t_target, f"%{t_target}%")
                        )
                    elif c_t and key is not None:
                        cur.execute(
                            "DELETE FROM RecordingSchedule WHERE Id = ? AND LOWER(Channel) = LOWER(?)",
                            (int(key), c_t)
                        )
                    elif c_t:
                        cur.execute(
                            "DELETE FROM RecordingSchedule WHERE LOWER(Channel) = LOWER(?)",
                            (c_t,)
                        )
                    elif key is not None:
                        cur.execute("DELETE FROM RecordingSchedule WHERE Id = ?", (int(key),))
                conn.commit()
                conn.close()
            except Exception as e:
                print(f"Error purging Kaffeine SQLite schedule: {e}", flush=True)

        return removed_any
