from kaffeine_dvr.config import DEFAULT_CATEGORY_COLORS, ConfigManager


def test_default_config(isolated_config: ConfigManager):
    cfg = isolated_config
    assert cfg.end_buffer_mins == 0
    assert cfg.sports_buffer_mins == 40
    assert cfg.auto_buffer_sports is True
    assert cfg.auto_check_updates is False
    assert cfg.update_check_frequency == "weekly"
    assert cfg.grid_visible_rows == 9
    assert cfg.guide_detail_lines == 3
    assert cfg.lead_time_mins == 5
    assert cfg.watcher_interval_seconds == 180
    assert cfg.notification_lead_time_mins == 2
    assert cfg.timeshift_buffer_seconds == 2

def test_grid_visible_rows_clamping(isolated_config: ConfigManager):
    cfg = isolated_config
    cfg.grid_visible_rows = 2
    assert cfg.grid_visible_rows == 4

    cfg.grid_visible_rows = 25
    assert cfg.grid_visible_rows == 16

    cfg.grid_visible_rows = 11
    assert cfg.grid_visible_rows == 11


def test_guide_detail_lines_clamping(isolated_config: ConfigManager):
    cfg = isolated_config
    cfg.guide_detail_lines = 1
    assert cfg.guide_detail_lines == 2

    cfg.guide_detail_lines = 5
    assert cfg.guide_detail_lines == 3

    cfg.guide_detail_lines = 2
    assert cfg.guide_detail_lines == 2

    cfg.guide_detail_lines = 3
    assert cfg.guide_detail_lines == 3

def test_reset_to_defaults_preserves_user_data(isolated_config: ConfigManager):
    cfg = isolated_config
    # Set user rules and channels
    cfg.channel_map = {"ABC": "Channel 7.1", "NBC": "Channel 12.1"}
    cfg.rules = [{"title": "My Favorite Show", "channel": "ABC"}]
    cfg.tvpassport_stations = {"ABC": 1234}

    # Change tweakable settings
    cfg.end_buffer_mins = 15
    cfg.lead_time_mins = 10
    cfg.grid_visible_rows = 12
    cfg.set_category_color("sports", "#112233")

    # Reset
    cfg.reset_to_defaults(keep_channels_and_rules=True)

    # Verify user data preserved
    assert cfg.channel_map == {"ABC": "Channel 7.1", "NBC": "Channel 12.1"}
    assert len(cfg.rules) == 1
    assert cfg.rules[0]["title"] == "My Favorite Show"
    assert cfg.tvpassport_stations == {"ABC": 1234}

    # Verify settings restored to defaults
    assert cfg.end_buffer_mins == 0
    assert cfg.lead_time_mins == 5
    assert cfg.grid_visible_rows == 9
    assert cfg.category_colors["sports"] == DEFAULT_CATEGORY_COLORS["sports"]

def test_reset_category_colors(isolated_config: ConfigManager):
    cfg = isolated_config
    cfg.set_category_color("movies", "#999999")
    assert cfg.category_colors["movies"] == "#999999"

    cfg.reset_category_colors()
    assert cfg.category_colors["movies"] == DEFAULT_CATEGORY_COLORS["movies"]


def test_settings_ui_scale_clamping(isolated_config: ConfigManager):
    cfg = isolated_config
    assert cfg.settings_ui_scale == 100

    cfg.settings_ui_scale = 50
    assert cfg.settings_ui_scale == 90

    cfg.settings_ui_scale = 250
    assert cfg.settings_ui_scale == 180

    cfg.settings_ui_scale = 125
    assert cfg.settings_ui_scale == 125


def test_custom_theme_presets_limit_and_overwrite(isolated_config: ConfigManager):
    cfg = isolated_config
    assert len(cfg.custom_theme_presets) == 0

    # Save 3 custom themes
    k1 = cfg.save_custom_theme_preset("Theme 1")
    k2 = cfg.save_custom_theme_preset("Theme 2")
    cfg.save_custom_theme_preset("Theme 3")
    assert len(cfg.custom_theme_presets) == 3

    # Attempting to save a 4th should raise ValueError
    import pytest
    with pytest.raises(ValueError, match="Maximum limit of 3"):
        cfg.save_custom_theme_preset("Theme 4")

    # Overwriting an existing key replaces it and preserves the 3 limit
    k4 = cfg.save_custom_theme_preset("Theme 4 Overwrite", overwrite_key=k1)
    assert len(cfg.custom_theme_presets) == 3
    assert k1 not in cfg.custom_theme_presets
    assert k4 in cfg.custom_theme_presets
    assert cfg.custom_theme_presets[k4]["name"] == "Theme 4 Overwrite"

    # Deleting allows adding a new one
    cfg.delete_custom_theme_preset(k2)
    assert len(cfg.custom_theme_presets) == 2
    cfg.save_custom_theme_preset("Theme 5")
    assert len(cfg.custom_theme_presets) == 3


