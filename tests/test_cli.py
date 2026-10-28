import argparse

import pytest
from fakes import FakeSpotify, FakeYouTube

from ipod2playlist import cli, library
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
    monkeypatch.setattr(cli, "_build_service", lambda name, args: services[name])


def test_scan_writes_deduped_songs_and_tsv(fake_ipod, work, capsys):
    cli.main(["scan", str(fake_ipod)])

    songs = library.load_songs(work / "songs.json")
    assert len(songs) == 5
    assert (work / "songs.tsv").read_text().startswith("Title\tArtist\tAlbum\tPath")
    assert "Found 6 songs, removed 1 duplicates" in capsys.readouterr().out


def test_end_to_end_spotify_then_youtube_with_quota_resume(fake_ipod, work, monkeypatch, capsys):
    cli.main(["scan", str(fake_ipod)])
    songs = library.load_songs(work / "songs.json")
    on_spotify = {title for title, _ in ON_SPOTIFY}
    not_on_spotify = [s for s in songs if s.title not in on_spotify]
    assert len(not_on_spotify) == 2

    spotify_fake = FakeSpotify([spotify_track(t, a) for t, a in ON_SPOTIFY])
    use_services(monkeypatch, spotify=SpotifyService(spotify_fake))
    cli.main(["spotify", "--name", "Mix"])
    assert "3 added / 2 missing / 0 skipped / 0 failed" in capsys.readouterr().out
    assert [p["name"] for p in spotify_fake.playlists] == ["Mix"]

    cli.main(["missing", "--service", "spotify"])
    report = (work / "spotify_missing.tsv").read_text().splitlines()
    assert sorted(line.split("\t")[0] for line in report[1:]) == sorted(s.title for s in not_on_spotify)

    catalog = [youtube_video(s.title, s.artist) for s in not_on_spotify]
    # First run: playlist create + search + add for song one succeed (3 calls), then quota.
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
    assert "1 added / 0 missing / 1 skipped / 0 failed" in capsys.readouterr().out

    assert len(finishing_fake.created) == 1 and len(finishing_fake.created[0]["items"]) == 2
    progress = Progress(work / "progress.json")
    assert sorted(progress.keys_with_status("youtube", "added")) == sorted(s.key for s in not_on_spotify)
    assert sorted(progress.keys_with_status("spotify", "missing")) == sorted(s.key for s in not_on_spotify)
    assert len(progress.keys_with_status("spotify", "added")) == 3


def test_missing_makes_no_api_calls(fake_ipod, work, monkeypatch):
    cli.main(["scan", str(fake_ipod)])

    def fail(name, args):
        raise AssertionError("missing must not build a service")

    monkeypatch.setattr(cli, "_build_service", fail)
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
    assert "delete progress.json" in out


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
        cli._build_service("youtube", args)

    assert stopped.value.code == (
        f"{tmp_path / 'nope.json'} not found; download the OAuth client JSON (see README) "
        "or pass --client-secrets."
    )
