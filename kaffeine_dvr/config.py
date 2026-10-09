import json
from pathlib import Path
from typing import Dict, Any, List

DEFAULT_CHANNEL_MAP = {}

class ConfigManager:
    def __init__(self):
        self.home_dir = Path.home()
        self.config_dir = self.home_dir / ".config" / "kaffeine-dvr"
        self.config_file = self.config_dir / "config.json"
        self.data_dir = self.home_dir / ".local" / "share" / "kaffeine-dvr"
        self.kaffeine_db_path = self.home_dir / ".local" / "share" / "kaffeine" / "sqlite.db"
        
        self.config_dir.mkdir(parents=True, exist_ok=True)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.data = self._load()

    def _load(self) -> Dict[str, Any]:
        if self.config_file.exists():
            try:
                with open(self.config_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if "channel_map" not in data:
                        data["channel_map"] = DEFAULT_CHANNEL_MAP.copy()
                    if "rules" not in data:
                        data["rules"] = []
                    if "guide_days_ahead" not in data:
                        data["guide_days_ahead"] = 7
                    if "auto_sync_interval_hours" not in data:
                        data["auto_sync_interval_hours"] = 6
                    if "watcher_interval_seconds" not in data:
                        data["watcher_interval_seconds"] = 120
                    if "guide_provider" not in data:
                        data["guide_provider"] = "hybrid"
                    if "xmltv_path_or_url" not in data:
                        data["xmltv_path_or_url"] = ""
                    if "schedules_direct" not in data:
                        data["schedules_direct"] = {"username": "", "password": "", "lineup": ""}
                    if "tvpassport_stations" not in data:
                        data["tvpassport_stations"] = {}
                    if "lead_time_mins" not in data:
                        data["lead_time_mins"] = 5
                    if "launch_minimized" not in data:
                        data["launch_minimized"] = True
                    if "launch_mode" not in data:
                        data["launch_mode"] = "taskbar" if data.get("launch_minimized", True) else "normal"
                    if "enable_desktop_notifications" not in data:
                        data["enable_desktop_notifications"] = True
                    if "first_run_completed" not in data:
                        data["first_run_completed"] = False
                    if "auto_cleanup_enabled" not in data:
                        data["auto_cleanup_enabled"] = False
                    if "retention_days" not in data:
                        data["retention_days"] = 14
                    if "min_free_disk_gb" not in data:
                        data["min_free_disk_gb"] = 25
                    if "custom_recording_folder" not in data:
                        data["custom_recording_folder"] = ""
                    if "end_buffer_mins" not in data:
                        data["end_buffer_mins"] = 0
                    if "sports_buffer_mins" not in data:
                        data["sports_buffer_mins"] = 30
                    if "auto_buffer_sports" not in data:
                        data["auto_buffer_sports"] = True
                    if "max_history_entries" not in data:
                        data["max_history_entries"] = 50
                    return data
            except Exception:
                pass
        
        default_data = {
            "channel_map": DEFAULT_CHANNEL_MAP.copy(),
            "rules": [],
            "guide_days_ahead": 7,
            "auto_sync_interval_hours": 6,
            "watcher_interval_seconds": 120,
            "lead_time_mins": 5,
            "launch_minimized": True,
            "launch_mode": "taskbar",
            "enable_desktop_notifications": True,
            "country_code": "US",
            "guide_provider": "hybrid",
            "xmltv_path_or_url": "",
            "schedules_direct": {
                "username": "",
                "password": "",
                "lineup": ""
            },
            "tvpassport_stations": {},
            "first_run_completed": False,
            "auto_cleanup_enabled": False,
            "retention_days": 14,
            "min_free_disk_gb": 25,
            "custom_recording_folder": "",
            "end_buffer_mins": 0,
            "sports_buffer_mins": 30,
            "auto_buffer_sports": True,
            "max_history_entries": 50
        }
        self._save(default_data)
        return default_data


    def _save(self, data: Dict[str, Any]):
        try:
            with open(self.config_file, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            print(f"Error saving configuration: {e}")

    def save(self):
        self._save(self.data)

    @property
    def channel_map(self) -> Dict[str, str]:
        return self.data.get("channel_map", DEFAULT_CHANNEL_MAP)

    @channel_map.setter
    def channel_map(self, val: Dict[str, str]):
        self.data["channel_map"] = val
        self.save()

    @property
    def channel_order(self) -> List[str]:
        return self.data.get("channel_order", [])

    @channel_order.setter
    def channel_order(self, val: List[str]):
        self.data["channel_order"] = val
        self.save()

    def get_ordered_channels(self) -> List[str]:
        """
        Returns all unique channels in configured manual order.
        Any active channels not yet in channel_order are appended to the end.
        """
        all_unique = list(dict.fromkeys(
            list(self.channel_map.values()) +
            list(self.tvpassport_stations.keys())
        ))
        saved_order = self.channel_order
        ordered = []
        for ch in saved_order:
            if ch in all_unique and ch not in ordered:
                ordered.append(ch)
        for ch in all_unique:
            if ch not in ordered:
                ordered.append(ch)
        return ordered

    @property
    def rules(self) -> List[Dict[str, Any]]:
        return self.data.get("rules", [])

    @rules.setter
    def rules(self, val: List[Dict[str, Any]]):
        self.data["rules"] = val
        self.save()

    @property
    def guide_days_ahead(self) -> int:
        return self.data.get("guide_days_ahead", 7)

    @guide_days_ahead.setter
    def guide_days_ahead(self, val: int):
        self.data["guide_days_ahead"] = val
        self.save()

    @property
    def watcher_interval_seconds(self) -> int:
        return self.data.get("watcher_interval_seconds", 120)

    @watcher_interval_seconds.setter
    def watcher_interval_seconds(self, val: int):
        self.data["watcher_interval_seconds"] = val
        self.save()

    @property
    def lead_time_mins(self) -> int:
        return self.data.get("lead_time_mins", 5)

    @lead_time_mins.setter
    def lead_time_mins(self, val: int):
        self.data["lead_time_mins"] = val
        self.save()

    @property
    def guide_provider(self) -> str:
        return self.data.get("guide_provider", "hybrid")

    @guide_provider.setter
    def guide_provider(self, val: str):
        self.data["guide_provider"] = val
        self.save()

    @property
    def xmltv_path_or_url(self) -> str:
        return self.data.get("xmltv_path_or_url", "")

    @xmltv_path_or_url.setter
    def xmltv_path_or_url(self, val: str):
        self.data["xmltv_path_or_url"] = val
        self.save()

    @property
    def schedules_direct(self) -> Dict[str, str]:
        return self.data.get("schedules_direct", {"username": "", "password": "", "lineup": ""})

    @schedules_direct.setter
    def schedules_direct(self, val: Dict[str, str]):
        self.data["schedules_direct"] = val
        self.save()

    @property
    def tvpassport_stations(self) -> Dict[str, str]:
        return self.data.get("tvpassport_stations", {})

    @tvpassport_stations.setter
    def tvpassport_stations(self, val: Dict[str, str]):
        self.data["tvpassport_stations"] = val
        self.save()

    @property
    def launch_mode(self) -> str:
        return self.data.get("launch_mode", "taskbar")

    @launch_mode.setter
    def launch_mode(self, val: str):
        self.data["launch_mode"] = val
        self.data["launch_minimized"] = (val != "normal")
        self.save()

    @property
    def launch_minimized(self) -> bool:
        return self.launch_mode != "normal"

    @launch_minimized.setter
    def launch_minimized(self, val: bool):
        self.data["launch_minimized"] = val
        if not val:
            self.data["launch_mode"] = "normal"
        elif self.data.get("launch_mode") == "normal":
            self.data["launch_mode"] = "taskbar"
        self.save()

    @property
    def enable_desktop_notifications(self) -> bool:
        return self.data.get("enable_desktop_notifications", True)

    @enable_desktop_notifications.setter
    def enable_desktop_notifications(self, val: bool):
        self.data["enable_desktop_notifications"] = val
        self.save()

    @property
    def first_run_completed(self) -> bool:
        return self.data.get("first_run_completed", False)

    @first_run_completed.setter
    def first_run_completed(self, val: bool):
        self.data["first_run_completed"] = val
        self.save()

    @property
    def auto_cleanup_enabled(self) -> bool:
        return self.data.get("auto_cleanup_enabled", False)

    @auto_cleanup_enabled.setter
    def auto_cleanup_enabled(self, val: bool):
        self.data["auto_cleanup_enabled"] = val
        self.save()

    @property
    def retention_days(self) -> int:
        return self.data.get("retention_days", 14)

    @retention_days.setter
    def retention_days(self, val: int):
        self.data["retention_days"] = val
        self.save()

    @property
    def min_free_disk_gb(self) -> int:
        return self.data.get("min_free_disk_gb", 25)

    @min_free_disk_gb.setter
    def min_free_disk_gb(self, val: int):
        self.data["min_free_disk_gb"] = val
        self.save()

    @property
    def custom_recording_folder(self) -> str:
        return self.data.get("custom_recording_folder", "")

    @custom_recording_folder.setter
    def custom_recording_folder(self, val: str):
        self.data["custom_recording_folder"] = val
        self.save()

    @property
    def end_buffer_mins(self) -> int:
        return self.data.get("end_buffer_mins", 0)

    @end_buffer_mins.setter
    def end_buffer_mins(self, val: int):
        self.data["end_buffer_mins"] = val
        self.save()

    @property
    def sports_buffer_mins(self) -> int:
        return self.data.get("sports_buffer_mins", 30)

    @sports_buffer_mins.setter
    def sports_buffer_mins(self, val: int):
        self.data["sports_buffer_mins"] = val
        self.save()

    @property
    def auto_buffer_sports(self) -> bool:
        return self.data.get("auto_buffer_sports", True)

    @auto_buffer_sports.setter
    def auto_buffer_sports(self, val: bool):
        self.data["auto_buffer_sports"] = val
        self.save()

    @property
    def max_history_entries(self) -> int:
        return self.data.get("max_history_entries", 50)

    @max_history_entries.setter
    def max_history_entries(self, val: int):
        self.data["max_history_entries"] = max(1, int(val))
        self.save()

    def get_scanned_kaffeine_channels(self) -> List[Dict[str, Any]]:
        """Read all scanned channels from Kaffeine's sqlite.db dynamically."""
        if not self.kaffeine_db_path.exists():
            return []
        try:
            import sqlite3
            conn = sqlite3.connect(str(self.kaffeine_db_path))
            cur = conn.cursor()
            cur.execute("SELECT Id, Name, Number FROM Channels ORDER BY Number ASC, Name ASC")
            channels = [{"id": r[0], "name": r[1], "number": r[2]} for r in cur.fetchall()]
            conn.close()
            return channels
        except Exception as e:
            print(f"Error reading Kaffeine channels: {e}")
            return []

    def get_unconfigured_regional_channels(self) -> List[str]:
        """Detect any scanned channels that are not national networks and lack TV Passport station IDs."""
        national_keys = {"FOX", "CBS", "NBC", "ABC", "PBS", "CW", "THE CW"}
        scanned = self.get_scanned_kaffeine_channels()
        configured_passport = {k.strip().upper() for k in self.tvpassport_stations.keys()}

        # Build reverse lookup of channel aliases from channel_map
        # e.g., if "KPHO" is mapped to "CBS" or vice-versa
        alias_map = {}
        for guide_net, kaff_ch in self.channel_map.items():
            g_up = guide_net.strip().upper()
            k_up = kaff_ch.strip().upper()
            alias_map.setdefault(g_up, set()).add(k_up)
            alias_map.setdefault(k_up, set()).add(g_up)

        unconfigured = []
        for ch in scanned:
            name = ch.get("name", "").strip()
            if not name:
                continue
            name_upper = name.upper()
            
            # Collect all names this channel is known by (scanned name + any mapped aliases)
            all_known_names = {name_upper} | alias_map.get(name_upper, set())

            # Check if any known alias matches a national network
            is_national = any(
                any(nat in alias for nat in national_keys)
                for alias in all_known_names
            )

            # Check if any known alias is configured in TV Passport
            is_in_passport = any(alias in configured_passport for alias in all_known_names)

            if not is_national and not is_in_passport:
                unconfigured.append(name)
        return unconfigured





