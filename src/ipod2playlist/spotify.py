"""Spotify: search for tracks and build a playlist, through a spotipy client."""
import spotipy
from spotipy.oauth2 import SpotifyOAuth

from ipod2playlist.library import Song
from ipod2playlist.matching import Candidate

SCOPE = "playlist-modify-private playlist-modify-public"
SEARCH_LIMIT = 5


class SpotifyService:
    name = "spotify"

    def __init__(self, client):
        self.client = client

    def search(self, song: Song) -> list[Candidate]:
        """Try an exact title+artist field search first, then a plain-text search."""
        strict = f'track:"{song.title}" artist:"{song.artist}"'
        items = self._tracks(strict) or self._tracks(f"{song.title} {song.artist}")
        return [
            Candidate(
                id=item["uri"],
                title=item["name"],
                artist=", ".join(artist["name"] for artist in item["artists"]),
            )
            for item in items
        ]

    def create_playlist(self, name: str, public: bool) -> str:
        return self.client.current_user_playlist_create(name, public=public)["id"]

    def add(self, playlist_id: str, item_id: str) -> None:
        self.client.playlist_add_items(playlist_id, [item_id])

    def _tracks(self, query: str) -> list[dict]:
        return self.client.search(q=query, limit=SEARCH_LIMIT, type="track")["tracks"]["items"]


def make_client() -> spotipy.Spotify:
    """Real client; spotipy reads SPOTIPY_CLIENT_ID/SECRET/REDIRECT_URI and caches the token."""
    return spotipy.Spotify(auth_manager=SpotifyOAuth(scope=SCOPE))
