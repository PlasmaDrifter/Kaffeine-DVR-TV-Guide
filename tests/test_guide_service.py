from kaffeine_dvr.gui import classify_guide_category, get_program_display_titles
from kaffeine_dvr.guide_service import GuideService, parse_xmltv_datetime


def test_parse_xmltv_datetime():
    # XMLTV with timezone
    dt = parse_xmltv_datetime("20261011193000 -0700")
    assert dt is not None
    assert dt.year == 2026 and dt.month == 10 and dt.day == 11 and dt.hour == 19 and dt.minute == 30

    # XMLTV without timezone
    dt2 = parse_xmltv_datetime("20261011200000")
    assert dt2 is not None
    assert dt2.year == 2026 and dt2.hour == 20

    # Invalid string returns None
    assert parse_xmltv_datetime("invalid_date_format") is None

def test_classify_and_display_titles():
    # 1. Movie (runtime >= 80 mins, feature film in summary)
    movie_prog = {
        "show_title": "The Dark Knight",
        "episode_title": "",
        "summary": "Feature film. Batman battles the Joker.",
        "runtime_mins": 152
    }
    assert classify_guide_category(movie_prog) == "movies"
    main_t, sub_t = get_program_display_titles(movie_prog)
    assert main_t == "The Dark Knight"
    assert sub_t == ""

    # 2. Sports matchup
    sports_prog = {
        "show_title": "NFL Football",
        "episode_title": "Ravens at Falcons",
        "summary": "Regular season game."
    }
    assert classify_guide_category(sports_prog) == "sports"
    main_t, sub_t = get_program_display_titles(sports_prog)
    assert main_t == "Ravens at Falcons"
    assert sub_t == "NFL Football"

    # 3. Standard Series
    series_prog = {
        "show_title": "Modern Family",
        "episode_title": "Pilot",
        "summary": "An honest look at American families."
    }
    assert classify_guide_category(series_prog) == "tvshows"
    main_t, sub_t = get_program_display_titles(series_prog)
    assert main_t == "Modern Family"
    assert sub_t == "Pilot"

def test_guide_service_wal_mode(isolated_guide_svc: GuideService):
    gs = isolated_guide_svc
    conn = gs._get_connection()
    cur = conn.cursor()
    cur.execute("PRAGMA journal_mode;")
    mode = cur.fetchone()[0]
    assert mode.lower() == "wal"
    conn.close()


def test_get_live_program_for_channel(isolated_guide_svc: GuideService):
    from datetime import datetime, timedelta
    gs = isolated_guide_svc

    now = datetime.now()
    start_dt = now - timedelta(minutes=15)
    start_iso = start_dt.strftime("%Y-%m-%dT%H:%M:%S")
    airdate = now.strftime("%Y-%m-%d")

    conn = gs._get_connection()
    cur = conn.cursor()
    cur.execute("""
        INSERT OR REPLACE INTO guide_programs (
            tvmaze_id, show_title, episode_title, network, kaffeine_channel,
            start_time_local, start_iso, duration_iso, runtime_mins, summary,
            season, number, airdate, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        88881, "Live Action News", "Evening Edition", "Local", "7.1 KGO-HD",
        start_dt.strftime("%I:%M %p"), start_iso, "01:00:00", 60, "Breaking news updates.",
        None, None, airdate, now.isoformat()
    ))
    conn.commit()
    conn.close()

    live_p = gs.get_live_program_for_channel("7.1 KGO-HD")
    assert live_p is not None
    assert live_p["show_title"] == "Live Action News"

    # Non-existent channel returns None
    assert gs.get_live_program_for_channel("99.9 NONEXISTENT") is None
