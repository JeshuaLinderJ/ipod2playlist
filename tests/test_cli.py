import argparse
import json
from types import SimpleNamespace

import pytest
import requests
from fakes import FakeSpotify, FakeYouTube, http_error
from googleapiclient.errors import HttpError
from google.auth.exceptions import RefreshError
from spotipy.exceptions import SpotifyException, SpotifyOauthError

from ipod2playlist import cli, commands, library, youtube
from ipod2playlist.progress import Progress
from ipod2playlist.spotify import SpotifyService
from ipod2playlist.youtube import YouTubeService

# fake_ipod has 5 unique songs; Spotify's catalog lacks the last two.
ON_SPOTIFY = [("Hey Jude", "The Beatles"), ("Paranoid Android", "Radiohead"), ("So What", "Miles Davis")]


def spotify_track(title, artist):
    return {"uri": f"spotify:track:{title}", "name": title, "artists": [{"name": artist}]}


def youtube_video(title, artist):
    return {"id": {"videoId": f"vid-{title}"}, "snippet": {"title": f"{artist} - {title}", "channelTitle": artist}}


@pytest.fixture
def work(tmp_path, monkeypatch):
    """Run in an empty directory so default output paths stay out of the repo."""
    monkeypatch.chdir(tmp_path)
    return tmp_path


def use_services(monkeypatch, **services):
    monkeypatch.setattr(commands, "build_service", lambda name, args: services[name])


def test_scan_writes_deduped_songs_and_tsv(fake_ipod, work, capsys):
    cli.main(["scan", str(fake_ipod)])

    songs = library.load_songs(work / "songs.json")
    assert len(songs) == 5
    assert (work / "songs.tsv").read_text().startswith("Title\tArtist\tAlbum\tPath")
    assert "Found 6 songs, removed 1 duplicates" in capsys.readouterr().out


def test_end_to_end_spotify_then_youtube_with_quota_resume(fake_ipod, work, monkeypatch, capsys):
    cli.main(["scan", str(fake_ipod)])
    songs = library.load_songs(work / "songs.json")
    not_on_spotify = [s for s in songs if s.title != "Hey Jude"]
    tagged = [s for s in not_on_spotify if s.title in ("Paranoid Android", "So What")]
    assert len(not_on_spotify) == 4 and len(tagged) == 2

    spotify_fake = FakeSpotify([spotify_track("Hey Jude", "The Beatles")])
    use_services(monkeypatch, spotify=SpotifyService(spotify_fake))
    cli.main(["spotify", "--name", "Mix"])
    assert "1 added / 4 missing / 0 skipped / 0 failed" in capsys.readouterr().out
    assert [p["name"] for p in spotify_fake.playlists] == ["Mix"]

    cli.main(["missing", "--service", "spotify"])
    report = (work / "spotify_missing.tsv").read_text().splitlines()
    assert sorted(line.split("\t")[0] for line in report[1:]) == sorted(s.title for s in not_on_spotify)

    catalog = [youtube_video(s.title, s.artist) for s in tagged]
    # First run: playlist create + search + add for the first tagged song succeed (3 calls), then
    # quota on the second search.
    quota_fake = FakeYouTube(catalog, fail_after=3)
    use_services(monkeypatch, youtube=YouTubeService(quota_fake))
    with pytest.raises(SystemExit) as stopped:
        cli.main(["youtube", "--only-spotify-missing"])
    assert stopped.value.code == 2
    assert "YouTube quota reached" in capsys.readouterr().err
    progress = Progress(work / "progress.json")
    assert len(progress.keys_with_status("youtube", "added")) == 1

    finishing_fake = FakeYouTube(catalog)
    finishing_fake.created = quota_fake.created  # same playlist on the fake "server"
    use_services(monkeypatch, youtube=YouTubeService(finishing_fake))
    cli.main(["youtube", "--only-spotify-missing"])
    assert "1 added / 2 missing / 1 skipped / 0 failed" in capsys.readouterr().out

    assert len(finishing_fake.created) == 1 and len(finishing_fake.created[0]["items"]) == 2
    progress = Progress(work / "progress.json")
    assert sorted(progress.keys_with_status("youtube", "added")) == sorted(s.key for s in tagged)
    assert sorted(progress.keys_with_status("spotify", "missing")) == sorted(s.key for s in not_on_spotify)
    assert len(progress.keys_with_status("spotify", "added")) == 1


def test_missing_makes_no_api_calls(fake_ipod, work, monkeypatch):
    cli.main(["scan", str(fake_ipod)])

    def fail(name, args):
        raise AssertionError("missing must not build a service")

    monkeypatch.setattr(commands, "build_service", fail)
    cli.main(["missing", "--service", "youtube"])

    assert (work / "youtube_missing.tsv").read_text().strip() == "Title\tArtist\tAlbum\tPath"


def test_hint_when_every_song_fails(fake_ipod, work, monkeypatch, capsys):
    cli.main(["scan", str(fake_ipod)])

    class DeletedPlaylist(SpotifyService):
        def add(self, playlist_id, item_id):
            raise RuntimeError("playlist not found")

    fake = FakeSpotify([spotify_track(t, a) for t, a in ON_SPOTIFY])
    use_services(monkeypatch, spotify=DeletedPlaylist(fake))
    capsys.readouterr()
    cli.main(["spotify"])

    out = capsys.readouterr().out
    assert "0 added / 2 missing / 0 skipped / 3 failed" in out
    assert "--new-playlist" in out and "delete progress.json" not in out


def test_no_hint_when_something_was_added(fake_ipod, work, monkeypatch, capsys):
    cli.main(["scan", str(fake_ipod)])
    use_services(monkeypatch, spotify=SpotifyService(FakeSpotify([spotify_track(*ON_SPOTIFY[0])])))
    cli.main(["spotify"])

    assert "delete" not in capsys.readouterr().out


def test_corrupt_progress_file_exits_cleanly(fake_ipod, work, monkeypatch):
    cli.main(["scan", str(fake_ipod)])
    (work / "progress.json").write_text("{not json")
    use_services(monkeypatch, spotify=SpotifyService(FakeSpotify()))

    with pytest.raises(SystemExit) as stopped:
        cli.main(["spotify"])

    assert stopped.value.code == "Progress file progress.json is corrupt; fix or delete it."


def test_missing_songs_file_exits_with_hint(work, monkeypatch):
    use_services(monkeypatch, spotify=SpotifyService(FakeSpotify()))

    for command in (["spotify"], ["missing", "--service", "spotify"]):
        with pytest.raises(SystemExit) as stopped:
            cli.main(command)
        assert stopped.value.code == "songs.json not found; run `ipod2playlist scan <ipod path>` first."


def test_invalid_songs_file_exits_with_hint(work):
    (work / "songs.json").write_text("{not json")

    with pytest.raises(SystemExit) as stopped:
        cli.main(["missing", "--service", "spotify"])

    assert stopped.value.code == "songs.json is not a valid song list; re-run scan."


def test_scan_of_missing_directory_leaves_songs_untouched(work):
    (work / "songs.json").write_text("[1]")

    with pytest.raises(SystemExit) as stopped:
        cli.main(["scan", str(work / "no-ipod")])

    assert "is not a directory (is the iPod mounted?)" in stopped.value.code
    assert (work / "songs.json").read_text() == "[1]"


def test_unreadable_songs_file_exits_with_hint(work):
    (work / "songs.json").mkdir()

    with pytest.raises(SystemExit) as stopped:
        cli.main(["missing", "--service", "spotify"])

    assert stopped.value.code == "songs.json is not a valid song list; re-run scan."


def test_missing_youtube_client_secrets_exits_with_hint(tmp_path):
    args = argparse.Namespace(client_secrets=tmp_path / "nope.json", token=tmp_path / "token.json")

    with pytest.raises(SystemExit) as stopped:
        commands.build_service("youtube", args)

    assert stopped.value.code == (
        f"{tmp_path / 'nope.json'} not found; download the OAuth client JSON (see README) "
        "or pass --client-secrets."
    )


def test_fake_ipod_is_a_subfolder(fake_ipod, tmp_path):
    assert fake_ipod == tmp_path / "ipod"
    assert [p.name for p in tmp_path.iterdir()] == ["ipod"]


def test_scan_into_missing_folder_exits_and_writes_nothing(fake_ipod, work):
    with pytest.raises(SystemExit) as stopped:
        cli.main(["scan", str(fake_ipod), "--songs", "nowhere/songs.json"])

    assert stopped.value.code == "Folder nowhere does not exist; create it or choose another --songs path."
    assert not (work / "nowhere").exists()
    assert not (work / "songs.json").exists()


@pytest.mark.parametrize("content", [
    '[{"title": "T", "artist": ["x"], "album": "A", "path": "a.mp3"}]',
    "[1]",
    '[{"title": "T"}]',
    "{}",
])
def test_bad_song_list_shapes_exit_cleanly(work, monkeypatch, content):
    (work / "songs.json").write_text(content)
    use_services(monkeypatch, spotify=SpotifyService(FakeSpotify()))

    with pytest.raises(SystemExit) as stopped:
        cli.main(["missing", "--service", "spotify"])

    assert stopped.value.code == "songs.json is not a valid song list; re-run scan."


@pytest.mark.parametrize("content", ["{}", "[]", '"text"'])
def test_wrong_shape_progress_file_exits_cleanly(work, monkeypatch, content):
    (work / "songs.json").write_text("[]")
    (work / "progress.json").write_text(content)

    with pytest.raises(SystemExit) as stopped:
        cli.main(["missing", "--service", "spotify"])

    assert stopped.value.code == "Progress file progress.json is corrupt; fix or delete it."


# --- flag wiring: each test fails if the flag were silently ignored ---

def scan_and_spotify_fake(fake_ipod, monkeypatch, titles=ON_SPOTIFY):
    cli.main(["scan", str(fake_ipod)])
    fake = FakeSpotify([spotify_track(t, a) for t, a in titles])
    use_services(monkeypatch, spotify=SpotifyService(fake))
    return fake


def test_songs_and_progress_flags_are_used(fake_ipod, work, monkeypatch):
    fake = scan_and_spotify_fake(fake_ipod, monkeypatch)
    hey_jude = [s for s in library.load_songs(work / "songs.json") if s.title == "Hey Jude"]
    library.save_songs(hey_jude, work / "tiny.json")
    (work / "progress.json").unlink(missing_ok=True)

    cli.main(["spotify", "--songs", "tiny.json", "--progress", "tiny_progress.json"])

    assert not (work / "progress.json").exists()
    progress = Progress(work / "tiny_progress.json")
    assert progress.keys_with_status("spotify", "added") == [hey_jude[0].key]
    assert len(json.loads((work / "tiny_progress.json").read_text())["services"]["spotify"]["songs"]) == 1
    assert fake.queries and all("Hey Jude" in query for query in fake.queries)


def test_public_flag(fake_ipod, work, monkeypatch):
    fake = scan_and_spotify_fake(fake_ipod, monkeypatch)
    cli.main(["spotify", "--public"])
    assert fake.playlists[0]["public"] is True

    fake = scan_and_spotify_fake(fake_ipod, monkeypatch)
    cli.main(["spotify", "--progress", "other.json"])
    assert fake.playlists[0]["public"] is False

    youtube_fake = FakeYouTube([youtube_video("Hey Jude", "The Beatles")])
    use_services(monkeypatch, youtube=YouTubeService(youtube_fake))
    cli.main(["youtube", "--public"])
    assert youtube_fake.created[0]["privacyStatus"] == "public"


def test_retry_missing_flag(fake_ipod, work, monkeypatch, capsys):
    fake = scan_and_spotify_fake(fake_ipod, monkeypatch, [t for t in ON_SPOTIFY if t[0] != "So What"])
    cli.main(["spotify"])
    capsys.readouterr()

    fake.catalog.append(spotify_track("So What", "Miles Davis"))
    cli.main(["spotify"])
    assert "0 added / 0 missing / 5 skipped / 0 failed" in capsys.readouterr().out

    cli.main(["spotify", "--retry-missing"])
    assert "1 added" in capsys.readouterr().out


def test_new_playlist_forgets_only_that_service(fake_ipod, work, monkeypatch, capsys):
    scan_and_spotify_fake(fake_ipod, monkeypatch)
    cli.main(["spotify"])
    youtube_fake = FakeYouTube()
    use_services(monkeypatch, youtube=YouTubeService(youtube_fake))
    cli.main(["youtube", "--only-spotify-missing"])
    before = json.loads((work / "progress.json").read_text())["services"]
    old_id = before["youtube"]["playlist_id"]
    capsys.readouterr()

    cli.main(["youtube", "--only-spotify-missing", "--new-playlist"])

    out = capsys.readouterr().out
    assert "Starting a new youtube playlist: forgot the saved youtube playlist and results in progress.json" in out
    after = json.loads((work / "progress.json").read_text())["services"]
    assert after["spotify"] == before["spotify"]
    assert after["youtube"]["playlist_id"] not in (None, old_id)
    assert len(youtube_fake.created) == 2
    # The Spotify-missing songs are still selected after the reset.
    progress = Progress(work / "progress.json")
    assert sorted(progress.keys_with_status("youtube", "missing")) == \
        sorted(progress.keys_with_status("spotify", "missing"))
    assert len(progress.keys_with_status("youtube", "missing")) == 2


def test_client_secrets_and_token_reach_make_client(work, monkeypatch):
    (work / "songs.json").write_text('[{"title": "T", "artist": "A", "album": "B", "path": "p.mp3"}]')
    secrets, token = work / "my_secrets.json", work / "my_token.json"
    secrets.write_text("{}")
    token.write_text("{}")
    seen = []

    def fake_make_client(secrets_file, token_file):
        seen.append((secrets_file, token_file))
        return FakeYouTube()

    monkeypatch.setattr(youtube, "make_client", fake_make_client)
    cli.main(["youtube", "--client-secrets", str(secrets), "--token", str(token)])

    assert seen == [(secrets, token)]


def test_scan_rejects_progress_flag(fake_ipod, work):
    with pytest.raises(SystemExit) as stopped:
        cli.main(["scan", str(fake_ipod), "--progress", "x.json"])
    assert stopped.value.code == 2


def test_playlist_gone_exits_3_and_keeps_progress(fake_ipod, work, monkeypatch, capsys):
    cli.main(["scan", str(fake_ipod)])
    progress = Progress(work / "progress.json")
    progress.set_playlist_id("youtube", "deleted-online")
    progress.save()
    before = (work / "progress.json").read_bytes()
    use_services(monkeypatch, youtube=YouTubeService(FakeYouTube()))

    with pytest.raises(SystemExit) as stopped:
        cli.main(["youtube"])

    assert stopped.value.code == 3
    err = capsys.readouterr().err
    assert "no longer exists" in err and "--new-playlist" in err
    assert (work / "progress.json").read_bytes() == before


# --- error boundary ---

def run_expecting_exit(monkeypatch, work, service_name, service):
    (work / "songs.json").write_text('[{"title": "T", "artist": "A", "album": "B", "path": "p.mp3"}]')
    use_services(monkeypatch, **{service_name: service})
    with pytest.raises(SystemExit) as stopped:
        cli.main([service_name])
    return stopped.value.code


def raising_build(error):
    def build(name, args):
        raise error
    return build


class FailingCreate(SpotifyService):
    def __init__(self, error):
        super().__init__(FakeSpotify())
        self.error = error

    def create_playlist(self, name, public):
        raise self.error


class FailingYouTubeCreate(YouTubeService):
    def __init__(self, error):
        super().__init__(FakeYouTube())
        self.error = error

    def create_playlist(self, name, public):
        raise self.error


def test_spotify_login_not_set_up(work, monkeypatch):
    (work / "songs.json").write_text('[{"title": "T", "artist": "A", "album": "B", "path": "p.mp3"}]')
    error = SpotifyOauthError("No client_id. Pass it or set a SPOTIPY_CLIENT_ID environment variable.")
    monkeypatch.setattr(commands, "build_service", raising_build(error))

    with pytest.raises(SystemExit) as stopped:
        cli.main(["spotify"])

    assert stopped.value.code == (
        "Spotify login is not set up: No client_id. Pass it or set a SPOTIPY_CLIENT_ID environment variable. "
        "Check the .env file in this folder (README step 2)."
    )


def test_spotify_refused_request(work, monkeypatch):
    msg = "Check settings on developer.spotify.com/dashboard, the user may not be registered."
    code = run_expecting_exit(monkeypatch, work, "spotify", FailingCreate(SpotifyException(403, -1, msg)))

    assert code == (
        "Spotify refused the request (HTTP 403): Check settings on developer.spotify.com/dashboard, "
        "the user may not be registered. If it says the user may not be registered, add this Spotify "
        "account to your app's users in the Spotify Developer Dashboard (README step 2)."
    )


def test_spotify_refused_keeps_only_the_last_line(work, monkeypatch):
    msg = "https://api.spotify.com/v1/users/x/playlists:\n Forbidden."
    code = run_expecting_exit(monkeypatch, work, "spotify", FailingCreate(SpotifyException(403, -1, msg)))

    assert "(HTTP 403): Forbidden. If it says" in code
    assert "https" not in code and "\n" not in code


def test_youtube_refused_request(work, monkeypatch):
    code = run_expecting_exit(monkeypatch, work, "youtube",
                              FailingYouTubeCreate(http_error(403, "youtubeSignupRequired")))

    assert code == "YouTube refused the request (HTTP 403): boom. Check the YouTube setup (README step 3)."


def test_youtube_refused_reason_ending_in_a_period_has_no_double_period(work, monkeypatch):
    body = {"error": {"code": 403, "message": "The caller does not have permission."}}
    error = HttpError(SimpleNamespace(status=403, reason="Forbidden"), json.dumps(body).encode())
    code = run_expecting_exit(monkeypatch, work, "youtube", FailingYouTubeCreate(error))

    assert code == ("YouTube refused the request (HTTP 403): The caller does not have permission. "
                    "Check the YouTube setup (README step 3).")
    assert ".." not in code


def test_youtube_login_failed(work, monkeypatch):
    (work / "songs.json").write_text('[{"title": "T", "artist": "A", "album": "B", "path": "p.mp3"}]')
    monkeypatch.setattr(commands, "build_service", raising_build(RefreshError("invalid_grant")))

    with pytest.raises(SystemExit) as stopped:
        cli.main(["youtube"])

    assert stopped.value.code == (
        "YouTube login failed: invalid_grant. Delete the saved login (youtube_token.json, or the file given "
        "with --token) and re-run to log in again (README step 3)."
    )


def test_network_error_gets_one_plain_line(work, monkeypatch):
    class Offline(SpotifyService):
        def playlist_exists(self, playlist_id):
            raise requests.exceptions.ConnectionError("Max retries exceeded")

    (work / "progress.json").write_text('{"services": {"spotify": {"playlist_id": "p1", "songs": {}}}}')
    code = run_expecting_exit(monkeypatch, work, "spotify", Offline(FakeSpotify()))

    assert code == ("Could not reach the service (Max retries exceeded). Check the internet connection "
                    "and re-run the same command; progress is saved.")


def test_malformed_client_secrets_exit_cleanly(work, monkeypatch):
    (work / "songs.json").write_text('[{"title": "T", "artist": "A", "album": "B", "path": "p.mp3"}]')
    (work / "client_secrets.json").write_text("{bad")

    def broken(secrets_file, token_file):
        raise ValueError("Expecting property name")

    monkeypatch.setattr(youtube, "make_client", broken)
    with pytest.raises(SystemExit) as stopped:
        cli.main(["youtube"])

    assert stopped.value.code == (
        "Could not read client_secrets.json or youtube_token.json (Expecting property name). Download the "
        "Desktop-app OAuth client again (README step 3), or delete youtube_token.json to log in again."
    )


def test_ctrl_c_stops_with_exit_130(fake_ipod, work, monkeypatch, capsys):
    cli.main(["scan", str(fake_ipod)])

    class Interrupted(SpotifyService):
        def search(self, song):
            raise KeyboardInterrupt

    use_services(monkeypatch, spotify=Interrupted(FakeSpotify()))
    with pytest.raises(SystemExit) as stopped:
        cli.main(["spotify"])

    assert stopped.value.code == 130
    assert "Stopped. Progress is saved" in capsys.readouterr().err


# --- M5: nothing to process means no login ---

def never_built(name, args):
    raise AssertionError("no service should be built when there is nothing to process")


def test_only_spotify_missing_before_spotify_ran(fake_ipod, work, monkeypatch, capsys):
    cli.main(["scan", str(fake_ipod)])
    monkeypatch.setattr(commands, "build_service", never_built)
    capsys.readouterr()

    cli.main(["youtube", "--only-spotify-missing"])

    out = capsys.readouterr().out
    assert "No songs to process." in out
    assert "run `ipod2playlist spotify` first" in out
    assert not (work / "progress.json").exists()


def test_only_spotify_missing_when_spotify_found_everything(fake_ipod, work, monkeypatch, capsys):
    cli.main(["scan", str(fake_ipod)])
    tagged = [s for s in library.load_songs(work / "songs.json") if s.title in ("Hey Jude", "So What")]
    library.save_songs(tagged, work / "songs.json")
    everything = [spotify_track(s.title, s.artist) for s in tagged]
    use_services(monkeypatch, spotify=SpotifyService(FakeSpotify(everything)))
    cli.main(["spotify"])
    monkeypatch.setattr(commands, "build_service", never_built)
    capsys.readouterr()

    cli.main(["youtube", "--only-spotify-missing"])

    out = capsys.readouterr().out
    assert "No songs to process. Spotify found every song." in out
    assert "first" not in out
