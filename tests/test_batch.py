"""Offline tests for the persistent batch queue."""
from yt import batch
from yt.downloader import DownloadResult
from yt.utils import read_json

WATCH_A = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
WATCH_B = "https://www.youtube.com/watch?v=aqz-KE-bpKQ"


def _queue(tmp_path):
    return batch.BatchQueue(
        path=tmp_path / "batch.json", history_path=tmp_path / "history.json"
    )


def test_add_and_reload(tmp_path):
    queue = _queue(tmp_path)
    added, failed = queue.add_urls(
        [
            "https://youtu.be/dQw4w9WgXcQ",  # normalizes to WATCH_A
            WATCH_B,
            WATCH_A,  # duplicate of the first after normalization
        ]
    )
    assert (added, failed) == (2, 0)

    reloaded = _queue(tmp_path)
    assert [item["url"] for item in reloaded.items] == [WATCH_A, WATCH_B]
    assert all(item["status"] == "pending" for item in reloaded.items)
    assert all(item["kind"] == "video" for item in reloaded.items)


def test_add_videos_dedupes(tmp_path):
    queue = _queue(tmp_path)
    videos = [
        {"url": WATCH_A, "title": "First"},
        {"url": WATCH_A, "title": "Duplicate"},
        {"url": WATCH_B, "title": "Second"},
    ]
    assert queue.add_videos(videos, verbose=False) == 2
    assert _queue(tmp_path).items[0]["title"] == "First"


def test_clear(tmp_path):
    queue = _queue(tmp_path)
    queue.add_urls([WATCH_A])
    assert queue.clear(assume_yes=True) == 0
    assert queue.items == []
    assert _queue(tmp_path).items == []


def test_corrupt_state_recovers(tmp_path):
    state = tmp_path / "batch.json"
    state.write_text("{ not json !", encoding="utf-8")
    queue = batch.BatchQueue(path=state, history_path=tmp_path / "history.json")
    assert queue.items == []
    added, _ = queue.add_urls([WATCH_A])
    assert added == 1


def test_record_history(tmp_path):
    media = tmp_path / "video.mp4"
    media.write_bytes(b"fake video data")
    history_path = tmp_path / "history.json"
    batch.record_history(
        DownloadResult(url=WATCH_A, ok=True, files=[str(media)]),
        history_path=history_path,
    )
    data = read_json(history_path, None)
    assert data is not None
    assert data["files"][0]["url"] == WATCH_A
    assert data["files"][0]["file"].endswith("video.mp4")
