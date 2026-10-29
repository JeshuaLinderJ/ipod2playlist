import json
import subprocess
import sys

import pytest

from conftest import snapshot
from ipod2playlist import cli, itunesdb
from ipod2playlist.itunesdb import INSTALL_HINT, DbTrack

UVWX = "ipod_control/music/f05/uvwx.wav"
ABCD = "ipod_control/music/f00/abcd.mp3"


@pytest.fixture
def work(tmp_path, monkeypatch):
    folder = tmp_path / "work"
    folder.mkdir()
    monkeypatch.chdir(folder)
    return folder


def test_read_itunesdb(fake_ipod_with_db):
    tracks, playlists = itunesdb.read_itunesdb(fake_ipod_with_db)
    assert tracks[UVWX] == DbTrack("Wish You Were Here", "Pink Floyd", "Wish You Were Here", 4, 12)
    assert playlists == {"Road Trip": [UVWX, ABCD]}


def test_reading_never_writes_to_the_ipod(fake_ipod_with_db):
    before = snapshot(fake_ipod_with_db)
    itunesdb.read_itunesdb(fake_ipod_with_db)
    assert snapshot(fake_ipod_with_db) == before


def test_scan_with_db(fake_ipod_with_db, work, capsys):
    before = snapshot(fake_ipod_with_db)
    cli.main(["scan", str(fake_ipod_with_db), "--itunesdb"])
    assert snapshot(fake_ipod_with_db) == before  # no new lock or journal file either
    songs = json.loads((work / "songs.json").read_text(encoding="utf-8"))
    by_title = {s["title"]: s for s in songs}
    assert "Hey Jude" in by_title  # tags win over "Hey Jude (iTunes)"
    assert by_title["Wish You Were Here"]["artist"] == "Pink Floyd"
    assert by_title["Wish You Were Here"]["rating"] == 4
    assert by_title["QRST"]["artist"] == "Unknown Artist"
    assert [s["plays"] for s in songs][:3] == [40, 12, 3]
    assert songs[0]["title"] == "Hey Jude"
    assert json.loads((work / "ipod_playlists.json").read_text(encoding="utf-8")) == {
        "Road Trip": ["pink floyd|wish you were here", "the beatles|hey jude"]}
    assert "Read the iPod's database: 1 untagged songs named, 1 playlists saved to" in capsys.readouterr().out


def test_lazy_import():
    out = subprocess.run([sys.executable, "-c", "import ipod2playlist.cli, sys; print('pygpod' in sys.modules)"],
                         capture_output=True, text=True, check=True).stdout
    assert out.strip() == "False"


def test_missing_pygpod(fake_ipod, work, monkeypatch):
    monkeypatch.setitem(sys.modules, "pygpod", None)
    with pytest.raises(SystemExit) as exit_info:
        cli.main(["scan", str(fake_ipod), "--itunesdb"])
    assert exit_info.value.code == INSTALL_HINT
    cli.main(["scan", str(fake_ipod)])
    assert (work / "songs.json").exists()


def test_unreadable_database_falls_back(fake_ipod, work, capsys):
    cli.main(["scan", str(fake_ipod), "--itunesdb"])
    captured = capsys.readouterr()
    assert "warning: could not read the iPod's database" in captured.err
    assert len(json.loads((work / "songs.json").read_text(encoding="utf-8"))) == 5
    assert not (work / "ipod_playlists.json").exists()


def test_importing_pygpod_shows_no_warning():
    result = subprocess.run([sys.executable, "-W", "error::UserWarning", "-c",
                             "from ipod2playlist import itunesdb; itunesdb._import_pygpod()"],
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
