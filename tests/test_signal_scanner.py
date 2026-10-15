import os
import struct
from unittest.mock import MagicMock, patch
import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QFrame

from kaffeine_dvr.signal_scanner import (
    DvbSignalReader,
    ChannelSignalScanWorker,
    FE_HAS_SIGNAL,
    FE_HAS_CARRIER,
    FE_HAS_VITERBI,
    FE_HAS_SYNC,
    FE_HAS_LOCK,
    FE_READ_STATUS,
    FE_READ_SIGNAL_STRENGTH,
    FE_READ_SNR,
    FE_READ_BER,
)
from kaffeine_dvr.gui import ChannelSignalHealthDialog


def test_dvb_signal_reader_no_device():
    with patch.object(DvbSignalReader, "find_frontend_device", return_value=None):
        metrics = DvbSignalReader.read_metrics()
        assert metrics["available"] is False
        assert metrics["locked"] is False
        assert metrics["quality_label"] == "No Device"


def test_dvb_signal_reader_permission_denied():
    with patch.object(DvbSignalReader, "find_frontend_device", return_value="/dev/dvb/adapter0/frontend0"), \
         patch("os.path.exists", return_value=True), \
         patch("os.open", side_effect=PermissionError("Permission denied")):
        metrics = DvbSignalReader.read_metrics()
        assert metrics["available"] is False
        assert "Permission denied" in metrics["error"]
        assert metrics["quality_label"] == "Permission Denied"


def test_dvb_signal_reader_locked_excellent():
    def mock_ioctl(fd, request, arg):
        if request == FE_READ_STATUS:
            # 0x1F = SIGNAL | CARRIER | VITERBI | SYNC | LOCK
            status_val = FE_HAS_SIGNAL | FE_HAS_CARRIER | FE_HAS_VITERBI | FE_HAS_SYNC | FE_HAS_LOCK
            arg[:] = struct.pack("I", status_val)
        elif request == FE_READ_SIGNAL_STRENGTH:
            # 45874 / 65535 = 70.0%
            arg[:] = (45874).to_bytes(2, "little")
        elif request == FE_READ_SNR:
            # 260 -> 26.0 dB
            arg[:] = (260).to_bytes(2, "little")
        elif request == FE_READ_BER:
            arg[:] = struct.pack("I", 0)

    with patch.object(DvbSignalReader, "find_frontend_device", return_value="/dev/dvb/adapter0/frontend0"), \
         patch("os.path.exists", return_value=True), \
         patch("os.open", return_value=99), \
         patch("os.close"), \
         patch("fcntl.ioctl", side_effect=mock_ioctl):
        metrics = DvbSignalReader.read_metrics()
        assert metrics["available"] is True
        assert metrics["locked"] is True
        assert metrics["has_signal"] is True
        assert metrics["has_carrier"] is True
        assert metrics["strength_pct"] == 70.0
        assert metrics["snr_db"] == 26.0
        assert metrics["quality_label"] == "Excellent"


def test_dvb_signal_reader_carrier_no_lock():
    def mock_ioctl(fd, request, arg):
        if request == FE_READ_STATUS:
            status_val = FE_HAS_SIGNAL | FE_HAS_CARRIER
            arg[:] = struct.pack("I", status_val)
        elif request == FE_READ_SIGNAL_STRENGTH:
            arg[:] = (10000).to_bytes(2, "little")
        elif request == FE_READ_SNR:
            arg[:] = (50).to_bytes(2, "little")
        elif request == FE_READ_BER:
            arg[:] = struct.pack("I", 0)

    with patch.object(DvbSignalReader, "find_frontend_device", return_value="/dev/dvb/adapter0/frontend0"), \
         patch("os.path.exists", return_value=True), \
         patch("os.open", return_value=99), \
         patch("os.close"), \
         patch("fcntl.ioctl", side_effect=mock_ioctl):
        metrics = DvbSignalReader.read_metrics()
        assert metrics["available"] is True
        assert metrics["locked"] is False
        assert metrics["has_signal"] is True
        assert metrics["quality_label"] == "Weak (No Lock)"


def test_channel_signal_scan_worker(qtbot):
    channels = [
        {"name": "2.1 KATU", "number": "2.1", "transponder": "533000000"},
        {"name": "6.1 KOIN", "number": "6.1", "transponder": "569000000"}
    ]

    mock_metrics = {
        "available": True,
        "locked": True,
        "has_signal": True,
        "has_carrier": True,
        "strength_pct": 65.0,
        "snr_db": 24.5,
        "ber": 0,
        "quality_label": "Excellent",
    }

    mock_dbus = MagicMock()
    mock_bus = MagicMock()
    mock_dbus.SessionBus.return_value = mock_bus
    mock_tv_iface = MagicMock()
    mock_player_iface = MagicMock()
    mock_bus.get_object.return_value = MagicMock()
    mock_dbus.Interface.side_effect = [mock_tv_iface, mock_player_iface]

    with patch.dict("sys.modules", {"dbus": mock_dbus}), \
         patch.object(DvbSignalReader, "read_metrics", return_value=mock_metrics):
        worker = ChannelSignalScanWorker(channels, lock_timeout_sec=0.2)

        started_events = []
        result_events = []
        progress_events = []
        finished_events = []

        worker.channel_started.connect(lambda name, cur, tot: started_events.append((name, cur, tot)))
        worker.channel_result.connect(lambda name, res: result_events.append((name, res)))
        worker.scan_progress.connect(lambda cur, tot: progress_events.append((cur, tot)))
        worker.scan_finished.connect(lambda all_res: finished_events.append(all_res))

        worker.start()
        qtbot.waitUntil(lambda: len(finished_events) > 0, timeout=5000)

        assert len(started_events) == 2
        assert len(result_events) == 2
        assert started_events[0][0] == "2.1 KATU"
        assert started_events[1][0] == "6.1 KOIN"
        assert result_events[0][1]["locked"] is True
        assert result_events[0][1]["quality_label"] == "Excellent"

        # Verify Kaffeine PlayChannel was called for each channel
        assert mock_tv_iface.PlayChannel.call_count == 2
        # Verify Kaffeine Player.Stop was called at conclusion
        assert mock_player_iface.Stop.call_count >= 1


def test_channel_signal_scan_worker_abort(qtbot):
    channels = [
        {"name": f"Channel {i}", "number": f"{i}.1"}
        for i in range(1, 10)
    ]

    mock_metrics = {
        "available": True,
        "locked": False,
        "has_signal": False,
        "has_carrier": False,
        "strength_pct": 0.0,
        "snr_db": 0.0,
        "ber": 0,
        "quality_label": "No Signal",
    }

    mock_dbus = MagicMock()
    mock_bus = MagicMock()
    mock_dbus.SessionBus.return_value = mock_bus
    mock_dbus.Interface.return_value = MagicMock()

    with patch.dict("sys.modules", {"dbus": mock_dbus}), \
         patch.object(DvbSignalReader, "read_metrics", return_value=mock_metrics):
        worker = ChannelSignalScanWorker(channels, lock_timeout_sec=0.3)
        finished_events = []
        worker.scan_finished.connect(lambda res: finished_events.append(res))

        worker.start()
        # Request abort immediately
        worker.request_stop()
        qtbot.waitUntil(lambda: len(finished_events) > 0, timeout=3000)

        assert len(finished_events) == 1
        # Should have stopped well before processing all 9 channels
        assert len(finished_events[0]) < 9


def test_channel_signal_health_dialog(qtbot, isolated_config):
    channels = [
        {"id": 1, "name": "2.1 KATU", "number": "2.1", "transponder": "533000000"},
        {"id": 2, "name": "6.1 KOIN", "number": "6.1", "transponder": "569000000"}
    ]

    mock_dbus = MagicMock()
    mock_player_iface = MagicMock()
    mock_dbus.SessionBus.return_value.get_object.return_value = MagicMock()
    mock_dbus.Interface.return_value = mock_player_iface

    with patch.dict("sys.modules", {"dbus": mock_dbus}):
        dlg = ChannelSignalHealthDialog(channels, config_mgr=isolated_config)
        qtbot.addWidget(dlg)

        # Verify explanation box exists
        explainer = dlg.findChild(QFrame, "signalExplainerBox")
        assert explainer is not None

        assert dlg.table.rowCount() == 2
        assert dlg.table.item(0, 0).text() == "2.1 KATU"
        assert dlg.table.item(0, 1).text() == "2.1"
        assert dlg.table.item(1, 0).text() == "6.1 KOIN"
        assert dlg.table.item(1, 1).text() == "6.1"

        # Simulate channel result update
        dlg._on_channel_result("2.1 KATU", {
            "locked": True,
            "has_signal": True,
            "strength_pct": 58.4,
            "snr_db": 23.2,
            "quality_label": "Good"
        })

        assert dlg.table.item(0, 3).text() == "Locked"
        assert "lock" in dlg.table.item(0, 3).toolTip().lower()
        assert "58.4%" in dlg.table.item(0, 4).text()
        assert "23.2 dB" in dlg.table.item(0, 5).text()

        # Check config persisted health
        assert isolated_config.channel_health["2.1 KATU"]["locked"] is True

        # Close dialog and verify cleanup stops playback
        dlg.close()
        assert mock_player_iface.Stop.called


def test_channel_order_signal_icons_and_badge(qtbot, isolated_config):
    from kaffeine_dvr.gui import MainWindow, make_status_dot_icon

    # Test make_status_dot_icon
    icon = make_status_dot_icon("#4ade80", size=14)
    assert not icon.isNull()

    isolated_config.channel_map = {
        "ABC": "2.1 KATU",
        "NBC": "6.1 KOIN",
        "CBS": "8.1 KGW",
        "FOX": "12.1 KPTV"
    }
    isolated_config.channel_order = ["ABC", "NBC", "CBS", "FOX"]
    isolated_config.channel_health = {
        "2.1 KATU": {"locked": True, "strength_pct": 65.0, "snr_db": 22.0, "quality_label": "Good"},
        "6.1 KOIN": {"locked": False, "has_carrier": True, "strength_pct": 30.0},
        "8.1 KGW": {"locked": False, "has_signal": False},
        # 12.1 KPTV left untested
    }

    win = MainWindow(config_mgr=isolated_config)
    qtbot.addWidget(win)

    win.refresh_channel_order_list()
    assert win.channel_order_list.count() == 4

    item_abc = win.channel_order_list.item(0)
    assert not item_abc.icon().isNull()
    assert "Locked" in item_abc.toolTip()

    item_nbc = win.channel_order_list.item(1)
    assert not item_nbc.icon().isNull()
    assert "Carrier" in item_nbc.toolTip()

    item_cbs = win.channel_order_list.item(2)
    assert not item_cbs.icon().isNull()
    assert "No Signal" in item_cbs.toolTip()

    item_fox = win.channel_order_list.item(3)
    assert not item_fox.icon().isNull()
    assert "Untested" in item_fox.toolTip()

    # Check summary badge
    badge_text = win.channel_health_badge.text()
    assert "1 Locked" in badge_text
    assert "1 Weak" in badge_text
    assert "1 No Signal" in badge_text

    # Check mapping text has colored dots
    mapping_html = win.mapping_text.toHtml()
    assert "#4ade80" in mapping_html  # Green dot for KATU
    assert "#facc15" in mapping_html  # Yellow dot for KOIN
    assert "#f87171" in mapping_html  # Red dot for KGW
    assert "#64748b" in mapping_html  # Slate dot for KPTV

    # Test saving channel mapping with dots strips them cleanly
    with patch("PyQt6.QtWidgets.QMessageBox.information"):
        win.save_channel_mapping()
    assert isolated_config.channel_map["ABC"] == "2.1 KATU"
    assert isolated_config.channel_map["NBC"] == "6.1 KOIN"

    win.close()

