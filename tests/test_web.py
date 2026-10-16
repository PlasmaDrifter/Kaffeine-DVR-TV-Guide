"""
Tests for Kaffeine DVR Remote Web Companion:
- Password hashing, salting, and verification
- Authentication token session management
- API endpoints: status, guide, schedule, recordings
- Video streaming with RFC 7233 HTTP Range seeking
- Path traversal security bounds
"""

import json
import time
import urllib.request

import pytest

from kaffeine_dvr.storage_manager import StorageManager
from kaffeine_dvr.web import KaffeineWebServer


@pytest.fixture
def web_test_env(isolated_config, isolated_queue_mgr, isolated_guide_svc, tmp_path):
    rec_folder = tmp_path / "recordings"
    rec_folder.mkdir(parents=True, exist_ok=True)

    cfg = isolated_config
    cfg.web_server_port = 18088
    cfg.web_server_bind = "127.0.0.1"
    cfg.custom_recording_folder = str(rec_folder)

    q_mgr = isolated_queue_mgr
    guide_svc = isolated_guide_svc
    storage_mgr = StorageManager(cfg, q_mgr)

    server = KaffeineWebServer(cfg, q_mgr, guide_svc, storage_mgr)
    assert server.start() is True
    time.sleep(0.1)

    yield {
        "cfg": cfg,
        "q_mgr": q_mgr,
        "guide_svc": guide_svc,
        "storage_mgr": storage_mgr,
        "server": server,
        "rec_folder": rec_folder,
        "base_url": f"http://127.0.0.1:{cfg.web_server_port}"
    }

    server.stop()


def test_web_password_hashing_and_auth(web_test_env):
    cfg = web_test_env["cfg"]
    server = web_test_env["server"]
    base_url = web_test_env["base_url"]

    # Initially no password set
    assert cfg.has_web_password is False

    # Set password
    cfg.set_web_password("secret_tailscale_123")
    assert cfg.has_web_password is True
    assert cfg.verify_web_password("secret_tailscale_123") is True
    assert cfg.verify_web_password("wrong_password") is False

    # Unauthenticated request should now receive 401
    req = urllib.request.Request(f"{base_url}/api/status")
    with pytest.raises(urllib.error.HTTPError) as exc_info:
        urllib.request.urlopen(req)
    assert exc_info.value.code == 401

    # Login with wrong password
    login_data = json.dumps({"password": "bad"}).encode("utf-8")
    login_req = urllib.request.Request(f"{base_url}/api/login", data=login_data, headers={"Content-Type": "application/json"})
    with pytest.raises(urllib.error.HTTPError) as exc_info:
        urllib.request.urlopen(login_req)
    assert exc_info.value.code == 401

    # Login with correct password
    login_data = json.dumps({"password": "secret_tailscale_123"}).encode("utf-8")
    login_req = urllib.request.Request(f"{base_url}/api/login", data=login_data, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(login_req) as resp:
        assert resp.status == 200
        res_json = json.loads(resp.read().decode("utf-8"))
        token = res_json.get("token")
        assert token is not None
        assert server.is_valid_token(token) is True

    # Use token in Authorization header
    auth_req = urllib.request.Request(f"{base_url}/api/status", headers={"Authorization": f"Bearer {token}"})
    with urllib.request.urlopen(auth_req) as resp:
        assert resp.status == 200
        data = json.loads(resp.read().decode("utf-8"))
        assert data.get("status") == "online"


def test_web_schedule_and_recordings_api(web_test_env):
    base_url = web_test_env["base_url"]
    q_mgr = web_test_env["q_mgr"]

    # Schedule a new show via POST /api/schedule
    payload = json.dumps({
        "title": "Evening News Broadcast",
        "channel": "KSTP-DT",
        "start_iso": "2026-10-15T18:00:00",
        "duration_iso": "00:30:00"
    }).encode("utf-8")

    req = urllib.request.Request(f"{base_url}/api/schedule", data=payload, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req) as resp:
        assert resp.status == 200
        data = json.loads(resp.read().decode("utf-8"))
        qid = data.get("id")
        assert qid is not None

    # Verify present in queue
    queue = q_mgr.list_queue()
    assert len(queue) == 1
    assert queue[0]["title"] == "Evening News Broadcast"

    # Fetch recordings via GET /api/recordings
    with urllib.request.urlopen(f"{base_url}/api/recordings") as resp:
        assert resp.status == 200
        data = json.loads(resp.read().decode("utf-8"))
        active = data.get("active", [])
        assert len(active) == 1
        assert active[0]["title"] == "Evening News Broadcast"

    # Cancel schedule via DELETE /api/schedule/<id>
    del_req = urllib.request.Request(f"{base_url}/api/schedule/{qid}", method="DELETE")
    with urllib.request.urlopen(del_req) as resp:
        assert resp.status == 200
        del_data = json.loads(resp.read().decode("utf-8"))
        assert del_data.get("status") == "cancelled"

    assert len(q_mgr.list_queue()) == 0

    # Test /api/guide endpoint with runtime_mins and summary
    g_conn = web_test_env["guide_svc"]._get_connection()
    g_cur = g_conn.cursor()
    g_cur.execute("""
        INSERT INTO guide_programs (show_title, episode_title, kaffeine_channel, start_time_local, start_iso, duration_iso, runtime_mins, summary, airdate)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, ("Morning Show", "Pilot", "KSTP-DT", "8:00 AM", "2026-10-15T08:00:00", "01:00:00", 60, "Fun morning news", "2026-10-15"))
    g_conn.commit()
    g_conn.close()

    with urllib.request.urlopen(f"{base_url}/api/guide?date=2026-10-15&trim=0") as resp:
        assert resp.status == 200
        progs = json.loads(resp.read().decode("utf-8"))
        assert len(progs) >= 1
        assert progs[0]["title"] == "Morning Show"
        assert progs[0]["runtime_mins"] == 60
        assert progs[0]["summary"] == "Fun morning news"


def test_web_video_streaming_and_http_range(web_test_env):
    base_url = web_test_env["base_url"]
    rec_folder = web_test_env["rec_folder"]
    q_mgr = web_test_env["q_mgr"]

    # Create a dummy video file of 10,000 bytes
    dummy_video = rec_folder / "Championship_Game_20261015.m2t"
    dummy_content = b"0123456789" * 1000
    dummy_video.write_bytes(dummy_content)

    # Insert into recording_history
    conn = q_mgr._get_connection()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO recording_history (title, channel, start_iso, duration_iso, start_time_local, completed_at, file_path)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, ("Championship Game", "ESPN-HD", "2026-10-15T14:00:00", "02:00:00", "2:00 PM", "2026-10-15 16:00:00", str(dummy_video)))
    hid = cur.lastrowid
    conn.commit()
    conn.close()

    # 1. Full stream request with raw parameter (200 OK)
    with urllib.request.urlopen(f"{base_url}/api/stream/{hid}?raw=1") as resp:
        assert resp.status == 200
        assert resp.headers.get("Accept-Ranges") == "bytes"
        assert int(resp.headers.get("Content-Length")) == 10000
        cd_header = resp.headers.get("Content-Disposition", "")
        assert "attachment" in cd_header
        assert "Championship_Game_20261015.m2t" in cd_header
        data = resp.read()
        assert len(data) == 10000

    # 1b. Request with filename in URL path
    with urllib.request.urlopen(f"{base_url}/api/stream/{hid}/Championship_Game_20261015.m2t?raw=1") as resp:
        assert resp.status == 200
        cd_header = resp.headers.get("Content-Disposition", "")
        assert "attachment" in cd_header
        assert "Championship_Game_20261015.m2t" in cd_header
        assert len(resp.read()) == 10000

    # 2. HTTP Range request for bytes 100-199 with raw parameter (206 Partial Content)
    range_req = urllib.request.Request(f"{base_url}/api/stream/{hid}?raw=1", headers={"Range": "bytes=100-199"})
    with urllib.request.urlopen(range_req) as resp:
        assert resp.status == 206
        assert resp.headers.get("Content-Range") == "bytes 100-199/10000"
        assert int(resp.headers.get("Content-Length")) == 100
        chunk = resp.read()
        assert chunk == dummy_content[100:200]

    # 3. Path Traversal Security Protection
    # A history item pointing outside the configured recording directory must be rejected (403 Forbidden)
    outside_file = rec_folder.parent / "secret_system_file.txt"
    outside_file.write_text("classified")
    conn = q_mgr._get_connection()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO recording_history (title, channel, start_iso, duration_iso, start_time_local, completed_at, file_path)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, ("Exploit Test", "Hack", "2026-10-15T00:00:00", "01:00:00", "12:00 AM", "2026-10-15 01:00:00", str(outside_file)))
    bad_hid = cur.lastrowid
    conn.commit()
    conn.close()

    with pytest.raises(urllib.error.HTTPError) as exc_info:
        urllib.request.urlopen(f"{base_url}/api/stream/{bad_hid}")
    assert exc_info.value.code == 403


def test_web_companion_ui_anchored_epg_and_channels(web_test_env):
    base_url = web_test_env["base_url"]

    # Fetch main companion web UI
    with urllib.request.urlopen(f"{base_url}/") as resp:
        assert resp.status == 200
        html = resp.read().decode("utf-8")
        assert "guideChannelSelect" in html
        assert "epg-channels-col" in html
        assert "epgTimelinePane" in html
        assert "epgChannelList" in html
        assert "populateChannelDropdown" in html
        assert "epg-rec-badge" in html
        assert "epg-sched-badge" in html
        assert 'href="/favicon.png"' in html
        assert 'href="/favicon.ico"' in html

    # Verify favicon endpoints return valid PNG bytes
    with urllib.request.urlopen(f"{base_url}/favicon.ico") as ico_resp:
        assert ico_resp.status == 200
        assert ico_resp.headers.get("Content-Type") == "image/png"
        data = ico_resp.read()
        assert data.startswith(b"\x89PNG\r\n\x1a\n")

    with urllib.request.urlopen(f"{base_url}/favicon.png") as png_resp:
        assert png_resp.status == 200
        assert png_resp.headers.get("Content-Type") == "image/png"
        data = png_resp.read()
        assert data.startswith(b"\x89PNG\r\n\x1a\n")

