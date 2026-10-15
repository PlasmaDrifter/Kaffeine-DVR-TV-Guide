from PyQt6.QtCore import QEvent, Qt

from kaffeine_dvr.gui import MainWindow


def test_custom_title_bar_widgets(qtbot, isolated_config):
    win = MainWindow(config_mgr=isolated_config)
    qtbot.addWidget(win)
    title_bar = win.custom_title_bar

    # Verify elements exist
    assert title_bar.title_lbl.text() == "Kaffeine DVR & TV Guide"
    assert title_bar.min_btn is not None
    assert title_bar.max_btn is not None
    assert title_bar.close_btn is not None

    # Verify clock is on tabs corner
    assert win.clock_widget is not None
    assert win.clock_label is not None
    assert not win.clock_widget.isHidden()

    # Verify maximize button icon reflects initial state
    assert title_bar.max_btn.text() == "▢"
    assert title_bar.max_btn.toolTip() == "Maximize"

    # Verify toggle maximize/restore updates button and frame styling
    title_bar._toggle_maximize_restore()
    assert win.isMaximized()
    assert title_bar.max_btn.text() == "❐"
    assert title_bar.max_btn.toolTip() == "Restore"
    assert win.centralWidget().property("frameless_rounded") == "false"

    title_bar._toggle_maximize_restore()
    assert not win.isMaximized()
    assert title_bar.max_btn.text() == "▢"
    assert title_bar.max_btn.toolTip() == "Maximize"
    assert win.centralWidget().property("frameless_rounded") == "true"


def test_custom_title_bar_config_toggle(qtbot, isolated_config):
    cfg = isolated_config
    assert cfg.use_custom_title_bar is True

    win = MainWindow(config_mgr=cfg)
    qtbot.addWidget(win)
    assert not win.custom_title_bar.isHidden()
    assert bool(win.windowFlags() & Qt.WindowType.FramelessWindowHint) is True
    assert win.centralWidget().property("frameless_rounded") == "true"

    # Toggle off via Settings method
    win.config_mgr.use_custom_title_bar = False
    win.custom_title_bar.setVisible(False)
    assert cfg.use_custom_title_bar is False
    assert win.custom_title_bar.isHidden() is True
    assert not win.clock_widget.isHidden()

    # Toggle back on
    win.config_mgr.use_custom_title_bar = True
    win.custom_title_bar.setVisible(True)
    assert cfg.use_custom_title_bar is True
    assert not win.custom_title_bar.isHidden()
    assert not win.clock_widget.isHidden()


def test_custom_title_bar_window_state_change(qtbot, isolated_config):
    win = MainWindow(config_mgr=isolated_config)
    qtbot.addWidget(win)
    title_bar = win.custom_title_bar

    # Simulate WindowStateChange event
    win.setWindowState(Qt.WindowState.WindowMaximized)
    event = QEvent(QEvent.Type.WindowStateChange)
    win.changeEvent(event)
    assert title_bar.max_btn.text() == "❐"
    assert win.centralWidget().property("frameless_rounded") == "false"

    win.setWindowState(Qt.WindowState.WindowNoState)
    event = QEvent(QEvent.Type.WindowStateChange)
    win.changeEvent(event)
    assert title_bar.max_btn.text() == "▢"
    assert win.centralWidget().property("frameless_rounded") == "true"
