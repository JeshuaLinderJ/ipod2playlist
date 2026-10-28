import pytest
import spotipy

from ipod2playlist import spotify
from ipod2playlist.errors import PlaylistGone
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


def test_add_to_unknown_playlist_raises_playlist_gone():
    with pytest.raises(PlaylistGone) as caught:
        SpotifyService(FakeSpotify()).add("nope", "spotify:track:1")
    assert caught.value.service == "spotify"


def test_add_forbidden_propagates_unchanged():
    class Forbidden:
        def playlist_add_items(self, playlist_id, items):
            raise spotipy.exceptions.SpotifyException(403, -1, "Insufficient scope")

    with pytest.raises(spotipy.exceptions.SpotifyException) as caught:
        SpotifyService(Forbidden()).add("p", "spotify:track:1")
    assert caught.value.http_status == 403


def test_playlist_exists_true_then_false_after_unfollow():
    fake = FakeSpotify()
    service = SpotifyService(fake)
    playlist_id = service.create_playlist("Mix", public=False)
    assert service.playlist_exists(playlist_id) is True
    fake.unfollow(playlist_id)
    assert service.playlist_exists(playlist_id) is False
    service.add(playlist_id, "spotify:track:1")  # real Spotify still accepts the song
    assert fake.playlists[0]["items"] == ["spotify:track:1"]


def test_search_skips_none_items():
    class Client:
        def search(self, q, limit, type):
            return {"tracks": {"items": [None, track("spotify:track:1", "Yesterday", "The Beatles")]}}

    assert len(SpotifyService(Client()).search(SONG)) == 1


def test_scope_has_library_read_and_playlist_modify():
    assert {"user-library-read", "playlist-modify-private", "playlist-modify-public"} <= set(spotify.SCOPE.split())
