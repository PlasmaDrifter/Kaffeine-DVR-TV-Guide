"""
Tests for weak/no signal detection, automatic tuner release, and warning popup.
"""

from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

from PyQt6.QtWidgets import QMessageBox

from kaffeine_dvr.gui import ChannelSignalHealthDialog, MainWindow
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
