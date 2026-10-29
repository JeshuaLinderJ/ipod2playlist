"""What the spotify/youtube commands decide: which songs to process, and what to tell the user."""
from pathlib import Path

from ipod2playlist.library import Song
from ipod2playlist.messages import new_playlist_command
from ipod2playlist.progress import Progress
from ipod2playlist.sync import SyncResult, search_count
from ipod2playlist.youtube import days_needed


def start_new(progress: Progress, service: str, progress_path: Path) -> str:
    progress.reset_service(service)
    progress.save()
    return (f"Starting a new {service} playlist: forgot the saved {service} playlist and results "
            f"in {progress_path} (other services are kept).")


def select_songs(songs: list[Song], progress: Progress, only_spotify_missing: bool) -> list[Song]:
    if not only_spotify_missing:
        return songs
    spotify_missing = set(progress.keys_with_status("spotify", "missing"))
    return [song for song in songs if song.key in spotify_missing]


def no_songs_message(only_spotify_missing: bool, progress: Progress) -> str:
    message = "No songs to process."
    if only_spotify_missing and progress.playlist_id("spotify") is None:
        message += " Spotify has no missing songs recorded; run `ipod2playlist spotify` first."
    elif only_spotify_missing:
        message += " Spotify found every song."
    return message


def failure_hint(service: str, argv) -> str:
    return (f"Nothing could be added; re-run to retry. If you deleted the {service} playlist online, "
            f"run `{new_playlist_command(argv, service)}` to start a new one.")


def check_flags(dry_run: bool, new_playlist: bool) -> None:
    if dry_run and new_playlist:
        raise SystemExit("--dry-run and --new-playlist can't be used together.")


def dry_run_summary(result: SyncResult) -> str:
    return (f"{result.added} would be added / {result.missing} missing / {result.skipped} skipped / "
            f"{result.failed} failed (dry run: nothing was changed)")


def youtube_estimate(songs: list[Song], progress: Progress, retry_missing: bool) -> str:
    n = search_count(songs, progress, "youtube", retry_missing)
    days = days_needed(n, progress.playlist_id("youtube") is not None)
    return (f"{n} songs to search on YouTube: about {days} day(s) of free quota. "
            "Nothing was searched (each YouTube search uses quota).")
