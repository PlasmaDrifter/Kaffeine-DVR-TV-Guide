import sqlite3
from datetime import datetime, timedelta
from unittest.mock import MagicMock

import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QPushButton, QTableWidget

from kaffeine_dvr.config import ConfigManager
from kaffeine_dvr.gui import MainWindow, TableButtonCell, build_app_stylesheet
from kaffeine_dvr.queue_manager import QueueManager


def _extract_watch_button(cell_widget):
    if cell_widget is None:
        return None
    if isinstance(cell_widget, QPushButton):
        return cell_widget
    return getattr(cell_widget, "button", cell_widget.findChild(QPushButton))


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


def test_table_watch_button_theming_and_fixed_dimensions():
    # Verify stylesheet generation contains tableWatchBtn with theme tokens
    sheet = build_app_stylesheet("midnight")
    assert "QPushButton#tableWatchBtn" in sheet
    assert "border-radius: 4px" in sheet

    sheet_oled = build_app_stylesheet("oled_black")
    assert "QPushButton#tableWatchBtn" in sheet_oled


def test_gui_active_schedule_status_and_history_updates(qtbot, isolated_config: ConfigManager):
    win = MainWindow(config_mgr=isolated_config)
    qtbot.addWidget(win)

    try:
        # Check column headers for rec_table and history_table
        assert win.rec_table.columnCount() == 7
        assert win.rec_table.horizontalHeaderItem(0).text() == "Watch"
        assert win.rec_table.horizontalHeaderItem(1).text() == "Title"
        assert win.history_table.columnCount() == 6
        assert win.history_table.horizontalHeaderItem(0).text() == "Watch"
        assert win.history_table.horizontalHeaderItem(1).text() == "Title"
        assert win.history_table.horizontalHeaderItem(5).text() == "Status"

        # Initially empty
        win.refresh_recordings(force=True)
        assert win.rec_table.rowCount() == 0
        assert win.history_table.rowCount() == 0

        # Add a queued recording in the future: should NOT have a Watch button
        future_iso = (datetime.now() + timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:%S")
        q_fut_id = win.queue_mgr.add_recording("Future Queued", "NBC 12.1", future_iso, "01:00:00")
        win.refresh_recordings(force=True)
        assert win.rec_table.rowCount() == 1
        assert _extract_watch_button(win.rec_table.cellWidget(0, 0)) is None
        win.queue_mgr.remove_recording(q_fut_id)

        # Add an armed recording starting now
        start_dt = datetime.now() - timedelta(seconds=10)
        start_iso = start_dt.strftime("%Y-%m-%dT%H:%M:%S")
        qid = win.queue_mgr.add_recording("Active Breaking News", "CNN 3.1", start_iso, "01:00:00")
        win.queue_mgr.mark_armed(qid, 555)

        # Trigger periodic status check (force=True since window is not shown)
        win._check_schedule_status_updates(force=True)

        # Active table should reflect transition to RECORDING
        assert win.rec_table.rowCount() == 1
        title_it = win.rec_table.item(0, 1)
        watch_btn = _extract_watch_button(win.rec_table.cellWidget(0, 0))
        assert isinstance(watch_btn, QPushButton)
        assert "Watch" in watch_btn.text()
        assert watch_btn.objectName() == "tableWatchBtn"
        assert watch_btn.maximumWidth() == 78 and watch_btn.maximumHeight() == 24
        assert watch_btn.minimumWidth() == 78 and watch_btn.minimumHeight() == 24

        status_it = win.rec_table.item(0, 5)
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
        assert win.rec_table.item(0, 1).text() == "Active Breaking News"
        # Watch button must still be available for completed recording
        completed_watch_btn = _extract_watch_button(win.rec_table.cellWidget(0, 0))
        assert isinstance(completed_watch_btn, QPushButton)
        assert "Watch" in completed_watch_btn.text()
        assert completed_watch_btn.objectName() == "tableWatchBtn"

        completed_status_it = win.rec_table.item(0, 5)
        assert completed_status_it.text() == "Completed"
        assert completed_status_it.foreground().color().name().lower() == "#28a745"

        # History table should also contain the completed show
        assert win.history_table.rowCount() == 1
        assert win.history_table.item(0, 1).text() == "Active Breaking News"
        hist_watch_btn = _extract_watch_button(win.history_table.cellWidget(0, 0))
        assert isinstance(hist_watch_btn, QPushButton)
        assert "Watch" in hist_watch_btn.text()
        assert hist_watch_btn.objectName() == "tableWatchBtn"
        assert hist_watch_btn.maximumWidth() == 78 and hist_watch_btn.maximumHeight() == 24
        assert hist_watch_btn.minimumWidth() == 78 and hist_watch_btn.minimumHeight() == 24
        assert win.history_table.item(0, 3).text() == "CNN 3.1"
        # Status column reflects that no physical file exists on disk
        assert "Deleted from Disk" in win.history_table.item(0, 5).text()
        assert not hist_watch_btn.isEnabled()

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


def test_gui_watch_button_and_double_click_playback(qtbot, isolated_config: ConfigManager, tmp_path):
    isolated_config.custom_recording_folder = str(tmp_path)
    win = MainWindow(config_mgr=isolated_config)
    qtbot.addWidget(win)

    try:
        # Mock play_recording_item
        win.play_recording_item = MagicMock()

        # 1. Active Schedule recording row
        start_iso = (datetime.now() - timedelta(minutes=10)).strftime("%Y-%m-%dT%H:%M:%S")
        qid = win.queue_mgr.add_recording("Playback Test Show", "ABC 7.1", start_iso, "01:00:00")
        win.queue_mgr.mark_armed(qid, 777)
        win.queue_mgr.update_statuses([])
        win.refresh_recordings(force=True)

        assert win.rec_table.rowCount() == 1
        watch_btn = _extract_watch_button(win.rec_table.cellWidget(0, 0))
        assert isinstance(watch_btn, QPushButton)

        # Click the watch button
        watch_btn.click()
        assert win.play_recording_item.call_count == 1
        call_rec = win.play_recording_item.call_args[0][0]
        assert call_rec["title"] == "Playback Test Show"

        # Double click the row item
        item = win.rec_table.item(0, 1)
        win._on_rec_table_double_clicked(item)
        assert win.play_recording_item.call_count == 2

        # 2. History table row with simulated video file on disk
        video_file = tmp_path / "Historic_Movie_20261015.m2t"
        video_file.write_bytes(b"0" * 1024 * 500)

        win.queue_mgr.add_history_entry("Historic Movie", "HBO 5.1", "2026-10-15T08:00:00", "02:00:00", file_path=str(video_file))
        win.refresh_history(force=True)
        assert win.history_table.rowCount() == 1
        hist_watch_btn = _extract_watch_button(win.history_table.cellWidget(0, 0))
        assert isinstance(hist_watch_btn, QPushButton)
        assert hist_watch_btn.isEnabled()

        hist_watch_btn.click()
        assert win.play_recording_item.call_count == 3
        hist_call_rec = win.play_recording_item.call_args[0][0]
        assert hist_call_rec["title"] == "Historic Movie"

        # Double click history row item
        hist_item = win.history_table.item(0, 1)
        win._on_history_table_double_clicked(hist_item)
        assert win.play_recording_item.call_count == 4
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
        assert win.rec_table.item(0, 1).text() == "Future Show"

        # Switch subtab to History (index 1)
        win.recordings_subtabs.setCurrentIndex(1)
        win._on_recordings_subtab_changed(1)

        # Insert entry in history
        win.queue_mgr.add_history_entry("Past Broadcast", "ABC 7.1", "2026-10-15T10:00:00", "00:30:00")
        win._on_recordings_subtab_changed(1)
        assert win.history_table.rowCount() == 1
        assert win.history_table.item(0, 1).text() == "Past Broadcast"
    finally:
        win.close()


def test_history_disk_availability_and_sync_rules(qtbot, isolated_config: ConfigManager, tmp_path):
    isolated_config.custom_recording_folder = str(tmp_path)
    win = MainWindow(config_mgr=isolated_config)
    qtbot.addWidget(win)

    try:
        # 1. Setup completed recording in both queue and history
        start_iso = (datetime.now() - timedelta(minutes=45)).strftime("%Y-%m-%dT%H:%M:%S")
        end_iso = (datetime.now() - timedelta(minutes=15)).strftime("%Y-%m-%dT%H:%M:%S")

        qid = win.queue_mgr.add_recording("Sync Test Broadcast", "PBS 10.1", start_iso, "00:30:00")
        conn = win.queue_mgr._get_connection()
        cur = conn.cursor()
        cur.execute("UPDATE recording_queue SET status = 'COMPLETED', end_iso = ? WHERE id = ?", (end_iso, qid))
        conn.commit()
        conn.close()

        hid = win.queue_mgr.add_history_entry("Sync Test Broadcast", "PBS 10.1", start_iso, "00:30:00")

        win.refresh_recordings(force=True)
        win.refresh_history(force=True)

        assert win.rec_table.rowCount() == 1
        assert win.history_table.rowCount() == 1

        # File does not exist yet -> "Deleted from Disk", watch button disabled
        assert "Deleted from Disk" in win.history_table.item(0, 5).text()
        hist_btn = _extract_watch_button(win.history_table.cellWidget(0, 0))
        assert hist_btn is not None and not hist_btn.isEnabled()

        # 2. Simulate video file creation on disk
        video_file = tmp_path / "Sync_Test_Broadcast.m2t"
        video_file.write_bytes(b"X" * (1024 * 1024 * 250))  # 250 MB

        win.refresh_history(force=True)
        assert "Available (250 MB)" in win.history_table.item(0, 5).text()
        hist_btn = _extract_watch_button(win.history_table.cellWidget(0, 0))
        assert hist_btn is not None and hist_btn.isEnabled()

        # 3. Rule: Clearing item in history ALSO clears it from active schedule (if within 6 hours)
        win.history_table.setCurrentCell(0, 1)
        win.clear_selected_history_entry()

        assert win.history_table.rowCount() == 0
        assert win.rec_table.rowCount() == 0  # Active schedule was also cleared!

        # 4. Rule: Clearing/canceling from active schedule does NOT remove from history
        fut_iso = (datetime.now() + timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:%S")
        qid2 = win.queue_mgr.add_recording("Keep In History Show", "NBC 4.1", fut_iso, "00:30:00")
        hid2 = win.queue_mgr.add_history_entry("Keep In History Show", "NBC 4.1", start_iso, "00:30:00")
        win.refresh_recordings(force=True)
        win.refresh_history(force=True)

        assert win.rec_table.rowCount() == 1
        assert win.history_table.rowCount() == 1

        # Cancel/remove from active schedule
        win.rec_table.setCurrentCell(0, 1)
        win.cancel_selected_recording()

        # Active schedule should be empty, but History must still retain the entry
        assert win.rec_table.rowCount() == 0
        assert win.history_table.rowCount() == 1
        assert win.history_table.item(0, 1).text() == "Keep In History Show"
    finally:
        win.close()


def test_gui_recording_schedule_column_placements_persistence(qtbot, isolated_config: ConfigManager):
    from PyQt6.QtCore import QSettings

    s = QSettings("KaffeineDVR", "TVGuide")
    # Pre-populate custom header states in settings
    mock_rec = QTableWidget(1, 7)
    rec_h = mock_rec.horizontalHeader()
    rec_h.setSectionsMovable(True)
    rec_h.moveSection(1, 3)
    s.setValue("rec_table_header_state", rec_h.saveState())

    mock_hist = QTableWidget(1, 6)
    hist_h = mock_hist.horizontalHeader()
    hist_h.setSectionsMovable(True)
    hist_h.moveSection(3, 1)
    s.setValue("history_table_header_state", hist_h.saveState())

    win = MainWindow(config_mgr=isolated_config)
    qtbot.addWidget(win)

    try:
        # Check that sections are movable
        assert win.rec_table.horizontalHeader().sectionsMovable() is True
        assert win.history_table.horizontalHeader().sectionsMovable() is True

        # Verify that custom column placements were restored from settings
        assert win.rec_table.horizontalHeader().visualIndex(1) == 3
        assert win.history_table.horizontalHeader().visualIndex(3) == 1

        # Move logical Column 1 to Visual Index 4, and check that settings value updates
        win.rec_table.horizontalHeader().moveSection(3, 4)
        saved_bytes = win.settings.value("rec_table_header_state")
        assert saved_bytes is not None

        # Verify dynamic update in settings reflects change
        check_table = QTableWidget(1, 7)
        check_table.horizontalHeader().restoreState(saved_bytes)
        assert check_table.horizontalHeader().visualIndex(1) == 4
    finally:
        win.close()
        s.remove("rec_table_header_state")
        s.remove("history_table_header_state")



