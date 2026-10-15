from datetime import date, datetime, timedelta

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QTableWidgetItem

from kaffeine_dvr.gui import GuideGridHeader, GuideGridTable, MainWindow


def test_config_guide_realtime_settings(isolated_config):
    # Verify defaults
    assert isolated_config.guide_auto_advance is True
    assert isolated_config.guide_show_time_indicator is True

    # Toggle and persist
    isolated_config.guide_auto_advance = False
    isolated_config.guide_show_time_indicator = False
    assert isolated_config.guide_auto_advance is False
    assert isolated_config.guide_show_time_indicator is False

    # Reload from disk
    from kaffeine_dvr.config import ConfigManager
    reloaded = ConfigManager()
    reloaded.config_file = isolated_config.config_file
    reloaded.data = reloaded._load()
    assert reloaded.guide_auto_advance is False
    assert reloaded.guide_show_time_indicator is False


def test_main_window_guide_settings_ui(qtbot, isolated_config):
    win = MainWindow(config_mgr=isolated_config)
    qtbot.addWidget(win)

    # Initial UI states
    assert win.guide_auto_advance_check.isChecked() is True
    assert win.hide_time_line_check.isChecked() is False
    assert "time_indicator" in win._cat_swatches

    # Toggle UI controls
    win.guide_auto_advance_check.setChecked(False)
    assert isolated_config.guide_auto_advance is False

    win.hide_time_line_check.setChecked(True)
    assert isolated_config.guide_show_time_indicator is False

    # Refresh all settings UI
    isolated_config.guide_auto_advance = True
    isolated_config.guide_show_time_indicator = True
    win._refresh_all_settings_ui()
    assert win.guide_auto_advance_check.isChecked() is True
    assert win.hide_time_line_check.isChecked() is False


def test_is_viewing_today(qtbot, isolated_config):
    win = MainWindow(config_mgr=isolated_config)
    qtbot.addWidget(win)

    today_str = date.today().strftime("%Y-%m-%d")
    tomorrow_str = (date.today() + timedelta(days=1)).strftime("%Y-%m-%d")

    # Item 1 is Today
    assert win.guide_date_combo.itemData(1) == today_str
    win.guide_date_combo.setCurrentIndex(1)
    assert win.is_viewing_today() is True

    # Item 0 is All Upcoming (None)
    win.guide_date_combo.setCurrentIndex(0)
    assert win.is_viewing_today() is True

    # Set to tomorrow
    t_idx = win.guide_date_combo.findData(tomorrow_str)
    if t_idx >= 0:
        win.guide_date_combo.setCurrentIndex(t_idx)
        assert win.is_viewing_today() is False


def test_grid_realtime_tile_update(qtbot, isolated_config):
    win = MainWindow(config_mgr=isolated_config)
    qtbot.addWidget(win)

    table = win.guide_grid_table
    table.setRowCount(1)
    table.setColumnCount(48)

    # Setup a program that has just ended
    now = datetime.now()
    past_start = (now - timedelta(hours=2)).isoformat()
    prog_past = {
        "start_iso": past_start,
        "duration_iso": "01:00:00",
        "_timing_state": "live",  # initially marked live
    }
    item = QTableWidgetItem("Past Show")
    item.setData(Qt.ItemDataRole.UserRole, prog_past)
    table.setItem(0, 0, item)

    # Trigger real-time tick
    win._update_guide_realtime()

    updated_data = item.data(Qt.ItemDataRole.UserRole)
    assert updated_data.get("_timing_state") == "past"


def test_guide_grid_header_and_table_painting(qtbot, isolated_config):
    win = MainWindow(config_mgr=isolated_config)
    qtbot.addWidget(win)

    assert isinstance(win.guide_grid_table, GuideGridTable)
    assert isinstance(win.guide_grid_header, GuideGridHeader)

    # Verify paintEvent executes without exception
    win.guide_grid_table.viewport().repaint()
    win.guide_grid_header.viewport().repaint()

    # Disable time line and ensure repaint still succeeds cleanly
    isolated_config.guide_show_time_indicator = False
    win.guide_grid_table.viewport().repaint()
    win.guide_grid_header.viewport().repaint()


def test_clock_widget_and_settings(qtbot, isolated_config):
    # Verify default config
    assert isolated_config.show_clock is True

    win = MainWindow(config_mgr=isolated_config)
    qtbot.addWidget(win)

    # Verify clock widget exists and is visible
    assert hasattr(win, "clock_widget")
    assert win.clock_widget.isHidden() is False
    assert hasattr(win, "clock_label")
    assert win.clock_label.text() != ""

    # Verify settings UI initial state
    assert hasattr(win, "hide_clock_check")
    assert win.hide_clock_check.isChecked() is False
    assert "clock" in win._cat_swatches

    # Toggle disable clock via UI checkbox
    win.hide_clock_check.setChecked(True)
    assert isolated_config.show_clock is False
    assert win.clock_widget.isHidden() is True

    # Re-enable clock via UI checkbox
    win.hide_clock_check.setChecked(False)
    assert isolated_config.show_clock is True
    assert win.clock_widget.isHidden() is False

    # Test settings UI refresh
    isolated_config.show_clock = False
    win._refresh_all_settings_ui()
    assert win.hide_clock_check.isChecked() is True
    assert win.clock_widget.isHidden() is True

    # Test clock color update
    isolated_config.show_clock = True
    isolated_config.set_category_color("clock", "#ff007f")
    win._update_clock_display()
    assert "#ff007f" in win.clock_label.styleSheet()

    # Test clock size stepper
    assert hasattr(win, "clock_size_spin")
    assert win.clock_size_spin.value() == 11
    win.clock_size_spin.setValue(16)
    assert isolated_config.clock_font_size == 16
    assert "font-size: 16px" in win.clock_label.styleSheet()


def test_auto_advance_minute_setting(qtbot, isolated_config):
    assert isolated_config.guide_auto_advance_minute == 50
    isolated_config.guide_auto_advance_minute = 45
    assert isolated_config.guide_auto_advance_minute == 45

    # Bounds clamping (0..59)
    isolated_config.guide_auto_advance_minute = 75
    assert isolated_config.guide_auto_advance_minute == 59
    isolated_config.guide_auto_advance_minute = -10
    assert isolated_config.guide_auto_advance_minute == 0

    isolated_config.guide_auto_advance_minute = 50
    win = MainWindow(config_mgr=isolated_config)
    qtbot.addWidget(win)

    assert hasattr(win, "guide_auto_advance_spin")
    assert win.guide_auto_advance_spin.value() == 50

    # Stepper value change updates config
    win.guide_auto_advance_spin.setValue(40)
    assert isolated_config.guide_auto_advance_minute == 40

    # Disabling auto-advance check disables stepper
    win.guide_auto_advance_check.setChecked(False)
    assert win.guide_auto_advance_spin.isEnabled() is False
    win.guide_auto_advance_check.setChecked(True)
    assert win.guide_auto_advance_spin.isEnabled() is True


def test_guide_grid_unhighlight_toggle_and_empty(qtbot, isolated_config):
    isolated_config.guide_single_click_play = False
    win = MainWindow(config_mgr=isolated_config)
    qtbot.addWidget(win)

    table = win.guide_grid_table
    table.setRowCount(1)
    table.setColumnCount(48)

    prog = {
        "channel_id": "ch1",
        "show_title": "Test Show",
        "start_iso": "2026-10-12T19:00:00",
        "duration_iso": "00:30:00",
        "_start_col": 0,
        "_span": 1,
    }
    item = QTableWidgetItem("Test Show")
    item.setData(Qt.ItemDataRole.UserRole, prog)
    table.setItem(0, 0, item)

    # 1. Click to select
    win.on_grid_cell_clicked(0, 0)
    assert win.selected_grid_program is not None
    assert win.selected_grid_program.get("channel_id") == "ch1"
    assert len(table.selectedItems()) == 1

    # 2. Option 1: Re-click same cell to unhighlight / deselect
    win.on_grid_cell_clicked(0, 0)
    assert win.selected_grid_program is None
    assert len(table.selectedItems()) == 0
    assert "Select a program" in win.guide_detail_title.text()

    # 3. Select again
    win.on_grid_cell_clicked(0, 0)
    assert win.selected_grid_program is not None
    assert win.selected_grid_program.get("channel_id") == "ch1"

    # 4. Option 2: Click empty cell (no program data) to unhighlight
    win.on_grid_cell_clicked(0, 5)
    assert win.selected_grid_program is None
    assert len(table.selectedItems()) == 0


def test_guide_grid_unhighlight_escape(qtbot, isolated_config):
    from PyQt6.QtCore import QEvent
    from PyQt6.QtGui import QKeyEvent

    isolated_config.guide_single_click_play = False
    win = MainWindow(config_mgr=isolated_config)
    qtbot.addWidget(win)

    table = win.guide_grid_table
    table.setRowCount(1)
    table.setColumnCount(48)

    prog = {
        "channel_id": "ch1",
        "show_title": "Test Show",
        "start_iso": "2026-10-12T19:00:00",
        "duration_iso": "00:30:00",
        "_start_col": 0,
        "_span": 1,
    }
    item = QTableWidgetItem("Test Show")
    item.setData(Qt.ItemDataRole.UserRole, prog)
    table.setItem(0, 0, item)

    # Select
    win.on_grid_cell_clicked(0, 0)
    assert win.selected_grid_program is not None
    assert win.selected_grid_program.get("channel_id") == "ch1"

    # Option 3: Press Escape key
    esc_event = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Escape, Qt.KeyboardModifier.NoModifier)
    win.keyPressEvent(esc_event)
    assert win.selected_grid_program is None
    assert len(table.selectedItems()) == 0
    assert "Select a program" in win.guide_detail_title.text()


def test_guide_list_unhighlight_toggle_and_escape(qtbot, isolated_config):
    from PyQt6.QtCore import QEvent
    from PyQt6.QtGui import QKeyEvent

    win = MainWindow(config_mgr=isolated_config)
    qtbot.addWidget(win)

    prog = {
        "channel_id": "ch1",
        "kaffeine_channel": "Channel 1",
        "show_title": "List Show",
        "start_iso": "2026-10-12T19:00:00",
        "duration_iso": "00:30:00",
        "start_time_local": "7:00 PM",
    }
    win.current_guide_items = [prog]
    win.guide_table.setRowCount(1)
    for c in range(6):
        win.guide_table.setItem(0, c, QTableWidgetItem(f"Col {c}"))

    # Switch to list view page
    win.guide_stack.setCurrentIndex(1)

    # 1. Click list item to select
    win.guide_table.setCurrentCell(0, 0)
    win.on_guide_selection_changed()
    assert "List Show" in win.guide_detail_title.text()
    assert win._get_active_selected_program() is prog

    # 2. Option 1: Re-click same list item to unhighlight
    win.on_guide_list_cell_clicked(0, 0)
    assert win._get_active_selected_program() is None
    assert len(win.guide_table.selectedItems()) == 0
    assert "Select a program" in win.guide_detail_title.text()

    # 3. Select again
    win.guide_table.setCurrentCell(0, 0)
    win.on_guide_selection_changed()
    assert win._get_active_selected_program() is prog

    # 4. Option 3: Press Escape key
    esc_event = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Escape, Qt.KeyboardModifier.NoModifier)
    win.keyPressEvent(esc_event)
    assert win._get_active_selected_program() is None
    assert len(win.guide_table.selectedItems()) == 0



