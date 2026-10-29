import json

import pytest

from ipod2playlist import cli, commands, export, library
from ipod2playlist.library import Song
from ipod2playlist.progress import Progress


@pytest.fixture
def work(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    return tmp_path


def test_golden_file(tmp_path):
    songs = [Song("Hoppípolla", "Sigur Rós", "Takk...", "a.mp3"), Song('Say "Hi", Bye', "A, B", "X", "b.mp3")]

    export.write_csv(songs, tmp_path / "out.csv")

    expected = ('﻿' + 'title,artist,album\r\nHoppípolla,Sigur Rós,Takk...\r\n'
                '"Say ""Hi"", Bye","A, B",X\r\n').encode("utf-8")
    assert (tmp_path / "out.csv").read_bytes() == expected


def test_service_exports_only_missing_without_api_calls(work, monkeypatch, capsys):
    found, lost = Song("Found", "A", "X", "a.mp3"), Song("Lost", "B", "Y", "b.mp3")
    library.save_songs([found, lost], work / "songs.json")
    progress = Progress(work / "progress.json")
    progress.record("spotify", found.key, "added")
    progress.record("spotify", lost.key, "missing")
    progress.save()

    def fail(name, args):
        raise AssertionError("export-csv must not build a service")

    monkeypatch.setattr(commands, "build_service", fail)
    cli.main(["export-csv", "--service", "spotify"])

    assert (work / "spotify_missing.csv").read_text(encoding="utf-8-sig").splitlines() == [
        "title,artist,album", "Lost,B,Y"]
    lines = capsys.readouterr().out.splitlines()
    assert lines[0] == "Wrote 1 songs to spotify_missing.csv"
    assert lines[-1] == export.ADVICE


def test_default_run_writes_library_and_playlist_files(work, capsys):
    first, second = Song("One", "A", "X", "a.mp3"), Song("Two", "B", "Y", "b.mp3")
    library.save_songs([first, second], work / "songs.json")
    (work / "ipod_playlists.json").write_text(json.dumps({"Road Trip": [first.key, "unknown|key"]}))

    cli.main(["export-csv"])

    assert len((work / "library.csv").read_text(encoding="utf-8-sig").splitlines()) == 3
    assert (work / "playlist_Road Trip.csv").read_text(encoding="utf-8-sig").splitlines() == [
        "title,artist,album", "One,A,X"]
    assert "Wrote 1 songs to playlist_Road Trip.csv" in capsys.readouterr().out


def test_no_playlist_file_when_ipod_playlists_missing(work):
    library.save_songs([Song("One", "A", "X", "a.mp3")], work / "songs.json")

    cli.main(["export-csv"])

    assert [p.name for p in work.glob("*.csv")] == ["library.csv"]


def test_missing_songs_file_exits_with_hint(work):
    with pytest.raises(SystemExit) as stopped:
        cli.main(["export-csv"])

    assert stopped.value.code == "songs.json not found; run `ipod2playlist scan <ipod path>` first."
