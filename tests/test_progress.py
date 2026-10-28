import json

import pytest

from ipod2playlist.progress import Progress


def test_fresh_path_is_empty(tmp_path):
    progress = Progress(tmp_path / "progress.json")
    assert progress.playlist_id("spotify") is None
    assert progress.status("spotify", "a|b") is None
    assert progress.keys_with_status("spotify", "added") == []


def test_set_and_get_playlist_id(tmp_path):
    progress = Progress(tmp_path / "progress.json")
    progress.set_playlist_id("spotify", "pl1")
    assert progress.playlist_id("spotify") == "pl1"


def test_record_and_status(tmp_path):
    progress = Progress(tmp_path / "progress.json")
    progress.record("spotify", "a|b", "added")
    progress.record("spotify", "c|d", "missing")
    assert progress.status("spotify", "a|b") == "added"
    assert progress.status("spotify", "c|d") == "missing"


def test_persisted_across_instances(tmp_path):
    path = tmp_path / "progress.json"
    progress = Progress(path)
    progress.set_playlist_id("spotify", "pl1")
    progress.record("spotify", "a|b", "added")
    progress.save()

    reloaded = Progress(path)
    assert reloaded.playlist_id("spotify") == "pl1"
    assert reloaded.status("spotify", "a|b") == "added"
    assert json.loads(path.read_text()) == {
        "version": 1,
        "services": {"spotify": {"playlist_id": "pl1", "songs": {"a|b": "added"}}},
    }


def test_services_are_independent(tmp_path):
    progress = Progress(tmp_path / "progress.json")
    progress.set_playlist_id("spotify", "sp1")
    progress.record("spotify", "a|b", "added")
    assert progress.playlist_id("youtube") is None
    assert progress.status("youtube", "a|b") is None
    progress.set_playlist_id("youtube", "yt1")
    assert progress.playlist_id("spotify") == "sp1"


def test_keys_with_status(tmp_path):
    progress = Progress(tmp_path / "progress.json")
    progress.record("spotify", "a|b", "added")
    progress.record("spotify", "c|d", "missing")
    progress.record("spotify", "e|f", "added")
    progress.record("youtube", "g|h", "added")
    assert progress.keys_with_status("spotify", "added") == ["a|b", "e|f"]
    assert progress.keys_with_status("spotify", "missing") == ["c|d"]


def test_invalid_status_raises(tmp_path):
    progress = Progress(tmp_path / "progress.json")
    with pytest.raises(ValueError):
        progress.record("spotify", "a|b", "done")
    assert progress.status("spotify", "a|b") is None


def test_failed_write_leaves_existing_file_intact(tmp_path, monkeypatch):
    path = tmp_path / "progress.json"
    progress = Progress(path)
    progress.record("spotify", "a|b", "added")
    progress.save()
    original = path.read_text()

    progress.record("spotify", "c|d", "added")

    def boom(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(json, "dump", boom)
    with pytest.raises(OSError):
        progress.save()
    assert path.read_text() == original


def test_leftover_tmp_file_is_ignored_and_overwritten(tmp_path):
    path = tmp_path / "progress.json"
    progress = Progress(path)
    progress.record("spotify", "a|b", "added")
    progress.save()
    (tmp_path / "progress.json.tmp").write_text("{ half written")

    reloaded = Progress(path)
    assert reloaded.status("spotify", "a|b") == "added"
    reloaded.record("spotify", "c|d", "added")
    reloaded.save()
    assert Progress(path).status("spotify", "c|d") == "added"


@pytest.mark.parametrize("content", ["{}", "[]", '"text"'])
def test_wrong_shape_file_raises_value_error(tmp_path, content):
    path = tmp_path / "progress.json"
    path.write_text(content)
    with pytest.raises(ValueError):
        Progress(path)


def test_reset_service_removes_only_that_service(tmp_path):
    progress = Progress(tmp_path / "p.json")
    for service in ("spotify", "youtube"):
        progress.set_playlist_id(service, f"{service}-id")
        progress.record(service, "k", "added")

    progress.reset_service("youtube")

    assert progress.playlist_id("youtube") is None
    assert progress.status("youtube", "k") is None
    assert progress.playlist_id("spotify") == "spotify-id"
    assert progress.status("spotify", "k") == "added"


def test_reset_service_of_unknown_service_is_a_no_op(tmp_path):
    progress = Progress(tmp_path / "p.json")
    progress.set_playlist_id("spotify", "id")

    progress.reset_service("youtube")

    assert progress.playlist_id("spotify") == "id"


def test_services_lists_blocks(tmp_path):
    progress = Progress(tmp_path / "progress.json")
    assert progress.services() == []
    progress.record("spotify", "a|b", "added")
    progress.set_playlist_id("youtube", "pl1")
    assert progress.services() == ["spotify", "youtube"]


V15 = {"version": 1, "services": {"spotify": {"playlist_id": "pl1", "songs": {"a|b": "added", "c|d": "missing"}}}}


def test_v15_file_round_trips_without_a_maybe_key(tmp_path):
    path = tmp_path / "progress.json"
    path.write_text(json.dumps(V15))
    progress = Progress(path)
    progress.record("spotify", "e|f", "missing")
    progress.save()
    expected = json.loads(json.dumps(V15))
    expected["services"]["spotify"]["songs"]["e|f"] = "missing"
    assert json.loads(path.read_text()) == expected


def test_file_with_maybe_is_still_valid_for_v15_logic(tmp_path):
    from ipod2playlist.matching import Candidate

    path = tmp_path / "progress.json"
    path.write_text(json.dumps(V15))
    progress = Progress(path)
    progress.record_maybe("spotify", "c|d", Candidate("id1", "T", "A"), 73.66)
    progress.save()
    data = json.loads(path.read_text())
    block = data["services"]["spotify"]
    assert data["version"] == 1
    assert block["playlist_id"] is None or isinstance(block["playlist_id"], str)
    assert set(block["songs"].values()) <= {"added", "missing"}
    assert Progress(path).maybe("spotify", "c|d") == {"id": "id1", "title": "T", "artist": "A", "score": 73.7}


def test_added_clears_maybe_and_missing_block_is_tolerated(tmp_path):
    from ipod2playlist.matching import Candidate

    progress = Progress(tmp_path / "progress.json")
    assert progress.maybe("spotify", "a|b") is None
    progress.clear_maybe("spotify", "a|b")  # no block at all: no error
    progress.record_maybe("spotify", "a|b", Candidate("i", "T", "A"), 70)
    progress.record("spotify", "a|b", "added")
    assert progress.maybe("spotify", "a|b") is None
