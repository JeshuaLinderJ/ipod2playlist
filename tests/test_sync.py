import pytest
from fakes import FakeSpotify, FakeYouTube

from ipod2playlist.errors import PlaylistGone
from ipod2playlist.library import UNKNOWN_ARTIST, Song
from ipod2playlist.progress import Progress
from ipod2playlist.spotify import SpotifyService
from ipod2playlist.sync import SyncResult, pending, search_count, searchable, sync
from ipod2playlist.youtube import QuotaExceeded, YouTubeService

TITLES = ["Alpha", "Bravo", "Charlie", "Delta"]
ARTIST = "The Band"


def songs(titles=TITLES):
    return [Song(title=t, artist=ARTIST, album="Album", path=f"/{t}.mp3") for t in titles]


def spotify_track(title):
    return {"uri": f"spotify:track:{title}", "name": title, "artists": [{"name": ARTIST}]}


def youtube_video(title):
    return {"id": {"videoId": f"vid-{title}"}, "snippet": {"title": f"{ARTIST} - {title}", "channelTitle": ARTIST}}


def spotify_service(titles=TITLES):
    fake = FakeSpotify(catalog=[spotify_track(t) for t in titles])
    return SpotifyService(fake), fake


def test_full_run_adds_found_songs_and_records_missing(tmp_path):
    service, fake = spotify_service(["Alpha", "Bravo", "Charlie"])  # Delta is not in the catalog
    progress = Progress(tmp_path / "progress.json")

    result = sync(songs(), service, progress, "My Mix")

    assert result == SyncResult(added=3, missing=1, skipped=0, failed=0)
    assert [p["name"] for p in fake.playlists] == ["My Mix"]
    assert len(fake.playlists[0]["items"]) == 3
    assert progress.keys_with_status("spotify", "missing") == [songs()[3].key]


def test_second_run_skips_everything_and_creates_no_playlist(tmp_path):
    service, fake = spotify_service()
    path = tmp_path / "progress.json"
    sync(songs(), service, Progress(path), "My Mix")

    result = sync(songs(), service, Progress(path), "My Mix")

    assert result == SyncResult(added=0, missing=0, skipped=4, failed=0)
    assert len(fake.playlists) == 1
    assert len(fake.playlists[0]["items"]) == 4


def test_quota_error_saves_progress_and_rerun_resumes_same_playlist(tmp_path):
    catalog = [youtube_video(t) for t in TITLES]
    path = tmp_path / "progress.json"
    # create_playlist = 1 call, then 2 calls (search + add) per song: the 3rd song's search fails
    first = FakeYouTube(catalog=catalog, fail_after=5)

    with pytest.raises(QuotaExceeded):
        sync(songs(), YouTubeService(first), Progress(path), "My Mix")

    saved = Progress(path)
    assert [saved.status("youtube", s.key) for s in songs()] == ["added", "added", None, None]
    playlist_id = saved.playlist_id("youtube")

    second = FakeYouTube(catalog=catalog)
    second.created.append({"id": playlist_id, "privacyStatus": "private", "items": []})  # exists on YouTube already
    result = sync(songs(), YouTubeService(second), saved, "My Mix")

    assert result == SyncResult(added=2, missing=0, skipped=2, failed=0)
    assert len(second.created) == 1  # still only the existing playlist
    assert len(second.created[0]["items"]) == 2
    assert Progress(path).playlist_id("youtube") == playlist_id


def test_quota_error_creating_playlist_propagates(tmp_path):
    service = YouTubeService(FakeYouTube(fail_after=0))
    progress = Progress(tmp_path / "progress.json")

    with pytest.raises(QuotaExceeded):
        sync(songs(), service, progress, "My Mix")

    assert progress.playlist_id("youtube") is None


def test_playlist_id_is_saved_before_the_first_song(tmp_path):
    path = tmp_path / "progress.json"
    service = YouTubeService(FakeYouTube(fail_after=1))  # playlist created, first search fails

    with pytest.raises(QuotaExceeded):
        sync(songs(), service, Progress(path), "My Mix")

    assert Progress(path).playlist_id("youtube") == "playlist1"


def test_retry_missing_researches_missing_songs_only(tmp_path):
    path = tmp_path / "progress.json"
    service, fake = spotify_service(["Alpha", "Bravo"])
    sync(songs(), service, Progress(path), "My Mix")  # Charlie and Delta are missing

    # without the flag, missing songs stay skipped even if they are now findable
    fake.catalog.append(spotify_track("Charlie"))
    assert sync(songs(), service, Progress(path), "My Mix").skipped == 4

    result = sync(songs(), service, Progress(path), "My Mix", retry_missing=True)

    assert result == SyncResult(added=1, missing=1, skipped=2, failed=0)
    assert Progress(path).status("spotify", songs()[2].key) == "added"


class FlakySpotify(FakeSpotify):
    """Search raises for one title, like a transient network error."""

    def search(self, q, limit=10, type="track"):
        if "Bravo" in q:
            raise ConnectionError("network blip")
        return super().search(q, limit, type)


def test_transient_error_on_one_song_is_counted_and_left_unrecorded(tmp_path, capsys):
    fake = FlakySpotify(catalog=[spotify_track(t) for t in TITLES])
    progress = Progress(tmp_path / "progress.json")

    result = sync(songs(), SpotifyService(fake), progress, "My Mix")

    assert result == SyncResult(added=3, missing=0, skipped=0, failed=1)
    assert progress.status("spotify", songs()[1].key) is None
    assert "Bravo" in capsys.readouterr().out


def test_youtube_playlist_deleted_since_last_run_stops_with_zero_searches(tmp_path):
    path = tmp_path / "progress.json"
    first = FakeYouTube(catalog=[youtube_video(t) for t in TITLES])
    sync(songs(["Alpha"]), YouTubeService(first), Progress(path), "My Mix")
    first.delete_playlist(Progress(path).playlist_id("youtube"))
    first.queries.clear()

    with pytest.raises(PlaylistGone):
        sync(songs(), YouTubeService(first), Progress(path), "My Mix")

    assert first.queries == []
    assert first.created == []  # no replacement playlist
    assert Progress(path).status("youtube", songs()[1].key) is None


def test_spotify_playlist_unfollowed_stops_with_zero_searches(tmp_path):
    service, fake = spotify_service()
    path = tmp_path / "progress.json"
    sync(songs(["Alpha"]), service, Progress(path), "My Mix")
    fake.unfollow(Progress(path).playlist_id("spotify"))
    fake.queries.clear()

    with pytest.raises(PlaylistGone):
        sync(songs(), service, Progress(path), "My Mix")

    assert fake.queries == []
    assert len(fake.playlists) == 1


class DeletedOnSecondAdd(YouTubeService):
    """The playlist is deleted on youtube.com while the run is going."""

    adds = 0

    def add(self, playlist_id, item_id):
        self.adds += 1
        if self.adds == 2:
            raise PlaylistGone("youtube")
        super().add(playlist_id, item_id)


def test_playlist_deleted_mid_run_stops_instead_of_failing_every_song(tmp_path):
    path = tmp_path / "progress.json"
    fake = FakeYouTube(catalog=[youtube_video(t) for t in TITLES])

    with pytest.raises(PlaylistGone):
        sync(songs(), DeletedOnSecondAdd(fake), Progress(path), "My Mix")

    assert len(fake.queries) == 2  # swallowing PlaylistGone as a per-song failure would search all 4
    saved = Progress(path)
    assert [saved.status("youtube", s.key) for s in songs()] == ["added", None, None, None]


def test_empty_song_list_touches_nothing(tmp_path):
    service, fake = spotify_service()
    path = tmp_path / "progress.json"

    result = sync([], service, Progress(path), "My Mix")

    assert result == SyncResult(0, 0, 0, 0)
    assert fake.playlists == []
    assert not path.exists()


def test_songs_without_an_artist_are_recorded_missing_and_not_searched(tmp_path, capsys):
    service, fake = spotify_service()
    untagged = [
        Song(title="Alpha", artist=UNKNOWN_ARTIST, album="", path="/a.mp3"),
        Song(title="Bravo", artist="", album="", path="/b.mp3"),
    ]
    progress = Progress(tmp_path / "progress.json")

    result = sync(untagged, service, progress, "My Mix")

    assert result == SyncResult(added=0, missing=2, skipped=0, failed=0)
    assert fake.queries == []
    assert [progress.status("spotify", s.key) for s in untagged] == ["missing", "missing"]
    assert "not searched" in capsys.readouterr().out


class FailingSearch(FakeSpotify):
    """Search raises for the given titles, like a dropped network."""

    def __init__(self, failing, catalog=()):
        super().__init__(catalog)
        self.failing = failing

    def search(self, q, limit=10, type="track"):
        if any(title in q for title in self.failing):
            raise ConnectionError("network down")
        return super().search(q, limit, type)


def test_three_failures_in_a_row_stop_the_run_and_save_progress(tmp_path):
    fake = FailingSearch(["Bravo", "Charlie", "Delta"], catalog=[spotify_track("Alpha")])
    path = tmp_path / "progress.json"

    with pytest.raises(ConnectionError):
        sync(songs(), SpotifyService(fake), Progress(path), "My Mix")

    assert Progress(path).status("spotify", songs()[0].key) == "added"


def test_a_success_between_failures_resets_the_count(tmp_path):
    fake = FailingSearch(["Alpha", "Charlie", "Delta"], catalog=[spotify_track("Bravo")])

    result = sync(songs(), SpotifyService(fake), Progress(tmp_path / "progress.json"), "My Mix")

    assert result == SyncResult(added=1, missing=0, skipped=0, failed=3)


def test_dry_run_changes_nothing_and_says_what_would_happen(tmp_path, capsys):
    service, fake = spotify_service(["Alpha", "Bravo"])  # 2 of 4 songs are in the catalog
    path = tmp_path / "progress.json"

    result = sync(songs(), service, Progress(path), "My Mix", dry_run=True)

    assert (result.added, result.missing) == (2, 2)
    assert fake.playlists == []
    assert not path.exists()
    assert "would add: The Band - Alpha  ->  Alpha by The Band" in capsys.readouterr().out


def test_dry_run_never_calls_create_add_record_or_save(tmp_path, monkeypatch):
    service, _ = spotify_service()
    progress = Progress(tmp_path / "progress.json")

    def forbidden(*args, **kwargs):
        raise AssertionError("a dry run must not change anything")

    for owner, method in [(service, "create_playlist"), (service, "add"), (service, "playlist_exists"),
                          (progress, "record"), (progress, "save"), (progress, "set_playlist_id")]:
        monkeypatch.setattr(owner, method, forbidden)

    assert sync(songs(), service, progress, "My Mix", dry_run=True).added == 4


def test_dry_run_after_real_run_skips_everything_and_searches_nothing(tmp_path):
    service, fake = spotify_service()
    path = tmp_path / "progress.json"
    sync(songs(), service, Progress(path), "My Mix")
    fake.queries.clear()
    before = path.read_bytes()

    result = sync(songs(), service, Progress(path), "My Mix", dry_run=True)

    assert result.skipped == 4
    assert fake.queries == []
    assert path.read_bytes() == before


def test_dry_run_counts_untagged_as_missing_without_writing(tmp_path):
    service, fake = spotify_service()
    untagged = [Song(title="Alpha", artist=UNKNOWN_ARTIST, album="", path="/a.mp3"),
                Song(title="Bravo", artist="", album="", path="/b.mp3")]
    path = tmp_path / "progress.json"

    result = sync(untagged, service, Progress(path), "My Mix", dry_run=True)

    assert result.missing == 2
    assert fake.queries == []
    assert not path.exists()


@pytest.mark.parametrize("retry_missing", [False, True])
def test_pending_agrees_with_sync(tmp_path, retry_missing):
    service, _ = spotify_service(["Alpha", "Charlie", "Delta"])
    path = tmp_path / "progress.json"
    sync(songs(["Alpha", "Bravo"]), service, Progress(path), "My Mix")  # Alpha added, Bravo missing
    progress = Progress(path)

    expected = len(pending(songs(), progress, "spotify", retry_missing))
    result = sync(songs(), service, progress, "My Mix", retry_missing=retry_missing)

    assert expected == result.added + result.missing + result.failed


def test_untagged_songs_are_not_searchable_or_counted(tmp_path):
    progress = Progress(tmp_path / "progress.json")
    untagged = [Song(title="A", artist=UNKNOWN_ARTIST, album="", path="/a.mp3"),
                Song(title="B", artist="", album="", path="/b.mp3")]

    assert not any(searchable(s) for s in untagged)
    assert searchable(songs()[0])
    assert search_count(untagged, progress, "youtube") == 0
    assert search_count(untagged + songs(), progress, "youtube") == 4


def test_near_miss_is_remembered_in_a_real_run_but_never_added(tmp_path, capsys):
    video = {"id": {"videoId": "vid1"}, "snippet": {"title": "Oasis - Dont Look Back", "channelTitle": "Oasis"}}
    fake = FakeYouTube(catalog=[video])
    song = Song(title="Don't Look Back in Anger", artist="Oasis", album="", path="/a.mp3")
    progress = Progress(tmp_path / "progress.json")

    result = sync([song], YouTubeService(fake), progress, "Mix")

    assert result.missing == 1 and result.added == 0
    saved = progress.maybe("youtube", song.key)
    assert (saved["id"], saved["title"], saved["artist"]) == ("vid1", "Oasis - Dont Look Back", "Oasis")
    assert 60 <= saved["score"] < 80
    assert fake.created[0]["items"] == []
    assert "(close match saved for review)" in capsys.readouterr().out


def test_dry_run_mentions_near_miss_but_records_nothing(tmp_path, capsys):
    video = {"id": {"videoId": "vid1"}, "snippet": {"title": "Oasis - Dont Look Back", "channelTitle": "Oasis"}}
    song = Song(title="Don't Look Back in Anger", artist="Oasis", album="", path="/a.mp3")
    path = tmp_path / "progress.json"

    sync([song], YouTubeService(FakeYouTube(catalog=[video])), Progress(path), "Mix", dry_run=True)

    assert "(close match saved for review)" in capsys.readouterr().out
    assert not path.exists()
