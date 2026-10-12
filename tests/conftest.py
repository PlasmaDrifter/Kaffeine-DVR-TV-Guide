from pathlib import Path

import pytest

from kaffeine_dvr.config import ConfigManager
from kaffeine_dvr.guide_service import GuideService
from kaffeine_dvr.queue_manager import QueueManager


@pytest.fixture
def tmp_app_dirs(tmp_path: Path):
    config_dir = tmp_path / "config"
    data_dir = tmp_path / "data"
    config_dir.mkdir(parents=True, exist_ok=True)
    data_dir.mkdir(parents=True, exist_ok=True)
    return config_dir, data_dir

@pytest.fixture
def isolated_config(tmp_app_dirs):
    config_dir, data_dir = tmp_app_dirs
    cfg = ConfigManager()
    cfg.config_dir = config_dir
    cfg.config_file = config_dir / "config.json"
    cfg.data_dir = data_dir
    cfg.kaffeine_db_path = data_dir / "kaffeine.db"
    cfg.data = cfg.get_default_config()
    cfg.save()
    return cfg

@pytest.fixture
def isolated_queue_mgr(tmp_app_dirs):
    _, data_dir = tmp_app_dirs
    qm = QueueManager(data_dir=data_dir)
    return qm

@pytest.fixture
def isolated_guide_svc(tmp_app_dirs, isolated_config):
    _, data_dir = tmp_app_dirs
    gs = GuideService(data_dir=data_dir, config_mgr=isolated_config)
    return gs
