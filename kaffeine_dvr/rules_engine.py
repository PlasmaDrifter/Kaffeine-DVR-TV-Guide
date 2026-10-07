import uuid
from typing import List, Dict, Any, Optional
from .dbus_client import KaffeineDbusClient
from .guide_service import GuideService
from .config import ConfigManager
from .queue_manager import QueueManager

class RulesEngine:
    def __init__(self, config_mgr: ConfigManager, dbus_client: KaffeineDbusClient, guide_service: GuideService, queue_mgr: Optional[QueueManager] = None):
        self.config_mgr = config_mgr
        self.dbus_client = dbus_client
        self.guide_service = guide_service
        self.queue_mgr = queue_mgr or QueueManager()

    def get_rules(self) -> List[Dict[str, Any]]:
        return self.config_mgr.rules

    def add_rule(self, title_keyword: str, channel: str = "All") -> Dict[str, Any]:
        rules = self.config_mgr.rules
        rule = {
            "id": str(uuid.uuid4())[:8],
            "title_keyword": title_keyword.strip(),
            "channel": channel.strip(),
            "enabled": True
        }
        rules.append(rule)
        self.config_mgr.rules = rules
        return rule

    def remove_rule(self, rule_id: str):
        rules = [r for r in self.config_mgr.rules if r.get("id") != rule_id]
        self.config_mgr.rules = rules

    def update_rule(self, rule_id: str, title_keyword: str, channel: str = "All", enabled: bool = True) -> bool:
        rules = self.config_mgr.rules
        found = False
        for r in rules:
            if r.get("id") == rule_id:
                r["title_keyword"] = title_keyword.strip()
                r["channel"] = channel.strip()
                r["enabled"] = enabled
                found = True
                break
        if found:
            self.config_mgr.rules = rules
        return found

    def toggle_rule(self, rule_id: str, enabled: bool):
        rules = self.config_mgr.rules
        for r in rules:
            if r.get("id") == rule_id:
                r["enabled"] = enabled
        self.config_mgr.rules = rules

    def evaluate_and_schedule(self, progress_callback=None) -> List[Dict[str, Any]]:
        """
        Cross-reference active rules with cached guide listings,
        and add any upcoming episodes to the DVR queue (deferred until air time).
        """
        queue_mgr = self.queue_mgr

        active_rules = [r for r in self.config_mgr.rules if r.get("enabled", True)]
        if not active_rules:
            if progress_callback:
                progress_callback("No active auto-recording rules configured.")
            return []

        # Get existing queued or armed recordings to avoid duplicates
        existing_queue = queue_mgr.list_queue(include_completed=False)
        scheduled_signatures = set()
        for s in existing_queue:
            sig = (s.get("channel", "").strip().lower(), s.get("start_iso", "")[:16])
            scheduled_signatures.add(sig)

        newly_scheduled = []

        for rule in active_rules:
            kw = rule.get("title_keyword", "").strip()
            ch = rule.get("channel", "All")
            if not kw:
                continue

            matching_programs = self.guide_service.search_programs(
                query=kw,
                channel=ch if ch != "All" else None
            )

            for prog in matching_programs:
                show_title = prog.get("show_title", "")
                episode_title = prog.get("episode_title") or ""
                full_text = f"{show_title} {episode_title}".lower()
                if kw.lower() not in full_text:
                    continue


                prog_channel = prog.get("kaffeine_channel", "")
                start_iso = prog.get("start_iso", "")
                duration_iso = prog.get("duration_iso", "")
                episode_title = prog.get("episode_title") or ""
                rec_title = f"{show_title} - {episode_title}" if episode_title else show_title

                sig = (prog_channel.lower(), start_iso[:16])
                if sig in scheduled_signatures:
                    continue  # already queued

                # Add to deferred DVR queue
                try:
                    if progress_callback:
                        progress_callback(f"Queueing: {rec_title} on {prog_channel} ({prog.get('start_time_local')})...")

                    qid = queue_mgr.add_recording(
                        title=rec_title,
                        channel=prog_channel,
                        start_iso=start_iso,
                        duration_iso=duration_iso,
                        lead_time_mins=5
                    )
                    scheduled_signatures.add(sig)
                    newly_scheduled.append({
                        "id": qid,
                        "title": rec_title,
                        "channel": prog_channel,
                        "start_time": prog.get("start_time_local")
                    })
                except Exception as e:
                    print(f"Error queueing '{rec_title}': {e}")

        if progress_callback:
            progress_callback(f"Rule evaluation complete. {len(newly_scheduled)} new recordings queued.")

        return newly_scheduled

