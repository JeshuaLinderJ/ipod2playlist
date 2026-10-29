"""CSV files that Soundiiz and TuneMyMusic can import. No API calls."""
import csv
from pathlib import Path

from ipod2playlist import backup, itunesdb
from ipod2playlist.library import Song
from ipod2playlist.progress import Progress

# The first three columns of Soundiiz's own sample file. Whether it accepts a file without the other
# columns, and which header TuneMyMusic wants, is unverified (see the README).
CSV_COLUMNS = ["title", "artist", "album"]

ADVICE = ("Upload it at soundiiz.com or tunemymusic.com to rebuild it on another service; "
          "their matching is looser than ipod2playlist's, so check the result.")


def write_csv(songs: list[Song], path: Path) -> None:
    # utf-8-sig: Soundiiz's sample has a BOM, and it makes Excel read accents correctly.
    # Cells are NOT prefixed with ' like review_rows._safe_cell does: this file is uploaded to importers
    # that would keep the apostrophe and then fail to match the song. The cost: a title that starts with
    # = + - or @ could run as a formula if someone opens the file in a spreadsheet instead of uploading it.
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(CSV_COLUMNS)
        for song in songs:
            writer.writerow([song.title, song.artist, song.album])


def playlist_file_name(name: str) -> str:
    return f"playlist_{backup.safe_name(name)}.csv"


def export_all(songs: list[Song], progress: Progress, service: str | None,
               songs_path: Path, out: Path | None) -> list[str]:
    if service:
        out = out or Path(f"{service}_missing.csv")
        missing = set(progress.keys_with_status(service, "missing"))
        chosen = [song for song in songs if song.key in missing]
    else:
        out = out or Path("library.csv")
        chosen = songs
    write_csv(chosen, out)
    lines = [f"Wrote {len(chosen)} songs to {out}"]
    if not service:
        by_key = {song.key: song for song in songs}
        playlists = itunesdb.load_playlists(songs_path.with_name("ipod_playlists.json"))
        for name, keys in playlists.items():  # dict order is the iPod's playlist order
            members = [by_key[key] for key in keys if key in by_key]
            path = out.with_name(playlist_file_name(name))  # next to the library file
            write_csv(members, path)
            lines.append(f"Wrote {len(members)} songs to {path}")
    lines.append(ADVICE)
    return lines
