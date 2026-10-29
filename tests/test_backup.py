import shutil
from pathlib import Path

import pytest

from conftest import FIXTURES, snapshot
from ipod2playlist import backup, cli
from ipod2playlist.library import Song
from ipod2playlist.scan import scan


def run(root, dest, *extra):
    cli.main(["backup", str(root), str(dest), *extra])


def song(title, artist="A", album="B", path="/x/f.mp3"):
    return Song(title=title, artist=artist, album=album, path=path)


def test_first_run_copies_every_file(fake_ipod, tmp_path, capsys):
    dest = tmp_path / "backup"
    run(fake_ipod, dest)
    sources = [Path(s.path) for s in scan(fake_ipod)]
    assert len(sources) == 6
    copies = [p for p in dest.rglob("*") if p.is_file() and p.suffix != ".m3u8"]
    assert len(copies) == 6
    assert sorted(p.read_bytes() for p in copies) == sorted(p.read_bytes() for p in sources)
    assert (dest / "The Beatles/Past Masters/Hey Jude.mp3").exists()
    assert (dest / "The Beatles/1/Hey Jude.mp3").exists()
    assert (dest / "Unknown Artist/Unknown Album/QRST.mp3").exists()
    assert "6 copied / 0 already there / 0 left alone; wrote 1 playlist file(s)" in capsys.readouterr().out


def test_ipod_is_untouched(fake_ipod, tmp_path):
    before = snapshot(fake_ipod)
    run(fake_ipod, tmp_path / "backup")
    assert snapshot(fake_ipod) == before


def test_resume_skips_what_is_there(fake_ipod, tmp_path):
    songs = scan(fake_ipod)
    dest = tmp_path / "backup"
    backup.backup(songs, fake_ipod, dest)
    result, present = backup.backup(songs, fake_ipod, dest)
    assert (result.copied, result.present) == (0, 6)
    assert len(present) == 6


def test_interrupted_copy_resumes(fake_ipod, tmp_path, monkeypatch):
    songs = scan(fake_ipod)
    dest = tmp_path / "backup"
    real_copy, calls = shutil.copy2, []

    def flaky(source, target):
        calls.append(source)
        if len(calls) == 3:
            Path(target).write_bytes(b"half")  # a half-written .part, as a pulled cable would leave
            raise OSError("cable pulled")
        return real_copy(source, target)

    monkeypatch.setattr(backup.shutil, "copy2", flaky)
    with pytest.raises(OSError):
        backup.backup(songs, fake_ipod, dest)
    targets = [t for _, t in backup.plan(songs, dest)]
    assert all(t.exists() for t in targets[:2])
    assert not any(t.exists() for t in targets[2:])  # nothing half-written under a real name
    monkeypatch.setattr(backup.shutil, "copy2", real_copy)  # also overwrites the leftover .part
    result, _ = backup.backup(songs, fake_ipod, dest)
    assert (result.copied, result.present) == (4, 2)
    assert not list(dest.rglob("*.part"))


def test_never_overwrites_a_different_file(fake_ipod, tmp_path, capsys):
    songs = scan(fake_ipod)
    dest = tmp_path / "backup"
    target = backup.plan(songs, dest)[0][1]
    target.parent.mkdir(parents=True)
    target.write_bytes(b"mine")
    result, present = backup.backup(songs, fake_ipod, dest)
    assert result.conflicts == 1 and result.copied == 5
    assert target.read_bytes() == b"mine"
    assert target not in [t for _, t in present]  # a stranger's file is not our song
    assert f"! exists, left alone: {target}" in capsys.readouterr().out


def test_destination_inside_the_ipod_is_refused(fake_ipod):
    before = snapshot(fake_ipod)
    for dest in (fake_ipod / "backup", fake_ipod):
        with pytest.raises(backup.BackupError, match="must not be on the iPod"):
            backup.backup(scan(fake_ipod), fake_ipod, dest)
    assert not (fake_ipod / "backup").exists()
    assert snapshot(fake_ipod) == before


def test_cli_reports_destination_error(fake_ipod):
    with pytest.raises(SystemExit, match="must not be on the iPod"):
        run(fake_ipod, fake_ipod / "backup")


def test_not_enough_space(fake_ipod, tmp_path, monkeypatch):
    monkeypatch.setattr(backup.shutil, "disk_usage", lambda p: shutil._ntuple_diskusage(100, 90, 10))
    dest = tmp_path / "backup"
    with pytest.raises(backup.BackupError, match="Not enough space"):
        backup.backup(scan(fake_ipod), fake_ipod, dest)
    assert not [p for p in dest.rglob("*") if p.is_file()]


def test_name_collisions_and_unsafe_names(tmp_path):
    dest = tmp_path / "d"
    two = backup.plan([song("Hells Bells", "AC/DC", "Back in Black"),
                       song("Hells Bells", "AC/DC", "Back in Black")], dest)
    assert [t.relative_to(dest).as_posix() for _, t in two] == [
        "ACDC/Back in Black/Hells Bells.mp3", "ACDC/Back in Black/Hells Bells (2).mp3"]
    assert backup.plan([song("..")], dest)[0][1].name == "_.mp3"


def test_names_differing_only_in_case_both_survive(fake_ipod, tmp_path):
    dest = tmp_path / "backup"
    plan = backup.plan([song("Hey Jude"), song("hey jude")], dest)
    assert [t.name for _, t in plan] == ["Hey Jude.mp3", "hey jude (2).mp3"]
    # Two real files on disk: the second must not land on the first, even on a case-insensitive Mac.
    music = fake_ipod / "iPod_Control/Music/F00"
    one, two = music / "case1.mp3", music / "case2.mp3"
    shutil.copy(music / "ABCD.mp3", one)
    one.write_bytes(one.read_bytes() + b"1")
    shutil.copy(music / "ABCD.mp3", two)
    two.write_bytes(two.read_bytes() + b"22")
    songs = [song("Hey Jude", path=str(one)), song("hey jude", path=str(two))]
    backup.backup(songs, fake_ipod, dest)  # the other iPod files are not in `songs`, so they land in Unreadable/
    assert sorted(p.read_bytes() for p in (dest / "A/B").iterdir()) == sorted([one.read_bytes(), two.read_bytes()])


def test_playlist_file(fake_ipod, tmp_path):
    dest = tmp_path / "backup"
    run(fake_ipod, dest)
    lines = (dest / "My iPod.m3u8").read_text(encoding="utf-8").splitlines()
    assert lines[0] == "#EXTM3U"
    assert lines.count("#EXTINF:-1,The Beatles - Hey Jude") == 2
    paths = [line for line in lines if not line.startswith("#")]
    assert len(paths) == 6
    assert all(not Path(p).is_absolute() and (dest / p).is_file() for p in paths)


def test_ipod_playlist_named_my_ipod_gets_a_new_name(fake_ipod, tmp_path):
    songs = scan(fake_ipod)
    dest = tmp_path / "backup"
    _, present = backup.backup(songs, fake_ipod, dest)
    key = backup.relative_key(songs[0].path, fake_ipod)
    count = backup.write_playlists(present, fake_ipod, dest, {"My iPod": [key], "my ipod": [key]})
    assert count == 3
    assert (dest / "My iPod (2).m3u8").exists() and (dest / "My iPod (3).m3u8").exists()
    assert (dest / "My iPod.m3u8").read_text(encoding="utf-8").count("#EXTINF") == 6


def test_cli_itunesdb_playlists(fake_ipod_with_db, tmp_path):
    dest = tmp_path / "backup"
    run(fake_ipod_with_db, dest, "--itunesdb")
    lines = (dest / "Road Trip.m3u8").read_text(encoding="utf-8").splitlines()
    assert len([line for line in lines if not line.startswith("#")]) == 2


def test_cli_junk_database_warns_and_still_backs_up(fake_ipod, tmp_path, capsys):
    pytest.importorskip("pygpod")
    dest = tmp_path / "backup"
    run(fake_ipod, dest, "--itunesdb")
    captured = capsys.readouterr()
    assert "warning: could not read the iPod's database" in captured.err
    assert "6 copied" in captured.out


def test_protected_m4p_is_counted_and_noted(fake_ipod, tmp_path, capsys):
    drm = fake_ipod / "iPod_Control/Music/F08/DRM1.m4p"
    drm.parent.mkdir()
    shutil.copy(FIXTURES / "silence.m4a", drm)
    run(fake_ipod, tmp_path / "backup")
    out = capsys.readouterr().out
    assert "1 songs are .m4p files bought from iTunes with copy protection" in out
    assert "authorised with that Apple ID." in out


def test_unreadable_file_is_copied_to_unreadable_folder(fake_ipod, tmp_path, capsys):
    bad = fake_ipod / "iPod_Control/Music/F07/BAD1.mp3"
    bad.parent.mkdir()
    bad.write_bytes(b"\x00\xffnot audio at all" * 20)
    before = snapshot(fake_ipod)
    dest = tmp_path / "backup"
    run(fake_ipod, dest)
    assert (dest / "Unreadable/BAD1.mp3").read_bytes() == bad.read_bytes()
    assert "1 files had unreadable tags and were copied to Unreadable/" in capsys.readouterr().out
    assert "BAD1" not in (dest / "My iPod.m3u8").read_text(encoding="utf-8")
    run(fake_ipod, dest)  # resume: nothing is copied again
    out = capsys.readouterr().out
    assert "0 copied / 7 already there" in out
    assert "1 files had unreadable tags" in out
    assert snapshot(fake_ipod) == before
