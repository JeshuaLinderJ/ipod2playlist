"""The sync loop: search each song, add the best match, record progress so a re-run resumes."""
from dataclasses import dataclass

from ipod2playlist.matching import best_match
from ipod2playlist.youtube import QuotaExceeded


@dataclass
class SyncResult:
    added: int = 0
    missing: int = 0
    skipped: int = 0  # already had a status from a previous run
    failed: int = 0   # transient per-song errors; left unrecorded so a re-run retries them


def sync(songs, service, progress, playlist_name, public=False, retry_missing=False) -> SyncResult:
    result = SyncResult()
    name = service.name

    playlist_id = progress.playlist_id(name)
    if playlist_id is None:
        playlist_id = service.create_playlist(playlist_name, public)
        progress.set_playlist_id(name, playlist_id)
        progress.save()

    for song in songs:
        status = progress.status(name, song.key)
        if status == "added" or (status == "missing" and not retry_missing):
            result.skipped += 1
            continue

        try:
            match = best_match(song, service.search(song))
            if match is not None:
                service.add(playlist_id, match.id)
        except QuotaExceeded:
            progress.save()
            raise
        except Exception as error:  # one bad song must not stop the run; KeyboardInterrupt still does
            print(f"! failed: {song.artist} - {song.title} ({error})")
            result.failed += 1
            continue

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
