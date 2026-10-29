"""Copy every audio file off the iPod into a folder on this Mac. Never writes to the iPod."""
import os
import shutil
from dataclasses import dataclass
from pathlib import Path

from pathvalidate import sanitize_filename

from ipod2playlist.backup_guard import BackupError, check_destination, claim_key
from ipod2playlist.library import Song
from ipod2playlist.scan import AUDIO_EXTENSIONS

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


def _on_disk(path: Path, dest: Path) -> Path:
    """Spell each folder and file the way DEST already does (macOS ignores case), so playlists match the disk."""
    current = dest
    for name in path.relative_to(dest).parts:
        try:
            existing = os.listdir(current)
        except OSError:
            existing = []
        match = name if name in existing else next((e for e in existing if claim_key(e) == claim_key(name)), name)
        current = current / match
    return current


def _same_file(source: Path, target: Path) -> bool:
    """rsync's quick check: same size and modification time (copy2 keeps the time). A target time with no
    fraction means the drive rounds times (FAT and HFS+ keep 1-2 s), so allow 2 s; otherwise they must agree."""
    a, b = source.stat(), target.stat()
    slack = 2_000_000_000 if b.st_mtime_ns % 1_000_000_000 == 0 else 1_000_000
    return a.st_size == b.st_size and abs(a.st_mtime_ns - b.st_mtime_ns) < slack


def _place(source: Path, folder: Path, stem: str, suffix: str, dest: Path, claimed: set, result: BackupResult):
    """Pick the file name for one source: its own copy if there, else a free name. Never skips, never overwrites."""
    number = 1
    while True:
        target = _on_disk(folder / _numbered(stem, suffix, number), dest)
        number += 1
        if claim_key(str(target)) in claimed:
            continue
        if not target.exists():
            claimed.add(claim_key(str(target)))
            return target, True
        if _same_file(source, target):
            claimed.add(claim_key(str(target)))
            return target, False
        result.conflicts += 1  # someone else's file (or another song's) has this name; try the next one
        print(f"! exists, left alone: {target}")


def plan(songs: list[Song], dest: Path) -> list[tuple[Song, Path]]:
    """Where each song goes in DEST as it is now (a clean DEST gives the plain Artist/Album/Title names)."""
    claimed, result = set(), BackupResult()
    return [(song, _place_song(song, dest, claimed, result)[0]) for song in songs]


def _place_song(song: Song, dest: Path, claimed: set, result: BackupResult):
    source = Path(song.path)
    folder = dest / safe_name(song.artist) / safe_name(song.album)
    return _place(source, folder, safe_name(song.title), source.suffix.lower(), dest, claimed, result)


def unreadable_files(songs: list[Song], root: Path) -> list[Path]:
    """Audio files scan() skipped (tags mutagen cannot read); found the way scan walks. May be the only copy."""
    known = {Path(song.path).resolve() for song in songs}
    return [path for path in sorted(Path(root).rglob("*"))
            if not path.name.startswith("._") and path.suffix.lower() in AUDIO_EXTENSIONS
            and path.is_file() and path.resolve() not in known]


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
    check_destination(root, dest)  # before anything is created
    dest.mkdir(parents=True, exist_ok=True)
    result, claimed, jobs = BackupResult(), set(), []   # jobs: [source, target, song or None, needs copy]
    for song in songs:
        target, needs_copy = _place_song(song, dest, claimed, result)
        jobs.append([Path(song.path), target, song, needs_copy])
    for source in unreadable_files(songs, root):
        target, needs_copy = _place(source, dest / UNREADABLE_FOLDER, source.stem, source.suffix, dest, claimed, result)
        jobs.append([source, target, None, needs_copy])
    to_copy = [job for job in jobs if job[3]]
    needed = sum(job[0].stat().st_size for job in to_copy)
    free = shutil.disk_usage(dest).free
    if needed > free:
        raise BackupError(f"Not enough space in {dest}: need {needed / 1e9:.1f} GB, {free / 1e9:.1f} GB free.")
    result.present = len(jobs) - len(to_copy)
    for i, job in enumerate(to_copy, start=1):
        source, target, song, _ = job
        try:
            if target.exists():  # appeared since the check: never overwrite
                raise FileExistsError(f"{target} appeared during the backup")
            _copy_one(source, target, source.stat().st_size)
        except OSError as error:
            print(f"! could not read {source}: {error}")
            result.failed += 1
            job[3] = None  # not in DEST
            continue
        result.copied += 1
        print(f"[{i}/{len(to_copy)}] " + (f"{song.artist} - {song.title}" if song else f"{UNREADABLE_FOLDER}/{target.name}"))
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
