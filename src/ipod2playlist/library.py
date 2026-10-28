"""The song list: a Song record plus saving, loading and exporting it."""
import json
from dataclasses import asdict, dataclass
from pathlib import Path


def _norm(text: str) -> str:
    return " ".join(text.casefold().split())


@dataclass(frozen=True)
class Song:
    title: str
    artist: str
    album: str
    path: str

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


def load_songs(path: Path) -> list[Song]:
    return [Song(**item) for item in json.loads(path.read_text(encoding="utf-8"))]


def write_tsv(songs: list[Song], path: Path) -> None:
    lines = ["Title\tArtist\tAlbum\tPath"]
    lines += [f"{s.title}\t{s.artist}\t{s.album}\t{s.path}" for s in songs]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
