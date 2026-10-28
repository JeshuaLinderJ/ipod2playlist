"""Walk an iPod's files and read song tags with mutagen."""

import sys
from pathlib import Path

import mutagen

from ipod2playlist.library import Song

AUDIO_EXTENSIONS = frozenset(
    {".mp3", ".m4a", ".m4p", ".aac", ".flac", ".ogg", ".wav", ".aif", ".aiff"}
)


def _first(audio, key: str) -> str | None:
    values = audio.get(key)
    return values[0].strip() or None if values else None


def read_song(path: Path) -> Song | None:
    """Read one file's tags. Returns None (with a stderr warning) if unreadable."""
    try:
        audio = mutagen.File(path, easy=True)
    except Exception as exc:  # mutagen raises many different error types
        audio, reason = None, str(exc)
    else:
        reason = "not a readable audio file"
    if audio is None:
        print(f"warning: skipping {path}: {reason}", file=sys.stderr)
        return None
    tags = audio.tags or {}
    return Song(
        title=_first(tags, "title") or path.stem,
        artist=_first(tags, "artist") or "Unknown Artist",
        album=_first(tags, "album") or "Unknown Album",
        path=str(path),
    )


def scan(root: Path) -> list[Song]:
    """Read every audio file under root, in sorted order. Does not dedupe."""
    songs = []
    for path in sorted(Path(root).rglob("*")):
        if path.name.startswith("._") or path.suffix.lower() not in AUDIO_EXTENSIONS:
            continue
        if path.is_file() and (song := read_song(path)):
            songs.append(song)
    return songs
