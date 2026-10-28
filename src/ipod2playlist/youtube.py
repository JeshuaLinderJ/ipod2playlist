"""YouTube: search for videos and build a playlist, through a googleapiclient client."""
import html
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from ipod2playlist.library import Song
from ipod2playlist.matching import Candidate

SCOPES = ["https://www.googleapis.com/auth/youtube"]
SEARCH_LIMIT = 5
QUOTA_REASONS = {"quotaExceeded", "dailyLimitExceeded"}


class QuotaExceeded(Exception):
    """YouTube's daily API quota is used up; resume tomorrow."""


class YouTubeService:
    name = "youtube"

    def __init__(self, client):
        self.client = client

    def search(self, song: Song) -> list[Candidate]:
        request = self.client.search().list(
            part="snippet", q=f"{song.artist} - {song.title}", type="video", maxResults=SEARCH_LIMIT
        )
        return [
            Candidate(
                id=item["id"]["videoId"],
                title=html.unescape(item["snippet"]["title"]),
                artist=item["snippet"]["channelTitle"],
            )
            for item in _execute(request).get("items", [])
        ]

    def create_playlist(self, name: str, public: bool) -> str:
        body = {
            "snippet": {"title": name},
            "status": {"privacyStatus": "public" if public else "private"},
        }
        return _execute(self.client.playlists().insert(part="snippet,status", body=body))["id"]

    def add(self, playlist_id: str, item_id: str) -> None:
        body = {
            "snippet": {
                "playlistId": playlist_id,
                "resourceId": {"kind": "youtube#video", "videoId": item_id},
            }
        }
        _execute(self.client.playlistItems().insert(part="snippet", body=body))


def _execute(request) -> dict:
    """Run a request, turning a quota HttpError into QuotaExceeded (the one place this happens)."""
    try:
        return request.execute()
    except HttpError as error:
        # error_details is the "errors" list from Google's error body, e.g. [{"reason": "quotaExceeded"}]
        details = error.error_details if isinstance(error.error_details, list) else []
        if any(d.get("reason") in QUOTA_REASONS for d in details):
            raise QuotaExceeded(error.reason) from error
        raise


def make_client(secrets_file: Path, token_file: Path):
    """Real client; reuses the cached token when valid, otherwise asks the user to log in."""
    creds = None
    if token_file.exists():
        creds = Credentials.from_authorized_user_file(str(token_file), SCOPES)
    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
    elif not creds or not creds.valid:
        creds = InstalledAppFlow.from_client_secrets_file(str(secrets_file), SCOPES).run_local_server(port=0)
    token_file.write_text(creds.to_json())
    return build("youtube", "v3", credentials=creds)
