from pathlib import Path
import shutil

import mutagen
import pytest

FIXTURES = Path(__file__).parent / "fixtures"

# (path relative to the iPod root, tags). None = leave the file untagged.
IPOD_FILES = [
    ("iPod_Control/Music/F00/ABCD.mp3", {"title": "Hey Jude", "artist": "The Beatles", "album": "Past Masters"}),
    ("iPod_Control/Music/F01/EFGH.m4a", {"title": "Paranoid Android", "artist": "Radiohead", "album": "OK Computer"}),
    ("iPod_Control/Music/F02/IJKL.flac", {"title": "So What", "artist": "Miles Davis", "album": "Kind of Blue"}),
    # Same artist and title as ABCD.mp3 (scan keeps it; dedupe is a later step).
    ("iPod_Control/Music/F03/MNOP.mp3", {"title": "Hey Jude", "artist": "The Beatles", "album": "1"}),
    ("iPod_Control/Music/F04/QRST.mp3", None),
    # The .wav fixture cannot take easy tags, so it is also untagged.
    ("iPod_Control/Music/F05/UVWX.wav", None),
]
# Junk that is not a song: the iTunes database.
IPOD_JUNK = ["iPod_Control/iTunes/iTunesDB"]
# AppleDouble file: a valid tagged mp3, so only the "._" name filter can exclude it.
APPLEDOUBLE = "iPod_Control/Music/F00/._ABCD.mp3"
APPLEDOUBLE_TITLE = "APPLEDOUBLE SHOULD NOT APPEAR"


@pytest.fixture
def fake_ipod(tmp_path) -> Path:
    """A disk-mode iPod Classic tree in tmp_path / "ipod"; returns the iPod root.

    Files tests write under tmp_path (songs.json, backups) lie outside the iPod root."""
    root = tmp_path / "ipod"
    for rel, tags in IPOD_FILES + [(APPLEDOUBLE, {"title": APPLEDOUBLE_TITLE, "artist": "X", "album": "X"})]:
        dest = root / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(FIXTURES / f"silence{dest.suffix}", dest)
        if tags:
            audio = mutagen.File(dest, easy=True)
            audio.update({k: [v] for k, v in tags.items()})
            audio.save()
    for rel in IPOD_JUNK:
        junk = root / rel
        junk.parent.mkdir(parents=True, exist_ok=True)
        junk.write_bytes(b"\x00junk\xff" * 50)
    return root
