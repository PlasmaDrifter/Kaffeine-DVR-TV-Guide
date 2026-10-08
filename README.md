# Kaffeine-DVR-TV-Guide

Modern TV Guide browser, auto-record series scheduler, and Just-In-Time (JIT) DVR recording daemon for Kaffeine on Linux.

---

## Overview

Kaffeine is a powerful digital TV viewer for KDE and Linux desktop environments, but managing recording timers natively presents two common challenges:
1. Native Kaffeine timers inhibit system power management, blocking automated or manual system restarts and shutdowns while timers are pending.
2. In many broadcast markets, electronic program guide (EPG) data over-the-air is sparse, incomplete, or requires continuous manual tuning.

**Kaffeine-DVR-TV-Guide** solves both problems:
- **Zero-Block Power Operations:** Scheduled recordings are held in an external queue database (`recordings_queue.sqlite`). Kaffeine stays completely clean with zero active timers until minutes before showtime.
- **Just-In-Time (JIT) Dispatching:** A lightweight systemd user background service monitors the queue. When a broadcast is about to begin (e.g. 5 minutes before airtime), it launches Kaffeine minimized and arms the timer over D-Bus automatically.
- **Comprehensive EPG Providers:** Browse up to 14 days of TV listings across multiple providers:
  - **TVMaze Cloud API (Free & Automatic):** Instant national broadcast network listings (FOX, CBS, NBC, ABC, PBS, The CW) with zero configuration or API keys required.
  - **TV Passport (Web Station Directory):** Full 24/7 schedules including morning, daytime, and local syndicated programming for local affiliate stations and independent subchannels.
  - **Free Hybrid Mode:** Simultaneously uses TV Passport for any configured local affiliate station IDs while automatically filling in any unmapped channels with TVMaze without duplicate show rows.
  - **Custom XMLTV Feeds:** Supports local files or remote HTTP/HTTPS XMLTV feeds from tools like zap2xml or WebGrab+.
  - **Schedules Direct:** Direct commercial Gracenote EPG integration by postal/zip code.
- **Dual-Mode TV Guide (Traditional EPG Grid & Searchable List):**
  - **Traditional Grid Layout:** Displays channels vertically and 48 half-hour time slots across the 24-hour day, with program tiles spanning their duration.
  - **Genre Color Coding:** Show titles dynamically styled by genre (Sports = Orange, News = Light Blue, Movies = Red, TV Shows = Green).
  - **Smart Timeline Navigation:** Auto-centers on live programming when viewing Today, rewinds to 12:00 AM Midnight for future dates, with quick "Jump to Now" and "Prime Time (8 PM)" buttons.
- **Configurable Recording End Buffers (Post-Roll Padding):**
  - **Global Post-Roll Buffer:** Append extra minutes (0-180m) to scheduled recordings to safeguard against broadcast delays.
  - **Sports Broadcast Auto-Extend:** Automatically adds extended post-roll padding (default: +30 minutes) to live sporting events (NFL, NBA, MLB, NCAA, Premier League, NASCAR, racing, etc.) so overtime and extra innings are never cut short.
  - **Per-Rule Custom Overrides:** Override end buffer duration on individual series auto-record rules or manual schedule dialogs.
- **Series Auto-Record Rules:** Define keyword-based auto-record rules (e.g., specific sports leagues, talk shows, or series titles) that automatically schedule upcoming episodes as guide data refreshes.
- **Automated Video Retention & Storage Management:** Prevents recording drives from filling up:
  - **Age Retention:** Automatically deletes recordings older than *N* days (configurable).
  - **Low-Disk Auto-Purge:** If available disk space drops below a safety threshold (e.g., 25 GB), automatically purges the oldest unprotected recordings first.
  - **Active Recording & Sidecar Safety:** Never deletes files actively being written, cleans up associated sidecars (`.txt`, `.log`), and allows users to flag favorite recordings as "Protected / Keep Forever".

---

## Screenshots

| Traditional EPG Grid TV Guide View |
|:---:|
| [![Traditional EPG Grid TV Guide View](docs/screenshots/guide_grid.png)](docs/screenshots/guide_grid.png) |

| Recordings Schedule (DVR Queue & History) | Automation and DVR Settings |
|:---:|:---:|
| [![Recordings Schedule](docs/screenshots/recordings_schedule.png)](docs/screenshots/recordings_schedule.png) | [![Automation and DVR Settings](docs/screenshots/automation_dvr.png)](docs/screenshots/automation_dvr.png) |

---

## Architecture and Workflow

```
+--------------------------------------------------------------+
|                    Kaffeine DVR GUI / CLI                    |
|  - TV Guide Grid Browser (Search, Filter, Date Picker)       |
|  - Series Auto-Record Rule Manager                           |
|  - Source Health and Connectivity Monitor                    |
+--------------------------------------------------------------+
                               |
                               v
               +-------------------------------+
               |    recordings_queue.sqlite     |
               | (Queued DVR Recording Timers) |
               +-------------------------------+
                               |
                               v (Monitored every 120s, Configurable)
               +-------------------------------+
               |   kaffeine-dvr-watcher daemon |
               |     (systemd --user service)  |
               +-------------------------------+
                               |
                (5 mins before showtime: JIT, Configurable)
                               v
            +------------------------------------+
            | Kaffeine Media Player (D-Bus MPRIS)|
            |  - Launched minimized to taskbar   |
            |  - ScheduleProgram called via D-Bus|
            +------------------------------------+
```

> **Note on Timing & Flexibility:**
> - **Poll Interval (Default: 120s):** How often the background watcher checks the queue database. This is fully configurable via the settings dialog or CLI `--interval` flag.
> - **Just-In-Time Lead Time (Default: 5 mins):** How early Kaffeine is launched and scheduled before broadcast start. This allows Kaffeine ample time to initialize tuner hardware and buffer without missing the start of a program, and can be customized anywhere from 1 to 60 minutes in the DVR Settings tab.
> - **Post-Roll Buffers (Default: +30 mins for Sports):** Extra recording duration appended to the end of a scheduled recording so programs that run late or enter overtime are fully captured. Kaffeine is dispatched the total duration (base duration + buffer) via D-Bus.

---

## Installation

### Prerequisites
- Python 3.9 or newer
- PyQt6 (`pip install PyQt6` or via distribution package manager)
- Kaffeine (`kaffeine`)
- Standard desktop tools: `systemd`, `notify-send` (optional, for notifications), `kdotool` or `xdotool` (optional, for window minimization)

### Install via pip / local clone
```bash
git clone https://github.com/PlasmaDrifter/Kaffeine-DVR-TV-Guide.git
cd Kaffeine-DVR-TV-Guide
pip install .
```

### Install Desktop Launcher and Systemd User Service
```bash
# User binary wrapper
mkdir -p ~/.local/bin
cat << 'BIN_EOF' > ~/.local/bin/kaffeine-dvr
#!/usr/bin/env bash
exec python3 -m kaffeine_dvr.cli "$@"
BIN_EOF
chmod +x ~/.local/bin/kaffeine-dvr

# Desktop launcher
mkdir -p ~/.local/share/applications
cp desktop/kaffeine-dvr.desktop ~/.local/share/applications/

# Systemd background watcher service
mkdir -p ~/.config/systemd/user
cp systemd/kaffeine-dvr-watcher.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now kaffeine-dvr-watcher.service
```

---

## Configuration & Guide Sources

### 1. Channel Lineup
Open **Settings > Channels Lineup**. Click **Import Channels from Kaffeine** to read your scanned channels directly from `~/.local/share/kaffeine/sqlite.db`.

Lineup format:
```text
Guide Network Name = Kaffeine Tuned Name
```
Examples:
```text
Fox = Fox
NBC = NBC
CBS = CBS
ABC = ABC
The CW = CW6
```

### 1. TV Guide Sources & Zero-Configuration TVMaze
- **TVMaze (Zero Configuration Required):** Out of the box, national broadcast networks (**FOX, CBS, NBC, ABC, PBS, and The CW**) work automatically with **no accounts, no API keys, and no manual setup**. As soon as the application opens, it downloads 7 days of prime-time listings for all mapped channels.
- **National vs. Local Daytime Programming:** TVMaze catalogs national network programming (evening prime-time dramas, comedies, national sports, and network specials). However, because broadcast networks leave morning, midday, and late-afternoon blocks to local stations, **local news broadcasts, daytime syndicated talk shows, game shows, and independent local subchannels** are not part of TVMaze's national feed.

### 2. TV Passport Setup (24/7 Local Affiliate Coverage & Independent Channels)
To get complete 24/7 continuous schedules with local morning/evening news, daytime talk shows, or independent local channels:
1. Search for your local affiliate station on [tvpassport.com](https://www.tvpassport.com).
2. Note the numeric ID from the station listings URL (for example, `/station/1812/`).
3. Under **Settings > Guide Sources > TV Passport**, enter your station mapping:
   ```text
   NBC = 1812
   ABC = 4163
   Fox = 1809
   CBS = 1813
   CW6 = 11611
   ```
4. Click **Save Station IDs**. The app verifies connectivity and triggers background synchronization immediately. In Free Hybrid mode, TV Passport automatically supersedes TVMaze for those stations to provide full 24/7 local affiliate schedules, while TVMaze continues covering any remaining national channels with zero setup and no duplicates.

---

## CLI Usage

The command-line interface provides full control without launching the GUI:

```bash
# Show current status, cache stats, and backend health
kaffeine-dvr --status

# Synchronize 7 days of TV listings
kaffeine-dvr --sync --days 7

# Evaluate auto-record rules and queue matching episodes
kaffeine-dvr --rules

# List current planned queue and active Kaffeine timers
kaffeine-dvr --list

# Run the background watcher daemon in terminal
kaffeine-dvr --watch
```

---

## License

GPL-3.0-or-later. See LICENSE for details.
