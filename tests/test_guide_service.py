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
