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
