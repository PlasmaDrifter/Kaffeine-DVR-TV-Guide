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


def test_check_history_file_availability(tmp_path: Path, isolated_config, isolated_queue_mgr):
    rec_dir = tmp_path / "recordings"
    rec_dir.mkdir()
    isolated_config.custom_recording_folder = str(rec_dir)

    sm = StorageManager(isolated_config, isolated_queue_mgr)

    # 1. Non-existent file
    entry1 = {"title": "Missing Show", "start_iso": "2026-10-15T10:00:00", "file_path": str(rec_dir / "missing.m2t")}
    avail1, path1, sz1 = sm.check_history_file_availability(entry1)
    assert not avail1
    assert path1 is None
    assert sz1 == 0

    # 2. Existing file with exact path recorded
    video2 = rec_dir / "Movie_20261015.m2t"
    video2.write_bytes(b"A" * 50000)
    entry2 = {"title": "Movie", "start_iso": "2026-10-15T10:00:00", "file_path": str(video2)}
    avail2, path2, sz2 = sm.check_history_file_availability(entry2)
    assert avail2
    assert path2 == video2
    assert sz2 == 50000

    # 3. Existing file discovered in directory by matching title and date
    video3 = rec_dir / "Evening News_2026-10-15.ts"
    video3.write_bytes(b"B" * 80000)
    entry3 = {"title": "Evening News", "start_iso": "2026-10-15T18:00:00", "file_path": None}
    avail3, path3, sz3 = sm.check_history_file_availability(entry3)
    assert avail3
    assert path3 == video3
    assert sz3 == 80000

