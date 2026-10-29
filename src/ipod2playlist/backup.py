"""Copy every audio file off the iPod into a folder on this Mac, plus M3U8 playlists. Never writes to the iPod."""
import os
import shutil
import unicodedata
from dataclasses import dataclass
from pathlib import Path

from pathvalidate import sanitize_filename

from ipod2playlist.itunesdb import relative_key
from ipod2playlist.library import Song
from ipod2playlist.scan import AUDIO_EXTENSIONS

ALL_SONGS_PLAYLIST = "My iPod"
# Headroom under the 255-byte file name limit for " (2)" and ".part".
MAX_NAME = 200
UNREADABLE_FOLDER = "Unreadable"


@dataclass
class BackupResult:
    copied: int = 0
    present: int = 0      # already in DEST with the same size (resume)
    conflicts: int = 0    # a different file already has that name; left alone
    protected: int = 0    # .m4p (FairPlay) files copied
    unreadable: int = 0   # audio files scan() could not read tags from, copied as-is to Unreadable/


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


def unreadable_files(songs: list[Song], root: Path, dest: Path) -> list[tuple[Path, Path]]:
    """Audio files scan() skipped (tags mutagen cannot read). They may be the only copy, so back them up as-is."""
    known = {Path(song.path) for song in songs}
    claimed = set()
    result = []
    for source in sorted((root / "iPod_Control" / "Music").rglob("*")):
        if (source in known or source.name.startswith("._") or source.suffix.lower() not in AUDIO_EXTENSIONS
                or not source.is_file()):
            continue
        target = dest / UNREADABLE_FOLDER / source.name
        number = 1
        while _claim_key(target) in claimed:  # same file name in two Music folders
            number += 1
            target = dest / UNREADABLE_FOLDER / f"{source.stem} ({number}){source.suffix}"
        claimed.add(_claim_key(target))
        result.append((source, target))
    return result


def backup(songs: list[Song], root: Path, dest: Path) -> tuple[BackupResult, list[tuple[Song, Path]]]:
    _check_destination(root, dest)  # before anything is created
    dest.mkdir(parents=True, exist_ok=True)
    result = BackupResult()
    present = []      # songs in DEST and equal to the source: these go in the playlists
    # (source, target, song or None for an unreadable file, label for progress)
    jobs = [(Path(song.path), target, song, f"{song.artist} - {song.title}") for song, target in plan(songs, dest)]
    jobs += [(source, target, None, f"{UNREADABLE_FOLDER}/{target.name}")
             for source, target in unreadable_files(songs, root, dest)]
    to_copy = []
    for source, target, song, label in jobs:
        size = source.stat().st_size
        if not target.exists():
            to_copy.append((source, target, size, song, label))
            continue
        if target.stat().st_size != size:
            result.conflicts += 1
            print(f"! exists, left alone: {target}")
            continue
        result.present += 1
        if song is None:
            result.unreadable += 1
        else:
            present.append((song, target))
    needed = sum(job[2] for job in to_copy)
    free = shutil.disk_usage(dest).free
    if needed > free:
        raise BackupError(f"Not enough space in {dest}: need {needed / 1e9:.1f} GB, {free / 1e9:.1f} GB free.")
    for i, (source, target, size, song, label) in enumerate(to_copy, start=1):
        if target.exists():  # appeared since the check: never overwrite
            result.conflicts += 1
            print(f"! exists, left alone: {target}")
            continue
        _copy_one(source, target, size)
        result.copied += 1
        if song is None:
            result.unreadable += 1
        else:
            present.append((song, target))
        print(f"[{i}/{len(to_copy)}] {label}")
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
    os.replace(part, path)  # replacing is fine: the playlists are generated files; never-overwrite covers audio


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
    if result.unreadable:
        lines.append(f"{result.unreadable} files had unreadable tags and were copied to {UNREADABLE_FOLDER}/")
    if result.protected:
        lines.append(f"{result.protected} songs are .m4p files bought from iTunes with copy protection; "
                     "they were copied but only play on a computer authorised with that Apple ID.")
    return lines
