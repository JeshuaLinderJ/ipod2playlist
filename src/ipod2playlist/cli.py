"""The `ipod2playlist` command: scan, spotify, youtube, missing."""
import argparse
import os
import sys
from pathlib import Path

from dotenv import find_dotenv, load_dotenv

from ipod2playlist import library, spotify, youtube
from ipod2playlist.progress import Progress
from ipod2playlist.scan import scan
from ipod2playlist.spotify import SpotifyService
from ipod2playlist.sync import sync
from ipod2playlist.youtube import QuotaExceeded, YouTubeService

DEFAULT_PLAYLIST_NAME = "My iPod Playlist"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ipod2playlist", description="Turn an iPod's music into playlists.")
    commands = parser.add_subparsers(dest="command", required=True)

    def add_command(name: str, help: str) -> argparse.ArgumentParser:
        command = commands.add_parser(name, help=help)
        command.add_argument("--songs", type=Path, default=Path("songs.json"), help="song list (default: songs.json)")
        command.add_argument("--progress", type=Path, default=Path("progress.json"),
                             help="progress file (default: progress.json)")
        return command

    scan_cmd = add_command("scan", "read an iPod's songs into songs.json and songs.tsv")
    scan_cmd.add_argument("root", type=Path, help="the iPod's mount point, e.g. /Volumes/IPOD")

    for name in ("spotify", "youtube"):
        command = add_command(name, f"add the songs to a {name} playlist (resumable)")
        command.add_argument("--name", default=DEFAULT_PLAYLIST_NAME, help="playlist name")
        command.add_argument("--public", action="store_true", help="make the playlist public (default: private)")
        command.add_argument("--retry-missing", action="store_true", help="search again for songs marked missing")
        if name == "youtube":
            command.add_argument("--only-spotify-missing", action="store_true",
                                 help="only songs Spotify could not find")
            command.add_argument("--client-secrets", type=Path,
                                 default=Path(os.environ.get("YOUTUBE_CLIENT_SECRETS", "client_secrets.json")))
            command.add_argument("--token", type=Path, default=Path("youtube_token.json"))

    missing = add_command("missing", "write the songs a service could not find to a TSV (no API calls)")
    missing.add_argument("--service", required=True, choices=["spotify", "youtube"])
    return parser


def _build_service(name: str, args):
    """The only place real API clients are built; tests replace this."""
    if name == "spotify":
        return SpotifyService(spotify.make_client())
    if not args.client_secrets.exists():
        raise SystemExit(f"{args.client_secrets} not found; download the OAuth client JSON (see README) "
                         "or pass --client-secrets.")
    return YouTubeService(youtube.make_client(args.client_secrets, args.token))


def _load_progress(path: Path) -> Progress:
    try:
        return Progress(path)
    except ValueError:  # bad JSON, or JSON that is not a progress file
        raise SystemExit(f"Progress file {path} is corrupt; fix or delete it.")


def _load_songs(path: Path) -> list[library.Song]:
    try:
        return library.load_songs(path)
    except FileNotFoundError:
        raise SystemExit(f"{path} not found; run `ipod2playlist scan <ipod path>` first.")
    except (OSError, ValueError, TypeError):  # unreadable, bad encoding, bad JSON (a ValueError), wrong shape
        raise SystemExit(f"{path} is not a valid song list; re-run scan.")


def _scan(args) -> None:
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


def _playlist(args) -> None:
    songs = _load_songs(args.songs)
    progress = _load_progress(args.progress)
    if getattr(args, "only_spotify_missing", False):
        spotify_missing = set(progress.keys_with_status("spotify", "missing"))
        songs = [song for song in songs if song.key in spotify_missing]

    service = _build_service(args.command, args)
    result = sync(songs, service, progress, args.name, public=args.public, retry_missing=args.retry_missing)
    print(f"{result.added} added / {result.missing} missing / {result.skipped} skipped / {result.failed} failed")
    if result.failed and not result.added:
        print(f"Nothing could be added. If the {args.command} playlist was deleted, delete {args.progress} "
              "to start a new playlist; otherwise just re-run to retry.")


def _missing(args) -> None:
    progress = _load_progress(args.progress)
    keys = set(progress.keys_with_status(args.service, "missing"))
    songs = [song for song in _load_songs(args.songs) if song.key in keys]
    out = Path(f"{args.service}_missing.tsv")
    library.write_tsv(songs, out)
    print(f"Wrote {len(songs)} missing songs to {out}")


def main(argv=None) -> None:
    load_dotenv(find_dotenv(usecwd=True))  # the user's cwd, not the installed package's directory
    args = build_parser().parse_args(argv)
    commands = {"scan": _scan, "spotify": _playlist, "youtube": _playlist, "missing": _missing}
    try:
        commands[args.command](args)
    except QuotaExceeded:
        print("YouTube quota reached; progress saved. Re-run this command after the quota resets.",
              file=sys.stderr)
        raise SystemExit(2)
