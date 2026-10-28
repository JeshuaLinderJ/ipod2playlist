"""In-memory stand-ins for the Spotify and YouTube API clients."""
import json
import re
from types import SimpleNamespace

import spotipy
from googleapiclient.errors import HttpError

_STRICT_QUERY = re.compile(r'track:"(.*)" artist:"(.*)"')


def http_error(status: int, reason: str) -> HttpError:
    """A real HttpError shaped like Google's error body."""
    body = {"error": {
        "code": status,
        "message": "boom",
        "errors": [{"reason": reason}],
        # Google also sends this block; the library reads it INSTEAD of "errors" for error_details
        "details": [{"@type": "type.googleapis.com/google.rpc.ErrorInfo", "reason": "RATE_LIMIT_EXCEEDED"}],
    }}
    resp = SimpleNamespace(status=status, reason="Error")
    return HttpError(resp, json.dumps(body).encode())


class FakeSpotify:
    """Implements only the spotipy methods SpotifyService calls.

    catalog items look like Spotify track objects:
    {"uri": ..., "name": ..., "artists": [{"name": ...}]}
    """

    def __init__(self, catalog=()):
        self.catalog = list(catalog)
        self.playlists = []  # {"id", "name", "public", "items", "followed"}
        self.queries = []

    def search(self, q, limit=10, type="track"):
        self.queries.append(q)
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
        playlist = {"id": f"playlist{len(self.playlists) + 1}", "name": name, "public": public, "items": [], "followed": True}
        self.playlists.append(playlist)
        return {"id": playlist["id"]}

    def playlist_add_items(self, playlist_id, items):
        # An unfollowed (deleted in the app) playlist still accepts songs, like real Spotify.
        playlist = next((p for p in self.playlists if p["id"] == playlist_id), None)
        if playlist is None:
            raise spotipy.exceptions.SpotifyException(404, -1, "Resource not found")
        playlist["items"].extend(items)

    def unfollow(self, playlist_id):
        """Test helper: what deleting a playlist in the Spotify app does."""
        next(p for p in self.playlists if p["id"] == playlist_id)["followed"] = False

    def current_user_saved_items(self, uris):
        followed = {f"spotify:playlist:{p['id']}" for p in self.playlists if p["followed"]}
        return [uri in followed for uri in uris]

    @staticmethod
    def _text(track):
        return " ".join([track["name"], *(a["name"] for a in track["artists"])]).casefold()


class _Request:
    """What client.<resource>().<method>(...) returns; execute() runs the call."""

    def __init__(self, fake, action):
        self.fake = fake
        self.action = action

    def execute(self):
        fake = self.fake
        fake.calls += 1
        if fake.fail_after is not None and fake.calls > fake.fail_after:
            raise fake.http_error()
        return self.action()


class FakeYouTube:
    """Implements only the googleapiclient calls YouTubeService makes.

    catalog items look like YouTube search results:
    {"id": {"videoId": ...}, "snippet": {"title": ..., "channelTitle": ...}}
    fail_after=N makes every execute() after the first N raise a real HttpError
    with the given fail_reason (e.g. "quotaExceeded").
    """

    def __init__(self, catalog=(), fail_after=None, fail_reason="quotaExceeded"):
        self.catalog = list(catalog)
        self.fail_after = fail_after
        self.fail_reason = fail_reason
        self.calls = 0
        self.queries = []
        self.created = []  # playlists made: {"id", "privacyStatus", "items"}

    def http_error(self):
        not_found = {"notFound", "playlistNotFound", "videoNotFound"}
        return http_error(404 if self.fail_reason in not_found else 403, self.fail_reason)

    def search(self):
        return self

    def list(self, part, q, type, maxResults):
        self.queries.append(q)
        return _Request(self, lambda: {"items": self.catalog[:maxResults]})

    def delete_playlist(self, playlist_id):
        """Test helper: the user deletes the playlist on youtube.com."""
        self.created[:] = [p for p in self.created if p["id"] != playlist_id]

    def playlists(self):
        return _Playlists(self)

    def playlistItems(self):
        return _PlaylistItems(self)


class _Playlists:
    def __init__(self, fake):
        self.fake = fake

    def insert(self, part, body):
        def action():
            playlists = self.fake.created
            playlists.append({
                "id": f"playlist{len(playlists) + 1}",
                "privacyStatus": body["status"]["privacyStatus"],
                "items": [],
            })
            return {"id": playlists[-1]["id"]}
        return _Request(self.fake, action)

    def list(self, part, id, maxResults):
        def action():
            if not any(p["id"] == id for p in self.fake.created):
                raise http_error(404, "playlistNotFound")  # documented behaviour for an unknown id
            return {"items": [{"id": id}]}
        return _Request(self.fake, action)


class _PlaylistItems:
    def __init__(self, fake):
        self.fake = fake

    def insert(self, part, body):
        def action():
            snippet = body["snippet"]
            playlist = next((p for p in self.fake.created if p["id"] == snippet["playlistId"]), None)
            if playlist is None:
                raise http_error(404, "playlistNotFound")
            playlist["items"].append(snippet["resourceId"]["videoId"])
            return {}
        return _Request(self.fake, action)
