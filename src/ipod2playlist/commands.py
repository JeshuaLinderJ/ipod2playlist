"""Thin command handlers; the decisions live in playlist.py and the other feature modules."""
from pathlib import Path

from ipod2playlist import library, messages, playlist, spotify, youtube
from ipod2playlist.progress import Progress
from ipod2playlist.scan import scan
from ipod2playlist.spotify import SpotifyService
from ipod2playlist.sync import sync
from ipod2playlist.youtube import YouTubeService


def build_service(name: str, args):
    """The only place real API clients are built; tests replace this."""
    if name == "spotify":
        return SpotifyService(spotify.make_client())
    if not args.client_secrets.exists():
        raise SystemExit(f"{args.client_secrets} not found; download the OAuth client JSON (see README) "
                         "or pass --client-secrets.")
    try:
        client = youtube.make_client(args.client_secrets, args.token)
    except ValueError as error:  # malformed JSON, or the wrong kind of client file
        raise SystemExit(messages.client_files(error, args.client_secrets, args.token))
    return YouTubeService(client)


def load_progress(path: Path) -> Progress:
    try:
        return Progress(path)
    except ValueError:  # bad JSON, or JSON that is not a progress file
        raise SystemExit(f"Progress file {path} is corrupt; fix or delete it.")


def load_songs(path: Path) -> list[library.Song]:
    try:
        return library.load_songs(path)
    except FileNotFoundError:
        raise SystemExit(f"{path} not found; run `ipod2playlist scan <ipod path>` first.")
    except (OSError, ValueError, TypeError):  # unreadable, bad encoding, bad JSON (a ValueError), wrong shape
        raise SystemExit(f"{path} is not a valid song list; re-run scan.")


def run_scan(args) -> None:
    if not args.root.is_dir():
        raise SystemExit(f"{args.root} is not a directory (is the iPod mounted?)")
    if not args.songs.parent.is_dir():
        raise SystemExit(f"Folder {args.songs.parent} does not exist; create it or choose another --songs path.")
    found = scan(args.root)
    songs = library.dedupe(found)
    library.save_songs(songs, args.songs)
    library.write_tsv(songs, args.songs.with_suffix(".tsv"))
    print(f"Found {len(found)} songs, removed {len(found) - len(songs)} duplicates; "
          f"wrote {len(songs)} to {args.songs} and {args.songs.with_suffix('.tsv')}")


def run_playlist(args) -> None:
    songs = load_songs(args.songs)
    playlist.check_flags(args.dry_run, args.new_playlist)  # first, so a refused run leaves progress alone
    progress = load_progress(args.progress)
    if args.new_playlist:
        print(playlist.start_new(progress, args.command, args.progress))
    only_missing = args.command == "youtube" and args.only_spotify_missing
    songs = playlist.select_songs(songs, progress, only_missing)
    if not songs:  # no login needed for nothing to do
        print(playlist.no_songs_message(only_missing, progress))
        return
    if args.dry_run and args.command == "youtube":  # no login, no search: searches cost quota
        print(playlist.youtube_estimate(songs, progress, args.retry_missing))
        return
    service = build_service(args.command, args)
    if args.dry_run:
        print(playlist.dry_run_summary(sync(songs, service, progress, args.name, retry_missing=args.retry_missing,
                                            dry_run=True)))
        return
    result = sync(songs, service, progress, args.name, public=args.public, retry_missing=args.retry_missing)
    print(f"{result.added} added / {result.missing} missing / {result.skipped} skipped / {result.failed} failed")
    if result.failed and not result.added:
        print(playlist.failure_hint(args.command))


def run_missing(args) -> None:
    progress = load_progress(args.progress)
    keys = set(progress.keys_with_status(args.service, "missing"))
    songs = [song for song in load_songs(args.songs) if song.key in keys]
    out = Path(f"{args.service}_missing.tsv")
    library.write_tsv(songs, out)
    print(f"Wrote {len(songs)} missing songs to {out}")
