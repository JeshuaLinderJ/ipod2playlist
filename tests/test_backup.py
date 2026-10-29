import shutil
from pathlib import Path

import pytest

from conftest import FIXTURES, snapshot
import errno
import sys
import hashlib
import os
import unicodedata

import mutagen

from ipod2playlist import backup, backup_guard, cli, m3u8
from ipod2playlist.itunesdb import relative_key
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
            raise KeyboardInterrupt
        return real_copy(source, target)

    monkeypatch.setattr(backup.shutil, "copy2", flaky)
    with pytest.raises(KeyboardInterrupt):
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
    assert result.conflicts == 1 and result.copied == 6  # the song is still backed up, under another name
    assert target.read_bytes() == b"mine"
    assert (target.parent / "Hey Jude (2).mp3").read_bytes() == Path(songs[0].path).read_bytes()
    assert target not in [t for _, t in present]
    assert f"! exists, left alone: {target}" in capsys.readouterr().out


def test_same_size_different_file_is_not_taken_for_ours(fake_ipod, tmp_path):
    songs = scan(fake_ipod)
    dest = tmp_path / "backup"
    target = backup.plan(songs, dest)[0][1]
    target.parent.mkdir(parents=True)
    target.write_bytes(b"x" * Path(songs[0].path).stat().st_size)
    os.utime(target, (0, 0))  # a stranger's old file; the 2 s window must not take it for ours
    backup.backup(songs, fake_ipod, dest)
    assert target.read_bytes().startswith(b"xxxx")
    assert (target.parent / "Hey Jude (2).mp3").read_bytes() == Path(songs[0].path).read_bytes()


def digests(folder):
    return [hashlib.sha256(p.read_bytes()).hexdigest() for p in folder.rglob("*")
            if p.suffix == ".mp3" and "Unreadable" not in p.parts]


def test_order_shift_loses_no_song(fake_ipod, tmp_path):
    dest = tmp_path / "backup"
    music = fake_ipod / "iPod_Control/Music"
    for name, tags, extra in (("F05/A.mp3", "a", b"a"), ("F01/B.mp3", "b", b"bbbbb")):
        path = music / name
        shutil.copy(FIXTURES / "silence.mp3", path)
        audio = mutagen.File(path, easy=True)
        audio.update({"title": ["Twist"], "artist": ["Zed"], "album": ["Z"]})
        audio.save()
        path.write_bytes(path.read_bytes() + extra)
    a, b = music / "F05/A.mp3", music / "F01/B.mp3"
    backup.backup([s for s in scan(fake_ipod) if s.path == str(a)], fake_ipod, dest)  # only A exists in DEST
    backup.backup(scan(fake_ipod), fake_ipod, dest)  # now B sorts first and wants A's name
    got = digests(dest)
    for source in (a, b):
        assert got.count(hashlib.sha256(source.read_bytes()).hexdigest()) == 1


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
    key = relative_key(songs[0].path, fake_ipod)
    count = m3u8.write_playlists(present, fake_ipod, dest, {"My iPod": [key], "my ipod": [key], "Cafe\u0301": [key], "Caf\u00e9": [key]})
    assert count == 5
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


def test_copy_error_on_one_file_does_not_stop_the_others(fake_ipod, tmp_path, monkeypatch, capsys):
    dest = tmp_path / "backup"
    real, calls = shutil.copy2, []

    def flaky(source, target):
        calls.append(source)
        if len(calls) == 2:
            raise OSError(errno.EIO, "Input/output error")
        return real(source, target)

    monkeypatch.setattr(backup.shutil, "copy2", flaky)
    with pytest.raises(SystemExit) as stop:
        run(fake_ipod, dest)
    assert str(stop.value) == "1 files could not be copied; run the same backup again to retry."
    out = capsys.readouterr().out
    assert "! could not copy" in out
    assert len(digests(dest)) + len(list(dest.rglob("*.flac"))) + len(list(dest.rglob("*.m4a"))) + len(list(dest.rglob("*.wav"))) == 5
    assert len([ln for ln in (dest / "My iPod.m3u8").read_text().splitlines() if ln.startswith("./")]) == 5
    monkeypatch.setattr(backup.shutil, "copy2", real)
    run(fake_ipod, dest)  # the retry finishes the job
    assert "1 copied / 5 already there" in capsys.readouterr().out


@pytest.mark.parametrize("dest_name", ["IPOD/bk", "ipod/bk", "iPod/sub/bk", "bk"])
def test_guard_ignores_case(tmp_path, dest_name):
    root = tmp_path / "ipod"
    (root / "iPod_Control").mkdir(parents=True)
    dest = tmp_path / dest_name if dest_name != "bk" else root / "BK"
    with pytest.raises(backup.BackupError, match="must not be on the iPod"):
        backup_guard.check_destination(root, dest)


def test_guard_ignores_unicode_form(tmp_path):
    root = tmp_path / unicodedata.normalize("NFC", "Café")
    (root / "iPod_Control").mkdir(parents=True)
    with pytest.raises(backup.BackupError):
        backup_guard.check_destination(root, tmp_path / unicodedata.normalize("NFD", "Café") / "bk")


def test_guard_finds_the_ipod_when_root_is_a_subfolder(fake_ipod):
    music = fake_ipod / "iPod_Control/Music"
    with pytest.raises(backup.BackupError):
        backup_guard.check_destination(music, fake_ipod / "bk4")
    with pytest.raises(backup.BackupError):
        backup_guard.check_destination(music, fake_ipod.parent)  # DEST contains the iPod


def test_guard_refuses_the_ipods_disk_but_not_another(fake_ipod, tmp_path, monkeypatch):
    monkeypatch.setattr(backup_guard, "_is_mount", lambda path: path == fake_ipod)
    monkeypatch.setattr(backup_guard, "_device_of", lambda path: 7)
    with pytest.raises(backup.BackupError, match="must not be on the iPod"):
        backup_guard.check_destination(fake_ipod, tmp_path / "elsewhere" / "backup")
    monkeypatch.setattr(backup_guard, "_device_of", lambda path: 7 if path == fake_ipod else 8)
    backup_guard.check_destination(fake_ipod, tmp_path / "elsewhere" / "backup")


def test_uppercase_music_folder_gives_no_duplicates(tmp_path):
    root = tmp_path / "ipod"
    for name, title in (("F00/S0.mp3", "One"), ("F01/S1.mp3", "Two")):
        path = root / "IPOD_CONTROL/MUSIC" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(FIXTURES / "silence.mp3", path)
        audio = mutagen.File(path, easy=True)
        audio.update({"title": [title], "artist": ["A"], "album": ["B"]})
        audio.save()
    dest = tmp_path / "backup"
    run(root, dest)
    assert len(list(dest.rglob("*.mp3"))) == 2
    assert not (dest / "Unreadable").exists()


def test_playlist_lines_are_valid_for_odd_names(fake_ipod, tmp_path):
    songs = [Song(title="line1\nline2", artist="#hash", album="a", path=str(next(fake_ipod.rglob("ABCD.mp3"))))]
    dest = tmp_path / "backup"
    _, present = backup.backup(songs, fake_ipod, dest)
    m3u8.write_playlists(present, fake_ipod, dest, {})
    lines = (dest / "My iPod.m3u8").read_text(encoding="utf-8").splitlines()
    assert lines[1] == "#EXTINF:-1,#hash - line1 line2"
    assert lines[2] == "./#hash/a/line1line2.mp3" or lines[2].startswith("./#hash/a/")
    assert (dest / lines[2]).is_file()


def test_playlist_uses_the_spelling_on_disk(fake_ipod, tmp_path):
    music = fake_ipod / "iPod_Control/Music"
    other = music / "F09/CASE.mp3"
    other.parent.mkdir()
    shutil.copy(music / "F00/ABCD.mp3", other)
    audio = mutagen.File(other, easy=True)
    audio.update({"title": ["Other"], "artist": ["the beatles"], "album": ["past masters"]})
    audio.save()
    dest = tmp_path / "backup"
    songs = scan(fake_ipod)
    backup.backup([s for s in songs if "ABCD" in s.path], fake_ipod, dest)
    _, present = backup.backup(songs, fake_ipod, dest)
    m3u8.write_playlists(present, fake_ipod, dest, {})
    paths = [ln for ln in (dest / "My iPod.m3u8").read_text(encoding="utf-8").splitlines() if ln.startswith("./")]
    for line in paths:  # every component is spelled exactly as listed on disk
        folder = dest
        for part in Path(line).parts:
            assert part in os.listdir(folder)
            folder = folder / part


def test_rename_that_resets_mtime_like_fat_does_not_cause_recopies(fake_ipod, tmp_path, monkeypatch):
    dest = tmp_path / "backup"
    real_rename = os.rename

    def msdos_rename(src, dst):
        real_rename(src, dst)
        os.utime(dst, (1_900_000_000, 1_900_000_000))  # the macOS msdos driver sets "now" on rename

    monkeypatch.setattr(os, "rename", msdos_rename)
    run(fake_ipod, dest)
    result, _ = backup.backup(scan(fake_ipod), fake_ipod, dest)
    assert (result.copied, result.present, result.conflicts) == (0, 6, 0)
    assert len(list(dest.rglob("*.mp3"))) == 3


def test_fresh_destination_playlist_matches_disk_spelling(fake_ipod, tmp_path):
    music = fake_ipod / "iPod_Control/Music"
    other = music / "F09/CASE.mp3"
    other.parent.mkdir()
    shutil.copy(music / "F00/ABCD.mp3", other)
    audio = mutagen.File(other, easy=True)
    audio.update({"title": ["Other"], "artist": ["the beatles"], "album": ["past masters"]})
    audio.save()
    dest = tmp_path / "backup"
    _, present = backup.backup(scan(fake_ipod), fake_ipod, dest)
    m3u8.write_playlists(present, fake_ipod, dest, {})
    lines = [ln for ln in (dest / "My iPod.m3u8").read_text(encoding="utf-8").splitlines() if ln.startswith("./")]
    for line in lines:
        folder = dest
        for part in Path(line).parts:
            assert part in os.listdir(folder)
            folder = folder / part
    assert not any(ln.startswith("./the beatles") for ln in lines)


def fail_second_file(monkeypatch, how):
    real, calls = shutil.copy2, []

    def flaky(source, target):
        calls.append(source)
        if len(calls) == 2:
            if how == "short":
                Path(target).write_bytes(b"short")
                return target
            raise OSError(errno.EIO, "Input/output error")
        return real(source, target)

    monkeypatch.setattr(backup.shutil, "copy2", flaky)


def test_incomplete_copy_is_a_per_file_failure(fake_ipod, tmp_path, monkeypatch, capsys):
    fail_second_file(monkeypatch, "short")
    dest = tmp_path / "backup"
    with pytest.raises(SystemExit) as stop:
        run(fake_ipod, dest)
    assert str(stop.value) == "1 files could not be copied; run the same backup again to retry."
    assert "was incomplete" in capsys.readouterr().out
    assert (dest / "My iPod.m3u8").read_text().count("#EXTINF") == 5
    assert not list(dest.rglob("*.part"))


def test_unstatable_source_is_a_per_file_failure(fake_ipod, tmp_path, monkeypatch, capsys):
    victim = fake_ipod / "iPod_Control/Music/F01/EFGH.m4a"
    real_stat = Path.stat

    def stat(self, *args, **kwargs):
        # Fail only where backup reads sizes and times (scan and is_file keep working).
        if self == victim and sys._getframe(1).f_code.co_name in ("backup", "size_of", "same_file"):
            raise OSError(errno.EIO, "Input/output error")
        return real_stat(self, *args, **kwargs)

    monkeypatch.setattr(Path, "stat", stat)
    dest = tmp_path / "backup"
    with pytest.raises(SystemExit) as stop:
        run(fake_ipod, dest)
    assert str(stop.value) == "1 files could not be copied; run the same backup again to retry."
    assert f"! could not copy {victim}" in capsys.readouterr().out
    assert (dest / "My iPod.m3u8").read_text().count("#EXTINF") == 5


def test_target_that_appears_mid_run_is_skipped_not_overwritten(fake_ipod, tmp_path, monkeypatch, capsys):
    dest = tmp_path / "backup"
    target = backup.plan(scan(fake_ipod), dest)[0][1]
    real = shutil.disk_usage

    def usage(path):  # called after planning, before copying
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"someone else")
        return real(path)

    monkeypatch.setattr(backup.shutil, "disk_usage", usage)
    with pytest.raises(SystemExit):
        run(fake_ipod, dest)
    assert target.read_bytes() == b"someone else"
    assert f"! skipped {target}: it appeared while copying; run backup again" in capsys.readouterr().out


def test_read_only_dest_gives_one_clear_message(fake_ipod, tmp_path, capsys):
    if os.geteuid() == 0:
        pytest.skip("root can write to a read-only folder")
    read_only = tmp_path / "ro"
    read_only.mkdir()
    read_only.chmod(0o555)
    try:
        for dest in (read_only / "new", read_only):
            with pytest.raises(SystemExit) as stop:
                run(fake_ipod, dest)
            assert str(stop.value).startswith(f"Can't write to {dest} (")
            assert str(stop.value).endswith("choose a folder on this Mac or a drive formatted for Mac.")
            assert "could not copy" not in capsys.readouterr().out
    finally:
        read_only.chmod(0o755)


def test_failed_playlist_write_is_a_message_not_a_traceback(fake_ipod, tmp_path, monkeypatch):
    def refuse(*args, **kwargs):
        raise PermissionError(13, "Permission denied")
    monkeypatch.setattr(m3u8, "write_playlists", refuse)
    with pytest.raises(SystemExit) as stop:
        run(fake_ipod, tmp_path / "backup")
    assert str(stop.value).startswith(f"Could not write playlists to {tmp_path / 'backup'} (")


def test_commands_refuse_to_run_from_inside_the_ipod(fake_ipod, monkeypatch, capsys):
    monkeypatch.chdir(fake_ipod)
    before = snapshot(fake_ipod)
    for argv in (["scan", "."], ["review", "--service", "spotify"], ["export-csv"], ["missing", "--service", "spotify"],
                 ["backup", ".", "backup"]):
        with pytest.raises(SystemExit) as stop:
            cli.main(argv)
        assert str(stop.value) == backup_guard.IPOD_REFUSAL
    assert snapshot(fake_ipod) == before
    assert {p.name for p in fake_ipod.iterdir()} == {"iPod_Control"}


def test_doctor_may_run_inside_the_ipod(fake_ipod, monkeypatch):
    monkeypatch.chdir(fake_ipod)
    cli.main(["doctor"])


def test_songs_path_on_the_ipod_is_refused(fake_ipod, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    before = snapshot(fake_ipod)
    with pytest.raises(SystemExit) as stop:
        cli.main(["scan", str(fake_ipod), "--songs", str(fake_ipod / "songs.json")])
    assert str(stop.value) == backup_guard.IPOD_REFUSAL
    assert snapshot(fake_ipod) == before
