import csv

import pytest
from fakes import FakeSpotify

from fakes import http_error

from ipod2playlist import cli, commands, review
from ipod2playlist.errors import PlaylistGone
from ipod2playlist.library import Song, save_songs
from ipod2playlist.matching import Candidate
from ipod2playlist.progress import Progress
from ipod2playlist.spotify import SpotifyService

EVIL = Song('<script>alert(1)</script> & "AC/DC"', "Band <b>&", "Alb", "a.mp3")
JOGA = Song("Jóga", "Björk", "Homogenic", "b.mp3")
PLAIN = Song("So What", "Miles Davis", "Kind of Blue", "c.mp3")
SONGS = [EVIL, JOGA, PLAIN]


@pytest.fixture
def work(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    return tmp_path


def make_progress(tmp_path, service="spotify", guess_for=(JOGA,)):
    progress = Progress(tmp_path / "progress.json")
    progress.set_playlist_id(service, "playlist1")
    for song in SONGS:
        progress.record(service, song.key, "missing")
    for song in guess_for:
        progress.record_maybe(service, song.key, Candidate("spotify:track:SAVED", "Joga (Live)", "Bjork"), 72.5)
    progress.save()
    return progress


def fake_service():
    fake = FakeSpotify()
    fake.current_user_playlist_create("Mix")  # becomes "playlist1"
    return fake, SpotifyService(fake)


def write_csv(path, rows, delimiter=","):
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f, delimiter=delimiter)
        writer.writerow(review.COLUMNS)
        writer.writerows(rows)


def row(answer, key, **edited):
    values = {"Add? (y/n)": answer, "Key": key}
    values.update(edited)
    return [values.get(name, "") for name in review.COLUMNS]


def test_review_makes_no_api_calls_and_writes_files(work, monkeypatch, capsys):
    save_songs(SONGS, work / "songs.json")
    make_progress(work)
    monkeypatch.setattr(commands, "build_service", lambda *a: pytest.fail("review must not log in"))

    cli.main(["review", "--service", "spotify"])

    out = capsys.readouterr().out
    assert out.startswith("Wrote 3 missing songs (1 with a close guess) to spotify_review.html and spotify_review.csv.\n")
    assert out.rstrip().endswith("run: ipod2playlist apply-review --service spotify")
    rows = list(csv.DictReader(open(work / "spotify_review.csv", encoding="utf-8-sig")))
    assert len(rows) == 3
    guessed = [r for r in rows if r["Best guess"]]
    assert [r["Guess link"] for r in guessed] == ["https://open.spotify.com/track/SAVED"]
    assert guessed[0]["Best guess"] == "Joga (Live) by Bjork (72.5)"
    assert all(r["Add? (y/n)"] == "" for r in rows)


def test_html_escapes_untrusted_text_and_has_search_links(work):
    save_songs(SONGS, work / "songs.json")
    progress = make_progress(work)

    review.write_reports(SONGS, progress, "spotify", work)

    page = (work / "spotify_review.html").read_text()
    assert "<script" not in page.lower()
    assert "&lt;script&gt;alert(1)&lt;/script&gt; &amp; &quot;AC/DC&quot;" in page
    assert "Band &lt;b&gt;&amp;" in page
    for song in SONGS:
        spotify_link, youtube_link = review.search_links(song)
        assert spotify_link.replace("&", "&amp;") in page and youtube_link.replace("&", "&amp;") in page
    assert page.index("Joga (Live)") < page.index("So What")  # guessed songs first
    assert 'target="_blank" rel="noopener"' in page


def test_search_links_are_url_encoded():
    assert review.search_links(JOGA) == ("https://open.spotify.com/search/Bj%C3%B6rk%20J%C3%B3ga",
                                         "https://www.youtube.com/results?search_query=Bj%C3%B6rk+J%C3%B3ga")
    spotify_link, _ = review.search_links(EVIL)
    assert "<" not in spotify_link and " " not in spotify_link and "AC%2FDC" in spotify_link


def test_read_decisions_comma_and_semicolon_agree(tmp_path):
    rows = [row("Y ", "a|1"), row("sí", "b|2"), row("yes", "c|3"), row("n", "d|4"), row("", "e|5"), row("maybe", "f|6")]
    write_csv(tmp_path / "comma.csv", rows, ",")
    write_csv(tmp_path / "semi.csv", rows, ";")

    expected = (["a|1", "b|2", "c|3"], ["d|4"])
    assert review.read_decisions(tmp_path / "comma.csv") == expected
    assert review.read_decisions(tmp_path / "semi.csv") == expected


def test_apply_adds_only_the_saved_id_even_if_csv_was_edited(work, capsys):
    progress = make_progress(work)
    fake, service = fake_service()
    write_csv(work / "r.csv", [row("y", JOGA.key, **{"Guess link": "https://open.spotify.com/track/EVIL",
                                                      "Title": "Something else", "Best guess": "EVIL"})])

    result = review.apply_file(work / "r.csv", service, progress)

    assert fake.playlists[0]["items"] == ["spotify:track:SAVED"]
    assert (result.added, result.rejected, result.skipped) == (1, 0, 0)
    reloaded = Progress(work / "progress.json")
    assert reloaded.status("spotify", JOGA.key) == "added" and reloaded.maybe("spotify", JOGA.key) is None
    assert fake.queries == []
    assert "+ added: Joga (Live) by Bjork" in capsys.readouterr().out


def test_apply_skips_accept_without_maybe_and_unknown_keys(work, capsys):
    progress = make_progress(work)
    fake, service = fake_service()
    write_csv(work / "r.csv", [row("y", PLAIN.key), row("y", "evil|unknown", **{"Guess link": "spotify:track:EVIL"})])

    result = review.apply_file(work / "r.csv", service, progress)

    assert fake.playlists[0]["items"] == []
    assert result.skipped == 2 and result.added == 0
    assert "skipped (no saved guess): " + PLAIN.key in capsys.readouterr().out


def test_apply_twice_adds_nothing_the_second_time(work):
    progress = make_progress(work)
    fake, service = fake_service()
    write_csv(work / "r.csv", [row("y", JOGA.key), row("y", JOGA.key)])  # even a repeated row

    first = review.apply_file(work / "r.csv", service, progress)
    second = review.apply_file(work / "r.csv", service, Progress(work / "progress.json"))

    assert (first.added, first.skipped) == (1, 1)
    assert (second.added, second.skipped) == (0, 2)
    assert fake.playlists[0]["items"] == ["spotify:track:SAVED"]


def test_apply_reject_keeps_missing_and_clears_maybe(work):
    progress = make_progress(work)
    fake, service = fake_service()
    write_csv(work / "r.csv", [row("no", JOGA.key)])

    result = review.apply_file(work / "r.csv", service, progress)

    reloaded = Progress(work / "progress.json")
    assert result.rejected == 1
    assert reloaded.status("spotify", JOGA.key) == "missing" and reloaded.maybe("spotify", JOGA.key) is None
    assert fake.playlists[0]["items"] == []


def test_apply_with_playlist_gone_raises_and_exits_3(work, monkeypatch, capsys):
    progress = make_progress(work)
    fake, service = fake_service()
    fake.unfollow("playlist1")
    with pytest.raises(PlaylistGone):
        review.apply_review([JOGA.key], [], service, progress)

    write_csv(work / "spotify_review.csv", [row("y", JOGA.key)])
    monkeypatch.setattr(commands, "build_service", lambda *a: service)
    with pytest.raises(SystemExit) as stopped:
        cli.main(["apply-review", "--service", "spotify"])
    assert stopped.value.code == 3


def test_apply_without_a_playlist_says_so(work):
    progress = Progress(work / "progress.json")
    _, service = fake_service()
    with pytest.raises(SystemExit, match="No spotify playlist yet; run `ipod2playlist spotify` first."):
        review.apply_review([], [], service, progress)


def test_apply_review_missing_file_exits_before_login(work, monkeypatch):
    monkeypatch.setattr(commands, "build_service", lambda *a: pytest.fail("no login for a missing file"))
    with pytest.raises(SystemExit) as stopped:
        cli.main(["apply-review", "--service", "youtube"])
    assert stopped.value.code == "youtube_review.csv not found; run `ipod2playlist review --service youtube` first."


def test_apply_review_has_no_songs_flag(work):
    with pytest.raises(SystemExit) as stopped:
        cli.main(["apply-review", "--service", "spotify", "--songs", "x.json"])
    assert stopped.value.code == 2


def test_apply_review_through_cli_prints_summary(work, monkeypatch, capsys):
    make_progress(work)
    _, service = fake_service()
    write_csv(work / "spotify_review.csv", [row("y", JOGA.key), row("n", EVIL.key)])
    monkeypatch.setattr(commands, "build_service", lambda *a: service)

    cli.main(["apply-review", "--service", "spotify"])

    assert capsys.readouterr().out.splitlines()[-1] == "1 added / 1 rejected / 0 skipped / 0 failed"


def three_guessed(work):
    songs = [Song(f"T{i}", "A", "B", f"{i}.mp3") for i in range(3)]
    progress = Progress(work / "progress.json")
    progress.set_playlist_id("spotify", "playlist1")
    for i, song in enumerate(songs):
        progress.record("spotify", song.key, "missing")
        progress.record_maybe("spotify", song.key, Candidate(f"spotify:track:ID{i}", f"T{i}", "A"), 70)
    progress.save()
    return songs, progress


class FlakyService:
    """Wraps the fake service; add() fails for the ids in `bad`."""
    name = "spotify"

    def __init__(self, inner, bad):
        self.inner, self.bad = inner, set(bad)

    def playlist_exists(self, playlist_id):
        return self.inner.playlist_exists(playlist_id)

    def add(self, playlist_id, item_id):
        if item_id in self.bad:
            raise http_error(404, "videoNotFound")
        self.inner.add(playlist_id, item_id)


def test_one_stale_id_does_not_block_the_rest_and_rerun_retries_only_it(work, capsys):
    songs, progress = three_guessed(work)
    fake, service = fake_service()
    write_csv(work / "r.csv", [row("y", s.key) for s in songs])

    result = review.apply_file(work / "r.csv", FlakyService(service, ["spotify:track:ID1"]), progress)

    assert (result.added, result.failed) == (2, 1)
    assert "! failed: A - T1" in capsys.readouterr().out
    assert review.apply_summary(result).endswith("/ 1 failed")
    again = review.apply_file(work / "r.csv", service, Progress(work / "progress.json"))
    assert (again.added, again.skipped) == (1, 2)
    assert fake.playlists[0]["items"] == ["spotify:track:ID0", "spotify:track:ID2", "spotify:track:ID1"]


def test_three_consecutive_failures_reraise(work):
    songs, progress = three_guessed(work)
    _, service = fake_service()
    bad = [f"spotify:track:ID{i}" for i in range(3)]
    write_csv(work / "r.csv", [row("y", s.key) for s in songs])
    with pytest.raises(Exception):
        review.apply_file(work / "r.csv", FlakyService(service, bad), progress)


def test_non_utf8_file_gets_a_clear_message(tmp_path):
    path = tmp_path / "r.csv"
    path.write_bytes("Add? (y/n),Title,Key\ny,Björk,k\n".encode("cp1252"))
    with pytest.raises(SystemExit) as stopped:
        review.read_decisions(path)
    assert str(stopped.value) == (f"{path} is not saved as UTF-8. In Excel or Numbers, export it as "
                                  "\"CSV UTF-8\" and run apply-review again.")


def test_file_without_key_columns_is_refused(tmp_path):
    path = tmp_path / "r.csv"
    path.write_text("Title,Artist\nx,y\n")
    with pytest.raises(SystemExit) as stopped:
        review.read_decisions(path)
    assert str(stopped.value) == (f"{path} has no \"Key\" and \"Add? (y/n)\" columns; "
                                  "run ipod2playlist review again to get a fresh file.")


def test_formula_text_is_neutralised_in_the_csv_but_apply_still_works(work):
    song = Song("=HYPERLINK(\"http://x\")", "+Artist", "@Alb", "a.mp3")
    progress = Progress(work / "progress.json")
    progress.set_playlist_id("spotify", "playlist1")
    progress.record("spotify", song.key, "missing")
    progress.record_maybe("spotify", song.key, Candidate("spotify:track:G", "=HYPERLINK(\"http://evil\")", "-x"), 70)
    progress.save()

    review.write_reports([song], progress, "spotify", work)

    written = list(csv.DictReader(open(work / "spotify_review.csv", encoding="utf-8-sig")))[0]
    assert written["Title"] == "'=HYPERLINK(\"http://x\")" and written["Artist"] == "'+Artist"
    assert written["Album"] == "'@Alb" and written["Best guess"].startswith("'=HYPERLINK(")
    assert written["Key"] == song.key
    text = (work / "spotify_review.csv").read_text(encoding="utf-8-sig").replace("\n,", "\ny,", 1)
    (work / "marked.csv").write_text(text, encoding="utf-8")
    fake, service = fake_service()
    assert review.apply_file(work / "marked.csv", service, progress).added == 1
    assert fake.playlists[0]["items"] == ["spotify:track:G"]
