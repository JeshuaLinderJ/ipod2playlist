"""The sync loop: search each song, add the best match, record progress so a re-run resumes."""
from dataclasses import dataclass

from ipod2playlist.errors import PlaylistGone, QuotaExceeded
from ipod2playlist.library import UNKNOWN_ARTIST, Song
from ipod2playlist.matching import best_match
from ipod2playlist.progress import Progress

# A revoked login or a dropped network fails every song; stop and let the CLI explain, not print N lines.
MAX_CONSECUTIVE_FAILURES = 3


@dataclass
class SyncResult:
    added: int = 0
    missing: int = 0
    skipped: int = 0  # already had a status from a previous run
    failed: int = 0   # transient per-song errors; left unrecorded so a re-run retries them


def sync(songs: list[Song], service, progress: Progress, playlist_name: str,
         public: bool = False, retry_missing: bool = False) -> SyncResult:
    result = SyncResult()
    if not songs:
        return result
    name = service.name

    playlist_id = progress.playlist_id(name)
    if playlist_id is not None and not service.playlist_exists(playlist_id):
        raise PlaylistGone(name)  # before any search, so a deleted playlist costs no quota
    if playlist_id is None:
        playlist_id = service.create_playlist(playlist_name, public)
        progress.set_playlist_id(name, playlist_id)
        progress.save()

    consecutive_failures = 0
    for song in songs:
        status = progress.status(name, song.key)
        if status == "added" or (status == "missing" and not retry_missing):
            result.skipped += 1
            continue

        if song.artist in ("", UNKNOWN_ARTIST):  # a search without an artist could add a wrong song
            progress.record(name, song.key, "missing")
            result.missing += 1
            print(f"- missing (no artist tag, not searched): {song.title}")
            progress.save()
            continue

        try:
            match = best_match(song, service.search(song))
            if match is not None:
                service.add(playlist_id, match.id)
        except (QuotaExceeded, PlaylistGone):  # these end the run; every other error is per-song
            progress.save()
            raise
        except Exception as error:  # one bad song must not stop the run; KeyboardInterrupt still does
            print(f"! failed: {song.artist} - {song.title} ({error})")
            result.failed += 1
            consecutive_failures += 1
            if consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
                progress.save()
                raise
            continue

        consecutive_failures = 0

        if match is None:
            progress.record(name, song.key, "missing")
            result.missing += 1
            print(f"- missing: {song.artist} - {song.title}")
        else:
            progress.record(name, song.key, "added")
            result.added += 1
            print(f"+ added: {song.artist} - {song.title}")
        progress.save()

    return result
