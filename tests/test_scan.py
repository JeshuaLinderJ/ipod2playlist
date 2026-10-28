from conftest import APPLEDOUBLE_TITLE
from ipod2playlist.scan import read_song, scan


def by_name(songs):
    return {song.path.rsplit("/", 1)[-1]: song for song in songs}


def test_scan_counts_songs_and_keeps_duplicates(fake_ipod):
    songs = scan(fake_ipod)
    assert len(songs) == 6  # 4 tagged + untagged mp3 + wav; junk skipped
    assert [s.title for s in songs].count("Hey Jude") == 2


def test_scan_order_is_sorted_by_path(fake_ipod):
    paths = [s.path for s in scan(fake_ipod)]
    assert paths == sorted(paths)


def test_tags_read_for_each_format(fake_ipod):
    songs = by_name(scan(fake_ipod))
    assert (songs["ABCD.mp3"].title, songs["ABCD.mp3"].artist, songs["ABCD.mp3"].album) == (
        "Hey Jude", "The Beatles", "Past Masters")
    assert (songs["EFGH.m4a"].title, songs["EFGH.m4a"].artist) == ("Paranoid Android", "Radiohead")
    assert (songs["IJKL.flac"].title, songs["IJKL.flac"].album) == ("So What", "Kind of Blue")


def test_untagged_files_fall_back(fake_ipod):
    songs = by_name(scan(fake_ipod))
    for name, stem in [("QRST.mp3", "QRST"), ("UVWX.wav", "UVWX")]:
        song = songs[name]
        assert (song.title, song.artist, song.album) == (stem, "Unknown Artist", "Unknown Album")


def test_junk_files_are_skipped(fake_ipod):
    songs = scan(fake_ipod)
    names = {s.path.rsplit("/", 1)[-1] for s in songs}
    assert "._ABCD.mp3" not in names
    assert APPLEDOUBLE_TITLE not in {s.title for s in songs}
    assert "iTunesDB" not in names


def test_corrupt_mp3_is_excluded_without_crashing(fake_ipod):
    bad = fake_ipod / "iPod_Control/Music/F09/ZZZZ.mp3"
    bad.parent.mkdir(parents=True)
    bad.write_bytes(bytes(range(256)) * 8)
    assert read_song(bad) is None
    assert "ZZZZ.mp3" not in by_name(scan(fake_ipod))
    assert len(scan(fake_ipod)) == 6


def test_read_song_stores_path_as_str(fake_ipod):
    song = read_song(fake_ipod / "iPod_Control/Music/F00/ABCD.mp3")
    assert song.path == str(fake_ipod / "iPod_Control/Music/F00/ABCD.mp3")


def test_directory_named_like_a_song_is_not_returned(fake_ipod, capsys):
    (fake_ipod / "iPod_Control/Music/F07/FAKE.mp3").mkdir(parents=True)
    songs = scan(fake_ipod)
    assert len(songs) == 6
    assert "FAKE.mp3" not in by_name(songs)
    # Without the is_file check mutagen would also reject it (count still 6) but would warn.
    assert "warning: skipping" not in capsys.readouterr().err
