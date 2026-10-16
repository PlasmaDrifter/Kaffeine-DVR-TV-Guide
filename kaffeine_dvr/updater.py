"""
Application update manager for Kaffeine DVR & TV Guide.
Handles checking for updates via Git or GitHub Releases, installing updates,
and restarting the application.
"""

import json
import os
import re
import subprocess
import sys
import urllib.request
from pathlib import Path
from typing import Any, Callable, Dict, Optional, Tuple

from kaffeine_dvr import __version__

GITHUB_REPO = "PlasmaDrifter/Kaffeine-DVR-TV-Guide"
RELEASES_API = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"


def parse_version_tuple(ver_str: str) -> Tuple[int, ...]:
    clean = re.sub(r"^[^\d]*", "", str(ver_str).strip())
    parts = []
    for part in clean.split("."):
        digits = re.match(r"^\d+", part)
        if digits:
            parts.append(int(digits.group(0)))
        else:
            break
    while len(parts) < 3:
        parts.append(0)
    return tuple(parts[:3])


def is_newer_version(latest: str, current: str) -> bool:
    try:
        return parse_version_tuple(latest) > parse_version_tuple(current)
    except Exception:
        return False


def get_repo_root() -> Optional[Path]:
    """Returns the repository root if running from a git clone."""
    # Check parent of package dir (e.g. repo root)
    pkg_dir = Path(__file__).resolve().parent
    parent = pkg_dir.parent
    if (parent / ".git").is_dir():
        return parent
    return None


def is_watcher_service_active() -> bool:
    """Checks if the systemd user watcher service is currently active."""
    try:
        res = subprocess.run(
            ["systemctl", "--user", "is-active", "kaffeine-dvr-watcher.service"],
            capture_output=True,
            text=True,
            timeout=3
        )
        return res.returncode == 0 and res.stdout.strip() == "active"
    except Exception:
        return False


def get_install_info() -> Dict[str, Any]:
    repo_root = get_repo_root()
    return {
        "current_version": __version__,
        "is_git": repo_root is not None,
        "repo_path": str(repo_root) if repo_root else None,
        "is_service_active": is_watcher_service_active(),
    }


def get_pip_flags() -> list:
    flags = ["--user"]
    try:
        res = subprocess.run(
            [sys.executable, "-m", "pip", "install", "--help"],
            capture_output=True,
            text=True,
            timeout=5
        )
        if "--break-system-packages" in res.stdout:
            flags.append("--break-system-packages")
    except Exception:
        pass
    return flags


EMBEDDED_RELEASE_NOTES: Dict[str, str] = {
    "0.8.13": (
        "## What's Changed in v0.8.13\n\n"
        "• **AppImage Standalone Runtime Fix**: Resolved `ImportError: attempted relative import with no known parent package` when launching packaged standalone AppImage bundles by moving web server and scanner imports to the top-level package namespace with robust fallback handlers.\n"
        "• **EPG Web Companion Enhancements**: Redesigned the companion web guide into an anchored two-panel layout keeping channel columns permanently fixed on the left while panning horizontally, made row heights compact, added channel filtering dropdown to the toolbar, and preserved grab-to-pan touch and mouse navigation."
    ),
    "0.8.12": (
        "## What's Changed in v0.8.12\n\n"
        "• **Remote Web Companion & Downloadable Recordings**: Introduced the lightweight, dependency-free remote web companion with 24-hour EPG Grid and List views, past show trimming, grab-to-pan scrolling, channel filtering, and named file downloads.\n"
        "• **Weak or No Signal Detection & Auto Tuner Release**: Implemented real-time stream data monitoring at channel start with configurable buffer timeout. Automatically cancels the recording in Kaffeine via D-Bus, cleans up 0-byte partial files, frees the hardware tuner, and displays an informative warning popup if no signal is received.\n"
        "• **EPG Grid View Enhancements**: Redesigned the web companion EPG Grid into a 2-column layout with permanently anchored channel column on the left, compact 44px rows, semi-transparent 30% opacity timeline marker, and grab-to-pan scrolling.\n"
        "• **Theme Color Distinctiveness**: Assigned signature representative accent colors to all built-in guide grid theme preset chips (Cyberpunk, Emerald Forest, Midnight Navy, Nordic Frost, OLED High Contrast, Retro Synthwave, Warm Amber) for maximum visual clarity.\n"
        "• **Factory Default Settings Refinement**: Updated default preferences to 40-minute sports auto-extend buffer, 180-second watcher polling interval, 2-minute notification lead time, and 2-second timeshift initial buffer.\n"
        "• **Performance & Storage Optimizations**: Precompiled regex matching patterns in `StorageManager` to speed up directory searches and active stream detection."
    ),
    "0.8.11": (
        "## What's Changed in v0.8.11\n\n"
        "• **Idle CPU Optimization**: Eliminated redundant 1-second stylesheet parsing and canvas invalidation on the top-corner clock, bringing idle CPU consumption down to flat 0.00%.\n"
        "• **Grid Options Box Checkbox Alignment**: Repositioned the 'Disable' checkboxes in Sub-Column 2 immediately adjacent to their items (Live Badge, Live Tile Tint, Time Line, Clock), and moved the Auto-Advance HelpBadge to the right of its checkbox.\n"
        "• **Guide Sync & Channel Import UI Reorganization**: Relocated the Guide Sync progress bar and real-time status text to Settings > Guide Sources and Health directly next to the 'Sync Guide Now' button. Moved channel import and reset buttons above the channel mapping box.\n"
        "• **Resource Lifecycle & Memory Hardening**: Connected `deleteLater` to all background QThread workers on task completion and added explicit post-sync garbage collection.\n"
        "• **Codebase Organization & Documentation**: Cleaned, sorted, and formatted imports according to PEP 8 standards, eliminated dead code and unused symbols, and added PEP 257 docstrings across all modules."
    ),
    "0.8.10": (
        "## What's Changed in v0.8.10\n\n"
        "• **Channel Importing & Renaming Setup**: Clarified the channel lineup and renaming section in Settings to focus on guide display names (`Guide Name = Tuned Channel`), using `Fox = KSAZ-HD` as an example, with guidance on Welcome Wizard imports and re-importing.\n"
        "• **TV Passport Station ID Instructions**: Streamlined station setup instructions using `Guide Name = Station ID` (e.g. `NBC = 1812`, `Fox = 1809`, or `PBS = 1184`), eliminating unnecessary technical jargon.\n"
        "• **Help and Information Tab Synchronization**: Synchronized the Quick Setup Walkthrough in the Help tab with the updated channel importing, renaming, and TV Passport setup formats."
    ),
    "0.8.9": (
        "## What's Changed in v0.8.9\n\n"
        "• **Guide Auto-Advance Controls**: Added a customizable minute-past-the-hour stepper and enable/disable toggle for guide auto-advance, with an inline help badge explaining next-hour advancement.\n"
        "• **Three-Way Guide Unhighlighting**: Added toggle-on-click, click-empty-space to deselect, and Escape key clearing across both EPG Grid and List views.\n"
        "• **Corner Clock Display & Sizing**: Added a live top-right tab bar clock widget with color customization, show/hide toggle, and a dedicated font size stepper in Settings.\n"
        "• **Settings UI Polish**: Standardized numeric stepper widths to 130 px, changed Live Badge toggle text to 'Disable' for consistency, and aligned auto-advance minute calculations across live sync and manual Jump-to-Now actions."
    ),
    "0.8.8": (
        "## What's Changed in v0.8.8\n\n"
        "• **Grid Options Three-Column Layout**: Reorganized the Grid Guide Options settings card into three balanced columns for cleaner visual hierarchy.\n"
        "• **Frameless Embedded Steppers**: Modernized numeric stepper controls with a sleek inset container and borderless inline increment/decrement buttons.\n"
        "• **Setting Label Streamlining**: Refined setting labels to 'Grid Rows' and 'Grid Box' for concise, uncluttered presentation.\n"
        "• **Updated Documentation & Previews**: Refreshed README preview screenshots showcasing the three-line EPG grid views and updated settings panel."
    ),
    "0.8.7": (
        "## What's Changed in v0.8.7\n\n"
        "• **Three-Line Grid Program Tiles**: Redesigned EPG grid program tiles into three dedicated lines for Primary Show Title, Broadcast Time Range, and Episode Title/Subtitle for superior clarity and reduced truncation.\n"
        "• **Grid Tile Margins & Badge Clearance**: Refined vertical padding to 5 px and inter-line spacing to 2 px, guaranteeing clean clearance for the lower-right LIVE pill badge and top-right recording dot indicator.\n"
        "• **Grid Row Height Legibility Floor**: Enforced a 58 px minimum row height baseline in grid zoom calculations so program tiles never collapse below readable multi-line bounds during window resizing.\n"
        "• **Description Box Height Configuration**: Added user-selectable 2-line or 3-line description box height preference in Settings."
    ),
    "0.8.6": (
        "## What's Changed in v0.8.6\n\n"
        "• **Past Recording History Indicators**: Added past recording cross-referencing so programs completed in history show a distinct badge and completion tooltip in both Grid and List guide views.\n"
        "• **Guide Toolbar Refresh Button**: Added a dedicated quick-refresh button next to Prime Time to instantly reload guide listings and active recording statuses.\n"
        "• **Refined Time Jump Alignment**: Aligned grid view hour-slot jumps with the current hour mark until 50 minutes past the hour.\n"
        "• **Grid Guide Live Tile Tint Controls**: Renamed the background tint toggle to 'Disable' for clear, intuitive toggle state semantics.\n"
        "• **Settings Layout Optimization**: Repositioned the broadcast category color swatches and secondary guide option controls into adjacent columns, removing excessive whitespace separation.\n"
        "• **Desktop & Dock Clapperboard Icon Refinement**: Bundled multi-resolution icon assets across XDG and Breeze icon specifications for consistent panel dock, titlebar, and launcher presentation."
    ),
    "0.8.5": (
        "## What's Changed in v0.8.5\n\n"
        "• **Recording Cancellation & Duplicate Prevention**: Fixed duplicate concurrent recording timers in Kaffeine by introducing active timer pre-checking and thorough multi-target cancellation across D-Bus and SQLite when recordings are stopped or restarted.\n"
        "• **Default Update Frequency**: Set the default automatic update check interval to weekly.\n"
        "• **TVPassport Direct Lineup URL**: Updated all TVPassport links in the guide and lineup dialogs to direct to https://www.tvpassport.com/index.php/lineups for immediate postal/zip code entry.\n"
        "• **EPG Grid Recording & Scheduled Indicators**: Differentiated active recording (● REC with solid red dot and red border) from scheduled recordings (○ SCHED with subtle outline only).\n"
        "• **EPG List View Enhancements**: Added subtle #2b3242 grid lines, removed row index headers, and differentiated scheduled vs active recordings.\n"
        "• **Release Notes Modal Viewer**: Added an interactive 'View Release Notes...' modal dialog with formatted changelog viewer in Settings -> Updates tab and status bar.\n"
        "• **AppImage Checkmark Rendering**: Bundled checkmark assets and fixed indicator icon resolution in read-only SquashFS AppImage environments."
    ),
    "0.8.4": (
        "## What's Changed in v0.8.4\n\n"
        "• **List View Navigation & Performance**: Fixed initial auto-scroll so list view immediately jumps to the first live or upcoming program on its first activation, matching subsequent switches.\n"
        "• **Direct DBus Channel Tuning**: Implemented direct KDBusService CommandLine parameter passing to tune live TV channels cleanly without requiring synthetic keypresses.\n"
        "• **Recording Indicator Redesign**: Replaced large rectangular badges with clean red dot indicators on EPG grid tiles for a more polished look.\n"
        "• **Sports Auto-Extend UI**: Aligned the sports buffer duration spinbox with the rest of the form input fields and repositioned the auto-extend toggle to the right.\n"
        "• **AppImage Distribution & Metadata**: Built and released a standalone x86_64 AppImage with embedded Python and PyQt6 runtimes, complete desktop metadata, and AppManager package compatibility.\n"
        "• **Background Watcher CLI Dispatching**: Fixed argument dispatch in entrypoint so CLI daemon modes like --watch execute headlessly as background services rather than opening a second GUI window.\n"
        "• **Background Service Auto-Provisioning**: Automated systemd user unit provisioning directly from the AppImage/application with dynamic ExecStart path resolution, allowing the background watcher service to enable, start, and run seamlessly without requiring manual install scripts.\n"
        "• **Documentation & UI Previews**: Refreshed README installation workflows (clarifying standalone AppImage vs. source installation), overview sections, and preview screenshots."
    ),
}


def _extract_version_section(markdown_text: str, version_str: str) -> str:
    """Extracts the section for a specific version from markdown release notes."""
    ver = version_str.lstrip("v").strip()
    pattern = rf"(?m)^##\s+v?{re.escape(ver)}\b(.*?)(?=^##\s+|\Z)"
    match = re.search(pattern, markdown_text, flags=re.DOTALL)
    if match:
        section = match.group(0).strip()
        return section
    return ""


def get_local_release_notes(version: Optional[str] = None) -> str:
    """
    Returns the release notes / changelog for the specified version (or current version).
    Searches bundled RELEASE_NOTES.md, repository RELEASE_NOTES.md, and embedded fallback notes.
    """
    ver = (version or __version__).lstrip("v").strip()

    # Search file candidates
    candidates = []
    if hasattr(sys, "_MEIPASS"):
        candidates.append(Path(sys._MEIPASS) / "RELEASE_NOTES.md")
        candidates.append(Path(sys._MEIPASS) / "assets" / "RELEASE_NOTES.md")
    try:
        exe_dir = Path(sys.executable).resolve().parent
        candidates.extend([
            exe_dir / "RELEASE_NOTES.md",
            exe_dir / "assets" / "RELEASE_NOTES.md",
            exe_dir / "_internal" / "RELEASE_NOTES.md",
            exe_dir.parent / "share" / "kaffeine-dvr" / "RELEASE_NOTES.md",
        ])
    except Exception:
        pass
    try:
        base_dir = Path(__file__).resolve().parent.parent
        candidates.append(base_dir / "RELEASE_NOTES.md")
    except Exception:
        pass

    for cand in candidates:
        if cand.is_file():
            try:
                content = cand.read_text(encoding="utf-8")
                extracted = _extract_version_section(content, ver)
                if extracted:
                    return extracted
            except Exception:
                pass

    return EMBEDDED_RELEASE_NOTES.get(ver, EMBEDDED_RELEASE_NOTES.get(__version__.lstrip("v"), ""))


def is_editable_install() -> bool:
    try:
        res = subprocess.run(
            [sys.executable, "-m", "pip", "show", "kaffeine-dvr"],
            capture_output=True,
            text=True,
            timeout=5
        )
        return "Editable project location:" in res.stdout
    except Exception:
        return False


def check_for_updates() -> Dict[str, Any]:
    """
    Checks GitHub or Git remote for available updates.
    Returns dictionary with status and version information.
    """
    info = get_install_info()
    repo_root = get_repo_root()

    result = {
        "update_available": False,
        "latest_version": __version__,
        "current_version": __version__,
        "details": "Your installation is up to date.",
        "release_notes": get_local_release_notes(__version__),
        "is_git": info["is_git"],
        "repo_path": info["repo_path"],
    }

    # 1. Git Clone check
    if repo_root:
        try:
            # Fetch remote status and tags
            subprocess.run(
                ["git", "fetch", "--tags", "origin", "main"],
                cwd=str(repo_root),
                capture_output=True,
                text=True,
                timeout=10,
                check=True
            )

            # Check latest release tag on origin/main
            latest_tag = ""
            try:
                tag_out = subprocess.check_output(
                    ["git", "describe", "--tags", "--abbrev=0", "origin/main"],
                    cwd=str(repo_root),
                    text=True,
                    timeout=5
                ).strip()
                latest_tag = tag_out.lstrip("v")
            except Exception:
                pass

            is_newer_remote_tag = bool(latest_tag and is_newer_version(latest_tag, __version__))
            if is_newer_remote_tag:
                notes = ""
                try:
                    req = urllib.request.Request(
                        RELEASES_API,
                        headers={"User-Agent": f"KaffeineDVR/{__version__}"}
                    )
                    with urllib.request.urlopen(req, timeout=5) as resp:  # nosemgrep: python.lang.security.audit.dynamic-urllib-use-detected.dynamic-urllib-use-detected
                        api_data = json.loads(resp.read().decode("utf-8"))
                        notes = api_data.get("body", "").strip()
                except Exception:
                    pass

                result["update_available"] = True
                result["latest_version"] = latest_tag
                result["details"] = f"New version v{latest_tag} is available on GitHub."
                result["release_notes"] = notes
                return result
            else:
                result["update_available"] = False
                result["latest_version"] = __version__
                result["details"] = "Your installation is up to date."
                result["release_notes"] = get_local_release_notes(__version__)
                return result
        except Exception:
            # If git fetch fails (offline or non-git remote), fall through to HTTP API
            pass

    # 2. HTTP Releases API fallback
    try:
        req = urllib.request.Request(
            RELEASES_API,
            headers={"User-Agent": f"KaffeineDVR/{__version__}"}
        )
        with urllib.request.urlopen(req, timeout=8) as resp:  # nosemgrep: python.lang.security.audit.dynamic-urllib-use-detected.dynamic-urllib-use-detected
            data = json.loads(resp.read().decode("utf-8"))
            tag = data.get("tag_name", "").lstrip("v")
            remote_notes = data.get("body", "").strip()
            if tag and is_newer_version(tag, __version__):
                result["update_available"] = True
                result["latest_version"] = tag
                result["release_notes"] = remote_notes
                result["details"] = f"Version v{tag} is available on GitHub."
            else:
                result["update_available"] = False
                result["latest_version"] = __version__
                result["release_notes"] = get_local_release_notes(__version__) or remote_notes
                result["details"] = "You are running the latest version."
    except Exception as e:
        result["details"] = f"Unable to check for updates: {e}"
        if not result["release_notes"]:
            result["release_notes"] = get_local_release_notes(__version__)

    return result


def apply_update(progress_cb: Optional[Callable[[str], None]] = None) -> Tuple[bool, str]:
    """
    Applies the latest update using git pull or pip upgrade.
    Returns (success, message).
    """
    appimage_path = os.environ.get("APPIMAGE")
    if appimage_path:
        import webbrowser
        webbrowser.open(f"https://github.com/{GITHUB_REPO}/releases/latest")
        return True, "AppImage updates must be downloaded from GitHub Releases. Opened the releases page in your browser."

    repo_root = get_repo_root()
    pip_flags = get_pip_flags()
    service_active = is_watcher_service_active()

    try:
        if repo_root:
            if progress_cb:
                progress_cb("Pulling latest changes from repository...")
            subprocess.run(
                ["git", "pull", "origin", "main"],
                cwd=str(repo_root),
                capture_output=True,
                text=True,
                timeout=30,
                check=True
            )

            if progress_cb:
                progress_cb("Updating Python package...")
            editable = is_editable_install()
            install_cmd = [sys.executable, "-m", "pip", "install"] + pip_flags
            if editable:
                install_cmd.extend(["-e", str(repo_root), "--no-deps"])
            else:
                install_cmd.append(str(repo_root))

            subprocess.run(
                install_cmd,
                capture_output=True,
                text=True,
                timeout=60,
                check=True
            )
        else:
            if progress_cb:
                progress_cb("Installing latest version from GitHub...")
            install_cmd = [
                sys.executable, "-m", "pip", "install"
            ] + pip_flags + ["--upgrade", f"git+https://github.com/{GITHUB_REPO}.git"]

            subprocess.run(
                install_cmd,
                capture_output=True,
                text=True,
                timeout=90,
                check=True
            )

        # Restart systemd watcher if it was running
        if service_active:
            if progress_cb:
                progress_cb("Restarting background watcher service...")
            subprocess.run(
                ["systemctl", "--user", "restart", "kaffeine-dvr-watcher.service"],
                capture_output=True,
                text=True,
                timeout=10,
                check=False
            )

        return True, "Update applied successfully."
    except subprocess.CalledProcessError as e:
        err = e.stderr if e.stderr else str(e)
        return False, f"Update command failed: {err}"
    except Exception as e:
        return False, f"Failed to apply update: {e!s}"
