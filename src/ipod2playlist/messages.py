"""The exact one-line text of each error-boundary message that cli.main shows."""
import shlex
from contextlib import contextmanager


def new_playlist_command(argv, service) -> str:
    """The command the user just ran, plus --new-playlist, so no option (--name, --songs...) is lost."""
    if not argv or argv[0] != service:  # e.g. apply-review has no --new-playlist: use the plain command
        argv = [service]
    kept = [word for word in argv if word not in ("--new-playlist", "--dry-run")]  # dry-run can't combine
    return shlex.join(["ipod2playlist", *kept, "--new-playlist"])


def playlist_gone(gone, progress_path, argv) -> str:
    return (f"The {gone.service} playlist saved in {progress_path} no longer exists (deleted online?). "
            f"Progress is saved. To start a new one, run: {new_playlist_command(argv, gone.service)}")


@contextmanager
def write_guard():
    """Turn a failed output write (read-only folder, full disk) into a one-line message."""
    try:
        yield
    except OSError as error:
        raise SystemExit(f"Could not write {error.filename} ({error.strerror or error}).")


def spotify_login(error) -> str:
    # Library text often ends in a period; strip it so the sentence never has "..".
    return (f"Spotify login is not set up: {str(error).rstrip('.')}. "
            "Check the .env file in this folder (README step 2).")


def spotify_refused(error) -> str:
    # Real messages are "https://api.spotify.com/...:\n <text>"; keep only the last line.
    lines = error.msg.splitlines() or [""]
    detail = lines[-1].strip().rstrip(".")
    return (f"Spotify refused the request (HTTP {error.http_status}): {detail}. "
            "If it says the user may not be registered, add this Spotify account to your app's users "
            "in the Spotify Developer Dashboard (README step 2).")


def youtube_refused(error) -> str:
    return (f"YouTube refused the request (HTTP {error.status_code}): {str(error.reason).rstrip('.')}. "
            "Check the YouTube setup (README step 3).")


def youtube_login(error) -> str:
    return (f"YouTube login failed: {str(error).rstrip('.')}. Delete the saved login (youtube_token.json, "
            "or the file given with --token) and re-run to log in again (README step 3).")


def network(error) -> str:
    # Not in the brief: a plain line in the same style for a dropped connection.
    return (f"Could not reach the service ({str(error).rstrip('.')}). Check the internet connection "
            "and re-run the same command; progress is saved.")


def client_files(error, client_secrets, token) -> str:
    return (f"Could not read {client_secrets} or {token} ({error}). Download the Desktop-app OAuth client "
            f"again (README step 3), or delete {token} to log in again.")


INTERRUPTED = "\nStopped. Progress is saved; re-run the same command to continue."
