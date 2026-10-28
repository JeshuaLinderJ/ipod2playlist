"""The sync loop: search each song, add the best match, record progress so a re-run resumes."""
from dataclasses import dataclass

from ipod2playlist.errors import PlaylistGone, QuotaExceeded
from ipod2playlist.library import UNKNOWN_ARTIST, Song
from ipod2playlist.matching import best_match, near_miss
from ipod2playlist.progress import Progress

# A revoked login or a dropped network fails every song; stop and let the CLI explain, not print N lines.
MAX_CONSECUTIVE_FAILURES = 3


@dataclass
class SyncResult:
    added: int = 0
    missing: int = 0
    skipped: int = 0  # already had a status from a previous run
    failed: int = 0   # transient per-song errors; left unrecorded so a re-run retries them


def _is_pending(status: str | None, retry_missing: bool) -> bool:
    """The one skip rule: a song with no status yet, or a missing one when retrying, is worked on."""
    return status is None or (status == "missing" and retry_missing)


def pending(songs: list[Song], progress: Progress, service_name: str,
            retry_missing: bool = False) -> list[Song]:
    """The songs sync would not skip."""
    return [s for s in songs if _is_pending(progress.status(service_name, s.key), retry_missing)]


def searchable(song: Song) -> bool:
    """Songs without an artist are never searched (a wrong match is worse than a missing one)."""
    return song.artist not in ("", UNKNOWN_ARTIST)


def search_count(songs: list[Song], progress: Progress, service_name: str,
                 retry_missing: bool = False) -> int:
    """How many searches a run would really make; untagged songs cost no quota."""
    return len([s for s in pending(songs, progress, service_name, retry_missing) if searchable(s)])


def sync(songs: list[Song], service, progress: Progress, playlist_name: str,
         public: bool = False, retry_missing: bool = False, dry_run: bool = False) -> SyncResult:
    result = SyncResult()
    if not songs:
        return result
    name = service.name

    # A dry run changes nothing: no playlist check or creation, no add, no progress record or save.
    playlist_id = progress.playlist_id(name)
    if not dry_run:
        if playlist_id is not None and not service.playlist_exists(playlist_id):
            raise PlaylistGone(name)  # before any search, so a deleted playlist costs no quota
        if playlist_id is None:
            playlist_id = service.create_playlist(playlist_name, public)
            progress.set_playlist_id(name, playlist_id)
            progress.save()

    consecutive_failures = 0
    for song in songs:
        if not _is_pending(progress.status(name, song.key), retry_missing):
            result.skipped += 1
            continue

        if not searchable(song):  # a search without an artist could add a wrong song
            result.missing += 1
            print(f"- missing (no artist tag, not searched): {song.title}")
            if not dry_run:
                progress.record(name, song.key, "missing")
                progress.save()
            continue

        try:
            candidates = service.search(song)
            match = best_match(song, candidates)
            if match is not None and not dry_run:
                service.add(playlist_id, match.id)
        except (QuotaExceeded, PlaylistGone):  # these end the run; every other error is per-song
            if not dry_run:
                progress.save()
            raise
        except Exception as error:  # one bad song must not stop the run; KeyboardInterrupt still does
            print(f"! failed: {song.artist} - {song.title} ({error})")
            result.failed += 1
            consecutive_failures += 1
            if consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
                if not dry_run:
                    progress.save()
                raise
            continue

        consecutive_failures = 0

        if match is None:
            result.missing += 1
            close = near_miss(song, candidates)
            if close is None:
                note = ""
            elif dry_run:
                note = " (close match; would be saved for review)"
            else:
                note = " (close match saved for review)"
            print(f"- missing: {song.artist} - {song.title}{note}")
            if not dry_run:
                if close:  # remembered only; a human approves it later
                    progress.record_maybe(name, song.key, *close)
                else:  # a re-search found nothing close; drop the stale guess
                    progress.clear_maybe(name, song.key)
        elif dry_run:
            result.added += 1
            print(f"would add: {song.artist} - {song.title}  ->  {match.title} by {match.artist}")
        else:
            result.added += 1
            print(f"+ added: {song.artist} - {song.title}")
        if not dry_run:
            progress.record(name, song.key, "missing" if match is None else "added")
            progress.save()

    return result
