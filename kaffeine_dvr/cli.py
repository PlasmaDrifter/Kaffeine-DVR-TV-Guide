import os
import argparse

try:
    from .config import ConfigManager
    from .dbus_client import KaffeineDbusClient
    from .guide_service import GuideService
    from .rules_engine import RulesEngine
except (ImportError, ValueError):
    from kaffeine_dvr.config import ConfigManager
    from kaffeine_dvr.dbus_client import KaffeineDbusClient
    from kaffeine_dvr.guide_service import GuideService
    from kaffeine_dvr.rules_engine import RulesEngine



def main():
    parser = argparse.ArgumentParser(description="Kaffeine DVR & Web TV Guide CLI Manager")
    parser.add_argument("--gui", action="store_true", help="Launch the TV Guide & DVR graphical user interface")
    parser.add_argument("--sync", action="store_true", help="Sync web TV guide cache")
    parser.add_argument("--days", type=int, default=7, help="Number of days to sync (default: 7)")
    parser.add_argument("--rules", action="store_true", help="Evaluate auto-record rules against cached guide")
    parser.add_argument("--watch", action="store_true", help="Run background watcher daemon to arm recordings before start")
    parser.add_argument("--interval", type=int, default=None, help="Watcher check interval in seconds (default: 120)")
    parser.add_argument("--list", action="store_true", help="List scheduled and queued recordings")
    parser.add_argument("--status", action="store_true", help="Show TV guide and Kaffeine connection status")

    args = parser.parse_args()

    # Launch GUI when explicitly requested or by default when invoked without CLI flags in a graphical session
    no_cli_flags = not any([args.sync, args.rules, args.watch, args.list, args.status])
    if args.gui or no_cli_flags:
        has_display = bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))
        if has_display or args.gui:
            try:
                from .gui import main as gui_main
            except (ImportError, ValueError):
                from kaffeine_dvr.gui import main as gui_main
            gui_main()
            return

    cfg = ConfigManager()
    dbus_client = KaffeineDbusClient()
    guide = GuideService(channel_map=cfg.channel_map)
    rules = RulesEngine(cfg, dbus_client, guide)

    try:
        from .queue_manager import QueueManager
        from .watcher import Watcher
    except (ImportError, ValueError):
        from kaffeine_dvr.queue_manager import QueueManager
        from kaffeine_dvr.watcher import Watcher

    queue_mgr = QueueManager()

    if args.watch:
        interval = args.interval or cfg.watcher_interval_seconds
        watcher = Watcher(dbus_client, queue_mgr)
        watcher.run_loop(interval_seconds=interval)
        return



    if args.status or no_cli_flags:
        k_running = dbus_client.is_running()
        print(f"Kaffeine D-Bus status: {'Running (Connected)' if k_running else 'Offline'}")
        print(f"Active Guide Provider: {cfg.guide_provider.upper()}")
        g_status = guide.get_guide_status()
        print(f"Guide last updated:    {g_status.get('last_updated') or 'Never'}")
        print(f"Programs in cache:     {g_status.get('total_programs', 0)}")
        if g_status.get('last_error'):
            print(f"Last error:            {g_status['last_error']}")

        print("\nGuide Sources Health:")
        health = guide.check_all_sources_health()
        for key, s in health.items():
            lat = f"{s.get('latency_ms')}ms" if s.get('latency_ms', 0) > 0 else "-"
            print(f"- {s.get('name')}: [{s.get('status')}] (Latency: {lat}) -> {s.get('details')}")
        return

    if args.sync:
        print(f"Syncing TV guide for next {args.days} days...")
        count = guide.sync_guide(days=args.days, progress_callback=print)
        print(f"Sync completed: {count} programs cached.")

    if args.rules:
        print("Evaluating auto-record rules...")
        newly = rules.evaluate_and_schedule(progress_callback=print)
        print(f"Rule evaluation completed: {len(newly)} new shows scheduled.")

    if args.list:
        from datetime import datetime, date
        today = date.today()
        queue = queue_mgr.list_queue(include_completed=True)
        print(f"DVR Planned Queue ({len(queue)} items):")
        for q in queue:
            start_iso = q.get('start_iso', '')
            sched = ""
            full_date = q.get('start_time_local', '')
            try:
                dt = datetime.fromisoformat(start_iso)
                full_date = dt.strftime("%a, %b %d, %Y  %I:%M %p")
                diff_days = (dt.date() - today).days
                time_24 = dt.strftime("%H%M")
                if diff_days == 0:
                    sched = f"Today @ {time_24}"
                elif diff_days == 1:
                    sched = f"Tomorrow @ {time_24}"
                elif 0 <= diff_days < 7:
                    sched = f"{dt.strftime('%a')} @ {time_24}"
                else:
                    sched = f"{dt.strftime('%b %d')} @ {time_24}"
            except Exception:
                sched = full_date

            print(f"- {q.get('title')} | {q.get('channel')} | When: {sched} | Date: {full_date} | {q.get('status')}")

        recs = dbus_client.list_scheduled_recordings()
        print(f"\nLive in Kaffeine Timers ({len(recs)} items):")
        for r in recs:
            state = "RECORDING" if r.get("is_running") else "Scheduled"
            print(f"- {r.get('name')} | {r.get('channel')} | {r.get('begin')} | Duration: {r.get('duration')} | {state}")



if __name__ == "__main__":
    main()
