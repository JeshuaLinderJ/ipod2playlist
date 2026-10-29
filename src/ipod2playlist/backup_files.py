"""File-level helpers for backup: names on disk, the already-copied check, the .part copy."""
import os
import shutil
from pathlib import Path

from ipod2playlist.backup_guard import BackupError, claim_key
from ipod2playlist.scan import AUDIO_EXTENSIONS

MTIME_WINDOW_NS = 2_000_000_000  # rsync's --modify-window for FAT: one rule for every volume


def on_disk(path: Path, dest: Path, names: dict) -> Path:
    """Spell each folder like DEST already does, or like earlier songs in this run did (macOS ignores case),
    so the playlists match the disk even on a first run."""
    current = dest
    parts = path.relative_to(dest).parts
    for index, name in enumerate(parts):
        try:
            existing = os.listdir(current)
        except OSError:
            existing = []
        match = name if name in existing else next((e for e in existing if claim_key(e) == claim_key(name)), name)
        if index < len(parts) - 1:  # folders only; file names are claimed by the caller
            match = names.setdefault(claim_key(str(current / name)), match)
        current = current / match
    return current


def same_file(source: Path, target: Path) -> bool:
    """rsync's quick check: same size, modification time within the window (copy_one sets the time)."""
    a, b = source.stat(), target.stat()
    return a.st_size == b.st_size and abs(a.st_mtime_ns - b.st_mtime_ns) < MTIME_WINDOW_NS


def size_of(path: Path) -> int:
    try:
        return path.stat().st_size
    except OSError:
        return 0


def unreadable_files(songs: list, root: Path) -> list[Path]:
    """Audio files scan() skipped (tags mutagen cannot read); found the way scan walks. May be the only copy."""
    known = {Path(song.path).resolve() for song in songs}
    return [path for path in sorted(Path(root).rglob("*"))
            if not path.name.startswith("._") and path.suffix.lower() in AUDIO_EXTENSIONS
            and path.is_file() and path.resolve() not in known]


def copy_one(source: Path, target: Path, size: int) -> None:
    """Copy to .part and rename, so a target is never half-written. A leftover .part is ours: overwrite it."""
    target.parent.mkdir(parents=True, exist_ok=True)
    part = target.with_name(target.name + ".part")
    shutil.copy2(source, part)
    if part.stat().st_size != size:
        part.unlink()
        raise BackupError(f"Copy of {source} was incomplete; re-run backup.")
    os.rename(part, target)
    info = source.stat()  # some drivers (macOS FAT) reset the time on rename: set it again so a re-run recognises it
    os.utime(target, ns=(info.st_atime_ns, info.st_mtime_ns))
