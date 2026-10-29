"""The song list: a Song record plus saving, loading and exporting it."""
import csv
import json
from dataclasses import asdict, dataclass
from pathlib import Path

UNKNOWN_ARTIST = "Unknown Artist"
UNKNOWN_ALBUM = "Unknown Album"


def _norm(text: str) -> str:
    return " ".join(text.casefold().split())


@dataclass(frozen=True)
class Song:
    title: str
    artist: str
    album: str
    path: str
    rating: int = 0  # 0-5 stars, from the iPod's database
    plays: int = 0   # play count, from the iPod's database

    @property
    def key(self) -> str:
        return f"{_norm(self.artist)}|{_norm(self.title)}"


def dedupe(songs: list[Song]) -> list[Song]:
    """Keep the first song for each key, preserving order."""
    seen: set[str] = set()
    unique = []
    for song in songs:
        if song.key not in seen:
            seen.add(song.key)
            unique.append(song)
    return unique


def save_songs(songs: list[Song], path: Path) -> None:
    data = [asdict(song) for song in songs]
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def _text(value) -> str:
    """Coerce a JSON value to text: hand-edited files may hold null or numbers."""
    if value is None:
        return ""
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, str):
        return value
    raise TypeError(f"expected text, got {type(value).__name__}")


def load_songs(path: Path) -> list[Song]:
    items = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(items, list):
        raise TypeError("song list must be a JSON list")
    songs = []
    for item in items:
        if not isinstance(item, dict):
            raise TypeError("each song must be a JSON object")
        for number in ("rating", "plays"):
            if number in item and not isinstance(item[number], int):
                raise TypeError(f"{number} must be a whole number")
        songs.append(Song(**{key: value if key in ("rating", "plays") else _text(value)
                             for key, value in item.items()}))
    return songs


def write_tsv(songs: list[Song], path: Path) -> None:
    # csv quotes any field holding a tab, newline or quote; plain rows are unchanged.
    with open(path, "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f, delimiter="\t", lineterminator="\n")
        writer.writerow(["Title", "Artist", "Album", "Path"])
        for s in songs:
            writer.writerow([s.title, s.artist, s.album, s.path])
