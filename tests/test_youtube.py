import json
import stat

import pytest
from googleapiclient.errors import HttpError

from ipod2playlist.library import Song
from ipod2playlist.matching import Candidate
from google.auth.exceptions import RefreshError

from ipod2playlist import youtube
from ipod2playlist.errors import PlaylistGone
from ipod2playlist.youtube import QuotaExceeded, YouTubeService, _reasons, _save_token
from fakes import FakeYouTube


def video(video_id, title, channel):
    return {"id": {"videoId": video_id}, "snippet": {"title": title, "channelTitle": channel}}


SONG = Song(title="Yesterday", artist="The Beatles", album="Help!", path="x.mp3")


def test_search_maps_results_and_unescapes_html():
    fake = FakeYouTube([video("abc", "Guns &amp; Roses &#39;Live&#39;", "GnR VEVO")])
    assert YouTubeService(fake).search(SONG) == [Candidate("abc", "Guns & Roses 'Live'", "GnR VEVO")]
    assert fake.queries == ["The Beatles - Yesterday"]


@pytest.mark.parametrize("public, expected", [(True, "public"), (False, "private")])
def test_create_playlist_privacy(public, expected):
    fake = FakeYouTube()
    playlist_id = YouTubeService(fake).create_playlist("Mix", public=public)
    assert fake.created == [{"id": playlist_id, "privacyStatus": expected, "items": []}]


def test_add_puts_video_in_playlist():
    fake = FakeYouTube()
    service = YouTubeService(fake)
    playlist_id = service.create_playlist("Mix", public=False)
    service.add(playlist_id, "abc")
    assert fake.created[0]["items"] == ["abc"]


@pytest.mark.parametrize("reason", ["quotaExceeded", "dailyLimitExceeded"])
def test_quota_error_becomes_quota_exceeded_in_every_call(reason):
    fake = FakeYouTube(fail_after=0, fail_reason=reason)
    service = YouTubeService(fake)
    for call in (
        lambda: service.search(SONG),
        lambda: service.create_playlist("Mix", public=False),
        lambda: service.add("playlist1", "abc"),
    ):
        with pytest.raises(QuotaExceeded):
            call()


def test_quota_hit_partway_through_keeps_earlier_work():
    fake = FakeYouTube([video("abc", "Yesterday", "Beatles")], fail_after=1)
    service = YouTubeService(fake)
    assert len(service.search(SONG)) == 1
    with pytest.raises(QuotaExceeded):
        service.search(SONG)


def test_other_http_error_propagates_unchanged():
    service = YouTubeService(FakeYouTube(fail_after=0, fail_reason="notFound"))
    with pytest.raises(HttpError) as caught:
        service.add("missing", "abc")
    assert not isinstance(caught.value, QuotaExceeded)
    assert caught.value.status_code == 404


def test_quota_detected_when_body_also_has_details_block():
    # FakeYouTube's body has both "errors" and "details"; the library only exposes "details"
    error = FakeYouTube(fail_reason="quotaExceeded").http_error()
    assert "quotaExceeded" not in [d.get("reason") for d in error.error_details]
    assert "quotaExceeded" in _reasons(error)


def test_reasons_tolerates_non_json_body():
    error = FakeYouTube().http_error()
    error.content = b"<html>bad gateway</html>"
    error.error_details = ""
    assert _reasons(error) == set()


def test_save_token_is_owner_only_even_over_existing_file(tmp_path):
    path = tmp_path / "token.json"
    path.write_text("old")
    path.chmod(0o644)
    _save_token(path, json.dumps({"a": 1}))
    assert json.loads(path.read_text()) == {"a": 1}
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_add_to_deleted_playlist_raises_playlist_gone():
    fake = FakeYouTube()
    service = YouTubeService(fake)
    playlist_id = service.create_playlist("Mix", public=False)
    fake.delete_playlist(playlist_id)
    with pytest.raises(PlaylistGone) as caught:
        service.add(playlist_id, "abc")
    assert caught.value.service == "youtube"
    assert not isinstance(caught.value, HttpError)


def test_add_video_not_found_stays_http_error():
    fake = FakeYouTube()
    service = YouTubeService(fake)
    playlist_id = service.create_playlist("Mix", public=False)
    fake.fail_after, fake.fail_reason = fake.calls, "videoNotFound"
    with pytest.raises(HttpError) as caught:
        service.add(playlist_id, "abc")
    assert not isinstance(caught.value, PlaylistGone)


def test_playlist_exists_true_then_false_after_delete():
    fake = FakeYouTube()
    service = YouTubeService(fake)
    playlist_id = service.create_playlist("Mix", public=False)
    assert service.playlist_exists(playlist_id) is True
    fake.delete_playlist(playlist_id)
    assert service.playlist_exists(playlist_id) is False


def test_playlist_exists_false_for_empty_items():
    class Stub:
        def playlists(self):
            return self

        def list(self, **kw):
            return self

        def execute(self):
            return {"items": []}

    assert YouTubeService(Stub()).playlist_exists("x") is False


def test_playlist_exists_quota_error_becomes_quota_exceeded():
    with pytest.raises(QuotaExceeded):
        YouTubeService(FakeYouTube(fail_after=0)).playlist_exists("x")


def test_playlist_exists_other_http_error_propagates():
    fake = FakeYouTube(fail_after=0, fail_reason="forbidden")
    with pytest.raises(HttpError):
        YouTubeService(fake).playlist_exists("x")


def test_search_typo_keyword_fails_like_the_real_client():
    with pytest.raises(TypeError):
        FakeYouTube().search().list(part="snippet", q="a", type="video", maxresult=5)


class FakeCreds:
    def __init__(self, valid=True, expired=False, refresh_token="r", refresh_error=None, text="{}"):
        self.valid, self.expired, self.refresh_token = valid, expired, refresh_token
        self.refresh_error, self.text = refresh_error, text

    def refresh(self, request):
        if self.refresh_error:
            raise self.refresh_error
        self.valid, self.expired = True, False

    def to_json(self):
        return self.text


@pytest.fixture
def client_env(monkeypatch, tmp_path):
    env = type("Env", (), {})()
    env.logins = []
    env.cached = None
    env.new_creds = FakeCreds(text='{"new": true}')
    env.token = tmp_path / "token.json"
    sentinel = object()
    env.sentinel = sentinel

    class Flow:
        def run_local_server(self, port):
            env.logins.append(port)
            return env.new_creds

    monkeypatch.setattr(youtube.Credentials, "from_authorized_user_file", lambda path, scopes: env.cached)
    monkeypatch.setattr(youtube, "Request", lambda: None)
    monkeypatch.setattr(youtube.InstalledAppFlow, "from_client_secrets_file", lambda path, scopes: Flow())
    monkeypatch.setattr(youtube, "build", lambda *args, **kw: sentinel)
    return env


def test_make_client_valid_cached_token_needs_no_login(client_env):
    client_env.cached = FakeCreds(text='{"cached": true}')
    client_env.token.write_text("old")
    assert youtube.make_client(None, client_env.token) is client_env.sentinel
    assert client_env.logins == []
    assert client_env.token.read_text() == '{"cached": true}'
    assert stat.S_IMODE(client_env.token.stat().st_mode) == 0o600


def test_make_client_refreshes_expired_token_without_login(client_env):
    client_env.cached = FakeCreds(valid=False, expired=True)
    client_env.token.write_text("old")
    youtube.make_client(None, client_env.token)
    assert client_env.logins == []


def test_make_client_logs_in_once_when_refresh_fails(client_env):
    client_env.cached = FakeCreds(valid=False, expired=True, refresh_error=RefreshError("revoked"))
    client_env.token.write_text("old")
    youtube.make_client(None, client_env.token)
    assert client_env.logins == [0]
    assert client_env.token.read_text() == '{"new": true}'


def test_make_client_logs_in_when_no_token_file(client_env):
    youtube.make_client(None, client_env.token)
    assert client_env.logins == [0]
    assert client_env.token.read_text() == '{"new": true}'
