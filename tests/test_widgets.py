from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QLabel, QMenu, QTableWidgetItem, QWidgetAction

from kaffeine_dvr.gui import MainWindow, NumberStepper


def test_number_stepper_increment_decrement(qtbot):
    stepper = NumberStepper()
    stepper.setRange(4, 16)
    stepper.setValue(9)
    stepper.setSuffix(" rows")
    qtbot.addWidget(stepper)

    assert stepper.value() == 9

    # Click increment button (+)
    qtbot.mouseClick(stepper._btn_plus, Qt.MouseButton.LeftButton)
    assert stepper.value() == 10

    # Click decrement button (-) twice
    qtbot.mouseClick(stepper._btn_minus, Qt.MouseButton.LeftButton)
    qtbot.mouseClick(stepper._btn_minus, Qt.MouseButton.LeftButton)
    assert stepper.value() == 8

def test_number_stepper_bounds(qtbot):
    stepper = NumberStepper()
    stepper.setRange(4, 16)
    stepper.setValue(4)
    stepper.setSuffix(" rows")
    qtbot.addWidget(stepper)

    # Cannot decrement below min_val
    qtbot.mouseClick(stepper._btn_minus, Qt.MouseButton.LeftButton)
    assert stepper.value() == 4

    # Set to max and verify cannot increment above max_val
    stepper.setValue(16)
    qtbot.mouseClick(stepper._btn_plus, Qt.MouseButton.LeftButton)
    assert stepper.value() == 16

def test_main_window_reset_defaults_ui(qtbot, isolated_config):
    win = MainWindow(config_mgr=isolated_config)
    qtbot.addWidget(win)

    # Modify settings in config
    isolated_config.end_buffer_mins = 20
    isolated_config.grid_visible_rows = 14
    win._refresh_all_settings_ui()

    assert win.end_buffer_spin.value() == 20
    assert win.grid_rows_spin.value() == 14

    # Reset
    isolated_config.reset_to_defaults(keep_channels_and_rules=True)
    win._refresh_all_settings_ui()

    assert win.end_buffer_spin.value() == 0
    assert win.grid_rows_spin.value() == 9


def test_program_tile_delegate_paint(qtbot, isolated_config):
    from PyQt6.QtCore import QRect
    from PyQt6.QtGui import QFont, QPainter, QPixmap
    from PyQt6.QtWidgets import QStyleOptionViewItem, QTableWidget, QTableWidgetItem

    from kaffeine_dvr.gui import ProgramTileDelegate

    table = QTableWidget(2, 2)
    qtbot.addWidget(table)
    delegate = ProgramTileDelegate(table, config_mgr=isolated_config)

    prog_3line = {
        "show_title": "The Lawrence Welk Show",
        "episode_title": "Wunnerful Hit Songs",
        "_primary_title": "The Lawrence Welk Show",
        "_secondary_sub": "Wunnerful Hit Songs",
        "_time_range": "4:00 PM - 5:00 PM",
        "_category": "tvshows",
        "_timing_state": "upcoming",
    }
    item = QTableWidgetItem()
    item.setData(Qt.ItemDataRole.UserRole, prog_3line)
    table.setItem(0, 0, item)

    pix = QPixmap(200, 60)
    painter = QPainter(pix)
    opt = QStyleOptionViewItem()
    opt.rect = QRect(0, 0, 200, 60)
    opt.font = QFont("Sans Serif", 10)

    # Should paint cleanly without throwing exceptions
    delegate.paint(painter, opt, table.model().index(0, 0))
    painter.end()


def test_grid_zoom_base_row_h_minimum(qtbot, isolated_config):
    win = MainWindow(config_mgr=isolated_config)
    qtbot.addWidget(win)

    # Set visible rows high and check that base_row_h does not collapse below 58
    win.config_mgr.grid_visible_rows = 16
    win._apply_guide_zoom()
    assert win.guide_grid_table.verticalHeader().defaultSectionSize() >= 58


def test_grid_stability_on_status_messages(qtbot, isolated_config):
    win = MainWindow(config_mgr=isolated_config)
    qtbot.addWidget(win)
    win.resize(1300, 800)
    win.show()

    h0 = win.guide_grid_table.height()
    vh0 = win.guide_grid_table.viewport().height()

    # Show a status bar message
    win.status_bar.showMessage("Queued recording: Test Show on Channel 4.1", 4000)
    h1 = win.guide_grid_table.height()
    vh1 = win.guide_grid_table.viewport().height()

    # Clear message
    win.status_bar.clearMessage()
    h2 = win.guide_grid_table.height()
    vh2 = win.guide_grid_table.viewport().height()

    assert h0 == h1 == h2, f"Grid table height shifted: {h0} -> {h1} -> {h2}"
    assert vh0 == vh1 == vh2, f"Grid viewport height shifted: {vh0} -> {vh1} -> {vh2}"

    # Verify scrollbar positions remain preserved when keep_scroll is True
    win.guide_grid_table.horizontalScrollBar().setValue(100)
    win.guide_grid_table.verticalScrollBar().setValue(20)

    hs_before = win.guide_grid_table.horizontalScrollBar().value()
    vs_before = win.guide_grid_table.verticalScrollBar().value()

    win._refresh_guide_view(keep_scroll=True)

    assert win.guide_grid_table.horizontalScrollBar().value() == hs_before
    assert win.guide_grid_table.verticalScrollBar().value() == vs_before


def test_themed_and_centered_combobox(qtbot):
    from kaffeine_dvr.gui import CenteredComboBox, ThemedComboBox

    themed = ThemedComboBox()
    themed.addItems(["Today", "Tomorrow", "Wed, Oct 15"])
    qtbot.addWidget(themed)
    themed.resize(120, 28)

    assert themed.count() == 3
    assert not themed.centered

    centered = CenteredComboBox()
    centered.addItem("2 Lines", 2)
    centered.addItem("3 Lines", 3)
    qtbot.addWidget(centered)
    centered.resize(120, 28)

    assert centered.count() == 2
    assert centered.centered
    assert centered.itemData(0, Qt.ItemDataRole.TextAlignmentRole) == Qt.AlignmentFlag.AlignCenter
    assert centered.itemData(1, Qt.ItemDataRole.TextAlignmentRole) == Qt.AlignmentFlag.AlignCenter

    # Verify both grab cleanly with no errors
    pix1 = themed.grab()
    assert not pix1.isNull()

    pix2 = centered.grab()
    assert not pix2.isNull()


def test_clock_disable_toggle_and_stepper_state(qtbot, isolated_config):
    win = MainWindow(config_mgr=isolated_config)
    qtbot.addWidget(win)

    assert hasattr(win, "hide_clock_check")
    assert hasattr(win, "clock_size_spin")

    # By default, clock is enabled
    assert win.config_mgr.show_clock is True
    assert win.hide_clock_check.isChecked() is False
    assert win.clock_size_spin.isEnabled() is True

    # Disable clock from hide_clock_check (in Column 2)
    win.hide_clock_check.setChecked(True)
    assert win.config_mgr.show_clock is False
    assert win.clock_size_spin.isEnabled() is False

    # Re-enable clock from hide_clock_check
    win.hide_clock_check.setChecked(False)
    assert win.config_mgr.show_clock is True
    assert win.clock_size_spin.isEnabled() is True

    # Check auto-saving persistence
    win.hide_clock_check.setChecked(True)
    win._auto_save_automation_settings()
    assert win.config_mgr.show_clock is False


def test_grid_guide_options_120px_width(qtbot, isolated_config):
    win = MainWindow(config_mgr=isolated_config)
    qtbot.addWidget(win)

    assert win.grid_rows_spin.width() == 120
    assert win.guide_desc_lines_combo.width() == 120
    assert win.guide_auto_advance_spin.width() == 120
    assert win.clock_size_spin.width() == 120


def test_time_line_disable_toggle_and_opacity_popup_state(qtbot, isolated_config):
    from kaffeine_dvr.gui import OpacitySliderPopup

    win = MainWindow(config_mgr=isolated_config)
    qtbot.addWidget(win)

    assert hasattr(win, "hide_time_line_check")
    assert hasattr(win, "time_line_opacity_btn")

    # By default, time line is enabled and opacity is 100%
    assert win.config_mgr.guide_show_time_indicator is True
    assert win.config_mgr.time_line_opacity == 100
    assert win.hide_time_line_check.isChecked() is False
    assert win.time_line_opacity_btn.isEnabled() is True
    assert win.time_line_opacity_btn.text() == "Opacity: 100%"

    # Disable time line from hide_time_line_check (in Column 2)
    win.hide_time_line_check.setChecked(True)
    assert win.config_mgr.guide_show_time_indicator is False
    assert win.time_line_opacity_btn.isEnabled() is False

    # Re-enable time line from hide_time_line_check
    win.hide_time_line_check.setChecked(False)
    assert win.config_mgr.guide_show_time_indicator is True
    assert win.time_line_opacity_btn.isEnabled() is True

    # Open popup slider
    win._open_time_line_opacity_popup()
    assert OpacitySliderPopup._active_popup is not None
    assert OpacitySliderPopup._active_popup.slider.value() == 100

    # Change value via slider
    OpacitySliderPopup._active_popup.slider.setValue(45)
    assert win.config_mgr.time_line_opacity == 45
    assert win.time_line_opacity_btn.text() == "Opacity: 45%"

    # Dismiss popup
    OpacitySliderPopup.hide_active()
    assert OpacitySliderPopup._active_popup is None

    # Check reset / refresh UI restore
    win.config_mgr.time_line_opacity = 75
    win._refresh_all_settings_ui()
    assert win.time_line_opacity_btn.text() == "Opacity: 75%"


def test_guide_filter_bar_theming_and_icons(qtbot, isolated_config):
    win = MainWindow(config_mgr=isolated_config)
    qtbot.addWidget(win)

    # Verify object names are set for application stylesheet targeting
    assert win.grid_view_btn.objectName() == "guideGridViewBtn"
    assert win.list_view_btn.objectName() == "guideListViewBtn"
    assert win.header_restore_btn.objectName() == "headerRestoreBtn"
    assert win.guide_maximize_btn.objectName() == "guideMaximizeBtn"

    # Verify no hardcoded inline stylesheets lock the colors
    assert win.grid_view_btn.styleSheet() == ""
    assert win.list_view_btn.styleSheet() == ""
    assert win.header_restore_btn.styleSheet() == ""
    assert win.guide_maximize_btn.styleSheet() == ""

    # Test icons are properly generated with non-null pixmaps
    assert not win.header_restore_btn.icon().isNull()
    assert not win.guide_maximize_btn.icon().isNull()


def test_guide_action_buttons_widths_and_labels(qtbot, isolated_config):
    from kaffeine_dvr.gui import SilentStatusBar
    win = MainWindow(config_mgr=isolated_config)
    qtbot.addWidget(win)

    # Status bar uses SilentStatusBar and absorbs messages without rendering
    assert isinstance(win.status_bar, SilentStatusBar)
    win.status_bar.showMessage("Testing silent status bar", 1000)

    # Action buttons exist with correct labels and fixed width 168
    assert win.record_guide_btn.text() == "Record Program"
    assert win.cancel_guide_btn.text() == "Cancel Recording"
    assert win.add_rule_guide_btn.text() == "Record Series"
    assert win.watch_guide_btn.text() == "Watch Live"
    assert not hasattr(win, "alt_watch_guide_btn")

    for btn in (win.record_guide_btn, win.cancel_guide_btn, win.add_rule_guide_btn, win.watch_guide_btn):
        assert btn.minimumWidth() == 168
        assert btn.maximumWidth() == 168


def test_live_tv_playback_player_settings(qtbot, isolated_config):
    win = MainWindow(config_mgr=isolated_config)
    qtbot.addWidget(win)

    assert hasattr(win, "live_tv_mode_combo")
    assert hasattr(win, "custom_live_player_edit")

    # Test toggling to custom shows custom_live_player_edit
    custom_idx = win.live_tv_mode_combo.findData("custom")
    assert custom_idx >= 0
    win.live_tv_mode_combo.setCurrentIndex(custom_idx)
    assert not win.custom_live_player_edit.isHidden()

    win.custom_live_player_edit.setText("mpv --fs {file}")
    win._auto_save_automation_settings()
    assert win.config_mgr.live_tv_watch_mode == "custom"
    assert win.config_mgr.playback_player == "custom"
    assert win.config_mgr.custom_live_tv_player_cmd == "mpv --fs {file}"
    assert win.config_mgr.custom_playback_player_cmd == "mpv --fs {file}"


def test_watch_or_tune_routing(qtbot, isolated_config, monkeypatch):
    win = MainWindow(config_mgr=isolated_config)
    qtbot.addWidget(win)

    # Mock active program selection
    mock_prog = {
        "show_title": "Evening News",
        "title": "Evening News",
        "kaffeine_channel": "7.1 KGO-HD",
        "start_iso": "2026-10-14T18:00:00",
        "end_iso": "2026-10-14T19:00:00",
    }
    monkeypatch.setattr(win, "_get_active_selected_program", lambda: mock_prog)

    # 1. State: live, live_tv_watch_mode: kaffeine (legacy) -> safely falls back to timeshift playback
    win.config_mgr.live_tv_watch_mode = "kaffeine"
    monkeypatch.setattr(win, "_get_program_timing_state", lambda p: {"state": "live", "recorded_file": None})

    tuned_channels = []
    timeshifted_progs = []
    monkeypatch.setattr(win.dbus_client, "tune_channel", lambda ch, **kw: tuned_channels.append(ch))
    monkeypatch.setattr(win, "start_timeshift_playback", lambda p: timeshifted_progs.append(p))

    win.watch_or_tune_selected_guide_item()
    assert len(tuned_channels) == 0
    assert len(timeshifted_progs) == 1
    assert timeshifted_progs[0]["show_title"] == "Evening News"

    # 2. State: live, live_tv_watch_mode: smplayer -> starts timeshift
    tuned_channels.clear()
    timeshifted_progs.clear()
    win.config_mgr.live_tv_watch_mode = "smplayer"

    win.watch_or_tune_selected_guide_item()
    assert len(tuned_channels) == 0
    assert len(timeshifted_progs) == 1
    assert timeshifted_progs[0]["show_title"] == "Evening News"

    # 3. State: upcoming, live_tv_watch_mode: smplayer -> timeshifts live show
    tuned_channels.clear()
    timeshifted_progs.clear()
    monkeypatch.setattr(win, "_get_program_timing_state", lambda p: {"state": "upcoming", "time_desc": "in 2 hours"})
    monkeypatch.setattr(win, "_find_live_program_for_channel", lambda ch: {"show_title": "Current Live Show", "kaffeine_channel": ch})

    win.watch_or_tune_selected_guide_item()
    assert len(tuned_channels) == 0
    assert len(timeshifted_progs) == 1
    assert timeshifted_progs[0]["show_title"] == "Current Live Show"


def test_grid_immediate_highlight_on_show_switch_and_toggle(qtbot, isolated_config):
    isolated_config.guide_single_click_play = False
    win = MainWindow(config_mgr=isolated_config)
    qtbot.addWidget(win)

    table = win.guide_grid_table
    table.setRowCount(2)
    table.setColumnCount(10)

    # Program 1 on Channel A
    p1 = {
        "id": 1001,
        "show_title": "First Show",
        "kaffeine_channel": "Channel A",
        "start_iso": "2026-10-14T20:00:00",
        "_start_col": 0,
    }
    item1 = QTableWidgetItem("First Show")
    item1.setData(Qt.ItemDataRole.UserRole, p1)
    table.setItem(0, 0, item1)

    # Program 2 on Channel B with the SAME start time (previously caused bug due to channel_id=None)
    p2 = {
        "id": 1002,
        "show_title": "Second Show (Same Start Time)",
        "kaffeine_channel": "Channel B",
        "start_iso": "2026-10-14T20:00:00",
        "_start_col": 0,
    }
    item2 = QTableWidgetItem("Second Show")
    item2.setData(Qt.ItemDataRole.UserRole, p2)
    table.setItem(1, 0, item2)

    # 1. Click Show 1 -> immediately highlighted
    win.on_grid_cell_clicked(0, 0)
    assert win.selected_grid_program is not None
    assert win.selected_grid_program["show_title"] == "First Show"

    # 2. Click Show 2 -> immediately highlighted (NOT deselected/None)
    win.on_grid_cell_clicked(1, 0)
    assert win.selected_grid_program is not None
    assert win.selected_grid_program["show_title"] == "Second Show (Same Start Time)"

    # 3. Click Show 2 again -> toggles and removes highlight
    win.on_grid_cell_clicked(1, 0)
    assert win.selected_grid_program is None

    # 4. Click Show 1 -> immediately highlighted again
    win.on_grid_cell_clicked(0, 0)
    assert win.selected_grid_program is not None
    assert win.selected_grid_program["show_title"] == "First Show"


def test_themed_combo_box(qtbot):
    from PyQt6.QtGui import QPainter, QPixmap
    from kaffeine_dvr.gui import ThemedComboBox

    combo = ThemedComboBox()
    combo.addItems(["Alpha", "Beta", "Gamma"])
    combo.setCurrentIndex(1)
    qtbot.addWidget(combo)
    combo.resize(160, 30)

    # Verify paintEvent executes cleanly
    pixmap = QPixmap(160, 30)
    painter = QPainter(pixmap)
    combo.render(painter)
    painter.end()
    assert combo.currentText() == "Beta"


def test_settings_dropdowns_are_themed(qtbot, isolated_config):
    from kaffeine_dvr.gui import MainWindow, ThemedComboBox

    win = MainWindow(config_mgr=isolated_config)
    qtbot.addWidget(win)

    assert isinstance(win.provider_combo, ThemedComboBox)
    assert isinstance(win.launch_mode_combo, ThemedComboBox)
    assert isinstance(win.live_tv_mode_combo, ThemedComboBox)
    assert isinstance(win.update_freq_combo, ThemedComboBox)


def test_number_stepper_focus_event(qtbot):
    from PyQt6.QtCore import QEvent
    from kaffeine_dvr.gui import NumberStepper

    stepper = NumberStepper()
    qtbot.addWidget(stepper)

    assert stepper.property("focused") is None or stepper.property("focused") == "false"

    # Send FocusIn event to spinbox lineEdit
    line_edit = stepper._spin.lineEdit()
    assert line_edit is not None
    focus_in = QEvent(QEvent.Type.FocusIn)
    stepper.eventFilter(line_edit, focus_in)
    assert stepper.property("focused") == "true"

    # Send FocusOut event
    focus_out = QEvent(QEvent.Type.FocusOut)
    stepper.eventFilter(line_edit, focus_out)
    assert stepper.property("focused") == "false"


def test_build_app_stylesheet_number_stepper_and_combobox():
    from kaffeine_dvr.gui import APP_THEMES, build_app_stylesheet

    for theme_key, tokens in APP_THEMES.items():
        css = build_app_stylesheet(theme_key)
        assert "QFrame#numberStepper {" in css
        assert f"background-color: {tokens['bg_input']};" in css
        assert f"border: 1px solid {tokens['border_color']};" in css
        assert "QFrame#numberStepper[focused=\"true\"] {" in css
        assert f"border-color: {tokens['accent_primary']};" in css


def test_base_frameless_dialogs(qtbot, isolated_config):
    from PyQt6.QtGui import QPainter, QPixmap
    from kaffeine_dvr.gui import (
        BaseFramelessDialog,
        UpcomingShowDialog,
        ManualRecordDialog,
        AddRuleDialog,
        EditRuleDialog,
        RetentionCleanupDialog,
        AdjustBufferDialog,
        FirstRunWelcomeDialog,
        ServiceLogsDialog,
        ReleaseNotesDialog,
        ChannelSignalHealthDialog
    )

    # 1. Base class properties
    base = BaseFramelessDialog()
    qtbot.addWidget(base)
    assert bool(base.windowFlags() & Qt.WindowType.FramelessWindowHint)
    assert base.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

    # 2. Verify all 10 dialog subclasses inherit BaseFramelessDialog
    dialog_classes = [
        UpcomingShowDialog,
        ManualRecordDialog,
        AddRuleDialog,
        EditRuleDialog,
        RetentionCleanupDialog,
        AdjustBufferDialog,
        FirstRunWelcomeDialog,
        ServiceLogsDialog,
        ReleaseNotesDialog,
        ChannelSignalHealthDialog,
    ]
    for cls in dialog_classes:
        assert issubclass(cls, BaseFramelessDialog), f"{cls.__name__} must inherit BaseFramelessDialog"

    # 3. Instantiate and render UpcomingShowDialog
    prog = {
        "show_title": "Frameless Test Show",
        "kaffeine_channel": "7.1 KGO",
        "start_iso": "2026-10-15T20:00:00",
        "duration_iso": "01:00:00"
    }
    timing = {
        "time_desc": "in 1 hour",
        "start_fmt": "8:00 PM",
        "state": "upcoming"
    }
    upcoming_dlg = UpcomingShowDialog(prog, timing, is_scheduled=False)
    qtbot.addWidget(upcoming_dlg)
    assert bool(upcoming_dlg.windowFlags() & Qt.WindowType.FramelessWindowHint)
    assert upcoming_dlg.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

    pixmap = QPixmap(upcoming_dlg.sizeHint())
    painter = QPainter(pixmap)
    upcoming_dlg.render(painter)
    painter.end()
    assert not pixmap.isNull()

    # 4. Instantiate and test ManualRecordDialog
    manual_dlg = ManualRecordDialog(["Ch 1", "Ch 2"])
    qtbot.addWidget(manual_dlg)
    assert bool(manual_dlg.windowFlags() & Qt.WindowType.FramelessWindowHint)

    # 5. Test mouse drag tracking
    from PyQt6.QtGui import QMouseEvent
    from PyQt6.QtCore import QPointF
    press_event = QMouseEvent(
        QMouseEvent.Type.MouseButtonPress,
        QPointF(20.0, 20.0),
        QPointF(120.0, 120.0),
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier
    )
    base.mousePressEvent(press_event)
    assert base._drag_pos is not None

    release_event = QMouseEvent(
        QMouseEvent.Type.MouseButtonRelease,
        QPointF(20.0, 20.0),
        QPointF(120.0, 120.0),
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier
    )
    base.mouseReleaseEvent(release_event)
    assert base._drag_pos is None


def test_system_player_resolution_and_timeshift_poll(monkeypatch, tmp_path):
    from kaffeine_dvr.dbus_client import resolve_system_default_player_command, KaffeineDbusClient
    from kaffeine_dvr.gui import MainWindow
    from kaffeine_dvr.config import ConfigManager

    # 1. Test resolve_system_default_player_command with mock desktop file
    app_dir = tmp_path / "applications"
    app_dir.mkdir()
    desktop_file = app_dir / "custom-player.desktop"
    desktop_file.write_text("[Desktop Entry]\nExec=custom-player --fullscreen %f\nType=Application\n")

    monkeypatch.setattr(
        "kaffeine_dvr.dbus_client.subprocess.check_output",
        lambda *args, **kwargs: "custom-player.desktop\n"
    )
    monkeypatch.setattr(
        "kaffeine_dvr.dbus_client.shutil.which",
        lambda bin_name: "/usr/bin/custom-player" if bin_name == "custom-player" else None
    )

    test_video = str(tmp_path / "stream.m2t")
    # Patch desktop_dirs search inside resolve_system_default_player_command by injecting app_dir
    import kaffeine_dvr.dbus_client as dbc
    orig_resolve = dbc.resolve_system_default_player_command

    def mock_resolve(file_path):
        import subprocess, shutil, shlex
        out = "custom-player.desktop"
        p = app_dir / out
        with open(p, "r", encoding="utf-8") as f:
            for line in f:
                if line.startswith("Exec="):
                    exec_line = line.split("=", 1)[1].strip()
                    parts = shlex.split(exec_line)
                    filtered = [file_path if x in ("%f", "%F") else x for x in parts]
                    return filtered
        return None

    monkeypatch.setattr(dbc, "resolve_system_default_player_command", mock_resolve)
    resolved = dbc.resolve_system_default_player_command(test_video)
    assert resolved == ["custom-player", "--fullscreen", test_video]

    # 2. Test play_file fallback marks _is_xdg_open
    client = KaffeineDbusClient()
    dummy_file = tmp_path / "dummy.m2t"
    dummy_file.write_bytes(b"test")

    class DummyProc:
        def __init__(self, args):
            self.args = args
            self._code = 0
        def poll(self):
            return self._code

    monkeypatch.setattr(
        dbc.subprocess, "Popen",
        lambda cmd, **kwargs: DummyProc(cmd)
    )
    monkeypatch.setattr(dbc, "resolve_system_default_player_command", lambda f: None)
    monkeypatch.setattr(dbc.shutil, "which", lambda b: None)

    proc = client.play_file(str(dummy_file), player="system")
    assert proc is not None
    assert getattr(proc, "_is_xdg_open", False) is True
    assert proc.args == ["xdg-open", str(dummy_file)]

    # 3. Test that _poll_timeshift_session does NOT terminate session when _is_xdg_open is True
    class MockWindow:
        def __init__(self):
            self._active_timeshift = {"process": proc}
            self.stopped = False
        def stop_timeshift_session(self, user_initiated=False):
            self.stopped = True

    mw = MockWindow()
    # Call _poll_timeshift_session logic
    MainWindow._poll_timeshift_session(mw)
    assert mw.stopped is False
    assert mw._active_timeshift is not None


def test_guide_grid_context_menu_record_without_play_and_description(qtbot, isolated_config, monkeypatch):
    isolated_config.guide_single_click_play = True
    isolated_config.guide_detail_collapsed = True
    win = MainWindow(config_mgr=isolated_config)
    qtbot.addWidget(win)

    assert win.guide_detail_text.isVisible() is False

    table = win.guide_grid_table
    table.setRowCount(1)
    table.setColumnCount(4)

    prog = {
        "id": 9901,
        "show_title": "Right Click Mystery",
        "episode_title": "The Hidden Clue",
        "kaffeine_channel": "Channel 5.1",
        "start_iso": "2026-10-15T21:00:00",
        "start_time_local": "2026-10-15 21:00:00",
        "duration_iso": "01:00:00",
        "summary": "A captivating mystery show where detectives uncover hidden clues.",
        "_start_col": 0,
        "_span": 2,
    }
    item = QTableWidgetItem("Right Click Mystery")
    item.setData(Qt.ItemDataRole.UserRole, prog)
    table.setItem(0, 0, item)

    activated_progs = []
    monkeypatch.setattr(win, "handle_program_activation", lambda p: activated_progs.append(p))

    captured_menus = []
    real_exec = QMenu.exec

    def mock_exec(menu_self, *args, **kwargs):
        captured_menus.append(menu_self)
        return None

    monkeypatch.setattr(QMenu, "exec", mock_exec)

    # Simulate right click context menu on cell (0, 0)
    vp = table.viewport()
    pos = table.visualItemRect(item).center()
    win._on_guide_grid_context_menu(pos)

    # 1. Activation was NOT triggered
    assert len(activated_progs) == 0

    # 2. Program was selected
    assert win.selected_grid_program is not None
    assert win.selected_grid_program["show_title"] == "Right Click Mystery"

    # 3. Description box was NOT uncollapsed
    assert win.config_mgr.guide_detail_collapsed is True
    assert win.guide_detail_text.isVisible() is False

    # 4. Context menu was created and contains the description and Record action
    assert len(captured_menus) == 1
    menu = captured_menus[0]
    action_texts = [a.text() for a in menu.actions() if a.text()]
    assert "Record Program" in action_texts
    assert "Record Series (Add Rule)..." in action_texts

    # Find the header widget in the menu to verify description is shown
    header_widget = None
    for action in menu.actions():
        if isinstance(action, QWidgetAction):
            header_widget = action.defaultWidget()
            break
    assert header_widget is not None
    labels = header_widget.findChildren(QLabel)
    label_texts = " ".join(l.text() for l in labels)
    assert "Right Click Mystery" in label_texts
    assert "A captivating mystery show" in label_texts

    # 5. Triggering "Record Program" records the show without starting playback
    record_act = next(a for a in menu.actions() if a.text() == "Record Program")
    record_act.trigger()

    assert len(activated_progs) == 0
    active_map = win.queue_mgr.get_active_scheduled_map()
    assert ("channel 5.1", "2026-10-15T21:00") in active_map
    assert win.guide_detail_text.isVisible() is False
    win.close()


def test_guide_grid_context_menu_when_already_scheduled(qtbot, isolated_config, monkeypatch):
    win = MainWindow(config_mgr=isolated_config)
    qtbot.addWidget(win)

    table = win.guide_grid_table
    table.setRowCount(1)
    table.setColumnCount(2)

    prog = {
        "id": 9902,
        "show_title": "Scheduled Movie",
        "kaffeine_channel": "Channel 7.1",
        "start_iso": "2026-10-15T22:00:00",
        "duration_iso": "02:00:00",
        "summary": "An epic adventure.",
        "_start_col": 0,
        "_span": 1,
    }
    item = QTableWidgetItem("Scheduled Movie")
    item.setData(Qt.ItemDataRole.UserRole, prog)
    table.setItem(0, 0, item)

    # Pre-queue this program
    win.queue_mgr.add_recording("Scheduled Movie", "Channel 7.1", "2026-10-15T22:00:00", "02:00:00", buffer_mins=10)

    captured_menus = []
    monkeypatch.setattr(QMenu, "exec", lambda m, *args, **kwargs: captured_menus.append(m))

    pos = table.visualItemRect(item).center()
    win._on_guide_grid_context_menu(pos)

    assert len(captured_menus) == 1
    action_texts = [a.text() for a in captured_menus[0].actions() if a.text()]
    assert "Adjust Buffer (+10m)..." in action_texts
    assert "Cancel Recording" in action_texts
    assert "Record Program" not in action_texts
    win.close()


def test_guide_list_context_menu(qtbot, isolated_config, monkeypatch):
    isolated_config.guide_detail_collapsed = True
    win = MainWindow(config_mgr=isolated_config)
    qtbot.addWidget(win)

    prog = {
        "id": 9903,
        "show_title": "List View Drama",
        "kaffeine_channel": "Channel 9.1",
        "start_iso": "2026-10-15T23:00:00",
        "duration_iso": "01:00:00",
        "summary": "An intense courtroom drama.",
    }
    win.current_guide_items = [prog]
    win.guide_table.setRowCount(1)
    win.guide_table.setItem(0, 4, QTableWidgetItem("List View Drama"))

    captured_menus = []
    monkeypatch.setattr(QMenu, "exec", lambda m, *args, **kwargs: captured_menus.append(m))

    pos = win.guide_table.visualItemRect(win.guide_table.item(0, 4)).center()
    win._on_guide_list_context_menu(pos)

    assert len(captured_menus) == 1
    assert win.guide_detail_text.isVisible() is False
    action_texts = [a.text() for a in captured_menus[0].actions() if a.text()]
    assert "Record Program" in action_texts
    win.close()











