"""
Configuration management and theme definitions for Kaffeine DVR.

Manages persistent JSON configuration settings in ~/.config/kaffeine-dvr/,
color themes, channel mappings, recording safety buffers, and bounds checking.
"""

import json
import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

DEFAULT_CHANNEL_MAP: Dict[str, str] = {}

DEFAULT_CATEGORY_COLORS = {
    "sports": "#ffa028",
    "news": "#4fc3f7",
    "movies": "#c084fc",
    "tvshows": "#b9feff",
    "highlight": "#38bdf8",
    "live_badge": "#059669",
    "live_bg": "#132400",
    "time_indicator": "#06b6d4",
    "clock": "#38bdf8",
    "grid_bg": "#222838",
    "past_bg": "#161922",
    "past_bg_alt": "#14171f",
    "past_border": "#262c3a",
    "past_title": "#788292",
    "past_subtext": "#5a6474",
}

DEFAULT_SHORTCUTS: Dict[str, str] = {
    "tab_guide": "Ctrl+1",
    "tab_recordings": "Ctrl+2",
    "tab_settings": "Ctrl+3",
    "tab_help": "Ctrl+4",
    "view_grid": "Ctrl+G",
    "view_list": "Ctrl+L",
    "focus_search": "Ctrl+F",
    "sync_refresh": "F5",
    "jump_now": "Home",
    "jump_primetime": "Alt+P",
    "zoom_in": "Ctrl++",
    "zoom_out": "Ctrl+-",
    "zoom_reset": "Ctrl+0",
    "maximize_grid": "F11",
    "show_shortcuts": "F1",
    "quit_app": "Ctrl+Q",
    "nav_up": "Up",
    "nav_down": "Down",
    "nav_left": "Left",
    "nav_right": "Right",
    "prog_watch": "W",
    "prog_record": "R",
    "prog_auto_record": "A",
    "prog_details": "Return",
}


def compute_past_theme_colors(grid_bg_hex: str, text_primary_hex: Optional[str] = None) -> Dict[str, str]:
    """
    Algorithmically compute harmonious past show colors from any grid_bg and text color.
    Used as an automatic fallback for custom user theme presets.
    """
    import colorsys
    bg_clean = (grid_bg_hex or "#222838").lstrip("#")
    if len(bg_clean) != 6:
        return {
            "past_bg": "#161922",
            "past_bg_alt": "#14171f",
            "past_border": "#262c3a",
            "past_title": "#788292",
            "past_subtext": "#5a6474",
        }
    try:
        r, g, b = [int(bg_clean[i:i+2], 16) / 255.0 for i in (0, 2, 4)]
    except ValueError:
        return {
            "past_bg": "#161922",
            "past_bg_alt": "#14171f",
            "past_border": "#262c3a",
            "past_title": "#788292",
            "past_subtext": "#5a6474",
        }
    h, lum, s = colorsys.rgb_to_hls(r, g, b)

    if lum < 0.08:
        l_past = min(1.0, lum + 0.03)
        l_past_alt = min(1.0, l_past + 0.02)
        l_border = min(1.0, l_past + 0.08)
    else:
        l_past = max(0.04, lum * 0.75)
        l_past_alt = max(0.03, l_past * 0.90)
        l_border = min(1.0, l_past * 1.5)

    s_past = max(0.05, s * 0.70)

    def to_hex(h_val, l_val, s_val):
        rgb = colorsys.hls_to_rgb(h_val, max(0.0, min(1.0, l_val)), max(0.0, min(1.0, s_val)))
        return f"#{int(round(rgb[0]*255)):02x}{int(round(rgb[1]*255)):02x}{int(round(rgb[2]*255)):02x}"

    past_bg = to_hex(h, l_past, s_past)
    past_bg_alt = to_hex(h, l_past_alt, s_past)
    past_border = to_hex(h, l_border, s_past * 0.8)

    l_title = max(0.45, min(0.65, lum + 0.45))
    l_sub = max(0.35, min(0.55, l_title - 0.15))
    s_text = max(0.08, min(0.35, s * 0.6))
    past_title = to_hex(h, l_title, s_text)
    past_subtext = to_hex(h, l_sub, s_text)

    return {
        "past_bg": past_bg,
        "past_bg_alt": past_bg_alt,
        "past_border": past_border,
        "past_title": past_title,
        "past_subtext": past_subtext,
    }

APP_THEMES: Dict[str, Dict[str, str]] = {
    "midnight": {
        "name": "Midnight Navy (Default)",
        "bg_window": "#191c28",
        "bg_panel": "#151822",
        "bg_subpanel": "#1e2333",
        "bg_input": "#12141d",
        "bg_button": "#272d3d",
        "bg_button_hover": "#333a50",
        "bg_button_pressed": "#1e2330",
        "border_color": "#333a4c",
        "border_light": "#3d465c",
        "border_subtabs": "#323a4d",
        "accent_primary": "#2d6cd4",
        "accent_hover": "#3b7ee8",
        "accent_pressed": "#2259b3",
        "text_primary": "#dce1e8",
        "text_secondary": "#8c9bb0",
        "table_header_bg": "#1e2330",
        "table_bg": "#161922",
        "table_gridline": "#2b3242",
        "scrollbar_bg": "#141722",
        "scrollbar_handle": "#4a5568",
        "scrollbar_handle_hover": "#55a84c",
        "scrollbar_handle_pressed": "#43873c",
        "tooltip_bg": "#1e293b",
        "tooltip_border": "#4a8df5",
        "menu_bg": "#1c202e",
        "menu_item_selected": "#2b3346",
    },
    "oled_black": {
        "name": "Obsidian (Pure OLED Black)",
        "bg_window": "#000000",
        "bg_panel": "#0a0a0d",
        "bg_subpanel": "#121217",
        "bg_input": "#050508",
        "bg_button": "#141419",
        "bg_button_hover": "#22222a",
        "bg_button_pressed": "#0a0a0d",
        "border_color": "#26262b",
        "border_light": "#33333a",
        "border_subtabs": "#26262b",
        "accent_primary": "#22c55e",
        "accent_hover": "#28d968",
        "accent_pressed": "#1ca14d",
        "text_primary": "#f4f4f5",
        "text_secondary": "#a1a1aa",
        "table_header_bg": "#0f0f13",
        "table_bg": "#050508",
        "table_gridline": "#1e1e24",
        "scrollbar_bg": "#050508",
        "scrollbar_handle": "#33333d",
        "scrollbar_handle_hover": "#22c55e",
        "scrollbar_handle_pressed": "#1ca14d",
        "tooltip_bg": "#121217",
        "tooltip_border": "#22c55e",
        "menu_bg": "#0d0d11",
        "menu_item_selected": "#1f1f26",
    },
    "nordic_frost": {
        "name": "Nordic Frost (Arctic Slate)",
        "bg_window": "#161c26",
        "bg_panel": "#11161f",
        "bg_subpanel": "#1d2533",
        "bg_input": "#0c1017",
        "bg_button": "#232d3d",
        "bg_button_hover": "#2f3d52",
        "bg_button_pressed": "#19212c",
        "border_color": "#2a374a",
        "border_light": "#384961",
        "border_subtabs": "#273446",
        "accent_primary": "#0284c7",
        "accent_hover": "#0ea5e9",
        "accent_pressed": "#0369a1",
        "text_primary": "#e2e8f0",
        "text_secondary": "#94a3b8",
        "table_header_bg": "#1b2330",
        "table_bg": "#0f141c",
        "table_gridline": "#222c3c",
        "scrollbar_bg": "#0e131b",
        "scrollbar_handle": "#3b495d",
        "scrollbar_handle_hover": "#38bdf8",
        "scrollbar_handle_pressed": "#0284c7",
        "tooltip_bg": "#1a222e",
        "tooltip_border": "#38bdf8",
        "menu_bg": "#171f2b",
        "menu_item_selected": "#263447",
    },
    "charcoal": {
        "name": "Deep Charcoal (Graphite)",
        "bg_window": "#1e2025",
        "bg_panel": "#17181c",
        "bg_subpanel": "#26282f",
        "bg_input": "#121316",
        "bg_button": "#2d3038",
        "bg_button_hover": "#3b3f4a",
        "bg_button_pressed": "#22242a",
        "border_color": "#363a44",
        "border_light": "#454a57",
        "border_subtabs": "#333640",
        "accent_primary": "#4f46e5",
        "accent_hover": "#6366f1",
        "accent_pressed": "#4338ca",
        "text_primary": "#e4e5e9",
        "text_secondary": "#979aa5",
        "table_header_bg": "#24262d",
        "table_bg": "#141518",
        "table_gridline": "#2e313a",
        "scrollbar_bg": "#131417",
        "scrollbar_handle": "#474b57",
        "scrollbar_handle_hover": "#6366f1",
        "scrollbar_handle_pressed": "#4f46e5",
        "tooltip_bg": "#23252c",
        "tooltip_border": "#6366f1",
        "menu_bg": "#1f2127",
        "menu_item_selected": "#31353f",
    },
    "cyberpunk": {
        "name": "Cyberpunk (Neon Matrix)",
        "bg_window": "#0a0d14",
        "bg_panel": "#06090e",
        "bg_subpanel": "#121824",
        "bg_input": "#04060a",
        "bg_button": "#141b29",
        "bg_button_hover": "#1e293d",
        "bg_button_pressed": "#0e131d",
        "border_color": "#1b273b",
        "border_light": "#283954",
        "border_subtabs": "#192437",
        "accent_primary": "#00f0ff",
        "accent_hover": "#38f5ff",
        "accent_pressed": "#00c4d1",
        "text_primary": "#e6edf3",
        "text_secondary": "#7d8fa3",
        "table_header_bg": "#101621",
        "table_bg": "#06080d",
        "table_gridline": "#172132",
        "scrollbar_bg": "#05070c",
        "scrollbar_handle": "#263750",
        "scrollbar_handle_hover": "#00f0ff",
        "scrollbar_handle_pressed": "#00c4d1",
        "tooltip_bg": "#101724",
        "tooltip_border": "#00f0ff",
        "menu_bg": "#0d131d",
        "menu_item_selected": "#1a2538",
    },
    "warm_sunset": {
        "name": "Warm Amber (Espresso Dusk)",
        "bg_window": "#1f1816",
        "bg_panel": "#171210",
        "bg_subpanel": "#29201d",
        "bg_input": "#120e0d",
        "bg_button": "#302421",
        "bg_button_hover": "#42322e",
        "bg_button_pressed": "#241b19",
        "border_color": "#3d2e2a",
        "border_light": "#4f3c36",
        "border_subtabs": "#382925",
        "accent_primary": "#ea580c",
        "accent_hover": "#f97316",
        "accent_pressed": "#c2410c",
        "text_primary": "#f3ede8",
        "text_secondary": "#a89993",
        "table_header_bg": "#261e1b",
        "table_bg": "#140f0e",
        "table_gridline": "#332623",
        "scrollbar_bg": "#130f0e",
        "scrollbar_handle": "#523e38",
        "scrollbar_handle_hover": "#f97316",
        "scrollbar_handle_pressed": "#ea580c",
        "tooltip_bg": "#291f1c",
        "tooltip_border": "#f97316",
        "menu_bg": "#221a18",
        "menu_item_selected": "#3a2c28",
    },
    "synthwave": {
        "name": "Retro Synthwave (Violet Dusk)",
        "bg_window": "#181424",
        "bg_panel": "#120f1c",
        "bg_subpanel": "#221c33",
        "bg_input": "#0e0c16",
        "bg_button": "#29213d",
        "bg_button_hover": "#392e54",
        "bg_button_pressed": "#1f192e",
        "border_color": "#352b4f",
        "border_light": "#463968",
        "border_subtabs": "#312749",
        "accent_primary": "#9333ea",
        "accent_hover": "#a855f7",
        "accent_pressed": "#7e22ce",
        "text_primary": "#eeeaf7",
        "text_secondary": "#9c93b3",
        "table_header_bg": "#1f1a2e",
        "table_bg": "#100d19",
        "table_gridline": "#2c2442",
        "scrollbar_bg": "#0f0c17",
        "scrollbar_handle": "#4a3c6e",
        "scrollbar_handle_hover": "#a855f7",
        "scrollbar_handle_pressed": "#9333ea",
        "tooltip_bg": "#231c34",
        "tooltip_border": "#a855f7",
        "menu_bg": "#1b1629",
        "menu_item_selected": "#332a4d",
    },
}

THEME_PRESETS: Dict[str, Dict[str, Any]] = {
    "cyberpunk": {
        "name": "Cyberpunk / Neon",
        "accent_color": "#ff007f",
        "colors": {
            "sports": "#ff5500",
            "news": "#00f0ff",
            "movies": "#ff007f",
            "tvshows": "#ffe600",
            "highlight": "#00f0ff",
            "live_badge": "#00ff66",
            "live_bg": "#032814",
            "time_indicator": "#ff007f",
            "clock": "#00f0ff",
            "grid_bg": "#1a1228",
            "past_bg": "#13101c",
            "past_bg_alt": "#0f0d17",
            "past_border": "#2b2040",
            "past_title": "#8e82a8",
            "past_subtext": "#655a7a",
        },
    },
    "emerald_forest": {
        "name": "Emerald Forest",
        "accent_color": "#10b981",
        "colors": {
            "sports": "#f59e0b",
            "news": "#4ade80",
            "movies": "#a7f3d0",
            "tvshows": "#6ee7b7",
            "highlight": "#34d399",
            "live_badge": "#15803d",
            "live_bg": "#0a2612",
            "time_indicator": "#10b981",
            "clock": "#6ee7b7",
            "grid_bg": "#14241b",
            "past_bg": "#0f1a14",
            "past_bg_alt": "#0b140f",
            "past_border": "#1d3327",
            "past_title": "#759883",
            "past_subtext": "#52705e",
        },
    },
    "midnight": {
        "name": "Midnight Navy (Default)",
        "accent_color": "#38bdf8",
        "colors": {
            "sports": "#ffa028",
            "news": "#4fc3f7",
            "movies": "#c084fc",
            "tvshows": "#b9feff",
            "highlight": "#38bdf8",
            "live_badge": "#059669",
            "live_bg": "#132400",
            "time_indicator": "#06b6d4",
            "clock": "#38bdf8",
            "grid_bg": "#222838",
            "past_bg": "#161922",
            "past_bg_alt": "#14171f",
            "past_border": "#262c3a",
            "past_title": "#788292",
            "past_subtext": "#5a6474",
        },
    },
    "nordic_frost": {
        "name": "Nordic Frost",
        "accent_color": "#67e8f9",
        "colors": {
            "sports": "#38bdf8",
            "news": "#67e8f9",
            "movies": "#c4b5fd",
            "tvshows": "#e0f2fe",
            "highlight": "#7dd3fc",
            "live_badge": "#10b981",
            "live_bg": "#0c222b",
            "time_indicator": "#38bdf8",
            "clock": "#67e8f9",
            "grid_bg": "#16222f",
            "past_bg": "#121a24",
            "past_bg_alt": "#0e151e",
            "past_border": "#223245",
            "past_title": "#7c93a8",
            "past_subtext": "#566c80",
        },
    },
    "oled_contrast": {
        "name": "OLED High Contrast",
        "accent_color": "#facc15",
        "colors": {
            "sports": "#facc15",
            "news": "#38bdf8",
            "movies": "#f472b6",
            "tvshows": "#ffffff",
            "highlight": "#facc15",
            "live_badge": "#22c55e",
            "live_bg": "#182c00",
            "time_indicator": "#ef4444",
            "clock": "#facc15",
            "grid_bg": "#050505",
            "past_bg": "#000000",
            "past_bg_alt": "#080808",
            "past_border": "#1a1a1a",
            "past_title": "#6b7280",
            "past_subtext": "#4b5563",
        },
    },
    "synthwave": {
        "name": "Retro Synthwave",
        "accent_color": "#a855f7",
        "colors": {
            "sports": "#fb923c",
            "news": "#06b6d4",
            "movies": "#e879f9",
            "tvshows": "#f43f5e",
            "highlight": "#d946ef",
            "live_badge": "#8b5cf6",
            "live_bg": "#1f0933",
            "time_indicator": "#ec4899",
            "clock": "#06b6d4",
            "grid_bg": "#1d162e",
            "past_bg": "#150f22",
            "past_bg_alt": "#110c1b",
            "past_border": "#2f1e4a",
            "past_title": "#957ca8",
            "past_subtext": "#6b567d",
        },
    },
    "warm_sunset": {
        "name": "Warm Amber / Sunset",
        "accent_color": "#f97316",
        "colors": {
            "sports": "#f97316",
            "news": "#f59e0b",
            "movies": "#fb7185",
            "tvshows": "#fde68a",
            "highlight": "#fb923c",
            "live_badge": "#ef4444",
            "live_bg": "#28120c",
            "time_indicator": "#f59e0b",
            "clock": "#fcd34d",
            "grid_bg": "#251c19",
            "past_bg": "#1c1513",
            "past_bg_alt": "#171110",
            "past_border": "#382a25",
            "past_title": "#a89288",
            "past_subtext": "#7a665d",
        },
    },
}
GUIDE_THEME_PRESETS = THEME_PRESETS

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
                        data["guide_days_ahead"] = 14
                    if "auto_sync_interval_hours" not in data:
                        data["auto_sync_interval_hours"] = 6
                    if "watcher_interval_seconds" not in data:
                        data["watcher_interval_seconds"] = 180
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
                        data["launch_mode"] = "tray" if data.get("launch_minimized", True) else "normal"
                    if "enable_desktop_notifications" not in data:
                        data["enable_desktop_notifications"] = True
                    if "persistent_desktop_notifications" not in data:
                        data["persistent_desktop_notifications"] = False
                    if "notification_lead_time_mins" not in data:
                        data["notification_lead_time_mins"] = 2
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
                    if "custom_kaffeine_path" not in data:
                        data["custom_kaffeine_path"] = ""
                    if "end_buffer_mins" not in data:
                        data["end_buffer_mins"] = 0
                    if "sports_buffer_mins" not in data:
                        data["sports_buffer_mins"] = 40
                    if "auto_buffer_sports" not in data:
                        data["auto_buffer_sports"] = True
                    if "max_history_entries" not in data:
                        data["max_history_entries"] = 50
                    if "auto_check_updates" not in data:
                        data["auto_check_updates"] = False
                    if "update_check_frequency" not in data:
                        data["update_check_frequency"] = "weekly"
                    if "last_update_check_timestamp" not in data:
                        data["last_update_check_timestamp"] = 0.0
                    if "dismissed_update_version" not in data:
                        data["dismissed_update_version"] = ""
                    if "playback_player" not in data:
                        data["playback_player"] = "system"
                    if "custom_playback_player_cmd" not in data:
                        data["custom_playback_player_cmd"] = ""
                    if "live_tv_watch_mode" not in data:
                        data["live_tv_watch_mode"] = "timeshift"
                    if "timeshift_buffer_seconds" not in data:
                        data["timeshift_buffer_seconds"] = 2
                    if "zero_byte_recording_timeout_secs" not in data:
                        data["zero_byte_recording_timeout_secs"] = 8
                    if "delete_timeshift_on_exit" not in data:
                        data["delete_timeshift_on_exit"] = True
                    if "tuner_count" not in data:
                        data["tuner_count"] = 0
                    if "grid_visible_rows" not in data:
                        data["grid_visible_rows"] = 9
                    if "guide_detail_lines" not in data:
                        data["guide_detail_lines"] = 3
                    if "live_same_bg_as_others" not in data:
                        data["live_same_bg_as_others"] = False
                    if "hide_live_badge" not in data:
                        data["hide_live_badge"] = False
                    if "guide_auto_advance" not in data:
                        data["guide_auto_advance"] = True
                    if "guide_auto_advance_minute" not in data:
                        data["guide_auto_advance_minute"] = 50
                    if "guide_detail_collapsed" not in data:
                        data["guide_detail_collapsed"] = True
                    if "guide_maximized" not in data:
                        data["guide_maximized"] = False
                    if "guide_show_time_indicator" not in data:
                        data["guide_show_time_indicator"] = True
                    if "time_line_opacity" not in data:
                        data["time_line_opacity"] = 100
                    if "show_clock" not in data:
                        data["show_clock"] = True
                    if "clock_font_size" not in data:
                        data["clock_font_size"] = 11
                    if "settings_ui_scale" not in data:
                        data["settings_ui_scale"] = 100
                    if "app_theme" not in data:
                        data["app_theme"] = "midnight"
                    if "theme_preset" not in data:
                        data["theme_preset"] = "midnight"
                    if "custom_theme_presets" not in data or not isinstance(data.get("custom_theme_presets"), dict):
                        data["custom_theme_presets"] = {}
                    if "category_colors" not in data or not isinstance(data.get("category_colors"), dict):
                        data["category_colors"] = dict(DEFAULT_CATEGORY_COLORS)
                    else:
                        for cat, def_col in DEFAULT_CATEGORY_COLORS.items():
                            if cat not in data["category_colors"]:
                                data["category_colors"][cat] = def_col
                    if "keyboard_shortcuts" not in data or not isinstance(data.get("keyboard_shortcuts"), dict):
                        data["keyboard_shortcuts"] = dict(DEFAULT_SHORTCUTS)
                    else:
                        for sc_k, sc_v in DEFAULT_SHORTCUTS.items():
                            if sc_k not in data["keyboard_shortcuts"]:
                                data["keyboard_shortcuts"][sc_k] = sc_v
                    return data
            except Exception:
                pass

        default_data = self.get_default_config()
        self._save(default_data)
        return default_data

    @staticmethod
    def get_default_config() -> Dict[str, Any]:
        return {
            "channel_map": DEFAULT_CHANNEL_MAP.copy(),
            "rules": [],
            "guide_days_ahead": 14,
            "auto_sync_interval_hours": 6,
            "watcher_interval_seconds": 180,
            "lead_time_mins": 5,
            "launch_minimized": True,
            "launch_mode": "tray",
            "enable_desktop_notifications": True,
            "persistent_desktop_notifications": False,
            "notification_lead_time_mins": 2,
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
            "custom_kaffeine_path": "",
            "end_buffer_mins": 0,
            "sports_buffer_mins": 40,
            "auto_buffer_sports": True,
            "max_history_entries": 50,
            "auto_check_updates": False,
            "update_check_frequency": "weekly",
            "last_update_check_timestamp": 0.0,
            "dismissed_update_version": "",
            "playback_player": "system",
            "custom_playback_player_cmd": "",
            "live_tv_watch_mode": "timeshift",
            "timeshift_buffer_seconds": 2,
            "zero_byte_recording_timeout_secs": 8,
            "delete_timeshift_on_exit": True,
            "tuner_count": 0,
            "grid_visible_rows": 9,
            "guide_detail_lines": 3,
            "guide_detail_collapsed": True,
            "guide_maximized": False,
            "live_same_bg_as_others": False,
            "hide_live_badge": False,
            "guide_auto_advance": True,
            "guide_auto_advance_minute": 50,
            "guide_show_time_indicator": True,
            "time_line_opacity": 100,
            "show_clock": True,
            "clock_font_size": 11,
            "settings_ui_scale": 100,
            "guide_single_click_play": True,
            "use_custom_title_bar": True,
            "app_theme": "midnight",
            "theme_preset": "midnight",
            "custom_theme_presets": {},
            "category_colors": dict(DEFAULT_CATEGORY_COLORS),
            "web_server_enabled": False,
            "web_server_port": 8088,
            "web_server_bind": "0.0.0.0",
            "web_server_password_hash": "",
            "web_server_salt": "",
            "keyboard_shortcuts": dict(DEFAULT_SHORTCUTS)
        }

    def reset_to_defaults(self, keep_channels_and_rules: bool = True):
        cur_channels = self.data.get("channel_map", DEFAULT_CHANNEL_MAP.copy())
        cur_rules = self.data.get("rules", [])
        cur_passport = self.data.get("tvpassport_stations", {})
        cur_first_run = self.data.get("first_run_completed", True)

        defaults = self.get_default_config()
        if keep_channels_and_rules:
            defaults["channel_map"] = cur_channels
            defaults["rules"] = cur_rules
            defaults["tvpassport_stations"] = cur_passport
            defaults["first_run_completed"] = cur_first_run

        self.data = defaults
        self.save()


    def _save(self, data: Dict[str, Any]):
        try:
            tmp_file = self.config_file.with_name(f"{self.config_file.name}.tmp")
            with open(tmp_file, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_file, self.config_file)
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

    def resolve_channel(self, channel_or_network: Optional[str]) -> str:
        """
        Resolves a channel name or guide network to the exact tuned Kaffeine channel name.
        Performs exact match, case-insensitive match, and reverse alias lookup against channel_map.
        If no mapping is found, returns the stripped original string.
        """
        if not channel_or_network:
            return ""
        raw = str(channel_or_network).strip()
        cmap = self.channel_map
        if not cmap:
            return raw

        # 1. Exact key match
        if raw in cmap:
            return cmap[raw]

        # 2. Case-insensitive key match
        raw_upper = raw.upper()
        for k, v in cmap.items():
            if k.strip().upper() == raw_upper:
                return v

        # 3. Exact value match (already a tuned channel name)
        for k, v in cmap.items():
            if v.strip() == raw:
                return v

        # 4. Case-insensitive value match
        for k, v in cmap.items():
            if v.strip().upper() == raw_upper:
                return v

        # 5. Fuzzy network alias matching (e.g., FOX -> Fox, THE CW -> CW)
        for k, v in cmap.items():
            k_upper = k.strip().upper()
            if ("CW" in raw_upper and "CW" in k_upper) or (raw_upper in ("THE CW", "CW") and "CW" in k_upper):
                return v
            if raw_upper == "FOX" and "FOX" in k_upper:
                return v
            if raw_upper == "PBS" and "PBS" in k_upper:
                return v

        return raw


    @property
    def channel_order(self) -> List[str]:
        return self.data.get("channel_order", [])

    @channel_order.setter
    def channel_order(self, val: List[str]):
        if self.channel_map:
            val_to_key = {v: k for k, v in self.channel_map.items()}
            normalized = []
            for ch in val:
                resolved = ch if ch in self.channel_map else val_to_key.get(ch, ch)
                if resolved not in normalized:
                    normalized.append(resolved)
            self.data["channel_order"] = normalized
        else:
            self.data["channel_order"] = val
        self.save()

    def get_ordered_channels(self) -> List[str]:
        """
        Returns all unique channels in configured manual order.
        Strictly reflects the guide display names configured in channel_map (Channel Importing).
        Any active channels not yet in channel_order are appended to the end.
        """
        if not self.channel_map:
            return []

        val_to_key = {v: k for k, v in self.channel_map.items()}
        guide_keys = list(self.channel_map.keys())

        saved_order = self.channel_order
        ordered = []
        for ch in saved_order:
            display_name = ch if ch in self.channel_map else val_to_key.get(ch)
            if display_name and display_name in guide_keys and display_name not in ordered:
                ordered.append(display_name)

        for ch in guide_keys:
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
        return self.data.get("guide_days_ahead", 14)

    @guide_days_ahead.setter
    def guide_days_ahead(self, val: int):
        self.data["guide_days_ahead"] = val
        self.save()

    @property
    def watcher_interval_seconds(self) -> int:
        return self.data.get("watcher_interval_seconds", 180)

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
        return self.data.get("launch_mode", "tray")

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
            self.data["launch_mode"] = "tray"
        self.save()

    @property
    def guide_watch_mode(self) -> str:
        return self.data.get("guide_watch_mode", "minimal")

    @guide_watch_mode.setter
    def guide_watch_mode(self, val: str):
        self.data["guide_watch_mode"] = val
        self.save()

    @property
    def playback_player(self) -> str:
        val = self.data.get("playback_player", "system")
        if val == "kaffeine":
            return "system"
        return val

    @playback_player.setter
    def playback_player(self, val: str):
        self.data["playback_player"] = val
        self.save()

    @property
    def custom_playback_player_cmd(self) -> str:
        return self.data.get("custom_playback_player_cmd", "")

    @custom_playback_player_cmd.setter
    def custom_playback_player_cmd(self, val: str):
        self.data["custom_playback_player_cmd"] = val
        self.save()

    @property
    def live_tv_watch_mode(self) -> str:
        val = self.data.get("live_tv_watch_mode", "smplayer")
        if val in ("timeshift", "kaffeine"):
            val = self.playback_player if self.playback_player != "kaffeine" else "smplayer"
        return val

    @live_tv_watch_mode.setter
    def live_tv_watch_mode(self, val: str):
        self.data["live_tv_watch_mode"] = val
        self.save()

    @property
    def custom_live_tv_player_cmd(self) -> str:
        return self.data.get("custom_live_tv_player_cmd") or self.custom_playback_player_cmd

    @custom_live_tv_player_cmd.setter
    def custom_live_tv_player_cmd(self, val: str):
        self.data["custom_live_tv_player_cmd"] = val
        self.save()

    @property
    def timeshift_buffer_seconds(self) -> int:
        return int(self.data.get("timeshift_buffer_seconds", 2))

    @timeshift_buffer_seconds.setter
    def timeshift_buffer_seconds(self, val: int):
        self.data["timeshift_buffer_seconds"] = max(1, min(30, int(val)))
        self.save()

    @property
    def zero_byte_recording_timeout_secs(self) -> int:
        return int(self.data.get("zero_byte_recording_timeout_secs", 8))

    @zero_byte_recording_timeout_secs.setter
    def zero_byte_recording_timeout_secs(self, val: int):
        self.data["zero_byte_recording_timeout_secs"] = max(3, min(120, int(val)))
        self.save()

    @property
    def delete_timeshift_on_exit(self) -> bool:
        return bool(self.data.get("delete_timeshift_on_exit", True))

    @delete_timeshift_on_exit.setter
    def delete_timeshift_on_exit(self, val: bool):
        self.data["delete_timeshift_on_exit"] = bool(val)
        self.save()

    @property
    def enable_desktop_notifications(self) -> bool:
        return self.data.get("enable_desktop_notifications", True)

    @enable_desktop_notifications.setter
    def enable_desktop_notifications(self, val: bool):
        self.data["enable_desktop_notifications"] = val
        self.save()

    @property
    def persistent_desktop_notifications(self) -> bool:
        return self.data.get("persistent_desktop_notifications", False)

    @persistent_desktop_notifications.setter
    def persistent_desktop_notifications(self, val: bool):
        self.data["persistent_desktop_notifications"] = val
        self.save()

    @property
    def notification_lead_time_mins(self) -> int:
        return self.data.get("notification_lead_time_mins", 2)

    @notification_lead_time_mins.setter
    def notification_lead_time_mins(self, val: int):
        self.data["notification_lead_time_mins"] = max(0, int(val))
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
    def custom_kaffeine_path(self) -> str:
        return self.data.get("custom_kaffeine_path", "")

    @custom_kaffeine_path.setter
    def custom_kaffeine_path(self, val: str):
        self.data["custom_kaffeine_path"] = val
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
        return self.data.get("sports_buffer_mins", 40)

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
            cur.execute("SELECT Id, Name, Number, Transponder FROM Channels ORDER BY Number ASC, Name ASC")
            channels = [{"id": r[0], "name": r[1], "number": r[2], "transponder": r[3] or ""} for r in cur.fetchall()]
            conn.close()
            return channels
        except Exception as e:
            print(f"Error reading Kaffeine channels: {e}")
            return []

    def get_unconfigured_regional_channels(self) -> List[str]:
        """Detect any scanned channels that are not national commercial networks and lack TV Passport station IDs."""
        national_keys = {"FOX", "CBS", "NBC", "ABC"}
        scanned = self.get_scanned_kaffeine_channels()
        configured_passport = {k.strip().upper() for k in self.tvpassport_stations.keys()}

        # Build reverse lookup of channel aliases from channel_map
        # e.g., if "KPHO" is mapped to "CBS" or vice-versa
        alias_map: Dict[str, set[str]] = {}
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

    @property
    def channel_health(self) -> Dict[str, Dict[str, Any]]:
        return self.data.get("channel_health", {})

    @channel_health.setter
    def channel_health(self, val: Dict[str, Dict[str, Any]]):
        self.data["channel_health"] = val
        self.save()

    @property
    def auto_check_updates(self) -> bool:
        return self.data.get("auto_check_updates", False)

    @auto_check_updates.setter
    def auto_check_updates(self, val: bool):
        self.data["auto_check_updates"] = bool(val)
        self.save()

    @property
    def update_check_frequency(self) -> str:
        freq = str(self.data.get("update_check_frequency", "weekly")).lower()
        return freq if freq in ("weekly", "monthly") else "weekly"

    @update_check_frequency.setter
    def update_check_frequency(self, val: str):
        freq = str(val).lower()
        self.data["update_check_frequency"] = freq if freq in ("weekly", "monthly") else "weekly"
        self.save()

    @property
    def last_update_check_timestamp(self) -> float:
        return float(self.data.get("last_update_check_timestamp", 0.0))

    @last_update_check_timestamp.setter
    def last_update_check_timestamp(self, val: float):
        self.data["last_update_check_timestamp"] = float(val)
        self.save()

    @property
    def dismissed_update_version(self) -> str:
        return str(self.data.get("dismissed_update_version", ""))

    @dismissed_update_version.setter
    def dismissed_update_version(self, val: str):
        self.data["dismissed_update_version"] = str(val)
        self.save()

    @property
    def category_colors(self) -> Dict[str, str]:
        raw = self.data.get("category_colors")
        if not isinstance(raw, dict):
            raw = {}
        merged = dict(DEFAULT_CATEGORY_COLORS)
        merged.update(raw)
        return merged

    @property
    def app_theme(self) -> str:
        val = str(self.data.get("app_theme", "midnight"))
        return val if val in APP_THEMES else "midnight"

    @app_theme.setter
    def app_theme(self, val: str):
        self.data["app_theme"] = str(val) if str(val) in APP_THEMES else "midnight"
        self.save()

    def apply_app_theme(self, theme_key: str):
        if theme_key in APP_THEMES:
            self.data["app_theme"] = theme_key
            self.save()

    @property
    def theme_preset(self) -> str:
        return str(self.data.get("theme_preset", "midnight"))

    @theme_preset.setter
    def theme_preset(self, val: str):
        self.data["theme_preset"] = str(val)
        self.save()

    @property
    def guide_theme(self) -> str:
        return self.theme_preset

    @guide_theme.setter
    def guide_theme(self, val: str):
        self.theme_preset = val

    @property
    def custom_theme_presets(self) -> Dict[str, Any]:
        return self.data.get("custom_theme_presets", {})

    def get_all_theme_presets(self) -> Dict[str, Any]:
        combined = dict(THEME_PRESETS)
        combined.update(self.custom_theme_presets)
        return combined

    def save_custom_theme_preset(self, name: str, overwrite_key: Optional[str] = None) -> str:
        clean_name = name.strip()
        if not clean_name:
            raise ValueError("Preset name cannot be empty")
        import re
        slug = re.sub(r"[^a-z0-9_]+", "_", clean_name.lower()).strip("_")
        preset_key = f"custom_{slug}" if not slug.startswith("custom_") else slug
        if not slug:
            preset_key = f"custom_{int(time.time())}"

        presets = dict(self.custom_theme_presets)
        if overwrite_key and overwrite_key in presets:
            if overwrite_key != preset_key:
                del presets[overwrite_key]
        elif preset_key not in presets and len(presets) >= 3:
            raise ValueError("Maximum limit of 3 custom theme presets reached.")

        presets[preset_key] = {
            "name": clean_name,
            "colors": dict(self.category_colors),
        }
        self.data["custom_theme_presets"] = presets
        self.data["theme_preset"] = preset_key
        self.save()
        return preset_key

    def delete_custom_theme_preset(self, preset_key: str) -> bool:
        presets = dict(self.custom_theme_presets)
        if preset_key in presets:
            del presets[preset_key]
            self.data["custom_theme_presets"] = presets
            if self.theme_preset == preset_key:
                self.theme_preset = "midnight"
                if "midnight" in THEME_PRESETS:
                    self.data["category_colors"] = dict(THEME_PRESETS["midnight"]["colors"])
            self.save()
            return True
        return False

    def apply_theme_preset(self, preset_key: str):
        all_presets = self.get_all_theme_presets()
        if preset_key in all_presets:
            preset = all_presets[preset_key]
            self.data["category_colors"] = dict(preset["colors"])
            self.data["theme_preset"] = preset_key
            self.save()

    def apply_guide_theme(self, preset_key: str):
        self.apply_theme_preset(preset_key)

    def set_category_color(self, category: str, hex_color: str):
        colors = dict(self.category_colors)
        colors[category] = str(hex_color).strip()
        self.data["category_colors"] = colors
        self.data["theme_preset"] = "custom"
        self.save()

    def reset_category_colors(self):
        self.data["category_colors"] = dict(DEFAULT_CATEGORY_COLORS)
        self.data["theme_preset"] = "midnight"
        self.save()

    @property
    def grid_visible_rows(self) -> int:
        try:
            return max(4, min(16, int(self.data.get("grid_visible_rows", 9))))
        except (ValueError, TypeError):
            return 9

    @grid_visible_rows.setter
    def grid_visible_rows(self, val: int):
        try:
            self.data["grid_visible_rows"] = max(4, min(16, int(val)))
        except (ValueError, TypeError):
            self.data["grid_visible_rows"] = 9
        self.save()

    @property
    def guide_detail_lines(self) -> int:
        try:
            val = int(self.data.get("guide_detail_lines", 3))
            return 3 if val != 2 else 2
        except (ValueError, TypeError):
            return 3

    @guide_detail_lines.setter
    def guide_detail_lines(self, val: int):
        try:
            v = int(val)
            self.data["guide_detail_lines"] = 2 if v <= 2 else 3
        except (ValueError, TypeError):
            self.data["guide_detail_lines"] = 3
        self.save()

    @property
    def guide_detail_collapsed(self) -> bool:
        return bool(self.data.get("guide_detail_collapsed", True))

    @guide_detail_collapsed.setter
    def guide_detail_collapsed(self, val: bool):
        self.data["guide_detail_collapsed"] = bool(val)
        self.save()

    @property
    def guide_maximized(self) -> bool:
        return bool(self.data.get("guide_maximized", False))

    @guide_maximized.setter
    def guide_maximized(self, val: bool):
        self.data["guide_maximized"] = bool(val)
        self.save()

    @property
    def live_same_bg_as_others(self) -> bool:
        return bool(self.data.get("live_same_bg_as_others", False))

    @live_same_bg_as_others.setter
    def live_same_bg_as_others(self, val: bool):
        self.data["live_same_bg_as_others"] = bool(val)
        self.save()

    @property
    def hide_live_badge(self) -> bool:
        return bool(self.data.get("hide_live_badge", False))

    @hide_live_badge.setter
    def hide_live_badge(self, val: bool):
        self.data["hide_live_badge"] = bool(val)
        self.save()

    @property
    def guide_auto_advance(self) -> bool:
        return bool(self.data.get("guide_auto_advance", True))

    @guide_auto_advance.setter
    def guide_auto_advance(self, val: bool):
        self.data["guide_auto_advance"] = bool(val)
        self.save()

    @property
    def guide_auto_advance_minute(self) -> int:
        return int(self.data.get("guide_auto_advance_minute", 50))

    @guide_auto_advance_minute.setter
    def guide_auto_advance_minute(self, val: int):
        self.data["guide_auto_advance_minute"] = max(0, min(59, int(val)))
        self.save()

    @property
    def guide_show_time_indicator(self) -> bool:
        return bool(self.data.get("guide_show_time_indicator", True))

    @guide_show_time_indicator.setter
    def guide_show_time_indicator(self, val: bool):
        self.data["guide_show_time_indicator"] = bool(val)
        self.save()

    @property
    def time_line_opacity(self) -> int:
        return int(self.data.get("time_line_opacity", 100))

    @time_line_opacity.setter
    def time_line_opacity(self, val: int):
        self.data["time_line_opacity"] = max(10, min(100, int(val)))
        self.save()

    @property
    def show_clock(self) -> bool:
        return bool(self.data.get("show_clock", True))

    @show_clock.setter
    def show_clock(self, val: bool):
        self.data["show_clock"] = bool(val)
        self.save()

    @property
    def clock_font_size(self) -> int:
        return int(self.data.get("clock_font_size", 11))

    @clock_font_size.setter
    def clock_font_size(self, val: int):
        self.data["clock_font_size"] = max(8, min(24, int(val)))
        self.save()

    @property
    def settings_ui_scale(self) -> int:
        return int(self.data.get("settings_ui_scale", 100))

    @settings_ui_scale.setter
    def settings_ui_scale(self, val: int):
        self.data["settings_ui_scale"] = max(90, min(180, int(val)))
        self.save()

    @property
    def use_custom_title_bar(self) -> bool:
        return bool(self.data.get("use_custom_title_bar", True))

    @use_custom_title_bar.setter
    def use_custom_title_bar(self, val: bool):
        self.data["use_custom_title_bar"] = bool(val)
        self.save()

    @property
    def guide_single_click_play(self) -> bool:
        return bool(self.data.get("guide_single_click_play", True))

    @guide_single_click_play.setter
    def guide_single_click_play(self, val: bool):
        self.data["guide_single_click_play"] = bool(val)
        self.save()

    @property
    def web_server_enabled(self) -> bool:
        return bool(self.data.get("web_server_enabled", False))

    @web_server_enabled.setter
    def web_server_enabled(self, val: bool):
        self.data["web_server_enabled"] = bool(val)
        self.save()

    @property
    def web_server_port(self) -> int:
        return int(self.data.get("web_server_port", 8088))

    @web_server_port.setter
    def web_server_port(self, val: int):
        self.data["web_server_port"] = max(1024, min(65535, int(val)))
        self.save()

    @property
    def web_server_bind(self) -> str:
        return str(self.data.get("web_server_bind", "0.0.0.0"))

    @web_server_bind.setter
    def web_server_bind(self, val: str):
        self.data["web_server_bind"] = str(val).strip() or "0.0.0.0"
        self.save()

    @property
    def has_web_password(self) -> bool:
        return bool(self.data.get("web_server_password_hash"))

    def set_web_password(self, password: str):
        """Hashes and stores the web access password with a secure cryptographic salt."""
        import hashlib
        import secrets
        if not password:
            self.data["web_server_password_hash"] = ""
            self.data["web_server_salt"] = ""
        else:
            salt = secrets.token_hex(16)
            h = hashlib.sha256((salt + password).encode("utf-8")).hexdigest()
            self.data["web_server_salt"] = salt
            self.data["web_server_password_hash"] = h
        self.save()

    def verify_web_password(self, password: str) -> bool:
        """Verifies candidate password against stored salt and hash."""
        stored_hash = self.data.get("web_server_password_hash", "")
        if not stored_hash:
            return True
        import hashlib
        import hmac
        salt = self.data.get("web_server_salt", "")
        cand_hash = hashlib.sha256((salt + password).encode("utf-8")).hexdigest()
        return hmac.compare_digest(stored_hash, cand_hash)

    @property
    def tuner_count(self) -> int:
        """User-configured tuner count (0 = Auto-detect)."""
        return int(self.data.get("tuner_count", 0))

    @tuner_count.setter
    def tuner_count(self, val: int):
        self.data["tuner_count"] = max(0, int(val))
        self.save()

    def get_detected_tuner_count(self) -> int:
        """Auto-detect the number of physical DVB frontend tuners on the system."""
        try:
            dvb_path = Path("/dev/dvb")
            if dvb_path.exists():
                frontends = list(dvb_path.glob("adapter*/frontend*"))
                if frontends:
                    return len(frontends)
        except Exception:
            pass
        return 1

    def get_effective_tuner_count(self) -> int:
        """
        Return user-configured tuner count if set (> 0),
        otherwise the auto-detected physical tuner count (minimum 1).
        """
        configured = self.tuner_count
        if configured > 0:
            return configured
        return max(1, self.get_detected_tuner_count())

    @property
    def keyboard_shortcuts(self) -> Dict[str, str]:
        sc = self.data.get("keyboard_shortcuts")
        if not isinstance(sc, dict):
            sc = dict(DEFAULT_SHORTCUTS)
            self.data["keyboard_shortcuts"] = sc
        return sc

    @keyboard_shortcuts.setter
    def keyboard_shortcuts(self, val: Dict[str, str]):
        if isinstance(val, dict):
            self.data["keyboard_shortcuts"] = dict(val)
            self.save()

    def get_shortcut(self, key_id: str, default: Optional[str] = None) -> str:
        sc = self.keyboard_shortcuts
        if key_id in sc:
            return sc[key_id]
        if default is not None:
            return default
        return DEFAULT_SHORTCUTS.get(key_id, "")

    def set_shortcut(self, key_id: str, key_seq: str):
        sc = dict(self.keyboard_shortcuts)
        sc[key_id] = key_seq.strip()
        self.keyboard_shortcuts = sc

    def reset_shortcuts_to_defaults(self):
        self.keyboard_shortcuts = dict(DEFAULT_SHORTCUTS)


