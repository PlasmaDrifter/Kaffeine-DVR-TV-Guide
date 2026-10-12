from datetime import datetime, timedelta

from kaffeine_dvr.queue_manager import QueueManager


def test_consecutive_recordings_on_different_channels_clamping(isolated_queue_mgr: QueueManager):
    qm = isolated_queue_mgr
    now = datetime(2026, 10, 11, 12, 0, 0)
    start_a = now
    end_a = now + timedelta(hours=1)
    start_b = end_a

    # Queue Show A on Channel 1 with 15 min buffer
    id_a = qm.add_recording(
        title="Show A",
        channel="FOX 10.1",
        start_iso=start_a.isoformat(),
        duration_iso="01:00:00",
        buffer_mins=15
    )

    # Queue Show B on Channel 2 starting immediately at Show A's end
    qm.add_recording(
        title="Show B",
        channel="CBS 5.1",
        start_iso=start_b.isoformat(),
        duration_iso="01:00:00",
        buffer_mins=0
    )

    qm.resolve_consecutive_buffer_conflicts()
    queue = {item["id"]: item for item in qm.list_queue()}

    # Show A's end buffer should be suppressed (buffer_mins == 0) and stopped 5s early to yield the tuner to Show B
    assert queue[id_a]["buffer_mins"] == 0
    assert queue[id_a]["duration_iso"] == "00:59:55"
    assert queue[id_a]["end_iso"] == "2026-10-11T12:59:55"

def test_consecutive_recordings_on_same_channel_not_clamped(isolated_queue_mgr: QueueManager):
    qm = isolated_queue_mgr
    now = datetime(2026, 10, 11, 12, 0, 0)
    start_a = now
    end_a = now + timedelta(hours=1)
    start_b = end_a

    id_a = qm.add_recording(
        title="Same Channel Show 1",
        channel="ABC 15.1",
        start_iso=start_a.isoformat(),
        duration_iso="01:00:00",
        buffer_mins=10
    )

    qm.add_recording(
        title="Same Channel Show 2",
        channel="ABC 15.1",
        start_iso=start_b.isoformat(),
        duration_iso="01:00:00",
        buffer_mins=0
    )

    qm.resolve_consecutive_buffer_conflicts()
    queue = {item["id"]: item for item in qm.list_queue()}

    # Same channel should retain its buffer because same tuner frequency is used
    assert queue[id_a]["buffer_mins"] == 10

def test_effective_dispatch_params_delayed_start_cheat(isolated_queue_mgr: QueueManager):
    qm = isolated_queue_mgr
    t0 = datetime(2026, 10, 11, 14, 0, 0)
    t1 = t0 + timedelta(hours=1)

    qm.add_recording("Preceding Show", "NBC 12.1", t0.isoformat(), "01:00:00", buffer_mins=0)
    qm.add_recording("Next Show", "FOX 10.1", t1.isoformat(), "01:00:00", buffer_mins=0)

    queue = qm.list_queue()
    rec_next = next(r for r in queue if r["title"] == "Next Show")

    dispatch_start, dispatch_dur = qm.get_effective_dispatch_params(rec_next)
    expected_start = (t1 + timedelta(seconds=2)).isoformat()
    assert dispatch_start == expected_start
    assert dispatch_dur == "00:59:58"

def test_archive_to_history(isolated_queue_mgr: QueueManager):
    qm = isolated_queue_mgr
    now_iso = datetime.now().isoformat()
    q_id = qm.add_recording("Recorded Show", "FOX 10.1", now_iso, "00:30:00", buffer_mins=0)

    assert len(qm.list_queue()) == 1
    assert len(qm.list_history()) == 0

    qm.archive_to_history(q_id)

    assert len(qm.list_queue()) == 0
    hist = qm.list_history()
    assert len(hist) == 1
    assert hist[0]["title"] == "Recorded Show"
    assert hist[0]["channel"] == "FOX 10.1"
