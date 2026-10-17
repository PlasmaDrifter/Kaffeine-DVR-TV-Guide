"""
DVB Signal Health Scanner for Kaffeine DVR.

Queries Linux DVB frontend hardware (/dev/dvb/adapter*/frontend*) via kernel ioctl
to read real-time carrier lock status, signal strength, SNR, and BER while Kaffeine
tunes digital channels in the background.
"""

import fcntl
import os
import struct
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from PyQt6.QtCore import QObject, QThread, pyqtSignal

# Linux DVB frontend ioctl definitions (linux/dvb/frontend.h)
FE_READ_STATUS = 0x80046F45           # _IOR('o', 69, sizeof(int))
FE_READ_BER = 0x80046F46              # _IOR('o', 70, sizeof(uint32))
FE_READ_SIGNAL_STRENGTH = 0x80026F47  # _IOR('o', 71, sizeof(uint16))
FE_READ_SNR = 0x80026F48              # _IOR('o', 72, sizeof(uint16))
FE_READ_UNCORRECTED = 0x80046F49      # _IOR('o', 73, sizeof(uint32))

# Status flags
FE_HAS_SIGNAL  = 0x01
FE_HAS_CARRIER = 0x02
FE_HAS_VITERBI = 0x04
FE_HAS_SYNC    = 0x08
FE_HAS_LOCK    = 0x10


class DvbSignalReader:
    """
    Direct low-level reader for Linux DVB frontend hardware metrics.
    Opens the frontend in O_RDONLY mode to read status without interfering with
    recording or playback processes that hold the device in O_RDWR mode.
    """
    @staticmethod
    def find_active_frontend() -> Optional[str]:
        """
        Locate the active DVB frontend device node.
        1. Checks /proc/<pid>/fd of running Kaffeine or DVR process to identify the exact
           frontend hardware device currently in use.
        2. Probes available frontends to find one with an active carrier or digital lock.
        3. Falls back to the first available frontend in /dev/dvb.
        """
        # 1. Check open file descriptors of Kaffeine or DVR process
        try:
            import glob
            for proc_dir in glob.glob("/proc/[0-9]*/fd"):
                try:
                    pid_str = proc_dir.split("/")[2]
                    comm_path = Path(f"/proc/{pid_str}/comm")
                    if comm_path.is_file():
                        comm = comm_path.read_text(encoding="utf-8", errors="ignore").strip().lower()
                        if "kaffeine" in comm or "dvr" in comm:
                            for fd_entry in Path(proc_dir).iterdir():
                                try:
                                    target = os.readlink(str(fd_entry))
                                    if "/dev/dvb/adapter" in target and "frontend" in target:
                                        if os.path.exists(target):
                                            return target
                                except (OSError, IOError):
                                    pass
                except (OSError, IOError, FileNotFoundError):
                    pass
        except Exception:
            pass

        # 2. Check frontends for active lock or carrier
        dvb_root = Path("/dev/dvb")
        if dvb_root.is_dir():
            frontends = []
            for adapter in sorted(dvb_root.glob("adapter*")):
                for fe in sorted(adapter.glob("frontend*")):
                    if fe.is_char_device():
                        frontends.append(str(fe))

            buf4 = bytearray(4)
            for fe in frontends:
                try:
                    fd = os.open(fe, os.O_RDONLY | os.O_NONBLOCK)
                    fcntl.ioctl(fd, FE_READ_STATUS, buf4)
                    os.close(fd)
                    status = struct.unpack("I", buf4)[0]
                    if status & (FE_HAS_LOCK | FE_HAS_SIGNAL | FE_HAS_CARRIER):
                        return fe
                except Exception:
                    pass

            if frontends:
                return frontends[0]

        return None

    @staticmethod
    def find_frontend_device() -> Optional[str]:
        """Locate the first available DVB frontend device node."""
        return DvbSignalReader.find_active_frontend()

    @classmethod
    def read_metrics(cls, frontend_path: Optional[str] = None) -> Dict[str, Any]:
        """
        Read real-time signal metrics from the DVB frontend device.
        Returns a dictionary of lock flags, signal strength percentage, and SNR.
        """
        path = frontend_path or cls.find_frontend_device()
        if not path or not os.path.exists(path):
            return {
                "available": False,
                "error": "DVB frontend device not found (/dev/dvb/adapter*/frontend*)",
                "locked": False,
                "has_signal": False,
                "has_carrier": False,
                "status_hex": "0x00",
                "strength_pct": 0.0,
                "snr_db": 0.0,
                "ber": 0,
                "quality_label": "No Device",
            }

        try:
            fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
        except PermissionError:
            return {
                "available": False,
                "error": f"Permission denied accessing {path} (user must be in video group)",
                "locked": False,
                "has_signal": False,
                "has_carrier": False,
                "status_hex": "0x00",
                "strength_pct": 0.0,
                "snr_db": 0.0,
                "ber": 0,
                "quality_label": "Permission Denied",
            }
        except Exception as e:
            return {
                "available": False,
                "error": str(e),
                "locked": False,
                "has_signal": False,
                "has_carrier": False,
                "status_hex": "0x00",
                "strength_pct": 0.0,
                "snr_db": 0.0,
                "ber": 0,
                "quality_label": "Error",
            }

        buf4 = bytearray(4)
        buf2 = bytearray(2)

        try:
            # 1. Read status bitmask
            fcntl.ioctl(fd, FE_READ_STATUS, buf4)
            status = struct.unpack("I", buf4)[0]

            has_signal = bool(status & FE_HAS_SIGNAL)
            has_carrier = bool(status & FE_HAS_CARRIER)
            has_viterbi = bool(status & FE_HAS_VITERBI)
            has_sync = bool(status & FE_HAS_SYNC)
            has_lock = bool(status & FE_HAS_LOCK)

            # 2. Read signal strength (16-bit uint, 0..65535)
            strength_pct = 0.0
            try:
                fcntl.ioctl(fd, FE_READ_SIGNAL_STRENGTH, buf2)
                raw_sig = int.from_bytes(buf2, "little")
                strength_pct = round((raw_sig / 65535.0) * 100.0, 1)
            except Exception:
                pass

            # 3. Read SNR
            snr_db = 0.0
            try:
                fcntl.ioctl(fd, FE_READ_SNR, buf2)
                raw_snr = int.from_bytes(buf2, "little")
                if raw_snr > 1000:
                    snr_db = round((raw_snr / 65535.0) * 35.0, 1)
                else:
                    snr_db = round(raw_snr / 10.0, 1)
            except Exception:
                pass

            # If carrier locked but AGC/SNR haven't populated yet (hardware settle lag), retry once
            if has_lock and (strength_pct == 0.0 or snr_db == 0.0):
                time.sleep(0.15)
                try:
                    fcntl.ioctl(fd, FE_READ_SIGNAL_STRENGTH, buf2)
                    raw_sig = int.from_bytes(buf2, "little")
                    if raw_sig > 0:
                        strength_pct = round((raw_sig / 65535.0) * 100.0, 1)
                except Exception:
                    pass
                try:
                    fcntl.ioctl(fd, FE_READ_SNR, buf2)
                    raw_snr = int.from_bytes(buf2, "little")
                    if raw_snr > 0:
                        if raw_snr > 1000:
                            snr_db = round((raw_snr / 65535.0) * 35.0, 1)
                        else:
                            snr_db = round(raw_snr / 10.0, 1)
                except Exception:
                    pass

            # 4. Read BER (Bit Error Rate)
            ber = 0
            try:
                fcntl.ioctl(fd, FE_READ_BER, buf4)
                ber = struct.unpack("I", buf4)[0]
            except Exception:
                pass

            # Quality categorization
            if has_lock:
                if strength_pct >= 60.0 or snr_db >= 22.0:
                    quality = "Excellent"
                elif strength_pct >= 40.0 or snr_db >= 17.0:
                    quality = "Good"
                else:
                    quality = "Fair"
            elif (has_signal or has_carrier) and strength_pct > 0.0:
                quality = "Weak (No Lock)"
            else:
                quality = "No Signal"

            return {
                "available": True,
                "error": None,
                "locked": has_lock,
                "has_signal": has_signal,
                "has_carrier": has_carrier,
                "has_viterbi": has_viterbi,
                "has_sync": has_sync,
                "status_hex": f"0x{status:02x}",
                "strength_pct": strength_pct,
                "snr_db": snr_db,
                "ber": ber,
                "quality_label": quality,
            }
        except Exception as e:
            return {
                "available": True,
                "error": str(e),
                "locked": False,
                "has_signal": False,
                "has_carrier": False,
                "status_hex": "0x00",
                "strength_pct": 0.0,
                "snr_db": 0.0,
                "ber": 0,
                "quality_label": "Read Error",
            }
        finally:
            os.close(fd)


class ChannelSignalScanWorker(QThread):
    """
    Background worker thread that sequentially tunes each channel in Kaffeine,
    allows hardware PLL carrier lock acquisition, measures DVB signal health,
    and reports progress.
    """
    channel_started = pyqtSignal(str, int, int)   # channel_name, current_idx (1-based), total
    channel_result = pyqtSignal(str, dict)        # channel_name, result_dict
    scan_progress = pyqtSignal(int, int)          # current_idx, total
    scan_finished = pyqtSignal(dict)              # dict mapping channel_name -> result_dict
    scan_error = pyqtSignal(str)                  # error string

    def __init__(
        self,
        channels: List[Dict[str, Any]],
        frontend_path: Optional[str] = None,
        lock_timeout_sec: float = 1.8,
        parent: Optional[QObject] = None,
    ):
        super().__init__(parent)
        self.channels = channels
        self.frontend_path = frontend_path
        self.lock_timeout_sec = lock_timeout_sec
        self._stop_requested = False

    def request_stop(self):
        """Request the scanner to abort processing after the current channel."""
        self._stop_requested = True

    def run(self):
        if not self.channels:
            self.scan_finished.emit({})
            return

        all_results: Dict[str, Dict[str, Any]] = {}
        total = len(self.channels)

        # 1. Ensure Kaffeine is running to tune physical tuner frequencies
        from .dbus_client import KaffeineDbusClient
        client = KaffeineDbusClient()
        if not client.is_running():
            launch_mode = "taskbar"
            try:
                from .config import ConfigManager
                cfg = ConfigManager()
                launch_mode = cfg.launch_mode
            except Exception:
                pass
            client.launch_kaffeine(mode=launch_mode)

        # 2. Connect to Kaffeine D-Bus interfaces
        television_iface = None
        player_iface = None
        try:
            import dbus
            bus = dbus.SessionBus()
            tv_proxy = bus.get_object("org.mpris.kaffeine", "/Television", introspect=False)
            television_iface = dbus.Interface(tv_proxy, "org.freedesktop.MediaPlayer")
            player_proxy = bus.get_object("org.mpris.kaffeine", "/Player", introspect=False)
            player_iface = dbus.Interface(player_proxy, "org.freedesktop.MediaPlayer")
        except Exception as e:
            self.scan_error.emit(f"Could not connect to Kaffeine D-Bus service: {e}")

        try:
            for idx, ch_info in enumerate(self.channels, 1):
                if self._stop_requested:
                    break

                ch_name = ch_info.get("name", "").strip()
                if not ch_name:
                    continue

                self.channel_started.emit(ch_name, idx, total)
                self.scan_progress.emit(idx, total)

                # 1. Instruct Kaffeine to tune to this channel silently in the background
                # Note: We use television_iface.PlayChannel directly instead of client.tune_channel()
                # because client.tune_channel() uses KDBusService CommandLine, which unminimizes/activates
                # Kaffeine's window on KDE/KWin and causes window flickering during the scan.
                tuned = False
                if television_iface:
                    try:
                        television_iface.PlayChannel(ch_name, timeout=3.0)
                        tuned = True
                    except Exception:
                        pass

                if not tuned:
                    try:
                        client.tune_channel(ch_name, raise_window=False)
                    except Exception:
                        pass

                # 2. Poll demodulator lock status up to lock_timeout_sec
                poll_interval = 0.15
                elapsed = 0.0
                best_metrics = {
                    "available": True,
                    "locked": False,
                    "has_signal": False,
                    "has_carrier": False,
                    "status_hex": "0x00",
                    "strength_pct": 0.0,
                    "snr_db": 0.0,
                    "ber": 0,
                    "quality_label": "No Signal",
                }

                while elapsed < self.lock_timeout_sec and not self._stop_requested:
                    time.sleep(poll_interval)
                    elapsed += poll_interval
                    metrics = DvbSignalReader.read_metrics(self.frontend_path)
                    if metrics.get("locked"):
                        # Acquired carrier lock; allow 350ms for AGC filter and SNR registers to settle
                        time.sleep(0.35)
                        refreshed = DvbSignalReader.read_metrics(self.frontend_path)
                        if refreshed.get("locked") or refreshed.get("strength_pct", 0) > 0:
                            best_metrics = refreshed
                        else:
                            best_metrics = metrics
                        break
                    elif metrics.get("strength_pct", 0) > best_metrics.get("strength_pct", 0):
                        best_metrics = metrics
                    elif (metrics.get("has_signal") or metrics.get("has_carrier")) and not best_metrics.get("locked"):
                        best_metrics = metrics

                best_metrics["channel_name"] = ch_name
                best_metrics["channel_number"] = ch_info.get("number")
                best_metrics["transponder"] = ch_info.get("transponder", "")
                best_metrics["scanned_at"] = time.strftime("%Y-%m-%d %H:%M:%S")

                all_results[ch_name] = best_metrics
                self.channel_result.emit(ch_name, best_metrics)

        finally:
            # Crucial: Stop Kaffeine playback completely so background channel audio/video is silent
            if player_iface:
                try:
                    player_iface.Stop(timeout=1.5)
                except Exception:
                    pass

            # Restore Kaffeine hidden/minimized state per launch mode
            try:
                from .config import ConfigManager
                cfg = ConfigManager()
                if cfg.launch_mode in ("taskbar", "tray"):
                    client.minimize_kaffeine(mode=cfg.launch_mode)
            except Exception:
                pass

            self.scan_finished.emit(all_results)
