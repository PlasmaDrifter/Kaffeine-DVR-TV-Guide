from pathlib import Path

from kaffeine_dvr.storage_manager import StorageManager


def test_storage_find_recorded_files(tmp_path: Path, isolated_config, isolated_queue_mgr):
    rec_dir = tmp_path / "recordings"
    rec_dir.mkdir()

    # Create dummy files
    f1 = rec_dir / "movie1.m2t"
    f2 = rec_dir / "show2.ts"
    f3 = rec_dir / "readme.txt"
    f1.write_bytes(b"x" * 1024)
    f2.write_bytes(b"y" * 2048)
    f3.write_bytes(b"z" * 100)

    sm = StorageManager(isolated_config, isolated_queue_mgr)
    found = sm.find_recorded_files(folder=rec_dir)

    # Only video files (.m2t, .ts) should be picked up
    names = [f["name"] for f in found]
    assert "movie1.m2t" in names
    assert "show2.ts" in names
    assert "readme.txt" not in names
