import pytest
from googleapiclient.errors import HttpError

from ipod2playlist.library import Song
from ipod2playlist.matching import Candidate
from ipod2playlist.youtube import QuotaExceeded, YouTubeService
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
