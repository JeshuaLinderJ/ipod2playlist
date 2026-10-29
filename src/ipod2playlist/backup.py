"""Copy every audio file off the iPod into a folder on this Mac, plus M3U8 playlists. Never writes to the iPod."""
import os
import shutil
import unicodedata
from dataclasses import dataclass
from pathlib import Path

from pathvalidate import sanitize_filename

from ipod2playlist.itunesdb import relative_key
from ipod2playlist.library import Song

ALL_SONGS_PLAYLIST = "My iPod"
# Headroom under the 255-byte file name limit for " (2)" and ".part".
MAX_NAME = 200


@dataclass
class BackupResult:
    copied: int = 0
    present: int = 0      # already in DEST with the same size (resume)
    conflicts: int = 0    # a different file already has that name; left alone
    protected: int = 0    # .m4p (FairPlay) files copied


class BackupError(Exception):
    pass


def safe_name(text: str) -> str:
    name = sanitize_filename(text, platform="universal", max_len=MAX_NAME).strip()
    return "_" if name in ("", ".", "..") else name


def _claim_key(path: Path) -> str:
    """macOS folders ignore case (and Unicode form), so compare names the way the Mac will."""
    return unicodedata.normalize("NFC", str(path)).casefold()


def plan(songs: list[Song], dest: Path) -> list[tuple[Song, Path]]:
    claimed = set()
    result = []
    for song in songs:
        folder = dest / safe_name(song.artist) / safe_name(song.album)
        suffix = Path(song.path).suffix.lower()
        stem = safe_name(song.title)
        target = folder / (stem + suffix)
        number = 1
        while _claim_key(target) in claimed:
            number += 1
            target = folder / f"{stem} ({number}){suffix}"
        claimed.add(_claim_key(target))
        result.append((song, target))
    return result


def _check_destination(root: Path, dest: Path) -> None:
    resolved_root, resolved_dest = root.resolve(), dest.resolve()
    if resolved_dest == resolved_root or resolved_root in resolved_dest.parents:
        raise BackupError("The backup folder must not be on the iPod; "
                          "choose a folder on this Mac, e.g. ~/Music/iPod backup.")


def _copy_one(source: Path, target: Path, size: int) -> None:
    """Copy to .part and rename, so a target is never half-written. A leftover .part is ours: overwrite it."""
    target.parent.mkdir(parents=True, exist_ok=True)
    part = target.with_name(target.name + ".part")
    shutil.copy2(source, part)
    if part.stat().st_size != size:
        part.unlink()
        raise BackupError(f"Copy of {source} was incomplete; re-run backup.")
    os.rename(part, target)


def backup(songs: list[Song], root: Path, dest: Path) -> tuple[BackupResult, list[tuple[Song, Path]]]:
    _check_destination(root, dest)  # before anything is created
    dest.mkdir(parents=True, exist_ok=True)
    result = BackupResult()
    present = []      # in DEST and equal to the source: these go in the playlists
    to_copy = []
    for song, target in plan(songs, dest):
        size = Path(song.path).stat().st_size
        if not target.exists():
            to_copy.append((song, target, size))
        elif target.stat().st_size == size:
            result.present += 1
            present.append((song, target))
        else:
            result.conflicts += 1
            print(f"! exists, left alone: {target}")
    needed = sum(size for _, _, size in to_copy)
    free = shutil.disk_usage(dest).free
    if needed > free:
        raise BackupError(f"Not enough space in {dest}: need {needed / 1e9:.1f} GB, {free / 1e9:.1f} GB free.")
    for i, (song, target, size) in enumerate(to_copy, start=1):
        if target.exists():  # appeared since the check: never overwrite
            result.conflicts += 1
            print(f"! exists, left alone: {target}")
            continue
        _copy_one(Path(song.path), target, size)
        result.copied += 1
        present.append((song, target))
        print(f"[{i}/{len(to_copy)}] {song.artist} - {song.title}")
    result.protected = sum(1 for song, _ in present if Path(song.path).suffix.lower() == ".m4p")
    return result, present


def write_m3u8(entries: list[tuple[Song, Path]], path: Path) -> None:
    lines = ["#EXTM3U"]
    for song, target in entries:
        lines.append(f"#EXTINF:-1,{song.artist} - {song.title}")
        lines.append(Path(os.path.relpath(target, path.parent)).as_posix())
    # Written beside the final name and renamed, so a crash never leaves half a playlist.
    part = path.with_name(path.name + ".part")
    part.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    os.replace(part, path)


def write_playlists(present: list[tuple[Song, Path]], root: Path, dest: Path,
                    playlists: dict[str, list[str]]) -> int:
    write_m3u8(present, dest / f"{ALL_SONGS_PLAYLIST}.m3u8")
    written = 1
    by_key = {relative_key(song.path, root): (song, target) for song, target in present}
    used = {ALL_SONGS_PLAYLIST.casefold()}  # an iPod playlist called "My iPod" must not replace the all-songs file
    for name, keys in playlists.items():
        entries = [by_key[key] for key in keys if key in by_key]
        if not entries:
            continue
        stem, number = safe_name(name), 1
        file_stem = stem
        while file_stem.casefold() in used:
            number += 1
            file_stem = f"{stem} ({number})"
        used.add(file_stem.casefold())
        write_m3u8(entries, dest / f"{file_stem}.m3u8")
        written += 1
    return written


def summary_lines(result: BackupResult, playlist_count: int, dest: Path) -> list[str]:
    lines = [f"{result.copied} copied / {result.present} already there / {result.conflicts} left alone; "
             f"wrote {playlist_count} playlist file(s) to {dest}"]
    if result.protected:
        lines.append(f"{result.protected} songs are .m4p files bought from iTunes with copy protection; "
                     "they were copied but only play on a computer authorised with that Apple ID.")
    return lines
