import shlex
from pathlib import Path

from ipod2playlist import cli, commands, doctor, library
from ipod2playlist.library import Song
from ipod2playlist.progress import Progress

FULL_ENV = {"SPOTIPY_CLIENT_ID": "id", "SPOTIPY_CLIENT_SECRET": "secret",
            "SPOTIPY_REDIRECT_URI": "http://127.0.0.1:8080/callback"}


class Setup:
    """A folder standing in for the user's, with a separate fake /Volumes."""

    def __init__(self, tmp_path):
        self.folder = tmp_path / "work"
        self.folder.mkdir()
        self.volumes = tmp_path / "volumes"
        self.volumes.mkdir()
        self.songs = self.folder / "songs.json"
        self.progress = self.folder / "progress.json"
        self.secrets = self.folder / "client_secrets.json"
        self.token = self.folder / "youtube_token.json"

    def report(self, env=None):
        return doctor.report(self.songs, self.progress, self.secrets, self.token,
                             {} if env is None else env, volumes=self.volumes)

    def next_line(self, env=None):
        lines = [line for line in self.report(env) if line.startswith("Next:")]
        assert len(lines) == 1
        return lines[0]


def song(title, artist="Artist"):
    return Song(title=title, artist=artist, album="Album", path=f"/{title}.mp3")


def test_find_ipods_only_returns_folders_with_ipod_control(tmp_path):
    (tmp_path / "Jo's iPod" / "iPod_Control").mkdir(parents=True)
    (tmp_path / "USB").mkdir()
    assert doctor.find_ipods(tmp_path) == [tmp_path / "Jo's iPod"]


def test_quoted():
    assert doctor.quoted(Path("/Volumes/Jo's iPod")) == '"/Volumes/Jo\'s iPod"'
    dollar = Path("/Volumes/$HOME iPod")
    assert doctor.quoted(dollar) == shlex.quote(str(dollar))


def test_empty_env_names_each_spotify_variable(tmp_path):
    setup = Setup(tmp_path)
    lines = setup.report()
    for name in doctor.SPOTIFY_VARS:
        assert any(line.startswith("!!   ") and name in line for line in lines)
    assert sum("is not set" in line for line in lines) == 3


def test_next_step_without_songs_or_ipod(tmp_path):
    setup = Setup(tmp_path)
    assert setup.next_line() == 'Next: plug in the iPod, then ipod2playlist scan "/Volumes/<iPod name>"'


def test_next_step_scan_names_the_ipod(tmp_path):
    setup = Setup(tmp_path)
    (setup.volumes / "Jo's iPod" / "iPod_Control").mkdir(parents=True)
    assert setup.next_line() == f'Next: ipod2playlist scan "{setup.volumes}/Jo\'s iPod"'


def test_next_step_is_spotify_fix_once_songs_exist(tmp_path):
    setup = Setup(tmp_path)
    library.save_songs([song("a")], setup.songs)
    assert setup.next_line() == "Next: fix the Spotify settings above (README step 2)."


def test_missing_and_invalid_song_list(tmp_path):
    setup = Setup(tmp_path)
    assert f"!!   {setup.songs} not found." in setup.report()
    setup.songs.write_text("not json")
    assert f"!!   {setup.songs} is not a valid song list; re-run scan." in setup.report()


def test_localhost_redirect_is_warned(tmp_path):
    setup = Setup(tmp_path)
    env = {**FULL_ENV, "SPOTIPY_REDIRECT_URI": "http://localhost:8888/callback"}
    lines = setup.report(env)
    assert '!!   SPOTIPY_REDIRECT_URI uses "localhost"; use http://127.0.0.1:8080/callback (README step 2).' in lines
    assert "ok   Spotify settings found" in lines


def test_client_file_kinds(tmp_path):
    setup = Setup(tmp_path)
    assert f"note {setup.secrets} not found; only needed for YouTube (README step 3)." in setup.report()
    setup.secrets.write_text('{"web": {}}')
    assert f"!!   {setup.secrets} is not a Desktop-app OAuth client file (README step 3)." in setup.report()
    setup.secrets.write_text('{"installed": {}}')
    assert "ok   YouTube client file found" in setup.report()
    setup.token.write_text("{}")
    assert f"ok   Logged in to YouTube before ({setup.token})" in setup.report()


def test_progress_lines_and_corrupt_file(tmp_path):
    setup = Setup(tmp_path)
    progress = Progress(setup.progress)
    progress.record("spotify", "a|b", "added")
    progress.record("spotify", "c|d", "missing")
    progress.set_playlist_id("youtube", "pl")
    progress.save()
    lines = setup.report()
    assert "ok   spotify: 1 added, 1 missing, playlist not created yet" in lines
    assert "ok   youtube: 0 added, 0 missing, playlist saved" in lines
    setup.progress.write_text("[]")
    assert f"!!   Progress file {setup.progress} is corrupt; fix or delete it." in setup.report()


def test_corrupt_progress_next_step_names_the_file(tmp_path):
    setup = Setup(tmp_path)
    library.save_songs([song("a")], setup.songs)
    setup.progress.write_text("not json")
    next_line = setup.next_line(FULL_ENV)
    assert str(setup.progress) in next_line
    assert "spotify" not in next_line


def test_estimate_skips_untagged_and_next_is_youtube(tmp_path):
    setup = Setup(tmp_path)
    songs = [song("a"), song("b"), song("c", artist=library.UNKNOWN_ARTIST), song("d")]
    library.save_songs(songs, setup.songs)
    progress = Progress(setup.progress)
    progress.set_playlist_id("spotify", "sp")
    for s in songs[:3]:
        progress.record("spotify", s.key, "missing")
    progress.record("spotify", songs[3].key, "added")
    progress.save()
    setup.secrets.write_text('{"installed": {}}')
    lines = setup.report(FULL_ENV)
    estimate = [line for line in lines if "day(s)" in line]
    assert estimate == ["note About 1 day(s) of free YouTube quota for 2 songs (150 units each, 10000 a day)."]
    assert setup.next_line(FULL_ENV) == "Next: ipod2playlist youtube --only-spotify-missing"


def test_next_steps_spotify_then_all_done(tmp_path):
    setup = Setup(tmp_path)
    library.save_songs([song("a")], setup.songs)
    assert setup.next_line(FULL_ENV) == "Next: ipod2playlist spotify --dry-run  (then ipod2playlist spotify)"
    progress = Progress(setup.progress)
    progress.record("spotify", song("a").key, "added")
    progress.save()
    assert setup.next_line(FULL_ENV).startswith("Next: all done.")


def test_premium_note_always_present(tmp_path):
    setup = Setup(tmp_path)
    assert doctor.SPOTIFY_NOTE in setup.report()
    assert doctor.SPOTIFY_NOTE in setup.report(FULL_ENV)


def test_report_writes_nothing(tmp_path):
    setup = Setup(tmp_path)
    setup.report(FULL_ENV)
    assert not setup.progress.exists()
    assert list(setup.folder.iterdir()) == []


def test_cli_doctor_makes_no_calls_and_writes_nothing(tmp_path, monkeypatch, capsys):
    setup = Setup(tmp_path)
    library.save_songs([song("a")], setup.songs)
    monkeypatch.setattr(doctor, "VOLUMES", setup.volumes)  # never read the real /Volumes

    def fail(*args, **kwargs):
        raise AssertionError("doctor must not build a service")

    monkeypatch.setattr(commands, "build_service", fail)
    before = sorted(p.name for p in setup.folder.iterdir())
    cli.main(["doctor", "--songs", str(setup.songs), "--progress", str(setup.progress),
              "--client-secrets", str(setup.secrets), "--token", str(setup.token)])
    assert sorted(p.name for p in setup.folder.iterdir()) == before
    output = capsys.readouterr().out
    assert f"!!   No iPod found in {setup.volumes}." in output
    assert "Next:" in output


def test_next_step_continues_interrupted_spotify_run(tmp_path):
    setup = Setup(tmp_path)
    library.save_songs([song("a"), song("b")], setup.songs)
    progress = Progress(setup.progress)
    progress.record("spotify", song("a").key, "added")
    progress.save()
    assert setup.next_line(FULL_ENV) == "Next: ipod2playlist spotify (it continues where it stopped)."


def test_next_step_fixes_youtube_client_file_when_songs_pending(tmp_path):
    setup = Setup(tmp_path)
    library.save_songs([song("a")], setup.songs)
    progress = Progress(setup.progress)
    progress.record("spotify", song("a").key, "missing")
    progress.save()
    expected = "Next: fix the YouTube client file above (README step 3)."
    assert setup.next_line(FULL_ENV) == expected  # file absent
    setup.secrets.write_text('{"web": {}}')
    assert setup.next_line(FULL_ENV) == expected  # wrong kind


def test_malformed_service_block_is_reported_as_corrupt(tmp_path):
    setup = Setup(tmp_path)
    for text in ('{"services": {"spotify": null}}', '{"services": {"spotify": {"songs": []}}}'):
        setup.progress.write_text(text)
        assert f"!!   Progress file {setup.progress} is corrupt; fix or delete it." in setup.report()
