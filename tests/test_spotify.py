from ipod2playlist.library import Song
from ipod2playlist.matching import Candidate
from ipod2playlist.spotify import SpotifyService
from fakes import FakeSpotify


def track(uri, name, *artists):
    return {"uri": uri, "name": name, "artists": [{"name": a} for a in artists]}


SONG = Song(title="Yesterday", artist="The Beatles", album="Help!", path="x.mp3")


def test_strict_hit_returns_only_exact_match():
    fake = FakeSpotify([
        track("spotify:track:1", "Yesterday", "The Beatles"),
        track("spotify:track:2", "Yesterday Once More", "The Beatles"),
    ])
    assert SpotifyService(fake).search(SONG) == [Candidate("spotify:track:1", "Yesterday", "The Beatles")]


def test_strict_miss_falls_back_to_loose_search():
    # artist differs, so the exact field search misses; the plain-text search finds it
    fake = FakeSpotify([track("spotify:track:3", "Yesterday", "The Beatles Tribute")])
    assert [c.id for c in SpotifyService(fake).search(SONG)] == ["spotify:track:3"]


def test_total_miss_returns_empty_list():
    fake = FakeSpotify([track("spotify:track:9", "Other", "Someone")])
    assert SpotifyService(fake).search(SONG) == []


def test_multiple_artists_are_joined():
    fake = FakeSpotify([track("spotify:track:4", "Yesterday", "The Beatles", "Guest")])
    [candidate] = SpotifyService(fake).search(SONG)
    assert candidate.artist == "The Beatles, Guest"


def test_create_playlist_honours_public():
    fake = FakeSpotify()
    service = SpotifyService(fake)
    private_id = service.create_playlist("Mine", public=False)
    public_id = service.create_playlist("Ours", public=True)
    assert private_id != public_id
    assert [(p["name"], p["public"]) for p in fake.playlists] == [("Mine", False), ("Ours", True)]


def test_add_records_item_on_playlist():
    fake = FakeSpotify()
    service = SpotifyService(fake)
    playlist_id = service.create_playlist("Mine", public=False)
    service.add(playlist_id, "spotify:track:1")
    assert fake.playlists[0]["items"] == ["spotify:track:1"]
