import sqlite3
from datetime import datetime, timedelta

import pytest
from PyQt6.QtCore import Qt

from kaffeine_dvr.config import ConfigManager
from kaffeine_dvr.gui import MainWindow
from kaffeine_dvr.queue_manager import QueueManager


def test_update_statuses_armed_to_recording(isolated_queue_mgr: QueueManager):
    qm = isolated_queue_mgr
    # Show started 5 minutes ago, duration 1 hour
    start_dt = datetime.now() - timedelta(minutes=5)
    start_iso = start_dt.strftime("%Y-%m-%dT%H:%M:%S")

    qid = qm.add_recording("Live Show", "FOX 10.1", start_iso, "01:00:00")
    qm.mark_armed(qid, 401)

    rec = next(r for r in qm.list_queue() if r["id"] == qid)
    assert rec["status"] == "ARMED"

    # Status update should transition to RECORDING
    res = qm.update_statuses([])
    assert res["started"] == 1
    assert res["archived"] == 0

    rec = next(r for r in qm.list_queue() if r["id"] == qid)
    assert rec["status"] == "RECORDING"

    # Calling again should not re-trigger started_count
    res2 = qm.update_statuses([])
    assert res2["started"] == 0
    assert res2["archived"] == 0


def test_update_statuses_recording_to_history(isolated_queue_mgr: QueueManager):
    qm = isolated_queue_mgr
    # Show ended 10 minutes ago
    start_dt = datetime.now() - timedelta(hours=1, minutes=10)
    start_iso = start_dt.strftime("%Y-%m-%dT%H:%M:%S")

    qid = qm.add_recording("Finished Show", "PBS 8.1", start_iso, "01:00:00")
    qm.mark_armed(qid, 402)
    qm.set_recording_file(qid, "/recordings/pbs_show.mkv")

    # update_statuses should archive to history and remove from queue
    res = qm.update_statuses([], max_history=20)
    assert res["archived"] == 1

    assert len(qm.list_queue()) == 0
    hist = qm.list_history()
    assert len(hist) == 1
    assert hist[0]["title"] == "Finished Show"
    assert hist[0]["channel"] == "PBS 8.1"
    assert hist[0]["start_iso"] == start_iso
    assert hist[0]["duration_iso"] == "01:00:00"
    assert hist[0]["completed_at"] is not None
    assert hist[0]["file_path"] == "/recordings/pbs_show.mkv"


def test_update_statuses_queued_expired_to_history(isolated_queue_mgr: QueueManager):
    qm = isolated_queue_mgr
    # Show ended in past without arming
    start_dt = datetime.now() - timedelta(hours=2)
    start_iso = start_dt.strftime("%Y-%m-%dT%H:%M:%S")

    qid = qm.add_recording("Expired Queued Show", "NBC 12.1", start_iso, "00:30:00")
    rec = next(r for r in qm.list_queue() if r["id"] == qid)
    assert rec["status"] == "QUEUED"

    res = qm.update_statuses([], max_history=10)
    assert res["archived"] == 1
    assert len(qm.list_queue()) == 0

    hist = qm.list_history()
    assert len(hist) == 1
    assert hist[0]["title"] == "Expired Queued Show"


def test_history_pruning(isolated_queue_mgr: QueueManager):
    qm = isolated_queue_mgr
    for i in range(12):
        qm.add_history_entry(
            f"Show {i}",
            "Channel",
            f"2026-10-15T{i:02d}:00:00",
            "00:30:00",
            max_entries=50
        )
    assert len(qm.list_history()) == 12

    # Prune to 5
    qm.prune_history(5)
    hist = qm.list_history()
    assert len(hist) == 5
    # Newest items should remain
    assert hist[0]["title"] == "Show 11"
    assert hist[4]["title"] == "Show 7"


def test_gui_active_schedule_status_and_history_updates(qtbot, isolated_config: ConfigManager):
    win = MainWindow(config_mgr=isolated_config)
    qtbot.addWidget(win)

    try:
        # Initially empty
        win.refresh_recordings(force=True)
        assert win.rec_table.rowCount() == 0
        assert win.history_table.rowCount() == 0

        # Add an armed recording starting now
        start_dt = datetime.now() - timedelta(seconds=10)
        start_iso = start_dt.strftime("%Y-%m-%dT%H:%M:%S")
        qid = win.queue_mgr.add_recording("Active Breaking News", "CNN 3.1", start_iso, "01:00:00")
        win.queue_mgr.mark_armed(qid, 555)

        # Trigger periodic status check (force=True since window is not shown)
        win._check_schedule_status_updates(force=True)

        # Active table should reflect transition to RECORDING
        assert win.rec_table.rowCount() == 1
        title_it = win.rec_table.item(0, 0)
        status_it = win.rec_table.item(0, 4)
        assert title_it.text() == "Active Breaking News"
        assert "Recording Now" in status_it.text()
        assert status_it.foreground().color().name().lower() == "#ff5252"
        assert win.history_table.rowCount() == 0

        # Now simulate show finishing by adjusting end_iso into the past in the database
        conn = win.queue_mgr._get_connection()
        cur = conn.cursor()
        past_end = (datetime.now() - timedelta(seconds=5)).isoformat()
        cur.execute("UPDATE recording_queue SET end_iso = ? WHERE id = ?", (past_end, qid))
        conn.commit()
        conn.close()

        # Trigger periodic check again
        win._check_schedule_status_updates(force=True)

        # Active table should now be empty (show completed)
        assert win.rec_table.rowCount() == 0
        # History table should now contain the completed show
        assert win.history_table.rowCount() == 1
        assert win.history_table.item(0, 0).text() == "Active Breaking News"
        assert win.history_table.item(0, 2).text() == "CNN 3.1"
    finally:
        win.close()


def test_gui_tab_switch_auto_refresh(qtbot, isolated_config: ConfigManager):
    win = MainWindow(config_mgr=isolated_config)
    qtbot.addWidget(win)

    try:
        # Directly insert an entry in queue
        start_iso = (datetime.now() + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%S")
        qid = win.queue_mgr.add_recording("Future Show", "ABC 7.1", start_iso, "00:30:00")

        # Switch to Recordings Schedule tab (index 1)
        win.tabs.setCurrentIndex(1)
        win._on_main_tab_changed(1)

        assert win.rec_table.rowCount() == 1
        assert win.rec_table.item(0, 0).text() == "Future Show"

        # Switch subtab to History (index 2)
        win.recordings_subtabs.setCurrentIndex(2)
        win._on_recordings_subtab_changed(2)

        # Insert entry in history
        win.queue_mgr.add_history_entry("Past Broadcast", "ABC 7.1", "2026-10-15T10:00:00", "00:30:00")
        win._on_recordings_subtab_changed(2)
        assert win.history_table.rowCount() == 1
        assert win.history_table.item(0, 0).text() == "Past Broadcast"
    finally:
        win.close()
