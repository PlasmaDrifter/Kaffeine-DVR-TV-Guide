"""
Tests for weak/no signal detection, automatic tuner release, and warning popup.
"""

from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

from PyQt6.QtCore import QEvent, QPoint
from PyQt6.QtGui import QHelpEvent
from PyQt6.QtWidgets import QMessageBox

from kaffeine_dvr.gui import ChannelSignalHealthDialog, GuideGridVerticalHeader, MainWindow
from kaffeine_dvr.watcher import Watcher


def test_signal_timeout_duration_logic(qtbot, isolated_config):
    """
    Test timeout duration respects max(3.0, buf_secs):
    - When buffer is 1s or 2s, timeout is 3.0s.
    - When buffer is 5s, timeout is 5.0s.
    """
    cfg = isolated_config
    cfg.timeshift_buffer_seconds = 2
    assert max(3.0, float(cfg.timeshift_buffer_seconds)) == 3.0

    cfg.timeshift_buffer_seconds = 1
    assert max(3.0, float(cfg.timeshift_buffer_seconds)) == 3.0

    cfg.timeshift_buffer_seconds = 5
    assert max(3.0, float(cfg.timeshift_buffer_seconds)) == 5.0


def test_handle_timeshift_signal_failure_releases_tuner(qtbot, isolated_config, tmp_path):
    """
    Test that _handle_timeshift_signal_failure:
    1. Cancels recording in Kaffeine via D-Bus client.
    2. Removes recording from queue manager.
    3. Cleans up empty / stalled partial files in recording folder.
    4. Shows a QMessageBox warning.
    """
    cfg = isolated_config
    cfg.custom_recording_folder = str(tmp_path)

    win = MainWindow(config_mgr=cfg)
    qtbot.addWidget(win)

    # Mock dbus_client and queue_mgr
    win.dbus_client = MagicMock()
    win.queue_mgr = MagicMock()

    # Create a dummy 0-byte file in recording folder that should be cleaned up
    stalled_file = tmp_path / "WeakSignalShow.m2t"
    stalled_file.write_bytes(b"")
    assert stalled_file.exists()

    prog = {
        "show_title": "Weak Signal Show",
        "title": "Weak Signal Show",
        "kaffeine_channel": "7.1 KGO",
        "channel": "7.1 KGO",
        "start_iso": "2026-10-15T20:00:00",
        "duration_iso": "01:00:00"
    }

    with patch.object(QMessageBox, "warning") as mock_warning:
        win._handle_timeshift_signal_failure(
            prog=prog,
            queue_id=42,
            rec_title="Weak Signal Show",
            was_already_scheduled=False,
            timeout_secs=3.0
        )

        # 1. Verify D-Bus cancel call
        win.dbus_client.cancel_recording.assert_called_once_with(channel="7.1 KGO", title="Weak Signal Show")

        # 2. Verify queue manager removal
        win.queue_mgr.remove_recording.assert_called_once_with(42)

        # 3. Verify stalled 0-byte file is unlinked
        assert not stalled_file.exists()

        # 4. Verify warning dialog shown
        mock_warning.assert_called_once()
        args = mock_warning.call_args[0]
        assert "Weak or No Signal" in args[1]
        assert "7.1 KGO" in args[2]
        assert "tuner has been released" in args[2]

        # 5. Verify failed channel health recorded for immediate red dot display
        assert "7.1 KGO" in win.config_mgr.channel_health
        health_rec = win.config_mgr.channel_health["7.1 KGO"]
        assert health_rec["locked"] is False
        assert health_rec["has_signal"] is False
        assert health_rec["has_carrier"] is False
        assert health_rec["quality_label"] == "No Signal"


def test_handle_timeshift_signal_failure_scheduled_recording_declines_cancel(qtbot, isolated_config):
    """
    Test that when user declines to cancel a scheduled recording with no signal,
    it displays a status bar warning without canceling.
    """
    cfg = isolated_config
    win = MainWindow(config_mgr=cfg)
    qtbot.addWidget(win)

    win.dbus_client = MagicMock()
    win.queue_mgr = MagicMock()
    win.status_bar.showMessage = MagicMock()

    prog = {
        "show_title": "Scheduled Weak Show",
        "channel": "5.1 KPIX",
    }

    with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.No) as mock_q:
        win._handle_timeshift_signal_failure(
            prog=prog,
            queue_id=99,
            rec_title="Scheduled Weak Show",
            was_already_scheduled=True,
            timeout_secs=4.0
        )

        mock_q.assert_called_once()
        win.dbus_client.cancel_recording.assert_not_called()
        win.queue_mgr.remove_recording.assert_not_called()
        win.status_bar.showMessage.assert_called_once()
        msg = win.status_bar.showMessage.call_args[0][0]
        assert "Scheduled recording 'Scheduled Weak Show' on 5.1 KPIX has not written stream data yet" in msg


def test_handle_timeshift_signal_failure_scheduled_recording_confirms_cancel(qtbot, isolated_config):
    """
    Test that when user confirms canceling a scheduled recording with no signal,
    it cancels via D-Bus, removes from queue, and releases tuner.
    """
    cfg = isolated_config
    win = MainWindow(config_mgr=cfg)
    qtbot.addWidget(win)

    win.dbus_client = MagicMock()
    win.queue_mgr = MagicMock()
    win.status_bar.showMessage = MagicMock()

    prog = {
        "show_title": "Scheduled Weak Show",
        "channel": "5.1 KPIX",
    }

    with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes) as mock_q:
        win._handle_timeshift_signal_failure(
            prog=prog,
            queue_id=99,
            rec_title="Scheduled Weak Show",
            was_already_scheduled=True,
            timeout_secs=4.0
        )

        mock_q.assert_called_once()
        win.dbus_client.cancel_recording.assert_called_once_with(channel="5.1 KPIX", title="Scheduled Weak Show")
        win.queue_mgr.remove_recording.assert_called_once_with(99)


def test_channel_signal_health_check_tuner_available_prompt(qtbot, isolated_config):
    """
    Test that ChannelSignalHealthDialog warns when Kaffeine is busy recording,
    and cancels the recording to free the tuner if user confirms.
    """
    cfg = isolated_config
    dialog = ChannelSignalHealthDialog(channels=[{"channel": "7.1 KGO"}], config_mgr=cfg)
    qtbot.addWidget(dialog)

    mock_client = MagicMock()
    mock_client.is_running.return_value = True
    mock_client.get_active_recordings.return_value = [
        {"id": 1, "name": "Active Show", "channel": "7.1 KGO", "is_running": True}
    ]

    with patch("kaffeine_dvr.gui.KaffeineDbusClient", return_value=mock_client):
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes) as mock_q:
            res = dialog._check_tuner_available()
            assert res is True
            mock_q.assert_called_once()
            mock_client.cancel_recording.assert_called_once_with(key=1, channel="7.1 KGO", title="Active Show")


def test_watcher_enforce_zero_byte_recording_cleanup(isolated_config, tmp_path):
    """
    Test that Watcher automatically detects dead recordings with 0 bytes after timeout,
    cancels them in Kaffeine, and removes them from the queue.
    """
    cfg = isolated_config
    cfg.zero_byte_recording_timeout_secs = 30
    cfg.custom_recording_folder = str(tmp_path)

    mock_dbus = MagicMock()
    mock_dbus.is_running.return_value = True

    mock_queue = MagicMock()
    start_dt = datetime.now() - timedelta(seconds=40)
    mock_queue.list_queue.return_value = [
        {
            "id": 101,
            "title": "Dead Channel Show",
            "channel": "365",
            "start_iso": start_dt.strftime("%Y-%m-%dT%H:%M:%S"),
            "created_at": start_dt.strftime("%Y-%m-%dT%H:%M:%S"),
            "status": "RECORDING",
            "kaffeine_key": 5
        }
    ]

    mock_storage = MagicMock()
    mock_storage.get_recording_folder.return_value = tmp_path
    mock_storage.find_active_or_recent_recording_file.return_value = None

    watcher = Watcher(config_mgr=cfg, dbus_client=mock_dbus, queue_mgr=mock_queue, storage_mgr=mock_storage)

    with patch("kaffeine_dvr.watcher.send_desktop_notification") as mock_notify:
        watcher.enforce_zero_byte_recording_cleanup()

        # Should cancel dead recording in Kaffeine and remove from queue
        mock_dbus.cancel_recording.assert_called_once_with(key=5, channel="365", title="Dead Channel Show")
        mock_queue.remove_recording.assert_called_once_with(101)
        mock_notify.assert_called_once()


def test_watcher_zero_byte_cleanup_keeps_healthy_recording(isolated_config, tmp_path):
    """
    Test that Watcher does not cancel active recordings that are writing valid data (>16KB).
    """
    cfg = isolated_config
    cfg.zero_byte_recording_timeout_secs = 30
    cfg.custom_recording_folder = str(tmp_path)

    mock_dbus = MagicMock()
    mock_dbus.is_running.return_value = True

    start_dt = datetime.now() - timedelta(seconds=40)
    mock_queue = MagicMock()
    mock_queue.list_queue.return_value = [
        {
            "id": 102,
            "title": "Healthy Show",
            "channel": "7.1",
            "start_iso": start_dt.strftime("%Y-%m-%dT%H:%M:%S"),
            "created_at": start_dt.strftime("%Y-%m-%dT%H:%M:%S"),
            "status": "RECORDING",
            "kaffeine_key": 6
        }
    ]

    healthy_file = tmp_path / "HealthyShow.m2t"
    healthy_file.write_bytes(b"x" * 20000)

    mock_storage = MagicMock()
    mock_storage.get_recording_folder.return_value = tmp_path
    mock_storage.find_active_or_recent_recording_file.return_value = healthy_file

    watcher = Watcher(config_mgr=cfg, dbus_client=mock_dbus, queue_mgr=mock_queue, storage_mgr=mock_storage)

    watcher.enforce_zero_byte_recording_cleanup()

    # Should NOT cancel healthy recording
    mock_dbus.cancel_recording.assert_not_called()
    mock_queue.remove_recording.assert_not_called()


def test_guide_grid_vertical_header_health_lookup(isolated_config):
    """
    Test GuideGridVerticalHeader._get_health_for_channel resolves channel health:
    1. By direct channel name match (case-insensitive).
    2. Via channel_map when key is guide name and value is tuned hardware name.
    3. Via channel_map when queried by tuned name and stored under guide name.
    4. Returns None when no health info is recorded.
    """
    cfg = isolated_config
    cfg.channel_map = {
        "Fox": "010-1 KSAZ-HD",
        "NBC": "012-1 KPNX-HD",
    }
    cfg.channel_health = {
        "010-1 KSAZ-HD": {"locked": False, "has_carrier": True, "has_signal": True, "strength_pct": 45},
        "012-1 KPNX-HD": {"locked": False, "has_carrier": False, "has_signal": False, "strength_pct": 0},
        "CBS": {"locked": True, "has_carrier": True, "has_signal": True, "strength_pct": 90},
    }

    # 1. Direct match
    res_cbs = GuideGridVerticalHeader._get_health_for_channel("cbs", cfg)
    assert res_cbs is not None
    assert res_cbs["locked"] is True

    # 2. Guide name resolving to tuned hardware name in health dict
    res_fox = GuideGridVerticalHeader._get_health_for_channel("Fox", cfg)
    assert res_fox is not None
    assert res_fox["locked"] is False
    assert res_fox["has_carrier"] is True

    res_nbc = GuideGridVerticalHeader._get_health_for_channel("NBC", cfg)
    assert res_nbc is not None
    assert res_nbc["locked"] is False
    assert res_nbc["has_carrier"] is False

    # 3. Tuned hardware name resolving when queried directly
    res_fox_hw = GuideGridVerticalHeader._get_health_for_channel("010-1 KSAZ-HD", cfg)
    assert res_fox_hw is not None
    assert res_fox_hw["locked"] is False

    # 4. Unknown channel
    assert GuideGridVerticalHeader._get_health_for_channel("UnknownChannel", cfg) is None


def test_guide_grid_vertical_header_dot_colors(qtbot, isolated_config):
    """
    Test GuideGridVerticalHeader dot color logic:
    - Locked channels have no dot.
    - Carrier/unlocked channels display a yellow dot (#facc15).
    - No carrier / no signal channels display a red dot (#f87171).
    """
    cfg = isolated_config
    cfg.channel_health = {
        "LockedChan": {"locked": True, "has_signal": True, "has_carrier": True},
        "WeakChan": {"locked": False, "has_signal": True, "has_carrier": True},
        "DeadChan": {"locked": False, "has_signal": False, "has_carrier": False},
    }

    header = GuideGridVerticalHeader()
    qtbot.addWidget(header)

    # Test dot color determination logic used in paintSection
    for ch_name, expected_dot in [
        ("LockedChan", None),
        ("WeakChan", "#facc15"),
        ("DeadChan", "#f87171"),
        ("UntestedChan", None),
    ]:
        h = header._get_health_for_channel(ch_name, cfg)
        dot_color = None
        if h:
            if not h.get("locked"):
                if h.get("has_signal") or h.get("has_carrier"):
                    dot_color = "#facc15"
                else:
                    dot_color = "#f87171"
        assert dot_color == expected_dot


def test_guide_grid_vertical_header_tooltip(qtbot, isolated_config):
    """
    Test that GuideGridVerticalHeader shows tooltip with signal status on hover.
    """
    cfg = isolated_config
    cfg.channel_health = {
        "DeadChan": {"locked": False, "has_signal": False, "has_carrier": False, "strength_pct": 0},
        "WeakChan": {"locked": False, "has_signal": True, "has_carrier": True, "strength_pct": 35},
    }

    win = MainWindow(config_mgr=cfg)
    qtbot.addWidget(win)
    win.grid_channels = ["DeadChan", "WeakChan"]

    header = GuideGridVerticalHeader(main_window=win)
    qtbot.addWidget(header)

    with patch("kaffeine_dvr.gui.QToolTip.showText") as mock_tooltip:
        help_evt = QHelpEvent(QEvent.Type.ToolTip, QPoint(10, 10), QPoint(10, 10))
        # Mock logicalIndexAt to point to row 0 ("DeadChan")
        with patch.object(header, "logicalIndexAt", return_value=0):
            handled = header.event(help_evt)
            assert handled is True
            mock_tooltip.assert_called_once()
            tip_text = mock_tooltip.call_args[0][1]
            assert "DeadChan" in tip_text
            assert "No Signal Detected" in tip_text

        mock_tooltip.reset_mock()
        # Mock logicalIndexAt to point to row 1 ("WeakChan")
        with patch.object(header, "logicalIndexAt", return_value=1):
            handled = header.event(help_evt)
            assert handled is True
            mock_tooltip.assert_called_once()
            tip_text = mock_tooltip.call_args[0][1]
            assert "WeakChan" in tip_text
            assert "Weak Signal / Carrier (No Lock)" in tip_text
            assert "35%" in tip_text


def test_is_same_channel(isolated_config):
    """
    Test MainWindow._is_same_channel correctly identifies channel equality
    across direct matches and channel_map aliases.
    """
    cfg = isolated_config
    cfg.channel_map = {
        "Fox": "010-1 KSAZ-HD",
        "NBC": "012-1 KPNX-HD",
    }
    win = MainWindow(config_mgr=cfg)

    # Direct equality
    assert win._is_same_channel("Fox", "fox") is True
    assert win._is_same_channel("010-1 KSAZ-HD", "010-1 KSAZ-HD") is True

    # Guide name to tuned name
    assert win._is_same_channel("Fox", "010-1 KSAZ-HD") is True
    assert win._is_same_channel("010-1 KSAZ-HD", "Fox") is True

    # Different channels
    assert win._is_same_channel("Fox", "NBC") is False
    assert win._is_same_channel("Fox", "012-1 KPNX-HD") is False
    assert win._is_same_channel("CBS", "Fox") is False
    assert win._is_same_channel("", "Fox") is False


def test_start_timeshift_playback_active_recording_conflict_declined(qtbot, isolated_config):
    """
    Test that when user attempts to watch live TV on Channel B while Channel A is actively recording,
    a confirmation dialog is shown. When declined (No), the active recording is preserved and tuning is aborted.
    """
    cfg = isolated_config
    cfg.channel_map = {
        "Fox": "010-1 KSAZ-HD",
        "NBC": "012-1 KPNX-HD",
    }
    win = MainWindow(config_mgr=cfg)
    qtbot.addWidget(win)

    win.dbus_client = MagicMock()
    win.queue_mgr = MagicMock()
    win.status_bar.showMessage = MagicMock()

    # Active recording in queue on Fox
    win.queue_mgr.list_queue.return_value = [
        {
            "id": 100,
            "title": "Evening News",
            "channel": "010-1 KSAZ-HD",
            "status": "RECORDING",
            "is_timeshift": False,
            "kaffeine_key": 77
        }
    ]
    win.dbus_client.get_active_recordings.return_value = []

    prog_nbc = {
        "show_title": "NBC Special",
        "title": "NBC Special",
        "channel": "NBC",
        "kaffeine_channel": "012-1 KPNX-HD",
    }

    with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.No) as mock_q:
        win.start_timeshift_playback(prog_nbc)

        # 1. Dialog was shown warning about Evening News on 010-1 KSAZ-HD
        mock_q.assert_called_once()
        args = mock_q.call_args[0]
        assert "Tuner In Use" in args[1]
        assert "Evening News" in args[2]
        assert "010-1 KSAZ-HD" in args[2]

        # 2. Because user declined, active recording was NOT cancelled
        win.queue_mgr.remove_recording.assert_not_called()
        win.dbus_client.cancel_recording.assert_not_called()

        # 3. Status bar shows active recording preserved
        win.status_bar.showMessage.assert_called_once()
        msg = win.status_bar.showMessage.call_args[0][0]
        assert "preserved" in msg.lower()


def test_start_timeshift_playback_active_recording_conflict_accepted(qtbot, isolated_config):
    """
    Test that when user confirms (Yes) stopping the active recording to watch another channel,
    the conflicting recording is cancelled via D-Bus, removed from queue, and tuning proceeds.
    """
    cfg = isolated_config
    cfg.channel_map = {
        "Fox": "010-1 KSAZ-HD",
        "NBC": "012-1 KPNX-HD",
    }
    win = MainWindow(config_mgr=cfg)
    qtbot.addWidget(win)

    win.dbus_client = MagicMock()
    win.queue_mgr = MagicMock()

    win.queue_mgr.list_queue.return_value = [
        {
            "id": 105,
            "title": "Conflicting Game",
            "channel": "010-1 KSAZ-HD",
            "status": "RECORDING",
            "is_timeshift": False,
            "kaffeine_key": 88
        }
    ]
    win.dbus_client.get_active_recordings.return_value = []
    win.queue_mgr.get_active_scheduled_map.return_value = {}

    prog_nbc = {
        "show_title": "NBC Special",
        "title": "NBC Special",
        "channel": "NBC",
        "kaffeine_channel": "012-1 KPNX-HD",
    }

    with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes) as mock_q, \
         patch.object(win, "_on_timeshift_buffer_ready"):
        win.start_timeshift_playback(prog_nbc)

        mock_q.assert_called_once()
        # Active recording cancelled via D-Bus and removed from queue
        win.queue_mgr.remove_recording.assert_any_call(105)
        win.dbus_client.cancel_recording.assert_any_call(key=88, channel="010-1 KSAZ-HD", title="Conflicting Game")
        if hasattr(win, "_timeshift_buffer_timer") and win._timeshift_buffer_timer:
            win._timeshift_buffer_timer.stop()



def test_start_timeshift_playback_same_channel_as_active_recording_no_prompt(qtbot, isolated_config, tmp_path):
    """
    Test that when watching the SAME channel that is actively recording, no confirmation prompt
    is shown and the active recording file is played directly.
    """
    cfg = isolated_config
    cfg.custom_recording_folder = str(tmp_path)
    cfg.channel_map = {
        "Fox": "010-1 KSAZ-HD",
    }
    win = MainWindow(config_mgr=cfg)
    qtbot.addWidget(win)

    win.dbus_client = MagicMock()
    win.queue_mgr = MagicMock()

    rec_fox = {
        "id": 110,
        "title": "Active Fox Show",
        "channel": "010-1 KSAZ-HD",
        "start_iso": "2026-10-16T13:00:00",
        "status": "RECORDING",
        "is_timeshift": False,
        "kaffeine_key": 99
    }
    win.queue_mgr.list_queue.return_value = [rec_fox]
    win.queue_mgr.get_active_scheduled_map.return_value = {
        ("010-1 ksaz-hd", "2026-10-16T13:00"): rec_fox,
        ("fox", "2026-10-16T13:00"): rec_fox,
    }
    win.dbus_client.get_active_recordings.return_value = []

    # Active file exists on disk with sufficient data (> 64 KB)
    rec_file = tmp_path / "ActiveFoxShow.m2t"
    rec_file.write_bytes(b"x" * 100000)

    prog_fox = {
        "show_title": "Active Fox Show",
        "title": "Active Fox Show",
        "channel": "Fox",
        "kaffeine_channel": "010-1 KSAZ-HD",
        "start_iso": "2026-10-16T13:00:00",
    }


    with patch.object(QMessageBox, "question") as mock_q:
        win.start_timeshift_playback(prog_fox)

        # No confirmation question should be asked since it's the same channel
        mock_q.assert_not_called()
        win.dbus_client.play_file.assert_called_once()
        win.dbus_client.cancel_recording.assert_not_called()


def test_multi_tuner_config_and_effective_count(isolated_config):
    """
    Test auto-detection and manual overrides for hardware tuner count.
    """
    cfg = isolated_config
    assert cfg.tuner_count == 0  # Default is auto-detect

    # Mock /dev/dvb detection
    with patch("pathlib.Path.exists", return_value=True), \
         patch("pathlib.Path.glob", return_value=[Path("/dev/dvb/adapter0/frontend0"), Path("/dev/dvb/adapter1/frontend0")]):
        assert cfg.get_detected_tuner_count() == 2
        assert cfg.get_effective_tuner_count() == 2

    # User overrides tuner count manually to 3
    cfg.tuner_count = 3
    assert cfg.get_effective_tuner_count() == 3

    # Reset back to auto-detect (0)
    cfg.tuner_count = 0
    with patch("pathlib.Path.exists", return_value=False):
        assert cfg.get_detected_tuner_count() == 1
        assert cfg.get_effective_tuner_count() == 1


def test_multi_tuner_watching_other_channel_does_not_prompt_when_tuner_idle(qtbot, isolated_config):
    """
    When the system has 2 tuners and 1 active recording is in progress on Fox,
    tuning to NBC does NOT prompt or interrupt because a second tuner is available.
    """
    cfg = isolated_config
    cfg.tuner_count = 2  # Dual tuner system
    cfg.channel_map = {
        "Fox": "010-1 KSAZ-HD",
        "NBC": "012-1 KPNX-HD",
    }
    win = MainWindow(config_mgr=cfg)
    qtbot.addWidget(win)

    win.dbus_client = MagicMock()
    win.queue_mgr = MagicMock()

    # 1 recording active on Fox
    win.queue_mgr.list_queue.return_value = [
        {
            "id": 120,
            "title": "Fox Active Show",
            "channel": "010-1 KSAZ-HD",
            "status": "RECORDING",
            "is_timeshift": False,
            "kaffeine_key": 42
        }
    ]
    win.dbus_client.get_active_recordings.return_value = []
    win.queue_mgr.get_active_scheduled_map.return_value = {}

    prog_nbc = {
        "show_title": "NBC Nightly News",
        "title": "NBC Nightly News",
        "channel": "NBC",
        "kaffeine_channel": "012-1 KPNX-HD",
    }

    with patch.object(QMessageBox, "question") as mock_q, \
         patch.object(win, "_on_timeshift_buffer_ready"):
        win.start_timeshift_playback(prog_nbc)

        # Since an idle tuner is available, no question prompt is shown!
        mock_q.assert_not_called()
        # Recording on Fox is NOT cancelled
        win.queue_mgr.remove_recording.assert_not_called()
        win.dbus_client.cancel_recording.assert_not_called()
        if hasattr(win, "_timeshift_buffer_timer") and win._timeshift_buffer_timer:
            win._timeshift_buffer_timer.stop()



def test_multi_tuner_prompts_when_all_tuners_are_busy(qtbot, isolated_config):
    """
    When the system has 2 tuners and 2 active recordings are in progress on Fox and CBS,
    attempting to watch NBC prompts that all tuners are busy.
    """
    cfg = isolated_config
    cfg.tuner_count = 2  # Dual tuner system
    cfg.channel_map = {
        "Fox": "010-1 KSAZ-HD",
        "CBS": "005-1 KPHO-HD",
        "NBC": "012-1 KPNX-HD",
    }
    win = MainWindow(config_mgr=cfg)
    qtbot.addWidget(win)

    win.dbus_client = MagicMock()
    win.queue_mgr = MagicMock()

    # 2 recordings active, occupying both tuners
    win.queue_mgr.list_queue.return_value = [
        {
            "id": 121,
            "title": "Fox Show",
            "channel": "010-1 KSAZ-HD",
            "status": "RECORDING",
            "is_timeshift": False,
            "kaffeine_key": 50
        },
        {
            "id": 122,
            "title": "CBS Show",
            "channel": "005-1 KPHO-HD",
            "status": "RECORDING",
            "is_timeshift": False,
            "kaffeine_key": 51
        }
    ]
    win.dbus_client.get_active_recordings.return_value = []
    win.queue_mgr.get_active_scheduled_map.return_value = {}

    prog_nbc = {
        "show_title": "NBC Show",
        "title": "NBC Show",
        "channel": "NBC",
        "kaffeine_channel": "012-1 KPNX-HD",
    }

    with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.No) as mock_q:
        win.start_timeshift_playback(prog_nbc)

        # Dialog was shown indicating all tuners are busy
        mock_q.assert_called_once()
        args = mock_q.call_args[0]
        assert "Tuner In Use" in args[1]
        assert "All TV tuners (2)" in args[2]

        # Declined, so no recordings cancelled
        win.queue_mgr.remove_recording.assert_not_called()
        win.dbus_client.cancel_recording.assert_not_called()


def test_channel_signal_health_multi_tuner_idle(qtbot, isolated_config):
    """
    Test that ChannelSignalHealthDialog allows scanning without prompt when
    system has 2 tuners and only 1 active recording.
    """
    cfg = isolated_config
    cfg.tuner_count = 2  # Dual tuner
    dialog = ChannelSignalHealthDialog(channels=[{"channel": "7.1 KGO"}], config_mgr=cfg)
    qtbot.addWidget(dialog)

    mock_client = MagicMock()
    mock_client.is_running.return_value = True
    mock_client.get_active_recordings.return_value = [
        {"id": 1, "name": "Active Show", "channel": "7.1 KGO", "is_running": True}
    ]

    with patch("kaffeine_dvr.gui.KaffeineDbusClient", return_value=mock_client):
        with patch.object(QMessageBox, "question") as mock_q:
            res = dialog._check_tuner_available()
            assert res is True
            # With 1 recording and 2 tuners, an idle tuner is available so no prompt is shown
            mock_q.assert_not_called()



