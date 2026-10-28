"""The rows of the review report: one per missing song, with search links and the saved best guess."""
import csv
from pathlib import Path
from urllib.parse import quote, quote_plus

from ipod2playlist.library import Song
from ipod2playlist.progress import Progress

COLUMNS = ["Add? (y/n)", "Title", "Artist", "Album", "Best guess", "Guess link",
           "Search Spotify", "Search YouTube", "Key"]
FORMULA_STARTS = ("=", "+", "-", "@", "\t", "\r")
def search_links(song: Song) -> tuple[str, str]:
    # safe="" so a "/" in a name (AC/DC) is encoded instead of splitting the URL path
    text = f"{song.artist} {song.title}"
    return ("https://open.spotify.com/search/" + quote(text, safe=""),
            "https://www.youtube.com/results?search_query=" + quote_plus(text))


def item_link(service: str, item_id: str) -> str:
    if service == "spotify":
        return "https://open.spotify.com/track/" + item_id.rsplit(":", 1)[-1]
    return "https://www.youtube.com/watch?v=" + item_id


def _safe_cell(text: str) -> str:
    """Third-party text opened in Excel must not run as a formula; a leading ' makes it plain text."""
    return "'" + text if text.startswith(FORMULA_STARTS) else text


def review_rows(songs: list[Song], progress: Progress, service: str) -> list[dict[str, str]]:
    rows = []
    for song in songs:
        if progress.status(service, song.key) != "missing":
            continue
        maybe = progress.maybe(service, song.key)
        spotify_link, youtube_link = search_links(song)
        rows.append({
            "Add? (y/n)": "", "Title": _safe_cell(song.title), "Artist": _safe_cell(song.artist),
            "Album": _safe_cell(song.album),
            "Best guess": _safe_cell(f"{maybe['title']} by {maybe['artist']} ({maybe['score']})") if maybe else "",
            "Guess link": item_link(service, maybe["id"]) if maybe else "",
            "Search Spotify": spotify_link, "Search YouTube": youtube_link, "Key": song.key,
        })
    return rows


def write_review_csv(rows, path: Path) -> None:
    with open(path, "w", encoding="utf-8-sig", newline="") as f:  # BOM so Numbers/Excel read UTF-8
        writer = csv.DictWriter(f, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
