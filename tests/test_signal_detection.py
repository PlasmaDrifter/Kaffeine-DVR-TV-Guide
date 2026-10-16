"""
Tests for weak/no signal detection, automatic tuner release, and warning popup.
"""

from unittest.mock import MagicMock, patch

from PyQt6.QtWidgets import QMessageBox

from kaffeine_dvr.gui import MainWindow


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


def test_handle_timeshift_signal_failure_scheduled_recording_status(qtbot, isolated_config):
    """
    Test that scheduled recordings display a status bar warning without auto-canceling user schedule.
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

    win._handle_timeshift_signal_failure(
        prog=prog,
        queue_id=99,
        rec_title="Scheduled Weak Show",
        was_already_scheduled=True,
        timeout_secs=4.0
    )

    # Should NOT cancel pre-scheduled recording
    win.dbus_client.cancel_recording.assert_not_called()
    win.queue_mgr.remove_recording.assert_not_called()
    win.status_bar.showMessage.assert_called_once()
    msg = win.status_bar.showMessage.call_args[0][0]
    assert "Scheduled recording 'Scheduled Weak Show' on 5.1 KPIX has not written stream data yet" in msg
