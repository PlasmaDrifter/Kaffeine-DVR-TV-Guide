from kaffeine_dvr.config import APP_THEMES, DEFAULT_CATEGORY_COLORS, THEME_PRESETS
from kaffeine_dvr.gui import build_app_stylesheet


def test_theme_presets_structure():
    required_keys = {
        "sports", "news", "movies", "tvshows",
        "highlight", "live_badge", "live_bg", "time_indicator", "clock", "grid_bg",
        "past_bg", "past_bg_alt", "past_border", "past_title", "past_subtext"
    }

    assert "midnight" in THEME_PRESETS
    assert "cyberpunk" in THEME_PRESETS
    assert "nordic_frost" in THEME_PRESETS
    assert "warm_sunset" in THEME_PRESETS
    assert "emerald_forest" in THEME_PRESETS
    assert "oled_contrast" in THEME_PRESETS
    assert "synthwave" in THEME_PRESETS

    for p_key, p_info in THEME_PRESETS.items():
        assert "name" in p_info, f"Preset {p_key} missing 'name'"
        assert "colors" in p_info, f"Preset {p_key} missing 'colors'"
        colors = p_info["colors"]
        missing = required_keys - set(colors.keys())
        assert not missing, f"Preset {p_key} missing color keys: {missing}"
        for c_key, c_val in colors.items():
            assert c_val.startswith("#") and len(c_val) == 7, f"Invalid hex color {c_val} for {c_key} in {p_key}"


def test_app_themes_structure():
    required_tokens = {
        "bg_window", "bg_panel", "bg_subpanel", "bg_input", "bg_button",
        "bg_button_hover", "bg_button_pressed", "border_color", "border_light",
        "border_subtabs", "accent_primary", "accent_hover", "accent_pressed",
        "text_primary", "text_secondary", "table_header_bg", "table_bg",
        "table_gridline", "scrollbar_bg", "scrollbar_handle", "scrollbar_handle_hover",
        "scrollbar_handle_pressed", "tooltip_bg", "tooltip_border", "menu_bg", "menu_item_selected"
    }

    assert "midnight" in APP_THEMES
    assert "oled_black" in APP_THEMES
    assert "nordic_frost" in APP_THEMES
    assert "charcoal" in APP_THEMES
    assert "cyberpunk" in APP_THEMES
    assert "warm_sunset" in APP_THEMES
    assert "synthwave" in APP_THEMES

    for t_key, t_info in APP_THEMES.items():
        assert "name" in t_info
        tokens = t_info
        missing = required_tokens - set(tokens.keys())
        assert not missing, f"App theme {t_key} missing token keys: {missing}"
        for k, v in tokens.items():
            if k == "name":
                continue
            assert v.startswith("#"), f"Token {k} has invalid color {v} in {t_key}"


def test_build_app_stylesheet():
    css = build_app_stylesheet("oled_black")
    assert "#000000" in css
    assert "QMainWindow" in css
    assert "QTabWidget" in css
    assert "QPushButton#guideGridViewBtn" in css
    assert "QPushButton#guideListViewBtn" in css
    assert "QPushButton#headerRestoreBtn" in css
    assert "QPushButton#guideMaximizeBtn" in css


def test_config_theme_presets(isolated_config):
    cfg = isolated_config
    assert cfg.theme_preset == "midnight"
    assert cfg.app_theme == "midnight"

    # Apply cyberpunk preset to guide
    cfg.apply_theme_preset("cyberpunk")
    assert cfg.theme_preset == "cyberpunk"
    assert cfg.category_colors["sports"] == THEME_PRESETS["cyberpunk"]["colors"]["sports"]
    assert cfg.category_colors["news"] == THEME_PRESETS["cyberpunk"]["colors"]["news"]
    assert cfg.category_colors["movies"] == THEME_PRESETS["cyberpunk"]["colors"]["movies"]
    # App theme remains untouched
    assert cfg.app_theme == "midnight"

    # Apply app theme
    cfg.apply_app_theme("oled_black")
    assert cfg.app_theme == "oled_black"
    # Guide preset remains cyberpunk
    assert cfg.theme_preset == "cyberpunk"

    # Custom edit flips guide preset to 'custom'
    cfg.set_category_color("sports", "#123456")
    assert cfg.category_colors["sports"] == "#123456"
    assert cfg.theme_preset == "custom"
    assert cfg.app_theme == "oled_black"

    # Apply another preset
    cfg.apply_theme_preset("nordic_frost")
    assert cfg.theme_preset == "nordic_frost"
    assert cfg.category_colors["sports"] == THEME_PRESETS["nordic_frost"]["colors"]["sports"]

    # Reset category colors restores 'midnight' for guide, leaves app theme
    cfg.reset_category_colors()
    assert cfg.theme_preset == "midnight"
    assert cfg.category_colors == DEFAULT_CATEGORY_COLORS
    assert cfg.app_theme == "oled_black"


def test_gui_dual_theme_switching(qapp, isolated_config):
    from kaffeine_dvr.gui import CenteredComboBox
    cfg = isolated_config

    # Test independent config application
    cfg.apply_app_theme("oled_black")
    assert cfg.app_theme == "oled_black"
    assert cfg.theme_preset == "midnight"

    cfg.apply_theme_preset("cyberpunk")
    assert cfg.theme_preset == "cyberpunk"
    assert cfg.app_theme == "oled_black"

    # Test combo mapping
    app_combo = CenteredComboBox()
    for t_key, t_info in APP_THEMES.items():
        app_combo.addItem(t_info["name"], t_key)
    assert app_combo.count() == len(APP_THEMES)
    idx = app_combo.findData("oled_black")
    assert idx >= 0
    app_combo.setCurrentIndex(idx)
    assert app_combo.currentData() == "oled_black"

    guide_combo = CenteredComboBox()
    for p_key, p_info in THEME_PRESETS.items():
        guide_combo.addItem(p_info["name"], p_key)
    guide_combo.addItem("Custom (Manual)", "custom")
    assert guide_combo.count() == len(THEME_PRESETS) + 1
    g_idx = guide_combo.findData("cyberpunk")
    assert g_idx >= 0
    guide_combo.setCurrentIndex(g_idx)
    assert guide_combo.currentData() == "cyberpunk"


def test_theme_chip_widget(qapp):
    from kaffeine_dvr.gui import ThemeChip, get_theme_chip_fixed_width

    w = get_theme_chip_fixed_width()
    assert w > 100

    clicked_keys = []
    chip = ThemeChip("test_theme", "Test Theme", "#38bdf8")
    chip.chip_clicked.connect(lambda k: clicked_keys.append(k))

    assert chip.key == "test_theme"
    assert chip.display_name == "Test Theme"
    assert chip.dot_color == "#38bdf8"
    assert not chip._is_selected
    assert chip.fixed_width == w
    assert chip.height() == 28
    assert chip.width() == w

    # Test selection toggle
    chip.set_selected(True)
    assert chip._is_selected
    chip.set_selected(False)
    assert not chip._is_selected

    # Test dot color update
    chip.set_dot_color("#ff0000")
    assert chip.dot_color == "#ff0000"

    # Test click signal
    chip.click()
    assert clicked_keys == ["test_theme"]


def test_theme_icon_generators(qapp):
    from kaffeine_dvr.gui import MainWindow
    # Ensure all icon methods accept optional color tokens without TypeError
    assert MainWindow._create_nav_arrow_icon("left", "#ffffff") is not None
    assert MainWindow._create_nav_arrow_icon("right", "#ffffff") is not None
    assert MainWindow._create_guide_refresh_icon("#ffffff") is not None
    assert MainWindow._create_restore_window_icon("#ffffff") is not None
    assert MainWindow._create_guide_restore_icon("#ffffff") is not None
    assert MainWindow._create_guide_maximize_icon("#ffffff") is not None


def test_today_theme_palettes_in_day_nav(isolated_config):
    from unittest.mock import MagicMock

    from kaffeine_dvr.gui import MainWindow

    dummy = MagicMock()
    dummy.config_mgr = isolated_config

    expected_colors = {
        "warm_sunset": ("#fbbf24", "#f59e0b"),
        "cyberpunk": ("#22d3ee", "#00f0ff"),
        "nordic_frost": ("#38bdf8", "#0ea5e9"),
        "midnight": ("#60a5fa", "#3b82f6"),
        "charcoal": ("#818cf8", "#6366f1"),
        "synthwave": ("#f472b6", "#e024c3"),
        "oled_black": ("#4ade80", "#22c55e"),
    }

    for theme_key, (unsel_token, sel_token) in expected_colors.items():
        isolated_config.app_theme = theme_key
        MainWindow._refresh_day_nav_styles(dummy)
        assert unsel_token in dummy._day_style_today_unselected
        assert sel_token in dummy._day_style_today_selected
        # Verify old hardcoded green border (#2e5937) is gone
        assert "#2e5937" not in dummy._day_style_today_unselected


def test_guide_filter_bar_theming(qapp):
    from PyQt6.QtGui import QPalette

    from kaffeine_dvr.gui import APP_THEMES, build_app_stylesheet, setup_dark_theme

    for theme_key, tokens in APP_THEMES.items():
        css = build_app_stylesheet(theme_key, "")
        assert "QLabel#guideFilterLabel" in css
        assert "QComboBox#guideDateCombo" in css
        assert "QComboBox#guideChannelCombo" in css
        assert "QLineEdit#guideSearchInput" in css
        assert "QLineEdit#guideSearchInput::placeholder" in css
        assert "QComboBox QAbstractItemView::item" in css
        assert tokens["bg_button"] in css
        assert tokens["border_light"] in css

        setup_dark_theme(qapp, theme_key)
        palette = qapp.palette()
        placeholder_color = palette.color(QPalette.ColorRole.PlaceholderText).name().lower()
        expected_color = tokens["text_secondary"].lower()
        assert placeholder_color == expected_color, f"Theme {theme_key} placeholder text color mismatch: {placeholder_color} != {expected_color}"


def test_compute_past_theme_colors():
    from kaffeine_dvr.config import compute_past_theme_colors
    res = compute_past_theme_colors("#251c19")
    assert "past_bg" in res
    assert "past_bg_alt" in res
    assert "past_border" in res
    assert "past_title" in res
    assert "past_subtext" in res
    for v in res.values():
        assert v.startswith("#") and len(v) == 7

    # Test invalid / fallback
    fallback = compute_past_theme_colors("invalid")
    assert fallback["past_bg"] == "#161922"
    assert fallback["past_title"] == "#788292"


def test_delegate_past_show_theming_sync(qtbot, isolated_config):
    from kaffeine_dvr.gui import MainWindow

    win = MainWindow(config_mgr=isolated_config)
    qtbot.addWidget(win)

    delegate = win.grid_tile_delegate

    # Verify default midnight past colors
    assert delegate.color_past_bg.name().lower() == "#161922"
    assert delegate.color_past_title.name().lower() == "#788292"

    # Switch to Warm Amber / Sunset preset
    isolated_config.apply_theme_preset("warm_sunset")
    delegate.refresh_category_colors()
    assert delegate.color_past_bg.name().lower() == "#1c1513"
    assert delegate.color_past_title.name().lower() == "#a89288"
    assert delegate.color_past_subtext.name().lower() == "#7a665d"

    # Switch to Emerald Forest preset
    isolated_config.apply_theme_preset("emerald_forest")
    delegate.refresh_category_colors()
    assert delegate.color_past_bg.name().lower() == "#0f1a14"
    assert delegate.color_past_title.name().lower() == "#759883"

    # Switch to Cyberpunk preset
    isolated_config.apply_theme_preset("cyberpunk")
    delegate.refresh_category_colors()
    assert delegate.color_past_bg.name().lower() == "#13101c"
    assert delegate.color_past_title.name().lower() == "#8e82a8"

