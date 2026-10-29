"""The `ipod2playlist` command: the argparse parser and the error boundary."""
import argparse
import os
import sys
from pathlib import Path

import google.auth.exceptions
import googleapiclient.errors
import httplib2
import requests
import spotipy
from dotenv import find_dotenv, load_dotenv

from ipod2playlist import commands, messages
from ipod2playlist.errors import PlaylistGone, QuotaExceeded

DEFAULT_PLAYLIST_NAME = "My iPod Playlist"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ipod2playlist", description="Turn an iPod's music into playlists.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    def add_command(name: str, summary: str, run) -> argparse.ArgumentParser:
        command = subparsers.add_parser(name, help=summary)
        command.add_argument("--songs", type=Path, default=Path("songs.json"), help="song list (default: songs.json)")
        command.set_defaults(run=run)
        return command

    def add_progress(command: argparse.ArgumentParser) -> None:
        command.add_argument("--progress", type=Path, default=Path("progress.json"),
                             help="progress file (default: progress.json)")

    def add_playlist_flags(command: argparse.ArgumentParser) -> None:
        add_progress(command)
        command.add_argument("--name", default=DEFAULT_PLAYLIST_NAME, help="playlist name")
        command.add_argument("--public", action="store_true", help="make the playlist public (default: private)")
        command.add_argument("--retry-missing", action="store_true", help="search again for songs marked missing")
        command.add_argument("--dry-run", action="store_true",
                             help="show what would happen without changing anything")
        command.add_argument("--new-playlist", action="store_true",
                             help="start a new playlist, forgetting only this service's saved results")

    scan_cmd = add_command("scan", "read an iPod's songs into songs.json and songs.tsv", commands.run_scan)
    scan_cmd.add_argument("root", type=Path, help="the iPod's mount point, e.g. /Volumes/IPOD")
    scan_cmd.add_argument("--itunesdb", action="store_true",
                          help="also read the iPod's own database (names for untagged songs, ratings, play counts, "
                               "playlists); needs the itunesdb extra")

    spotify_cmd = add_command("spotify", "add the songs to a spotify playlist (resumable)", commands.run_playlist)
    add_playlist_flags(spotify_cmd)

    youtube_cmd = add_command("youtube", "add the songs to a youtube playlist (resumable)", commands.run_playlist)
    add_playlist_flags(youtube_cmd)
    youtube_cmd.add_argument("--only-spotify-missing", action="store_true", help="only songs Spotify could not find")
    youtube_cmd.add_argument("--client-secrets", type=Path,
                             default=Path(os.environ.get("YOUTUBE_CLIENT_SECRETS", "client_secrets.json")),
                             help="Google OAuth client file (default: client_secrets.json, "
                                  "or $YOUTUBE_CLIENT_SECRETS)")
    youtube_cmd.add_argument("--token", type=Path, default=Path("youtube_token.json"),
                             help="where the YouTube login is saved (default: youtube_token.json)")

    doctor_cmd = add_command("doctor", "check the setup and say what to do next (no API calls)", commands.run_doctor)
    add_progress(doctor_cmd)
    doctor_cmd.add_argument("--client-secrets", type=Path,
                            default=Path(os.environ.get("YOUTUBE_CLIENT_SECRETS", "client_secrets.json")),
                            help="Google OAuth client file (default: client_secrets.json, "
                                 "or $YOUTUBE_CLIENT_SECRETS)")
    doctor_cmd.add_argument("--token", type=Path, default=Path("youtube_token.json"),
                            help="where the YouTube login is saved (default: youtube_token.json)")

    missing = add_command("missing", "write the songs a service could not find to a TSV (no API calls)",
                          commands.run_missing)
    add_progress(missing)
    missing.add_argument("--service", required=True, choices=["spotify", "youtube"])

    review_cmd = add_command("review", "write a report of missing songs to check by hand (no API calls)",
                             commands.run_review)
    add_progress(review_cmd)
    review_cmd.add_argument("--service", required=True, choices=["spotify", "youtube"])

    apply_cmd = subparsers.add_parser("apply-review", help="add the close matches you marked y in the review csv")
    apply_cmd.set_defaults(run=commands.run_apply_review)
    apply_cmd.add_argument("--service", required=True, choices=["spotify", "youtube"])
    apply_cmd.add_argument("--file", type=Path, default=None, help="review file (default: <service>_review.csv)")
    add_progress(apply_cmd)
    apply_cmd.add_argument("--client-secrets", type=Path,
                           default=Path(os.environ.get("YOUTUBE_CLIENT_SECRETS", "client_secrets.json")),
                           help="Google OAuth client file (default: client_secrets.json, "
                                "or $YOUTUBE_CLIENT_SECRETS)")
    apply_cmd.add_argument("--token", type=Path, default=Path("youtube_token.json"),
                           help="where the YouTube login is saved (default: youtube_token.json)")

    backup_cmd = subparsers.add_parser("backup", help="copy every song to a folder on this Mac, with M3U8 playlists")
    backup_cmd.set_defaults(run=commands.run_backup)
    backup_cmd.add_argument("root", type=Path, help="the iPod's mount point, e.g. /Volumes/IPOD")
    backup_cmd.add_argument("dest", type=Path, help="where to copy the music, e.g. ~/Music/iPod backup")
    backup_cmd.add_argument("--itunesdb", action="store_true",
                            help="also write the iPod's own playlists and use its song names; "
                                 "needs the itunesdb extra")

    export_cmd = add_command("export-csv", "write a CSV for soundiiz.com or tunemymusic.com (no API calls)",
                             commands.run_export_csv)
    add_progress(export_cmd)
    export_cmd.add_argument("--service", choices=["spotify", "youtube"],
                            help="export only the songs this service could not find")
    export_cmd.add_argument("--out", type=Path, default=None,
                            help="output file (default: library.csv, or <service>_missing.csv)")
    return parser


def main(argv=None) -> None:
    load_dotenv(find_dotenv(usecwd=True))  # the user's cwd, not the installed package's directory
    args = build_parser().parse_args(argv)
    try:
        args.run(args)
    except QuotaExceeded:
        print("YouTube quota reached; progress saved. Re-run this command after the quota resets.",
              file=sys.stderr)
        raise SystemExit(2)
    except PlaylistGone as gone:
        print(messages.playlist_gone(gone, args.progress), file=sys.stderr)
        raise SystemExit(3)
    except spotipy.exceptions.SpotifyOauthError as error:
        raise SystemExit(messages.spotify_login(error))
    except spotipy.exceptions.SpotifyException as error:
        raise SystemExit(messages.spotify_refused(error))
    except googleapiclient.errors.HttpError as error:
        raise SystemExit(messages.youtube_refused(error))
    except google.auth.exceptions.GoogleAuthError as error:
        raise SystemExit(messages.youtube_login(error))
    except (requests.exceptions.RequestException, httplib2.HttpLib2Error, ConnectionError, TimeoutError) as error:
        # Not bare OSError: that would mislabel local file errors as network errors.
        raise SystemExit(messages.network(error))
    except KeyboardInterrupt:
        print(messages.INTERRUPTED, file=sys.stderr)
        raise SystemExit(130)
