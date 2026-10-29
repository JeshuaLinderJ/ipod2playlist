"""Write M3U8 playlists next to the backed-up music."""
import os
from pathlib import Path

from ipod2playlist.backup import safe_name
from ipod2playlist.backup_guard import claim_key
from ipod2playlist.itunesdb import relative_key
from ipod2playlist.library import Song

ALL_SONGS_PLAYLIST = "My iPod"


def _one_line(text: str) -> str:
    return text.replace("\r", " ").replace("\n", " ")


def write_m3u8(entries: list[tuple[Song, Path]], path: Path) -> None:
    lines = ["#EXTM3U"]
    for song, target in entries:
        lines.append(f"#EXTINF:-1,{_one_line(song.artist)} - {_one_line(song.title)}")
        # "./" so a name starting with "#" is not read as a comment line.
        lines.append("./" + Path(os.path.relpath(target, path.parent)).as_posix())
    # Written beside the final name and renamed, so a crash never leaves half a playlist.
    part = path.with_name(path.name + ".part")
    part.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    os.replace(part, path)  # replacing is fine: the playlists are generated files; never-overwrite covers audio


def write_playlists(present: list[tuple[Song, Path]], root: Path, dest: Path,
                    playlists: dict[str, list[str]]) -> int:
    write_m3u8(present, dest / f"{ALL_SONGS_PLAYLIST}.m3u8")
    written = 1
    by_key = {relative_key(song.path, root): (song, target) for song, target in present}
    used = {claim_key(ALL_SONGS_PLAYLIST)}  # an iPod playlist called "My iPod" must not replace the all-songs file
    for name, keys in playlists.items():
        entries = [by_key[key] for key in keys if key in by_key]
        if not entries:
            continue
        stem, number = safe_name(name), 1
        file_stem = stem
        while claim_key(file_stem) in used:
            number += 1
            file_stem = f"{stem} ({number})"
        used.add(claim_key(file_stem))
        write_m3u8(entries, dest / f"{file_stem}.m3u8")
        written += 1
    return written


def write_playlists_or_exit(present, root: Path, dest: Path, playlists: dict[str, list[str]]) -> int:
    """write_playlists, but a failed write (read-only drive) ends with a one-line message, not a traceback."""
    try:
        return write_playlists(present, root, dest, playlists)
    except OSError as error:
        raise SystemExit(f"Could not write playlists to {dest} ({error}).")
