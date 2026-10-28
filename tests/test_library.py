import csv

import pytest

from ipod2playlist.library import Song, dedupe, load_songs, save_songs, write_tsv


def song(title="Halo", artist="Beyoncé", album="I Am", path="a.mp3"):
    return Song(title, artist, album, path)


def test_key_ignores_case_and_whitespace():
    assert song(title="Halo", artist="Beyoncé").key == song(title="  hALO ", artist="BEYONCÉ").key
    assert song(title="a  b").key == song(title="A b").key


def test_key_differs_for_different_songs():
    assert song(title="Halo").key != song(title="Crazy in Love").key
    assert song(artist="A").key != song(artist="B").key


def test_dedupe_keeps_first_and_order():
    first = song(title="One", path="1.mp3")
    other = song(title="Two", path="2.mp3")
    dup = song(title=" one ", path="3.mp3")
    assert dedupe([first, other, dup]) == [first, other]


def test_save_load_round_trip_non_ascii(tmp_path):
    songs = [song(), song(title="Hoppípolla", artist="Sigur Rós", path="b.m4a")]
    path = tmp_path / "songs.json"
    save_songs(songs, path)
    assert "Sigur Rós" in path.read_text(encoding="utf-8")
    assert load_songs(path) == songs


def test_write_tsv_header_and_row(tmp_path):
    path = tmp_path / "songs.tsv"
    write_tsv([song()], path)
    assert path.read_text(encoding="utf-8").splitlines() == [
        "Title\tArtist\tAlbum\tPath",
        "Halo\tBeyoncé\tI Am\ta.mp3",
    ]


def test_write_tsv_quotes_tabs_and_newlines(tmp_path):
    path = tmp_path / "songs.tsv"
    write_tsv([song(title="Tab\there", artist="New\nLine")], path)
    with open(path, encoding="utf-8", newline="") as f:
        rows = list(csv.reader(f, delimiter="\t"))
    assert len(rows) == 2
    assert rows[1] == ["Tab\there", "New\nLine", "I Am", "a.mp3"]


def test_load_songs_coerces_null_and_numbers(tmp_path):
    path = tmp_path / "songs.json"
    path.write_text('[{"title": 1999, "artist": "Prince", "album": null, "path": "a.mp3"}]')
    assert load_songs(path) == [Song("1999", "Prince", "", "a.mp3")]


@pytest.mark.parametrize("content", [
    '[{"title": "T", "artist": ["x"], "album": "A", "path": "a.mp3"}]',
    "[1]",
    '["x"]',
    '[{"title": "T"}]',
    "{}",
    '"x"',
])
def test_load_songs_rejects_wrong_shapes(tmp_path, content):
    path = tmp_path / "songs.json"
    path.write_text(content)
    with pytest.raises(TypeError):
        load_songs(path)
