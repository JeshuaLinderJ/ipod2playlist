"""In-memory stand-ins for the Spotify and YouTube API clients."""
import re

_STRICT_QUERY = re.compile(r'track:"(.*)" artist:"(.*)"')


class FakeSpotify:
    """Implements only the spotipy methods SpotifyService calls.

    catalog items look like Spotify track objects:
    {"uri": ..., "name": ..., "artists": [{"name": ...}]}
    """

    def __init__(self, catalog=()):
        self.catalog = list(catalog)
        self.playlists = []  # {"id", "name", "public", "items"}

    def search(self, q, limit=10, type="track"):
        strict = _STRICT_QUERY.fullmatch(q)
        if strict:
            title, artist = (part.casefold() for part in strict.groups())
            hits = [
                t for t in self.catalog
                if t["name"].casefold() == title
                and any(a["name"].casefold() == artist for a in t["artists"])
            ]
        else:
            hits = [t for t in self.catalog if q.casefold() in self._text(t)]
        return {"tracks": {"items": hits[:limit]}}

    def current_user_playlist_create(self, name, public=True):
        playlist = {"id": f"playlist{len(self.playlists) + 1}", "name": name, "public": public, "items": []}
        self.playlists.append(playlist)
        return {"id": playlist["id"]}

    def playlist_add_items(self, playlist_id, items):
        playlist = next(p for p in self.playlists if p["id"] == playlist_id)
        playlist["items"].extend(items)

    @staticmethod
    def _text(track):
        return " ".join([track["name"], *(a["name"] for a in track["artists"])]).casefold()
