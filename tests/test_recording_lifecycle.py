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


def test_update_statuses_recording_to_history_and_6hr_retention(isolated_queue_mgr: QueueManager):
    qm = isolated_queue_mgr
    # Show ended 10 minutes ago
    start_dt = datetime.now() - timedelta(hours=1, minutes=10)
    start_iso = start_dt.strftime("%Y-%m-%dT%H:%M:%S")

    qid = qm.add_recording("Finished Show", "PBS 8.1", start_iso, "01:00:00")
    qm.mark_armed(qid, 402)
    qm.set_recording_file(qid, "/recordings/pbs_show.mkv")

    # update_statuses should archive to history AND transition status to COMPLETED (kept for 6 hours)
    res = qm.update_statuses([], max_history=20)
    assert res["archived"] == 1

    # Active queue (without completed) excludes it, but full queue includes it as COMPLETED
    assert len(qm.list_queue(include_completed=False)) == 0
    full_q = qm.list_queue(include_completed=True)
    assert len(full_q) == 1
    assert full_q[0]["status"] == "COMPLETED"

    # Preserved in recording_history with metadata
    hist = qm.list_history()
    assert len(hist) == 1
    assert hist[0]["title"] == "Finished Show"
    assert hist[0]["channel"] == "PBS 8.1"
    assert hist[0]["start_iso"] == start_iso
    assert hist[0]["duration_iso"] == "01:00:00"
    assert hist[0]["completed_at"] is not None
    assert hist[0]["file_path"] == "/recordings/pbs_show.mkv"

    # Repeated calls within 6 hours must NOT re-insert into history
    res2 = qm.update_statuses([], max_history=20)
    assert res2["archived"] == 0
    assert len(qm.list_history()) == 1
    assert len(qm.list_queue(include_completed=True)) == 1

    # Now simulate passing 6 hours past end_iso
    conn = qm._get_connection()
    cur = conn.cursor()
    older_end = (datetime.now() - timedelta(hours=6, minutes=5)).isoformat()
    cur.execute("UPDATE recording_queue SET end_iso = ? WHERE id = ?", (older_end, qid))
    conn.commit()
    conn.close()

    # Calling update_statuses now purges the 6-hour expired entry from queue
    qm.update_statuses([], max_history=20)
    assert len(qm.list_queue(include_completed=True)) == 0
    # Still safely kept in history
    assert len(qm.list_history()) == 1


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

        # Active table should KEEP the show with status "Completed" (green #28a745)
        assert win.rec_table.rowCount() == 1
        assert win.rec_table.item(0, 0).text() == "Active Breaking News"
        completed_status_it = win.rec_table.item(0, 4)
        assert completed_status_it.text() == "Completed"
        assert completed_status_it.foreground().color().name().lower() == "#28a745"

        # History table should also contain the completed show
        assert win.history_table.rowCount() == 1
        assert win.history_table.item(0, 0).text() == "Active Breaking News"
        assert win.history_table.item(0, 2).text() == "CNN 3.1"

        # Now simulate 6 hours passing (older end_iso beyond 6 hours)
        conn = win.queue_mgr._get_connection()
        cur = conn.cursor()
        expired_end = (datetime.now() - timedelta(hours=6, seconds=10)).isoformat()
        cur.execute("UPDATE recording_queue SET end_iso = ? WHERE id = ?", (expired_end, qid))
        conn.commit()
        conn.close()

        win._check_schedule_status_updates(force=True)
        # Now Active Schedule table is purged of the 6-hour expired entry
        assert win.rec_table.rowCount() == 0
        # History table retains the record
        assert win.history_table.rowCount() == 1
    finally:
        win.close()


def test_gui_recording_subtabs_order_and_hint_label(qtbot, isolated_config: ConfigManager):
    win = MainWindow(config_mgr=isolated_config)
    qtbot.addWidget(win)

    try:
        # Check subtabs order: 0 = Active Schedule, 1 = History, 2 = Auto-Record Rules
        assert win.recordings_subtabs.count() == 3
        assert win.recordings_subtabs.tabText(0) == "Active Schedule"
        assert win.recordings_subtabs.tabText(1) == "History"
        assert win.recordings_subtabs.tabText(2) == "Auto-Record Rules"

        # Check retention hint label in empty space of control bar
        assert hasattr(win, "schedule_retention_hint_lbl")
        assert "6 hours" in win.schedule_retention_hint_lbl.text()
        assert "History" in win.schedule_retention_hint_lbl.text()

        # Directly insert an entry in queue
        start_iso = (datetime.now() + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%S")
        win.queue_mgr.add_recording("Future Show", "ABC 7.1", start_iso, "00:30:00")

        # Switch to Recordings Schedule tab (index 1)
        win.tabs.setCurrentIndex(1)
        win._on_main_tab_changed(1)

        assert win.rec_table.rowCount() == 1
        assert win.rec_table.item(0, 0).text() == "Future Show"

        # Switch subtab to History (index 1)
        win.recordings_subtabs.setCurrentIndex(1)
        win._on_recordings_subtab_changed(1)

        # Insert entry in history
        win.queue_mgr.add_history_entry("Past Broadcast", "ABC 7.1", "2026-10-15T10:00:00", "00:30:00")
        win._on_recordings_subtab_changed(1)
        assert win.history_table.rowCount() == 1
        assert win.history_table.item(0, 0).text() == "Past Broadcast"
    finally:
        win.close()
