"""Copy every audio file off the iPod into a folder on this Mac. Never writes to the iPod."""
import shutil
from dataclasses import dataclass
from pathlib import Path

from pathvalidate import sanitize_filename

from ipod2playlist.backup_files import copy_one, on_disk, same_file, size_of, unreadable_files
from ipod2playlist.backup_guard import BackupError, check_destination, claim_key
from ipod2playlist.library import Song

# Headroom under the 255-byte file name limit for " (2)" and ".part".
MAX_NAME = 200
UNREADABLE_FOLDER = "Unreadable"


@dataclass
class BackupResult:
    copied: int = 0
    present: int = 0      # already in DEST, same size and modification time (resume)
    conflicts: int = 0    # a different file already has that name; left alone, the song gets another name
    protected: int = 0    # .m4p (FairPlay) files in the backup
    unreadable: int = 0   # audio files scan() could not read tags from, copied as-is to Unreadable/
    failed: int = 0       # files that could not be copied this time


def safe_name(text: str) -> str:
    name = sanitize_filename(text, platform="universal", max_len=MAX_NAME).strip()
    return "_" if name in ("", ".", "..") else name


def _numbered(stem: str, suffix: str, number: int) -> str:
    return stem + suffix if number == 1 else f"{stem} ({number}){suffix}"


def _place(source: Path, folder: Path, stem: str, suffix: str, dest: Path, names: dict, result: BackupResult):
    """Pick the file name for one source: its own copy if there, else a free name. Never skips, never overwrites.
    `names` remembers every spelling used in this run, so the folders and files agree with the disk."""
    number = 1
    while True:
        target = on_disk(folder / _numbered(stem, suffix, number), dest, names)
        number += 1
        key = claim_key(str(target))
        if key in names:
            continue
        if not target.exists():
            names[key] = target.name
            return target, True
        try:
            ours = same_file(source, target)
        except OSError:  # the source cannot be read: the copy step reports it
            ours = None
        if ours is not False:
            names[key] = target.name
            return target, ours is None
        result.conflicts += 1  # someone else's file (or another song's) has this name; try the next one
        print(f"! exists, left alone: {target}")


def plan(songs: list[Song], dest: Path) -> list[tuple[Song, Path]]:
    """Where each song goes in DEST as it is now (a clean DEST gives the plain Artist/Album/Title names)."""
    names, result = {}, BackupResult()
    return [(song, _place_song(song, dest, names, result)[0]) for song in songs]


def _place_song(song: Song, dest: Path, names: dict, result: BackupResult):
    source = Path(song.path)
    folder = dest / safe_name(song.artist) / safe_name(song.album)
    return _place(source, folder, safe_name(song.title), source.suffix.lower(), dest, names, result)


def backup(songs: list[Song], root: Path, dest: Path) -> tuple[BackupResult, list[tuple[Song, Path]]]:
    check_destination(root, dest)  # before anything is created
    dest.mkdir(parents=True, exist_ok=True)
    result, names, jobs = BackupResult(), {}, []   # jobs: [source, target, song or None, needs copy]
    for song in songs:
        target, needs_copy = _place_song(song, dest, names, result)
        jobs.append([Path(song.path), target, song, needs_copy])
    for source in unreadable_files(songs, root):
        target, needs_copy = _place(source, dest / UNREADABLE_FOLDER, source.stem, source.suffix, dest, names, result)
        jobs.append([source, target, None, needs_copy])
    to_copy = [job for job in jobs if job[3]]
    needed = sum(size_of(job[0]) for job in to_copy)  # an unreadable source counts 0; the copy step reports it
    free = shutil.disk_usage(dest).free
    if needed > free:
        raise BackupError(f"Not enough space in {dest}: need {needed / 1e9:.1f} GB, {free / 1e9:.1f} GB free.")
    result.present = len(jobs) - len(to_copy)
    for i, job in enumerate(to_copy, start=1):
        source, target, song, _ = job
        job[3] = None  # not in DEST unless the copy below succeeds
        try:
            size = source.stat().st_size
            if target.exists():  # appeared since the check: never overwrite
                print(f"! skipped {target}: it appeared while copying; run backup again")
                result.failed += 1
                continue
            copy_one(source, target, size)
        except (OSError, BackupError) as error:  # one bad file must not stop the rest
            print(f"! could not read {source}: {error}")
            result.failed += 1
            continue
        job[3] = True
        result.copied += 1
        label = f"{song.artist} - {song.title}" if song else f"{UNREADABLE_FOLDER}/{target.name}"
        print(f"[{i}/{len(to_copy)}] {label}")
    in_dest = [job for job in jobs if job[3] is not None]
    result.unreadable = sum(1 for job in in_dest if job[2] is None)
    present = [(job[2], job[1]) for job in in_dest if job[2] is not None]
    result.protected = sum(1 for song, _ in present if Path(song.path).suffix.lower() == ".m4p")
    return result, present


def summary_lines(result: BackupResult, playlist_count: int, dest: Path) -> list[str]:
    lines = [f"{result.copied} copied / {result.present} already there / {result.conflicts} left alone; "
             f"wrote {playlist_count} playlist file(s) to {dest}"]
    if result.unreadable:
        lines.append(f"{result.unreadable} files had unreadable tags and were copied to {UNREADABLE_FOLDER}/")
    if result.protected:
        lines.append(f"{result.protected} songs are .m4p files bought from iTunes with copy protection; "
                     "they were copied but only play on a computer authorised with that Apple ID.")
    return lines
