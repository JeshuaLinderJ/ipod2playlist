"""Refuse a backup folder that is on the iPod. macOS volumes ignore case and Unicode form, so compare like the Mac."""
import os
import tempfile
import unicodedata
from pathlib import Path

class BackupError(Exception):
    pass


REFUSAL = "The backup folder must not be on the iPod; choose a folder on this Mac, e.g. ~/Music/iPod backup."


def claim_key(text: str) -> str:
    """Two names with the same key are the same file or folder on a Mac."""
    return unicodedata.normalize("NFC", text).casefold()


def _is_mount(path: Path) -> bool:  # separate functions so tests can pretend the iPod is a mounted volume
    return os.path.ismount(path)


def _device_of(path: Path) -> int:
    return os.stat(path).st_dev


def _find_ipod_root(path: Path) -> Path | None:
    """The nearest folder (path included) holding iPod_Control, or None."""
    for folder in [path, *path.parents]:
        try:
            names = os.listdir(folder)
        except OSError:
            continue
        if any(claim_key(name) == "ipod_control" for name in names):
            return folder
    return None


def _ipod_root(root: Path) -> Path:
    """The iPod root, in case ROOT was given as a subfolder; ROOT itself if none is found."""
    return _find_ipod_root(root) or root


IPOD_REFUSAL = "Run ipod2playlist from a folder on your Mac, not from the iPod (it never writes to the iPod)."


def refuse_on_ipod(path: Path) -> None:
    """The tool never writes to the iPod, so refuse a working folder or output file that is on it."""
    if _find_ipod_root(path.resolve()) is not None:
        raise SystemExit(IPOD_REFUSAL)


def refuse_ipod_paths(args) -> None:
    """The current folder (where outputs go by default) and every file path the command was given."""
    refuse_on_ipod(Path.cwd())
    for name in ("songs", "progress", "out", "file", "token"):
        path = getattr(args, name, None)
        if path is not None:
            refuse_on_ipod(path)


def ensure_writable(dest: Path) -> None:
    """Create DEST and prove we can write there; macOS mounts NTFS drives read-only."""
    try:
        dest.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=dest):
            pass
    except OSError as error:
        raise BackupError(f"Can't write to {dest} ({error}); choose a folder on this Mac or a drive formatted "
                          "for Mac.")


def _related(a: Path, b: Path) -> bool:
    """Equal, or one contains the other, ignoring case and Unicode form."""
    first, second = claim_key(str(a)).rstrip(os.sep), claim_key(str(b)).rstrip(os.sep)
    return first == second or first.startswith(second + os.sep) or second.startswith(first + os.sep)


def check_destination(root: Path, dest: Path) -> None:
    resolved_root, resolved_dest = root.resolve(), dest.resolve()
    ipod = _ipod_root(resolved_root)
    if _related(resolved_dest, ipod) or _related(resolved_dest, resolved_root):
        raise BackupError(REFUSAL)
    if _is_mount(ipod):  # same disk as the iPod, however the path is spelled
        existing = resolved_dest
        while not existing.exists():
            existing = existing.parent
        if _device_of(existing) == _device_of(ipod):
            raise BackupError(REFUSAL)

