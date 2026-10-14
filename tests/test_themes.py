from kaffeine_dvr.config import APP_THEMES, DEFAULT_CATEGORY_COLORS, THEME_PRESETS
from kaffeine_dvr.gui import build_app_stylesheet


def test_theme_presets_structure():
    required_keys = {
        "sports", "news", "movies", "tvshows",
        "highlight", "live_badge", "live_bg", "time_indicator", "clock"
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

