from PyQt6.QtCore import Qt

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

