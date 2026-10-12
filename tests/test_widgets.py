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
