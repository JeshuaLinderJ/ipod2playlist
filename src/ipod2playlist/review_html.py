"""The review report as one self-contained HTML page (no JavaScript, no external files)."""
import html
from pathlib import Path
from string import Template

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
