"""Human review of close-but-unsure matches: write a report, then add only what a person marked yes.

The only id ever added is the one saved in progress.json. The CSV's Key column picks the song and the
Add? column says yes or no; nothing else in the file (ids, links, titles) is ever read back.
"""
import csv
import html
from dataclasses import dataclass
from pathlib import Path
from string import Template
from urllib.parse import quote, quote_plus

from ipod2playlist.errors import PlaylistGone
from ipod2playlist.library import Song
from ipod2playlist.progress import Progress

COLUMNS = ["Add? (y/n)", "Title", "Artist", "Album", "Best guess", "Guess link",
           "Search Spotify", "Search YouTube", "Key"]
YES = {"y", "yes", "s", "si", "sí"}
NO = {"n", "no"}

PAGE = Template("""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>$service review</title>
<style>body{font-family:sans-serif;margin:2em}td,th{border:1px solid #ccc;padding:.4em;text-align:left}
table{border-collapse:collapse}</style></head><body>
<h1>Songs $service could not find</h1>
<p>Songs with a best guess come first. Open each guess to listen. To add one, type y in the "Add? (y/n)"
column of $service_review.csv, save it as CSV, then run: ipod2playlist apply-review --service $service</p>
<table><tr><th>Title</th><th>Artist</th><th>Album</th><th>Best guess</th><th>Search</th></tr>
$rows</table></body></html>
""")


def search_links(song: Song) -> tuple[str, str]:
    # safe="" so a "/" in a name (AC/DC) is encoded instead of splitting the URL path
    text = f"{song.artist} {song.title}"
    return ("https://open.spotify.com/search/" + quote(text, safe=""),
            "https://www.youtube.com/results?search_query=" + quote_plus(text))


def item_link(service: str, item_id: str) -> str:
    if service == "spotify":
        return "https://open.spotify.com/track/" + item_id.rsplit(":", 1)[-1]
    return "https://www.youtube.com/watch?v=" + item_id


def review_rows(songs: list[Song], progress: Progress, service: str) -> list[dict[str, str]]:
    rows = []
    for song in songs:
        if progress.status(service, song.key) != "missing":
            continue
        maybe = progress.maybe(service, song.key)
        spotify_link, youtube_link = search_links(song)
        rows.append({
            "Add? (y/n)": "", "Title": song.title, "Artist": song.artist, "Album": song.album,
            "Best guess": f"{maybe['title']} by {maybe['artist']} ({maybe['score']})" if maybe else "",
            "Guess link": item_link(service, maybe["id"]) if maybe else "",
            "Search Spotify": spotify_link, "Search YouTube": youtube_link, "Key": song.key,
        })
    return rows


def write_review_csv(rows, path: Path) -> None:
    with open(path, "w", encoding="utf-8-sig", newline="") as f:  # BOM so Numbers/Excel read UTF-8
        writer = csv.DictWriter(f, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows(rows)


def _link(url: str, label: str) -> str:
    return f'<a href="{html.escape(url)}" target="_blank" rel="noopener">{html.escape(label)}</a>'


def _html_row(row: dict[str, str]) -> str:
    guess = html.escape(row["Best guess"])
    if row["Guess link"]:
        guess = _link(row["Guess link"], row["Best guess"])
    searches = _link(row["Search Spotify"], "Spotify") + " " + _link(row["Search YouTube"], "YouTube")
    return ("<tr>" + "".join(f"<td>{html.escape(row[name])}</td>" for name in ("Title", "Artist", "Album"))
            + f"<td>{guess}</td><td>{searches}</td></tr>")


def write_review_html(rows, path: Path, service: str) -> None:
    ordered = [r for r in rows if r["Best guess"]] + [r for r in rows if not r["Best guess"]]
    page = PAGE.substitute(service=html.escape(service), service_review=f"{service}_review",
                           rows="\n".join(_html_row(row) for row in ordered))
    path.write_text(page, encoding="utf-8")


def read_decisions(path: Path) -> tuple[list[str], list[str]]:
    with open(path, encoding="utf-8-sig", newline="") as f:
        sample = f.read(4096)
        f.seek(0)
        try:
            delimiter = csv.Sniffer().sniff(sample, delimiters=",;\t").delimiter
        except csv.Error:
            delimiter = ","
        accepted, rejected = [], []
        for row in csv.DictReader(f, delimiter=delimiter):
            answer = (row.get(COLUMNS[0]) or "").strip().casefold()
            key = row.get("Key") or ""
            if not key:
                continue
            if answer in YES:
                accepted.append(key)
            elif answer in NO:
                rejected.append(key)
    return accepted, rejected


def write_reports(songs, progress, service: str, folder: Path) -> tuple[int, int]:
    rows = review_rows(songs, progress, service)
    write_review_csv(rows, folder / f"{service}_review.csv")
    write_review_html(rows, folder / f"{service}_review.html", service)
    return len(rows), sum(1 for row in rows if row["Best guess"])


def report_message(service: str, missing: int, guessed: int) -> str:
    return (f"Wrote {missing} missing songs ({guessed} with a close guess) to {service}_review.html "
            f"and {service}_review.csv.\n"
            "Open the .html file to check each guess. In the .csv, type y or n in the \"Add? (y/n)\" "
            f"column, save it as CSV, then run: ipod2playlist apply-review --service {service}")


def check_file(path: Path, service: str) -> None:
    if not path.exists():
        raise SystemExit(f"{path} not found; run `ipod2playlist review --service {service}` first.")


@dataclass
class ApplyResult:
    added: int = 0
    rejected: int = 0
    skipped: int = 0


def apply_review(accepted: list[str], rejected: list[str], service, progress: Progress) -> ApplyResult:
    playlist_id = progress.playlist_id(service.name)
    if playlist_id is None:
        raise SystemExit(f"No {service.name} playlist yet; run `ipod2playlist {service.name}` first.")
    if not service.playlist_exists(playlist_id):
        raise PlaylistGone(service.name)
    result = ApplyResult()
    for key in accepted:
        maybe = progress.maybe(service.name, key)
        # Status "missing" also makes a second run (or a repeated row) a no-op once the song is added.
        if progress.status(service.name, key) != "missing" or maybe is None:
            print(f"skipped (no saved guess): {key}")
            result.skipped += 1
            continue
        service.add(playlist_id, maybe["id"])  # the saved id, never anything from the CSV
        progress.record(service.name, key, "added")
        progress.save()
        result.added += 1
        print(f"+ added: {maybe['title']} by {maybe['artist']}")
    for key in rejected:
        progress.clear_maybe(service.name, key)
        progress.save()
        result.rejected += 1
    return result


def apply_file(path: Path, service, progress: Progress) -> ApplyResult:
    accepted, rejected = read_decisions(path)
    return apply_review(accepted, rejected, service, progress)


def apply_summary(result: ApplyResult) -> str:
    return f"{result.added} added / {result.rejected} rejected / {result.skipped} skipped"
