"""
Application update manager for Kaffeine DVR & TV Guide.
Handles checking for updates via Git or GitHub Releases, installing updates,
and restarting the application.
"""

import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import urllib.request
from typing import Dict, Any, Tuple, Optional, Callable

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
        "is_git": info["is_git"],
        "repo_path": info["repo_path"],
    }

    # 1. Git Clone check
    if repo_root:
        try:
            # Fetch remote status
            subprocess.run(
                ["git", "fetch", "--tags", "origin", "main"],
                cwd=str(repo_root),
                capture_output=True,
                text=True,
                timeout=10,
                check=True
            )

            # Check commits behind origin/main
            rev_out = subprocess.check_output(
                ["git", "rev-list", "--count", "HEAD..origin/main"],
                cwd=str(repo_root),
                text=True,
                timeout=5
            ).strip()
            behind = int(rev_out) if rev_out.isdigit() else 0

            # Check latest tag
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

            if behind > 0:
                result["update_available"] = True
                ver_display = latest_tag if latest_tag else f"{__version__}+{behind}"
                result["latest_version"] = ver_display
                result["details"] = f"{behind} new commit(s) available on origin/main."
                return result
            elif latest_tag and is_newer_version(latest_tag, __version__):
                result["update_available"] = True
                result["latest_version"] = latest_tag
                result["details"] = f"New version v{latest_tag} is available."
                return result
            else:
                result["update_available"] = False
                result["latest_version"] = latest_tag if latest_tag else __version__
                result["details"] = "Your repository clone is up to date with origin/main."
                return result
        except Exception as e:
            # If git fetch fails (offline or non-git remote), fall through to HTTP API
            pass

    # 2. HTTP Releases API fallback
    try:
        req = urllib.request.Request(
            RELEASES_API,
            headers={"User-Agent": f"KaffeineDVR/{__version__}"}
        )
        with urllib.request.urlopen(req, timeout=8) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            tag = data.get("tag_name", "").lstrip("v")
            if tag:
                result["latest_version"] = tag
                if is_newer_version(tag, __version__):
                    result["update_available"] = True
                    result["details"] = f"Version v{tag} is available on GitHub."
                else:
                    result["update_available"] = False
                    result["details"] = "You are running the latest released version."
    except Exception as e:
        result["details"] = f"Unable to check for updates: {e}"

    return result


def apply_update(progress_cb: Optional[Callable[[str], None]] = None) -> Tuple[bool, str]:
    """
    Applies the latest update using git pull or pip upgrade.
    Returns (success, message).
    """
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
        return False, f"Failed to apply update: {str(e)}"
