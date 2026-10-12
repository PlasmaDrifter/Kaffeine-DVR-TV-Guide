from kaffeine_dvr.dbus_client import KaffeineDbusClient
from kaffeine_dvr.rules_engine import RulesEngine, is_sports_program


def test_rules_crud(isolated_config, isolated_guide_svc, isolated_queue_mgr):
    dbus = KaffeineDbusClient()
    re = RulesEngine(isolated_config, dbus, isolated_guide_svc, isolated_queue_mgr)

    # 1. Add rule
    rule = re.add_rule("NFL Football", channel="FOX 10.1", buffer_mins=45)
    assert rule["title_keyword"] == "NFL Football"
    assert rule["channel"] == "FOX 10.1"
    assert rule["buffer_mins"] == 45
    assert rule["enabled"] is True
    assert len(re.get_rules()) == 1

    # 2. Toggle rule
    rule_id = rule["id"]
    re.toggle_rule(rule_id, False)
    assert re.get_rules()[0]["enabled"] is False

    # 3. Update rule
    re.update_rule(rule_id, "NFL Sunday", channel="All", enabled=True, buffer_mins=60)
    updated = re.get_rules()[0]
    assert updated["title_keyword"] == "NFL Sunday"
    assert updated["channel"] == "All"
    assert updated["buffer_mins"] == 60

    # 4. Remove rule
    re.remove_rule(rule_id)
    assert len(re.get_rules()) == 0

def test_is_sports_program():
    prog1 = {"show_title": "NFL Football", "episode_title": "", "summary": ""}
    prog2 = {"show_title": "Local News", "episode_title": "", "summary": ""}
    assert is_sports_program(prog1) is True
    assert is_sports_program(prog2) is False
