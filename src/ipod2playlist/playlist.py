"""What the spotify/youtube commands decide: which songs to process, and what to tell the user."""
from pathlib import Path

from ipod2playlist.library import Song
from ipod2playlist.progress import Progress


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


def failure_hint(service: str) -> str:
    return (f"Nothing could be added; re-run to retry. If you deleted the {service} playlist online, "
            f"run `ipod2playlist {service} --new-playlist` to start a new one.")
