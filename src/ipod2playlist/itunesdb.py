"""Optional: read the iPod's own iTunesDB with pygpod. Reads a COPY; nothing is ever written to the iPod."""
import json
import logging
import shutil
import sys
import tempfile
import warnings
from dataclasses import dataclass, replace
from pathlib import Path

from ipod2playlist.library import UNKNOWN_ALBUM, UNKNOWN_ARTIST, Song

INSTALL_HINT = ("Reading the iPod's database needs the optional pygpod package. Run the same command with: "
                "uv run --extra itunesdb ipod2playlist ... --itunesdb "
                "(or install with: uv tool install '.[itunesdb]')")


class PygpodMissing(Exception):
    pass


class ITunesDBUnreadable(Exception):
    pass


@dataclass(frozen=True)
class DbTrack:
    title: str
    artist: str
    album: str
    rating: int
    plays: int


def _import_pygpod():
    """Import lazily: most runs never need it. It warns when Pillow/pyusb are absent, which we do not use."""
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            import pygpod
    except ImportError:
        raise PygpodMissing(INSTALL_HINT)
    # pygpod logs warnings with tracebacks and sets no handler, so Python would print them as a crash.
    logging.getLogger("pygpod").addHandler(logging.NullHandler())
    return pygpod


def relative_key(song_path: str, root: Path) -> str:
    return Path(song_path).relative_to(root).as_posix().casefold()


def _track_key(ipod_path: str) -> str:
    """":iPod_Control:Music:F05:UVWX.wav" -> "ipod_control/music/f05/uvwx.wav"."""
    return "/".join(ipod_path.lstrip(":").split(":")).casefold()


def read_itunesdb(root: Path) -> tuple[dict[str, DbTrack], dict[str, list[str]]]:
    pygpod = _import_pygpod()
    from pygpod.device.mountpoint import find_itunesdb  # not in pygpod.__all__; the <0.3 cap guards it

    db_file = find_itunesdb(str(root))
    if db_file is None:
        raise ITunesDBUnreadable(f"no iTunesDB under {root}/iPod_Control/iTunes")
    with tempfile.TemporaryDirectory() as tmp:
        # Only reads touch the iPod. Never use `with Database(...)` or save(): both could write.
        shutil.copytree(db_file.parent, Path(tmp) / "iPod_Control" / "iTunes")
        try:
            db = pygpod.Database(tmp, recover=False, apply_play_counts=True)
        except pygpod.PyGpodError as error:
            raise ITunesDBUnreadable(str(error))
        tracks = {_track_key(t.ipod_path): DbTrack(t.title, t.artist, t.album, t.rating_stars, t.play_count)
                  for t in db.tracks}
        playlists = {}
        for playlist in db.playlists:
            if playlist.is_master or playlist.is_podcast or not playlist.tracks:
                continue
            playlists[playlist.name] = [_track_key(t.ipod_path) for t in playlist.tracks]
    return tracks, playlists


def enrich(songs: list[Song], root: Path, tracks: dict[str, DbTrack]) -> list[Song]:
    """File tags win: the database only fills what the scan had to guess."""
    result = []
    for song in songs:
        track = tracks.get(relative_key(song.path, root))
        if track is None:
            result.append(song)
            continue
        title, artist, album = song.title, song.artist, song.album
        if title == Path(song.path).stem and track.title:
            title = track.title
        if artist == UNKNOWN_ARTIST and track.artist:
            artist = track.artist
        if album == UNKNOWN_ALBUM and track.album:
            album = track.album
        result.append(replace(song, title=title, artist=artist, album=album, rating=track.rating, plays=track.plays))
    return result


def save_playlists(playlists: dict[str, list[str]], path: Path) -> None:
    path.write_text(json.dumps(playlists, indent=2, ensure_ascii=False), encoding="utf-8")


def load_playlists(path: Path) -> dict[str, list[str]]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def read_or_warn(root: Path) -> tuple[dict[str, DbTrack], dict[str, list[str]]]:
    """Shared by scan and backup."""
    try:
        return read_itunesdb(root)
    except PygpodMissing:
        raise SystemExit(INSTALL_HINT)  # the user asked for it explicitly
    except ITunesDBUnreadable as error:
        print(f"warning: could not read the iPod's database ({error}); using file tags only.", file=sys.stderr)
        return {}, {}


def scan_with_db(songs: list[Song], root: Path, tracks: dict[str, DbTrack], playlists: dict[str, list[str]]):
    """Returns (songs most-played first, playlists as name -> song keys, count of songs named from the database)."""
    enriched = enrich(songs, root, tracks)
    named = sum(1 for before, after in zip(songs, enriched)
                if (before.title, before.artist) != (after.title, after.artist))
    ordered = sorted(enriched, key=lambda s: (-s.plays, -s.rating, s.path))
    key_by_path = {relative_key(s.path, root): s.key for s in ordered}
    by_song_key = {name: [key_by_path[k] for k in keys if k in key_by_path] for name, keys in playlists.items()}
    return ordered, by_song_key, named
