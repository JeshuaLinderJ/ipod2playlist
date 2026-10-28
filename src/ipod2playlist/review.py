"""Human review of close-but-unsure matches: write a report, then add only what a person marked yes.

The only id ever added is the one saved in progress.json. The CSV's Key column picks the song and the
Add? column says yes or no; nothing else in the file (ids, links, titles) is ever read back.
"""
import csv
import io
from dataclasses import dataclass
from pathlib import Path

from ipod2playlist.errors import PlaylistGone, QuotaExceeded
from ipod2playlist.progress import Progress
from ipod2playlist.review_html import write_review_html
from ipod2playlist.review_rows import COLUMNS, item_link, review_rows, search_links, write_review_csv  # noqa: F401
from ipod2playlist.sync import MAX_CONSECUTIVE_FAILURES

YES = {"y", "yes", "s", "si", "sí"}
NO = {"n", "no"}


def read_decisions(path: Path) -> tuple[list[str], list[str]]:
    try:
        text = path.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError:
        raise SystemExit(f"{path} is not saved as UTF-8. In Excel or Numbers, export it as \"CSV UTF-8\" "
                         "and run apply-review again.")
    try:
        delimiter = csv.Sniffer().sniff(text[:4096], delimiters=",;\t").delimiter
    except csv.Error:
        delimiter = ","
    reader = csv.DictReader(io.StringIO(text, newline=""), delimiter=delimiter)
    if "Key" not in (reader.fieldnames or []) or COLUMNS[0] not in reader.fieldnames:
        raise SystemExit(f"{path} has no \"Key\" and \"Add? (y/n)\" columns; "
                         "run ipod2playlist review again to get a fresh file.")
    accepted, rejected = [], []
    for row in reader:
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
    failed: int = 0


def apply_review(accepted: list[str], rejected: list[str], service, progress: Progress) -> ApplyResult:
    playlist_id = progress.playlist_id(service.name)
    if playlist_id is None:
        raise SystemExit(f"No {service.name} playlist yet; run `ipod2playlist {service.name}` first.")
    if not service.playlist_exists(playlist_id):
        raise PlaylistGone(service.name)
    result = ApplyResult()
    consecutive_failures = 0
    for key in accepted:
        maybe = progress.maybe(service.name, key)
        # Status "missing" also makes a second run (or a repeated row) a no-op once the song is added.
        if progress.status(service.name, key) != "missing" or maybe is None:
            print(f"skipped (no saved guess): {key}")
            result.skipped += 1
            continue
        try:
            service.add(playlist_id, maybe["id"])  # the saved id, never anything from the CSV
        except (QuotaExceeded, PlaylistGone):
            raise
        except Exception as error:  # a stale id must not block the other rows; it stays missing for a re-run
            print(f"! failed: {maybe['artist']} - {maybe['title']} ({error})")
            result.failed += 1
            consecutive_failures += 1
            if consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
                progress.save()
                raise
            continue
        consecutive_failures = 0
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
    return f"{result.added} added / {result.rejected} rejected / {result.skipped} skipped / {result.failed} failed"
