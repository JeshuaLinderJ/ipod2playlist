"""`doctor`: a read-only setup check. No API calls, no writes; it says what to do next."""
import json
import shlex
import sys
from pathlib import Path
from typing import Mapping

from ipod2playlist import library, sync
from ipod2playlist.progress import Progress
from ipod2playlist.youtube import DAILY_QUOTA, INSERT_COST, SEARCH_COST, days_needed

VOLUMES = Path("/Volumes")
SPOTIFY_VARS = ("SPOTIPY_CLIENT_ID", "SPOTIPY_CLIENT_SECRET", "SPOTIPY_REDIRECT_URI")
SPOTIFY_NOTE = ("note Spotify needs the app's owner to have Spotify Premium, and a new app allows at most 5 users; "
                "add each person's account in the app's settings on the Spotify Developer Dashboard.")


def find_ipods(volumes: Path = VOLUMES) -> list[Path]:
    if not volumes.is_dir():
        return []
    return sorted(p for p in volumes.iterdir() if (p / "iPod_Control").is_dir())


def quoted(path: Path) -> str:
    """Quote a path for the shell. Plain double quotes cover spaces and apostrophes (the common cases)."""
    text = str(path)
    if any(char in text for char in '"$`\\'):
        return shlex.quote(text)
    return f'"{text}"'


def _spotify_lines(env: Mapping[str, str]) -> tuple[list[str], bool]:
    lines = []
    for name in SPOTIFY_VARS:
        if not env.get(name):
            lines.append(f"!!   {name} is not set; add it to the .env file (README step 2).")
    complete = not lines
    if complete:
        lines.append("ok   Spotify settings found")
    if "localhost" in env.get("SPOTIPY_REDIRECT_URI", ""):
        lines.append('!!   SPOTIPY_REDIRECT_URI uses "localhost"; use http://127.0.0.1:8080/callback (README step 2).')
        complete = False
    lines.append(SPOTIFY_NOTE)
    return lines, complete


def _youtube_lines(secrets_path: Path, token_path: Path) -> tuple[list[str], bool]:
    lines = []
    client_ok = False
    if not secrets_path.exists():
        lines.append(f"note {secrets_path} not found; only needed for YouTube (README step 3).")
    else:
        try:
            data = json.loads(secrets_path.read_text())
            client_ok = isinstance(data, dict) and "installed" in data
        except (OSError, ValueError):
            pass
        if client_ok:
            lines.append("ok   YouTube client file found")
        else:
            lines.append(f"!!   {secrets_path} is not a Desktop-app OAuth client file (README step 3).")
    if token_path.exists():
        lines.append(f"ok   Logged in to YouTube before ({token_path})")
    return lines, client_ok


def _progress_lines(progress_path: Path) -> tuple[list[str], Progress | None]:
    lines = []
    try:
        progress = Progress(progress_path)  # reading only; save() is never called
        for service in progress.services():
            added = len(progress.keys_with_status(service, "added"))
            missing = len(progress.keys_with_status(service, "missing"))
            playlist = "saved" if progress.playlist_id(service) else "not created yet"
            lines.append(f"ok   {service}: {added} added, {missing} missing, playlist {playlist}")
    except (OSError, ValueError, AttributeError):  # AttributeError: a hand-edited service block of the wrong shape
        return [f"!!   Progress file {progress_path} is corrupt; fix or delete it."], None
    return lines, progress


def report(songs_path: Path, progress_path: Path, secrets_path: Path, token_path: Path,
           env: Mapping[str, str], volumes: Path = VOLUMES) -> list[str]:
    lines = []
    ipods = find_ipods(volumes)
    for ipod in ipods:
        lines.append(f"ok   iPod found: {ipod}")
    if not ipods:
        lines.append(f'!!   No iPod found in {volumes}. Plug it in and tick "Enable disk use" in Finder (README step 4).')

    songs = None
    try:
        songs = library.load_songs(songs_path)
        lines.append(f"ok   {len(songs)} songs in {songs_path}")
    except FileNotFoundError:
        lines.append(f"!!   {songs_path} not found.")
    except (OSError, ValueError, TypeError):
        lines.append(f"!!   {songs_path} is not a valid song list; re-run scan.")

    spotify_lines, spotify_ok = _spotify_lines(env)
    youtube_lines, client_ok = _youtube_lines(secrets_path, token_path)
    progress_lines, progress = _progress_lines(progress_path)
    lines += spotify_lines + youtube_lines + progress_lines

    services = progress.services() if progress else []
    youtube_pending = False
    if songs is not None and progress is not None:
        candidates = songs
        if "spotify" in services:  # YouTube only gets what Spotify could not find
            missing_keys = set(progress.keys_with_status("spotify", "missing"))
            candidates = [song for song in songs if song.key in missing_keys]
        count = sync.search_count(candidates, progress, "youtube")
        youtube_pending = count > 0
        days = days_needed(count, progress.playlist_id("youtube") is not None)
        lines.append(f"note About {days} day(s) of free YouTube quota for {count} songs "
                     f"({SEARCH_COST + INSERT_COST} units each, {DAILY_QUOTA} a day).")

    if sys.version_info < (3, 11):
        lines.append("note Python 3.10 works, but Google's library prints a warning about it; "
                     "Python 3.11 or newer avoids that.")

    if songs is None:
        if ipods:
            lines.append(f"Next: ipod2playlist scan {quoted(ipods[0])}")
        else:
            lines.append('Next: plug in the iPod, then ipod2playlist scan "/Volumes/<iPod name>"')
    elif progress is None:  # corrupt: spotify/youtube would stop with the same message
        lines.append(f"Next: fix or delete {quoted(progress_path)}, then run ipod2playlist doctor again.")
    elif not spotify_ok:
        lines.append("Next: fix the Spotify settings above (README step 2).")
    elif "spotify" not in services:
        lines.append("Next: ipod2playlist spotify --dry-run  (then ipod2playlist spotify)")
    elif sync.pending(songs, progress, "spotify"):  # an interrupted run; Spotify comes first in the flow
        lines.append("Next: ipod2playlist spotify (it continues where it stopped).")
    elif youtube_pending and client_ok:
        lines.append("Next: ipod2playlist youtube --only-spotify-missing")
    elif youtube_pending:
        lines.append("Next: fix the YouTube client file above (README step 3).")
    else:
        lines.append("Next: all done. ipod2playlist review --service spotify shows what is still missing.")
    return lines
