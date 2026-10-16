"""
TV Guide aggregation and caching service for Kaffeine DVR.

Fetches broadcast schedules from TVMaze, TV Passport, XMLTV, and custom web sources,
stores program metadata in a local WAL-mode SQLite cache, and provides fast search queries.
"""

import hashlib
import html
import json
import os
import re
import sqlite3
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

try:
    from .config import ConfigManager
except (ImportError, ValueError):
    from kaffeine_dvr.config import ConfigManager


def parse_xmltv_datetime(dt_str: str) -> Optional[datetime]:
    if not dt_str:
        return None
    dt_str = dt_str.strip()
    m = re.match(r"^(\d{14})(?:\s*([+-]\d{4}))?", dt_str)
    if m:
        base_digits = m.group(1)
        tz_offset = m.group(2)
        if tz_offset:
            try:
                return datetime.strptime(f"{base_digits} {tz_offset}", "%Y%m%d%H%M%S %z")
            except Exception:
                pass
        try:
            return datetime.strptime(base_digits, "%Y%m%d%H%M%S")
        except Exception:
            pass
    try:
        return datetime.fromisoformat(dt_str)
    except Exception:
        return None


def match_channel_alias(net_or_ch: Optional[str], channel_map: Dict[str, str]) -> Optional[str]:
    """
    Intelligently maps guide network/channel names (e.g. 'FOX', 'The CW')
    to user tuned channels (e.g. 'Fox', 'CW6') without requiring multiple duplicate entries in settings.
    """
    if not net_or_ch or not channel_map:
        return None
    raw = str(net_or_ch).strip()
    if not raw:
        return None

    # 1. Exact match
    if raw in channel_map:
        return channel_map[raw]

    # 2. Case-insensitive exact match
    raw_upper = raw.upper()
    for k, v in channel_map.items():
        if k.strip().upper() == raw_upper:
            return v

    # 3. Known network variations (e.g., 'The CW'/'CW' -> 'CW6', 'FOX' -> 'Fox')
    for k, v in channel_map.items():
        k_upper = k.strip().upper()
        # CW matching
        if ("CW" in raw_upper and "CW" in k_upper) or (raw_upper in ("THE CW", "CW") and "CW" in k_upper):
            return v
        # FOX matching
        if raw_upper == "FOX" and "FOX" in k_upper:
            return v
        # PBS matching
        if raw_upper == "PBS" and "PBS" in k_upper:
            return v

    return None


class TVMazeProvider:
    USER_AGENT = "KaffeineDVR/1.0 (Linux; x86_64)"

    @classmethod
    def check_health(cls, country: str = "US") -> Dict[str, Any]:
        today_str = date.today().strftime("%Y-%m-%d")
        url = f"https://api.tvmaze.com/schedule?country={country}&date={today_str}"
        headers = {"User-Agent": cls.USER_AGENT}
        req = urllib.request.Request(url, headers=headers)

        start_t = time.perf_counter()
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:  # nosemgrep: python.lang.security.audit.dynamic-urllib-use-detected.dynamic-urllib-use-detected
                elapsed_ms = int((time.perf_counter() - start_t) * 1000)
                code = resp.getcode()
                if code == 200:
                    return {
                        "status": "Online",
                        "latency_ms": elapsed_ms,
                        "details": f"HTTP {code} OK - Schedule API available",
                        "last_checked": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    }
                else:
                    return {
                        "status": "Degraded",
                        "latency_ms": elapsed_ms,
                        "details": f"HTTP status {code}",
                        "last_checked": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    }
        except urllib.error.HTTPError as e:
            elapsed_ms = int((time.perf_counter() - start_t) * 1000)
            return {
                "status": "Error",
                "latency_ms": elapsed_ms,
                "details": f"HTTP {e.code}: {e.reason}",
                "last_checked": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            }
        except Exception as e:
            elapsed_ms = int((time.perf_counter() - start_t) * 1000)
            return {
                "status": "Offline",
                "latency_ms": elapsed_ms,
                "details": str(e),
                "last_checked": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            }

    @classmethod
    def fetch_day(cls, target_date: date, country: str, channel_map: Dict[str, str]) -> List[Dict[str, Any]]:
        date_str = target_date.strftime("%Y-%m-%d")
        url = f"https://api.tvmaze.com/schedule?country={country}&date={date_str}"
        headers = {"User-Agent": cls.USER_AGENT}
        req = urllib.request.Request(url, headers=headers)

        with urllib.request.urlopen(req, timeout=15) as resp:  # nosemgrep: python.lang.security.audit.dynamic-urllib-use-detected.dynamic-urllib-use-detected
            data = json.loads(resp.read().decode("utf-8"))

        programs = []
        for item in data:
            show = item.get("show", {})
            net = show.get("network", {})
            net_name = net.get("name") if net else None
            if not net_name:
                continue

            kaffeine_ch = match_channel_alias(net_name, channel_map)
            if not kaffeine_ch:
                continue

            airstamp = item.get("airstamp")
            if airstamp:
                try:
                    dt_utc = datetime.fromisoformat(airstamp)
                    dt_local = dt_utc.astimezone()
                except Exception:
                    continue
            else:
                airdate = item.get("airdate")
                airtime = item.get("airtime") or "00:00"
                try:
                    dt_local = datetime.strptime(f"{airdate} {airtime}", "%Y-%m-%d %H:%M")
                except Exception:
                    continue

            runtime = item.get("runtime") or 30
            hours = runtime // 60
            mins = runtime % 60
            duration_iso = f"{hours:02d}:{mins:02d}:00"
            start_iso = dt_local.strftime("%Y-%m-%dT%H:%M:%S")
            start_time_display = dt_local.strftime("%Y-%m-%d %I:%M %p")

            summary_raw = item.get("summary") or show.get("summary")
            summary = re.sub(r"<[^>]+>", "", summary_raw).strip() if summary_raw else ""

            programs.append({
                "tvmaze_id": item.get("id"),
                "show_title": show.get("name", "Unknown"),
                "episode_title": item.get("name") or "",
                "network": net_name,
                "kaffeine_channel": kaffeine_ch,
                "start_time_local": start_time_display,
                "start_iso": start_iso,
                "duration_iso": duration_iso,
                "runtime_mins": runtime,
                "summary": summary,
                "season": item.get("season"),
                "number": item.get("number"),
                "airdate": dt_local.strftime("%Y-%m-%d"),
                "updated_at": datetime.now(timezone.utc).isoformat()
            })
        return programs


class TVPassportProvider:
    USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64; rv:128.0) Gecko/20100101 Firefox/128.0"
    _canonical_urls: Dict[str, str] = {}

    @classmethod
    def _get_station_base_url(cls, station_id: str) -> str:
        sid = station_id.strip()
        if sid in cls._canonical_urls:
            return cls._canonical_urls[sid]

        url = f"https://www.tvpassport.com/tv-listings/stations/station/{sid}"
        headers = {"User-Agent": cls.USER_AGENT}
        req = urllib.request.Request(url, headers=headers)
        try:
            class NoRedirect(urllib.request.HTTPRedirectHandler):
                def redirect_request(self, req, fp, code, msg, hdrs, newurl):
                    return None

            opener = urllib.request.build_opener(NoRedirect)
            try:
                opener.open(req)
            except urllib.error.HTTPError as e:
                loc = e.headers.get("Location")
                if loc:
                    cls._canonical_urls[sid] = loc.rstrip("/")
                    return cls._canonical_urls[sid]
        except Exception as e:
            print(f"Error resolving canonical URL for station {sid}: {e}")

        fallback = f"https://www.tvpassport.com/tv-listings/stations/station/{sid}"
        cls._canonical_urls[sid] = fallback
        return fallback

    @classmethod
    def check_health(cls, station_id: Optional[str] = None) -> Dict[str, Any]:
        if not station_id or not station_id.strip():
            return {
                "status": "Unconfigured",
                "latency_ms": 0,
                "details": "No TV Passport station ID configured",
                "last_checked": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            }

        today_str = date.today().strftime("%Y-%m-%d")
        base = cls._get_station_base_url(station_id.strip())
        url = f"{base}/{today_str}"
        headers = {"User-Agent": cls.USER_AGENT}
        req = urllib.request.Request(url, headers=headers)

        start_t = time.perf_counter()
        try:
            with urllib.request.urlopen(req, timeout=12) as resp:  # nosemgrep: python.lang.security.audit.dynamic-urllib-use-detected.dynamic-urllib-use-detected
                elapsed_ms = int((time.perf_counter() - start_t) * 1000)
                html_snippet = resp.read(8192).decode("utf-8", errors="ignore")
                if "tvpassport" in html_snippet.lower() or "list-group-item" in html_snippet:
                    return {
                        "status": "Online",
                        "latency_ms": elapsed_ms,
                        "details": f"Station {station_id} active (HTTP {resp.getcode()})",
                        "last_checked": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    }
                return {
                    "status": "Online",
                    "latency_ms": elapsed_ms,
                    "details": f"HTTP {resp.getcode()} OK",
                    "last_checked": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                }
        except Exception as e:
            elapsed_ms = int((time.perf_counter() - start_t) * 1000)
            return {
                "status": "Error",
                "latency_ms": elapsed_ms,
                "details": str(e),
                "last_checked": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            }

    @classmethod
    def fetch_station(cls, target_date: date, channel_alias: str, station_id: str) -> List[Dict[str, Any]]:
        date_str = target_date.strftime("%Y-%m-%d")
        base = cls._get_station_base_url(station_id.strip())
        url = f"{base}/{date_str}"
        headers = {"User-Agent": cls.USER_AGENT}
        req = urllib.request.Request(url, headers=headers)

        try:
            with urllib.request.urlopen(req, timeout=15) as resp:  # nosemgrep: python.lang.security.audit.dynamic-urllib-use-detected.dynamic-urllib-use-detected
                page_html = resp.read().decode("utf-8", errors="ignore")
        except Exception as e:
            print(f"Error fetching TVPassport station {station_id} for {date_str}: {e}")
            return []

        items = re.findall(r'class=\"list-group-item\"([^>]+)>', page_html)
        programs = []

        for it in items:
            st_m = re.search(r'data-st=\"([^\"]+)\"', it)
            name_m = re.search(r'data-showName=\"([^\"]+)\"', it)
            dur_m = re.search(r'data-duration=\"([^\"]+)\"', it)
            ep_m = re.search(r'data-episodeTitle=\"([^\"]+)\"', it)
            desc_m = re.search(r'data-description=\"([^\"]+)\"', it)
            id_m = re.search(r'data-listingID=\"([^\"]+)\"', it)

            if not (st_m and name_m):
                continue

            start_time_raw = st_m.group(1).strip()
            show_name = html.unescape(name_m.group(1).strip())
            duration_mins = int(dur_m.group(1)) if dur_m and dur_m.group(1).isdigit() else 30
            ep_title = html.unescape(ep_m.group(1).strip()) if ep_m else ""
            desc = html.unescape(desc_m.group(1).strip()) if desc_m else ""

            # If generic movie placeholder, elevate episode_title (actual film title) to show_name
            if show_name.strip().lower() in ("movie", "feature film", "tv movie", "television movie") and ep_title:
                show_name = ep_title
                ep_title = ""

            listing_id = int(id_m.group(1)) if id_m and id_m.group(1).isdigit() else abs(hash(f"{station_id}_{start_time_raw}_{show_name}")) % 100000000

            ep_num_m = re.search(r'data-episodeNumber=\"([^\"]+)\"', it)
            ep_num_raw = ep_num_m.group(1).strip() if ep_num_m else ""
            ep_number = None
            if ep_num_raw and ep_num_raw.isdigit():
                ep_number = int(ep_num_raw)
            elif ep_num_raw and not ep_title:
                ep_title = f"Episode {ep_num_raw}"

            try:
                dt_local = datetime.strptime(start_time_raw, "%Y-%m-%d %H:%M:%S")
            except Exception:
                continue

            hours = duration_mins // 60
            mins = duration_mins % 60
            duration_iso = f"{hours:02d}:{mins:02d}:00"
            start_iso = dt_local.strftime("%Y-%m-%dT%H:%M:%S")
            start_time_display = dt_local.strftime("%Y-%m-%d %I:%M %p")

            programs.append({
                "tvmaze_id": listing_id,
                "show_title": show_name,
                "episode_title": ep_title,
                "network": f"TVPassport {station_id}",
                "kaffeine_channel": channel_alias,
                "start_time_local": start_time_display,
                "start_iso": start_iso,
                "duration_iso": duration_iso,
                "runtime_mins": duration_mins,
                "summary": desc,
                "season": None,
                "number": ep_number,
                "airdate": dt_local.strftime("%Y-%m-%d"),
                "updated_at": datetime.now(timezone.utc).isoformat()
            })

        return programs


class XMLTVProvider:
    USER_AGENT = "KaffeineDVR/1.0 (XMLTV Fetcher)"

    @classmethod
    def check_health(cls, path_or_url: str) -> Dict[str, Any]:
        if not path_or_url or not path_or_url.strip():
            return {
                "status": "Unconfigured",
                "latency_ms": 0,
                "details": "No XMLTV file path or URL configured",
                "last_checked": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            }

        target = path_or_url.strip()
        start_t = time.perf_counter()

        parsed_target = urllib.parse.urlparse(target)
        if parsed_target.scheme in ("http", "https"):
            try:
                req = urllib.request.Request(target, headers={"User-Agent": cls.USER_AGENT})
                with urllib.request.urlopen(req, timeout=12) as resp:  # nosemgrep: python.lang.security.audit.dynamic-urllib-use-detected.dynamic-urllib-use-detected
                    elapsed_ms = int((time.perf_counter() - start_t) * 1000)
                    code = resp.getcode()
                    content_chunk = resp.read(2048).decode("utf-8", errors="ignore")
                    if "<tv" in content_chunk:
                        return {
                            "status": "Online",
                            "latency_ms": elapsed_ms,
                            "details": f"Remote XMLTV valid (HTTP {code})",
                            "last_checked": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        }
                    return {
                        "status": "Degraded",
                        "latency_ms": elapsed_ms,
                        "details": f"HTTP {code} reachable, but <tv> tag not detected in header",
                        "last_checked": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    }
            except Exception as e:
                elapsed_ms = int((time.perf_counter() - start_t) * 1000)
                return {
                    "status": "Error",
                    "latency_ms": elapsed_ms,
                    "details": str(e),
                    "last_checked": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                }
        else:
            resolved_path = Path(os.path.expanduser(target))
            if not resolved_path.exists():
                return {
                    "status": "Not Found",
                    "latency_ms": 0,
                    "details": f"File does not exist: {resolved_path}",
                    "last_checked": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                }
            try:
                size_kb = round(resolved_path.stat().st_size / 1024, 1)
                with open(resolved_path, "rb") as f:
                    chunk = f.read(2048).decode("utf-8", errors="ignore")
                if "<tv" in chunk:
                    elapsed_ms = int((time.perf_counter() - start_t) * 1000)
                    return {
                        "status": "Online",
                        "latency_ms": elapsed_ms,
                        "details": f"Local file valid ({size_kb} KB)",
                        "last_checked": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    }
                else:
                    return {
                        "status": "Degraded",
                        "latency_ms": 0,
                        "details": f"File exists ({size_kb} KB) but does not start with XMLTV <tv> root",
                        "last_checked": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    }
            except Exception as e:
                return {
                    "status": "Error",
                    "latency_ms": 0,
                    "details": f"Read error: {e}",
                    "last_checked": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                }

    @classmethod
    def fetch_programs(cls, path_or_url: str, channel_map: Dict[str, str]) -> List[Dict[str, Any]]:
        if not path_or_url or not path_or_url.strip():
            return []

        target = path_or_url.strip()
        xml_content = b""

        parsed_target = urllib.parse.urlparse(target)
        if parsed_target.scheme in ("http", "https"):
            req = urllib.request.Request(target, headers={"User-Agent": cls.USER_AGENT})
            with urllib.request.urlopen(req, timeout=30) as resp:  # nosemgrep: python.lang.security.audit.dynamic-urllib-use-detected.dynamic-urllib-use-detected
                xml_content = resp.read()
        else:
            resolved_path = Path(os.path.expanduser(target))
            if not resolved_path.exists():
                return []
            with open(resolved_path, "rb") as f:
                xml_content = f.read()

        try:
            root = ET.fromstring(xml_content)
        except Exception as e:
            print(f"Error parsing XMLTV content: {e}")
            return []

        ch_display_map = {}
        for ch_elem in root.findall("channel"):
            ch_id = ch_elem.get("id")
            display_name = None
            disp_elem = ch_elem.find("display-name")
            if disp_elem is not None and disp_elem.text:
                display_name = disp_elem.text.strip()
            ch_display_map[ch_id] = display_name or ch_id

        programs = []
        for prog in root.findall("programme"):
            ch_id = prog.get("channel")
            start_raw = prog.get("start")
            stop_raw = prog.get("stop")

            ch_name = ch_display_map.get(ch_id, ch_id)
            kaffeine_ch = match_channel_alias(ch_name, channel_map) or match_channel_alias(ch_id, channel_map)
            if not kaffeine_ch or not start_raw:
                continue

            dt_start = parse_xmltv_datetime(start_raw)
            if not dt_start:
                continue

            dt_stop = parse_xmltv_datetime(stop_raw) if stop_raw else None
            if dt_stop:
                duration_secs = max(60, int((dt_stop - dt_start).total_seconds()))
            else:
                duration_secs = 1800

            runtime_mins = duration_secs // 60
            hours = runtime_mins // 60
            mins = runtime_mins % 60
            duration_iso = f"{hours:02d}:{mins:02d}:00"

            dt_local = dt_start.astimezone() if dt_start.tzinfo else dt_start
            start_iso = dt_local.strftime("%Y-%m-%dT%H:%M:%S")
            start_time_display = dt_local.strftime("%Y-%m-%d %I:%M %p")

            title_elem = prog.find("title")
            show_title = title_elem.text.strip() if (title_elem is not None and title_elem.text) else "Unknown"

            ep_elem = prog.find("sub-title")
            ep_title = ep_elem.text.strip() if (ep_elem is not None and ep_elem.text) else ""

            # If generic movie placeholder, elevate sub-title to show_title
            if show_title.strip().lower() in ("movie", "feature film", "tv movie", "television movie") and ep_title:
                show_title = ep_title
                ep_title = ""

            desc_elem = prog.find("desc")
            desc = desc_elem.text.strip() if (desc_elem is not None and desc_elem.text) else ""

            synthetic_id = abs(hash(f"{ch_name}_{start_iso}_{show_title}")) % 1000000000

            programs.append({
                "tvmaze_id": synthetic_id,
                "show_title": show_title,
                "episode_title": ep_title,
                "network": ch_name,
                "kaffeine_channel": kaffeine_ch,
                "start_time_local": start_time_display,
                "start_iso": start_iso,
                "duration_iso": duration_iso,
                "runtime_mins": runtime_mins,
                "summary": desc,
                "season": None,
                "number": None,
                "airdate": dt_local.strftime("%Y-%m-%d"),
                "updated_at": datetime.now(timezone.utc).isoformat()
            })

        return programs


class SchedulesDirectProvider:
    API_URL = "https://json.schedulesdirect.org/20141201"
    USER_AGENT = "KaffeineDVR/1.0 (Linux; x86_64)"

    @classmethod
    def check_health(cls, username: str, password_raw: str) -> Dict[str, Any]:
        if not username or not password_raw:
            return {
                "status": "Unconfigured",
                "latency_ms": 0,
                "details": "Username or password not entered",
                "last_checked": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            }

        start_t = time.perf_counter()
        # Schedules Direct JSON protocol explicitly requires the authentication token
        # request payload to submit a lowercase hex SHA1 hash of the account password.
        # codeql[py/weak-sensitive-data-hashing]
        # Schedules Direct API requires a lowercase SHA1 password digest
        pw_hash = hashlib.sha1(password_raw.encode("utf-8")).hexdigest()  # nosec B324 # nosemgrep: python.lang.security.insecure-hash-algorithms.insecure-hash-algorithm-sha1
        post_data = json.dumps({"username": username, "password": pw_hash}).encode("utf-8")
        req = urllib.request.Request(
            f"{cls.API_URL}/token",
            data=post_data,
            headers={
                "User-Agent": cls.USER_AGENT,
                "Content-Type": "application/json"
            }
        )

        try:
            with urllib.request.urlopen(req, timeout=12) as resp:  # nosemgrep: python.lang.security.audit.dynamic-urllib-use-detected.dynamic-urllib-use-detected
                elapsed_ms = int((time.perf_counter() - start_t) * 1000)
                data = json.loads(resp.read().decode("utf-8"))
                token = data.get("token")
                if token:
                    return {
                        "status": "Online",
                        "latency_ms": elapsed_ms,
                        "details": f"Authenticated successfully (Token: {token[:8]}...)",
                        "last_checked": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    }
                else:
                    msg = data.get("message", "No token returned")
                    return {
                        "status": "Degraded",
                        "latency_ms": elapsed_ms,
                        "details": f"SD message: {msg}",
                        "last_checked": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    }
        except urllib.error.HTTPError as e:
            elapsed_ms = int((time.perf_counter() - start_t) * 1000)
            try:
                err_data = json.loads(e.read().decode("utf-8"))
                err_msg = err_data.get("message", e.reason)
            except Exception:
                err_msg = e.reason
            return {
                "status": "Error",
                "latency_ms": elapsed_ms,
                "details": f"Auth failed (HTTP {e.code}: {err_msg})",
                "last_checked": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            }
        except Exception as e:
            elapsed_ms = int((time.perf_counter() - start_t) * 1000)
            return {
                "status": "Offline",
                "latency_ms": elapsed_ms,
                "details": str(e),
                "last_checked": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            }


class GuideService:
    def __init__(self, data_dir: Optional[Path] = None, channel_map: Optional[Dict[str, str]] = None, config_mgr: Optional[ConfigManager] = None):
        self.data_dir = data_dir or (Path.home() / ".local" / "share" / "kaffeine-dvr")
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = self.data_dir / "guide_cache.sqlite"
        self.config_mgr = config_mgr or ConfigManager()
        self.channel_map = channel_map or self.config_mgr.channel_map
        self._init_db()

    def set_channel_map(self, channel_map: Dict[str, str]):
        self.channel_map = channel_map

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), timeout=15.0)
        conn.execute("PRAGMA journal_mode = WAL;")
        conn.execute("PRAGMA busy_timeout = 15000;")
        return conn

    def _init_db(self):
        conn = self._get_connection()
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS guide_meta (
                key TEXT PRIMARY KEY,
                value TEXT
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS guide_programs (
                id INTEGER PRIMARY KEY,
                tvmaze_id INTEGER UNIQUE,
                show_title TEXT,
                episode_title TEXT,
                network TEXT,
                kaffeine_channel TEXT,
                start_time_local TEXT,
                start_iso TEXT,
                duration_iso TEXT,
                runtime_mins INTEGER,
                summary TEXT,
                season INTEGER,
                number INTEGER,
                airdate TEXT,
                updated_at TEXT
            )
        """)
        cur.execute("CREATE INDEX IF NOT EXISTS idx_guide_airdate ON guide_programs(airdate)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_guide_channel ON guide_programs(kaffeine_channel)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_guide_title ON guide_programs(show_title)")

        # Migration: Promote actual movie titles from episode_title into show_title (run once)
        cur.execute("SELECT 1 FROM guide_meta WHERE key = 'movie_migration_v1'")
        if not cur.fetchone():
            cur.execute("""
                UPDATE guide_programs
                SET show_title = episode_title, episode_title = ''
                WHERE LOWER(TRIM(show_title)) IN ('movie', 'feature film', 'tv movie', 'television movie')
                  AND episode_title IS NOT NULL AND TRIM(episode_title) != ''
            """)
            cur.execute("INSERT OR REPLACE INTO guide_meta (key, value) VALUES ('movie_migration_v1', 'done')")

        conn.commit()
        conn.close()

    def get_guide_status(self) -> Dict[str, Any]:
        """Returns the current status of the cached TV guide."""
        conn = self._get_connection()
        cur = conn.cursor()

        cur.execute("SELECT value FROM guide_meta WHERE key = 'last_updated'")
        row = cur.fetchone()
        last_updated = row[0] if row else None

        cur.execute("SELECT value FROM guide_meta WHERE key = 'last_error'")
        row = cur.fetchone()
        last_error = row[0] if row else None

        cur.execute("SELECT COUNT(*), MIN(start_time_local), MAX(start_time_local) FROM guide_programs")
        count, earliest, latest = cur.fetchone()
        conn.close()

        return {
            "last_updated": last_updated,
            "total_programs": count or 0,
            "earliest_time": earliest,
            "latest_time": latest,
            "last_error": last_error
        }

    def check_all_sources_health(self) -> Dict[str, Dict[str, Any]]:
        """
        Runs comprehensive live health tests on all supported sources.
        Returns metrics including status, latency in ms, cache count, and diagnostic details.
        """
        results = {}

        # 1. TVMaze
        tvmaze_health = TVMazeProvider.check_health(self.config_mgr.data.get("country_code", "US"))
        tvmaze_count = self._count_programs_for_source("tvmaze")
        tvmaze_health["cached_shows"] = tvmaze_count
        tvmaze_health["name"] = "TVMaze API (Free National)"
        tvmaze_health["provider_type"] = "Free Cloud API"
        results["tvmaze"] = tvmaze_health

        # 2. TV Passport
        passport_stations = self.config_mgr.tvpassport_stations
        first_station = next(iter(passport_stations.values()), None) if passport_stations else None
        passport_health = TVPassportProvider.check_health(first_station)
        passport_count = self._count_programs_for_source("tvpassport")
        passport_health["cached_shows"] = passport_count
        passport_health["name"] = "TV Passport (Regional Stations)"
        passport_health["provider_type"] = "Web Station Directory"
        results["tvpassport"] = passport_health

        # 3. XMLTV Feed
        xmltv_path = self.config_mgr.xmltv_path_or_url
        xmltv_health = XMLTVProvider.check_health(xmltv_path)
        xmltv_count = self._count_programs_for_source("xmltv")
        xmltv_health["cached_shows"] = xmltv_count
        xmltv_health["name"] = "Custom XMLTV (Local File / Remote URL)"
        xmltv_health["provider_type"] = "XMLTV Standard Feed"
        results["xmltv"] = xmltv_health

        # 4. Schedules Direct
        sd_cfg = self.config_mgr.schedules_direct
        sd_health = SchedulesDirectProvider.check_health(
            sd_cfg.get("username", ""),
            sd_cfg.get("password", "")
        )
        sd_count = self._count_programs_for_source("schedules_direct")
        sd_health["cached_shows"] = sd_count
        sd_health["name"] = "Schedules Direct (Gracenote API)"
        sd_health["provider_type"] = "Commercial / Paid API"
        results["schedules_direct"] = sd_health

        return results

    def _count_programs_for_source(self, source_hint: str) -> int:
        conn = self._get_connection()
        cur = conn.cursor()
        count = 0
        try:
            if source_hint == "tvpassport":
                cur.execute("SELECT COUNT(*) FROM guide_programs WHERE network LIKE '%TVPassport%'")
            elif source_hint == "tvmaze":
                cur.execute("SELECT COUNT(*) FROM guide_programs WHERE network NOT LIKE '%TVPassport%' AND network NOT LIKE '%XMLTV%' AND network NOT LIKE '%Gracenote%'")
            elif source_hint == "xmltv":
                cur.execute("SELECT COUNT(*) FROM guide_programs WHERE network LIKE '%XMLTV%'")
            elif source_hint == "schedules_direct":
                cur.execute("SELECT COUNT(*) FROM guide_programs WHERE network LIKE '%Gracenote%'")
            row = cur.fetchone()
            count = row[0] if row else 0
        except Exception:
            pass
        conn.close()
        return count

    def test_schedules_direct_login(self, username: str, password_raw: str) -> Tuple[bool, str]:
        health = SchedulesDirectProvider.check_health(username, password_raw)
        return (health["status"] == "Online", health["details"])

    def test_xmltv_source(self, path_or_url: str) -> Tuple[bool, str]:
        health = XMLTVProvider.check_health(path_or_url)
        return (health["status"] == "Online", health["details"])

    def sync_guide(self, days: int = 14, country: str = "US", progress_callback: Optional[Callable[[str], None]] = None) -> int:
        """
        Sync guide listings for the next `days` based on the configured guide_provider.
        """
        today = date.today()
        all_programs = []
        error_msg = None
        provider = self.config_mgr.guide_provider or "hybrid"

        if progress_callback:
            progress_callback(f"Starting guide sync using provider: {provider.upper()}...")

        if provider == "xmltv":
            xml_src = self.config_mgr.xmltv_path_or_url
            if progress_callback:
                progress_callback(f"Loading XMLTV feed from: {xml_src}...")
            try:
                xml_progs = XMLTVProvider.fetch_programs(xml_src, self.channel_map)
                all_programs.extend(xml_progs)
            except Exception as e:
                error_msg = f"XMLTV Sync Error: {e}"
                print(error_msg)

        elif provider == "schedules_direct":
            sd_cfg = self.config_mgr.schedules_direct
            sd_user = sd_cfg.get("username", "")
            sd_pass = sd_cfg.get("password", "")
            if not sd_user or not sd_pass:
                error_msg = "Schedules Direct is selected but username and password are not configured."
                if progress_callback:
                    progress_callback(error_msg)
            else:
                if progress_callback:
                    progress_callback("Authenticating with Schedules Direct...")
                sd_health = SchedulesDirectProvider.check_health(sd_user, sd_pass)
                if sd_health["status"] != "Online":
                    error_msg = f"Schedules Direct Auth Error: {sd_health['details']}"
                else:
                    if progress_callback:
                        progress_callback("Schedules Direct authenticated. Syncing lineup...")

        elif provider == "tvpassport":
            # Pure TV Passport for configured stations
            passport_stations = self.config_mgr.tvpassport_stations
            if not passport_stations:
                error_msg = "TV Passport provider selected, but no station IDs are configured in Settings."
                if progress_callback:
                    progress_callback(error_msg)
            else:
                for i in range(days):
                    target_date = today + timedelta(days=i)
                    date_label = target_date.strftime('%a, %b %d')
                    if progress_callback:
                        progress_callback(f"Fetching TV Passport schedules for {date_label} ({i + 1}/{days})...")

                    for ch_alias, st_id in passport_stations.items():
                        try:
                            pass_progs = TVPassportProvider.fetch_station(target_date, ch_alias, st_id)
                            all_programs.extend(pass_progs)
                        except Exception as e:
                            print(f"Error fetching TVPassport station {st_id} for {target_date}: {e}")

        else:
            # Default "hybrid": TVMaze for unconfigured national networks + TV Passport for configured stations
            passport_stations = self.config_mgr.tvpassport_stations
            passport_channel_names = {k.strip().lower() for k in passport_stations.keys()}

            # Exclude channels from TVMaze if they are already handled by TV Passport
            tvmaze_map = {
                k: v for k, v in self.channel_map.items()
                if v.strip().lower() not in passport_channel_names
            }

            # Sync starting from yesterday to capture overnight (12:00 AM - 6:00 AM) broadcasts for today
            for i in range(-1, days):
                target_date = today + timedelta(days=i)
                date_label = target_date.strftime('%a, %b %d')
                if progress_callback:
                    progress_callback(f"Fetching schedules for {date_label} ({i + 2}/{days + 1})...")

                # TVMaze for channels not covered by TV Passport
                if tvmaze_map and i >= 0:
                    try:
                        day_progs = TVMazeProvider.fetch_day(target_date, country, tvmaze_map)
                        all_programs.extend(day_progs)
                    except Exception as e:
                        error_msg = f"Error fetching TVMaze on {target_date}: {e}"
                        print(error_msg)

                # TV Passport for configured stations (includes yesterday overnight)
                for ch_alias, st_id in passport_stations.items():
                    try:
                        pass_progs = TVPassportProvider.fetch_station(target_date, ch_alias, st_id)
                        all_programs.extend(pass_progs)
                    except Exception as e:
                        print(f"Error fetching TVPassport station {st_id} for {target_date}: {e}")

        # Store into SQLite
        conn = self._get_connection()
        cur = conn.cursor()

        # Prune older guide dates earlier than today
        cutoff = today.strftime("%Y-%m-%d")
        cur.execute("DELETE FROM guide_programs WHERE airdate < ?", (cutoff,))

        # Purge existing rows for the synced channels and dates to prevent stale entries
        synced_channels = {p["kaffeine_channel"] for p in all_programs}
        start_date_str = today.strftime("%Y-%m-%d")
        end_date_str = (today + timedelta(days=days)).strftime("%Y-%m-%d")
        for ch in synced_channels:
            cur.execute(
                "DELETE FROM guide_programs WHERE kaffeine_channel = ? AND airdate >= ? AND airdate <= ?",
                (ch, start_date_str, end_date_str)
            )

        if all_programs:
            params = [
                (
                    p["tvmaze_id"], p["show_title"], p["episode_title"], p["network"], p["kaffeine_channel"],
                    p["start_time_local"], p["start_iso"], p["duration_iso"], p["runtime_mins"], p["summary"],
                    p["season"], p["number"], p["airdate"], p["updated_at"]
                )
                for p in all_programs
            ]
            cur.executemany("""
                INSERT OR REPLACE INTO guide_programs (
                    tvmaze_id, show_title, episode_title, network, kaffeine_channel,
                    start_time_local, start_iso, duration_iso, runtime_mins, summary,
                    season, number, airdate, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, params)

        now_str = datetime.now().strftime("%Y-%m-%d %I:%M:%S %p")
        cur.execute("INSERT OR REPLACE INTO guide_meta (key, value) VALUES ('last_updated', ?)", (now_str,))
        if error_msg:
            cur.execute("INSERT OR REPLACE INTO guide_meta (key, value) VALUES ('last_error', ?)", (error_msg,))
        else:
            cur.execute("INSERT OR REPLACE INTO guide_meta (key, value) VALUES ('last_error', '')")

        conn.commit()
        conn.close()

        if progress_callback:
            progress_callback(f"Sync complete. Cached {len(all_programs)} shows.")

        return len(all_programs)

    def search_programs(
        self,
        query: str = "",
        channel: Optional[str] = None,
        airdate: Optional[str] = None,
        trim_ended: bool = True,
        include_overhang: bool = False
    ) -> List[Dict[str, Any]]:
        conn = self._get_connection()
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()

        sql = "SELECT * FROM guide_programs WHERE 1=1"
        params = []

        if query:
            sql += " AND (show_title LIKE ? OR episode_title LIKE ? OR summary LIKE ?)"
            q_like = f"%{query}%"
            params.extend([q_like, q_like, q_like])

        if channel and channel != "All":
            ch_targets = {channel}
            if getattr(self, "channel_map", None):
                if channel in self.channel_map:
                    ch_targets.add(self.channel_map[channel])
                for k, v in self.channel_map.items():
                    if v == channel:
                        ch_targets.add(k)
            placeholders = ",".join("?" for _ in ch_targets)
            sql += f" AND (kaffeine_channel IN ({placeholders}) OR network IN ({placeholders}))"
            params.extend(list(ch_targets) + list(ch_targets))

        if airdate:
            if include_overhang:
                try:
                    target_dt = datetime.strptime(airdate, "%Y-%m-%d").date()
                    next_day_dt = target_dt + timedelta(days=1)
                    next_day_str = next_day_dt.strftime("%Y-%m-%d")
                    next_cutoff = f"{next_day_str}T04:00:00"
                    sql += " AND ((airdate = ?) OR (airdate = ? AND start_iso < ?))"
                    params.extend([airdate, next_day_str, next_cutoff])
                except Exception:
                    sql += " AND airdate = ?"
                    params.append(airdate)
            else:
                sql += " AND airdate = ?"
                params.append(airdate)

        sql += " ORDER BY start_iso ASC"

        cur.execute(sql, params)
        rows = [dict(r) for r in cur.fetchall()]
        conn.close()

        if trim_ended:
            now_dt = datetime.now()
            today_str = now_dt.strftime("%Y-%m-%d")
            # If querying a specific future date, don't trim
            if airdate and airdate > today_str:
                return rows

            filtered = []
            for r in rows:
                start_iso = r.get("start_iso")
                if not start_iso:
                    filtered.append(r)
                    continue

                try:
                    start_dt = datetime.fromisoformat(start_iso)
                    dur_iso = r.get("duration_iso") or "00:30:00"
                    parts = [int(x) for x in dur_iso.split(":")]
                    dur = timedelta(hours=parts[0], minutes=parts[1], seconds=parts[2] if len(parts) > 2 else 0)
                    end_dt = start_dt + dur

                    # Keep entry if end_dt >= now (currently airing or upcoming)
                    if end_dt >= now_dt:
                        filtered.append(r)
                except Exception:
                    filtered.append(r)
            return filtered

        return rows

    def prune_past_programs(self) -> int:
        """
        Deletes past guide entries from previous calendar days.
        Returns the count of purged records.
        """
        conn = self._get_connection()
        cur = conn.cursor()

        now_dt = datetime.now()
        today_str = now_dt.strftime("%Y-%m-%d")

        # Delete all programs with an airdate before today
        cur.execute("DELETE FROM guide_programs WHERE airdate < ?", (today_str,))
        count = cur.rowcount

        conn.commit()
        conn.close()
        return count

    def delete_channel_programs(self, channel_names: List[str]) -> int:
        """
        Explicitly removes all cached guide programs for the specified channel names.
        Matches against both kaffeine_channel and network.
        """
        if not channel_names:
            return 0
        conn = self._get_connection()
        cur = conn.cursor()
        placeholders = ",".join("?" for _ in channel_names)
        cur.execute(
            f"DELETE FROM guide_programs WHERE kaffeine_channel IN ({placeholders}) OR network IN ({placeholders})",
            list(channel_names) + list(channel_names)
        )
        count = cur.rowcount
        conn.commit()
        conn.close()
        return count

    def get_live_program_for_channel(self, channel: str) -> Optional[Dict[str, Any]]:
        """
        Locates the currently broadcasting program for a channel in the guide database.
        Calculates broadcast end time (start_iso + duration_iso) to check if start <= now < end.
        """
        if not channel:
            return None
        now_dt = datetime.now()
        airdate = now_dt.strftime("%Y-%m-%d")
        try:
            progs = self.search_programs(
                query="",
                channel=channel,
                airdate=airdate,
                trim_ended=False,
                include_overhang=True
            )
            for p in progs:
                start_iso = p.get("start_iso")
                if not start_iso:
                    continue
                try:
                    s_dt = p.get("_parsed_start_dt")
                    e_dt = p.get("_parsed_end_dt")
                    if s_dt is None or e_dt is None:
                        s_dt = datetime.fromisoformat(start_iso)
                        dur_iso = p.get("duration_iso") or "00:30:00"
                        parts = [int(x) for x in dur_iso.split(":")]
                        dur = timedelta(hours=parts[0], minutes=parts[1], seconds=parts[2] if len(parts) > 2 else 0)
                        e_dt = s_dt + dur
                    if s_dt <= now_dt < e_dt:
                        return p
                except Exception:
                    continue
        except Exception as e:
            print(f"Error querying live program for channel {channel}: {e}")
        return None
