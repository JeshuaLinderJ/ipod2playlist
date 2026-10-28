# ipod2playlist — rewrite plan

Turn three copy-pasted scripts into one small, tested, resumable CLI that
reads an iPod Classic (disk mode) and builds Spotify / YouTube playlists.

## Spec

### Problems being fixed (from the review of the original scripts)

1. No resume: a YouTube quota failure mid-run means re-running creates a new playlist and restarts at song 1.
2. No de-duplication of songs.
3. `lost_songs.py` repeats every Spotify search already done by `create_playlists.py`.
4. No error handling around YouTube calls; one HttpError kills the run.
5. Audio extensions miss `.m4p`, `.wav`, `.aif`, `.aiff`; macOS `._*` AppleDouble files are not skipped.
6. Matching takes Spotify's/YouTube's first result blindly; strict query fails on "(Remastered)"/"feat." variants.
7. Credentials are hardcoded empty strings in source (invites committing secrets).
8. Config via editing constants; no CLI.
9. Playlists are created public by default.
10. `.DS_Store` committed; no dependency manifest.
11. `load_songs` and Spotify auth/search duplicated across scripts.

### Target behaviour

```
ipod2playlist scan /Volumes/IPOD          # -> songs.json (+ songs.tsv), deduplicated
ipod2playlist spotify [--name N] [--public] [--retry-missing]
ipod2playlist youtube [--name N] [--public] [--retry-missing] [--only-spotify-missing]
ipod2playlist missing --service spotify   # -> spotify_missing.tsv, from progress.json, zero API calls
```

All playlist commands share `progress.json`, which records each service's
playlist id and a per-song status (`added` / `missing`). Re-running any command
continues where it stopped and reuses the same playlist. A YouTube quota error
saves progress and exits with a clear "re-run after quota resets" message.

### Non-goals (possible future work, do NOT build)

- Parsing `iTunesDB` for the iPod's own playlists / play counts.
- Docker packaging (uv makes setup a one-liner already).
- Any GUI.

## Global Constraints (bind every task)

- **Pragmatic, simple, legible.** Plain functions and small classes. No
  abstract base classes, plugin registries, or frameworks. A module should read
  top-to-bottom in a couple of minutes (aim < 150 lines). Prefer the obvious
  solution over the clever one.
- **Don't reinvent the wheel.** Use these libraries and nothing home-grown in their place:
  `mutagen` (tags), `spotipy` (Spotify; it already reads `SPOTIPY_CLIENT_ID`,
  `SPOTIPY_CLIENT_SECRET`, `SPOTIPY_REDIRECT_URI` from the environment and handles
  token caching and retries), `google-api-python-client` + `google-auth-oauthlib`
  (YouTube), `rapidfuzz` (fuzzy matching), `python-dotenv` (`.env` loading),
  stdlib `argparse`, `dataclasses`, `json`, `pathlib`. Dev: `pytest`.
- **Python ≥ 3.10, managed with `uv`.** `src/` layout, package `ipod2playlist`,
  console script `ipod2playlist = "ipod2playlist.cli:main"`.
- **Testability by injection.** Code that talks to Spotify/YouTube receives
  the API client object as a parameter. Only `make_client()` functions construct
  real clients. **No test touches the network or needs credentials.**
- **Test everything.** Every task adds pytest tests for the behaviour it adds;
  `uv run pytest` passes at the end of every task. Tests assert behaviour, not
  implementation details.
- **No secrets in the repo.** `.env`, `client_secrets.json`, token caches, and
  generated outputs are git-ignored.
- Commit at the end of each task with a descriptive message.

## Shared interfaces (exact — later tasks depend on these)

```python
# ipod2playlist/library.py
@dataclass(frozen=True)
class Song:
    title: str
    artist: str
    album: str
    path: str
    @property
    def key(self) -> str: ...        # f"{norm(artist)}|{norm(title)}", norm = casefold + collapse whitespace + strip

def dedupe(songs: list[Song]) -> list[Song]            # keep first occurrence per key, preserve order
def save_songs(songs: list[Song], path: Path) -> None  # JSON list of dicts, indent=2, ensure_ascii=False
def load_songs(path: Path) -> list[Song]
def write_tsv(songs: list[Song], path: Path) -> None   # header "Title\tArtist\tAlbum\tPath"

# ipod2playlist/scan.py
AUDIO_EXTENSIONS: frozenset[str]   # .mp3 .m4a .m4p .aac .flac .ogg .wav .aif .aiff
def read_song(path: Path) -> Song | None
def scan(root: Path) -> list[Song]  # sorted walk, skips files starting with "._", NOT deduplicated

# ipod2playlist/matching.py
@dataclass(frozen=True)
class Candidate:
    id: str
    title: str
    artist: str
def normalize(text: str) -> str
def score(song: Song, candidate: Candidate) -> float    # 0..100
def best_match(song: Song, candidates: list[Candidate], threshold: float = 80) -> Candidate | None

# ipod2playlist/progress.py
class Progress:
    def __init__(self, path: Path)                      # loads file if it exists
    def playlist_id(self, service: str) -> str | None
    def set_playlist_id(self, service: str, playlist_id: str) -> None
    def status(self, service: str, song_key: str) -> str | None   # "added" | "missing" | None
    def record(self, service: str, song_key: str, status: str) -> None
    def keys_with_status(self, service: str, status: str) -> list[str]
    def save(self) -> None                              # atomic: write tmp file then os.replace

# ipod2playlist/spotify.py  and  ipod2playlist/youtube.py  (same shape)
class SpotifyService / YouTubeService:
    name: str                                           # "spotify" / "youtube"
    def __init__(self, client)
    def search(self, song: Song) -> list[Candidate]
    def create_playlist(self, name: str, public: bool) -> str
    def add(self, playlist_id: str, item_id: str) -> None
def make_client(...)                                    # builds the real API client; not unit tested

# ipod2playlist/youtube.py only
class QuotaExceeded(Exception)

# ipod2playlist/sync.py
@dataclass
class SyncResult:
    added: int
    missing: int
    skipped: int        # already had a status from a previous run
    failed: int         # transient per-song errors; left unrecorded so a re-run retries them
def sync(songs, service, progress, playlist_name, public=False, retry_missing=False) -> SyncResult
```

## Task 1: Project scaffold and song library

Files: `pyproject.toml`, `.gitignore`, `src/ipod2playlist/__init__.py`,
`src/ipod2playlist/library.py`, `tests/test_library.py`. Delete the committed `.DS_Store`.

- `uv init`-style `pyproject.toml` (build backend `hatchling`), runtime deps:
  mutagen, spotipy, google-api-python-client, google-auth-oauthlib, rapidfuzz,
  python-dotenv; dev dependency group with pytest. Console script entry as in
  Global Constraints (point at `ipod2playlist.cli:main`; create a placeholder
  `cli.py` with `def main(): raise SystemExit("not implemented yet")` so install works).
  Generate and commit `uv.lock`.
- `.gitignore`: `.DS_Store`, `__pycache__/`, `.venv/`, `.pytest_cache/`, `.env`,
  `client_secrets.json`, `*token*.json`, `.cache*`, `songs.json`, `songs.tsv`,
  `progress.json`, `*_missing.tsv`, `.superpowers/`.
  Also ignore the original outputs `ipod_song_list.*`, `spotify_missing_songs.txt`.
- `library.py` exactly per the Shared interfaces.
- Tests: `key` is case/whitespace-insensitive; `dedupe` keeps first and order;
  `save_songs` → `load_songs` round-trip including non-ASCII ("Beyoncé", "Sigur Rós");
  `write_tsv` header and one row.
- Do NOT delete the original three scripts yet (Task 8 does).

## Task 2: Virtual iPod fixture and scanner

Files: `tests/fixtures/make_fixtures.sh`, `tests/fixtures/silence.{mp3,m4a,flac,wav}`,
`tests/conftest.py`, `src/ipod2playlist/scan.py`, `tests/test_scan.py`.

- `make_fixtures.sh`: ffmpeg one-liners producing ~0.5 s mono silent files at a
  low bitrate (each file must stay < 20 KB). Run it once and commit the outputs,
  so tests do not need ffmpeg.
- `conftest.py` fixture `fake_ipod(tmp_path) -> Path` building a realistic
  iPod Classic disk-mode tree:
  `iPod_Control/Music/F00/ABCD.mp3`, `F01/EFGH.m4a`, `F02/IJKL.flac`, … with
  obfuscated 4-letter names, tags written via mutagen (easy interface). Include:
  two files with the same artist/title (duplicate), one audio file with no tags,
  one `.wav`, one `._ABCD.mp3` AppleDouble junk file (copy of bytes is fine or
  random bytes), one non-audio file `iPod_Control/iTunes/iTunesDB` (random bytes).
  Return the iPod root.
- `scan.py` per Shared interfaces. `read_song` uses `mutagen.File(path, easy=True)`;
  missing tags fall back to `"Unknown Artist"`, `"Unknown Album"`, and the
  filename stem for title. Unreadable files: print a one-line warning to stderr,
  return None. `scan` walks with `sorted()` order so output is deterministic.
- Tests against `fake_ipod`: correct count (junk skipped, duplicate still
  present — scan does not dedupe), tags read for each format, untagged fallback,
  AppleDouble skipped, iTunesDB skipped, corrupt `.mp3` (random bytes) does not crash.

## Task 3: Fuzzy matching

Files: `src/ipod2playlist/matching.py`, `tests/test_matching.py`.

- `normalize`: casefold, strip accents (`unicodedata`), remove bracketed/parenthesised
  noise and trailing "- … Remaster…" segments, remove "feat./ft./featuring …"
  parts, drop punctuation, collapse whitespace.
- `score`: built on `rapidfuzz.fuzz` over normalized fields, combining a title
  similarity and an artist similarity (title weighted more). Must handle YouTube
  candidates where `candidate.title` is a video title like
  `"Artist - Song (Official Video)"` and `candidate.artist` is a channel name like
  `"ArtistVEVO"` or `"Artist - Topic"`. Keep the formula short and commented.
- `best_match`: highest score at/above threshold, else None.
- Tests (these ARE the spec; all must pass with default threshold 80):
  - exact title/artist → match
  - iPod "Song (Remastered 2009)" vs candidate "Song" → match, and vice versa "Song - 2011 Remaster"
  - "Song (feat. X)" vs "Song" → match
  - accents: "Jóga" / "Björk" vs "Joga" / "Bjork" → match
  - same title, different artist ("Hello"/"Adele" vs "Hello"/"Lionel Richie") → no match
  - different title, same artist → no match
  - YouTube style: Song("Karma Police","Radiohead") vs Candidate("Radiohead - Karma Police (Official Video)", "RadioheadVEVO") → match;
    and vs Candidate("Karma Police", "Radiohead - Topic") → match
  - `best_match` picks the higher scorer among several, and returns None for empty list.

## Task 4: Resumable progress store

Files: `src/ipod2playlist/progress.py`, `tests/test_progress.py`.

- Per Shared interfaces. File format:
  `{"version": 1, "services": {"spotify": {"playlist_id": "...", "songs": {"<key>": "added"}}}}`.
- `record` rejects statuses other than `"added"` / `"missing"` with ValueError.
- `save` is atomic (tmp file in same dir + `os.replace`).
- Tests: fresh path → empty; set/get playlist id; record/status; persisted across a
  new `Progress` instance; services are independent; `keys_with_status`; invalid
  status raises; a leftover `.tmp` file or crash between writes never corrupts the
  existing file (simulate by asserting original content intact if write raises).

## Task 5: Spotify service

Files: `src/ipod2playlist/spotify.py`, `tests/fakes.py`, `tests/test_spotify.py`.

- `SpotifyService(client)` where client is a `spotipy.Spotify` (or fake).
  - `search`: strict query `track:"{title}" artist:"{artist}"` with `limit=5`; if
    it returns nothing, fall back to plain `f"{title} {artist}"` query `limit=5`.
    Map items to `Candidate(id=uri-or-id, title=name, artist=", ".join(artist names))`.
  - `create_playlist(name, public)`: create via the current-user playlist creation
    method available in the installed spotipy version (check its source; Spotify
    has deprecated some user-id endpoints) and return the playlist id.
  - `add(playlist_id, item_id)`: `playlist_add_items(playlist_id, [item_id])`.
- `make_client()`: `spotipy.Spotify(auth_manager=SpotifyOAuth(scope="playlist-modify-private playlist-modify-public"))`
  — credentials come from env vars that spotipy reads itself.
- `tests/fakes.py`: `FakeSpotify` implementing only the methods used, backed by an
  in-memory catalog list of dicts, recording created playlists and added items, and
  modelling the strict-vs-loose query behaviour (strict query matches exactly on
  title+artist; loose matches substring). Keep it small.
- Tests: strict hit; strict miss → loose hit; total miss → []; candidate mapping
  (multiple artists joined); create_playlist honours `public`; add records the item.

## Task 6: YouTube service

Files: `src/ipod2playlist/youtube.py`, extend `tests/fakes.py`, `tests/test_youtube.py`.

- `YouTubeService(client)` where client is a `googleapiclient` youtube resource (or fake).
  - `search`: `search().list(part="snippet", q=f"{artist} - {title}", type="video", maxResults=5)`;
    Candidate(id=videoId, title=snippet.title (HTML-unescaped), artist=snippet.channelTitle).
  - `create_playlist`: privacyStatus `"public"` or `"private"`.
  - `add`: `playlistItems().insert(...)`.
  - Any `googleapiclient.errors.HttpError` whose reason is `quotaExceeded` or
    `dailyLimitExceeded` is re-raised as `QuotaExceeded`. Other HttpErrors propagate unchanged.
- `make_client(secrets_file: Path, token_file: Path)`: load cached credentials from
  `token_file` (google.oauth2.credentials), refresh if expired, otherwise run
  `InstalledAppFlow.run_local_server(port=0)`; save token. Scope
  `https://www.googleapis.com/auth/youtube`. Not unit tested.
- `FakeYouTube`: mimics the `client.search().list(**kw).execute()` chain, plus
  `playlists().insert` and `playlistItems().insert`; can be configured to raise a
  real `HttpError` (built with a minimal resp object and JSON content) after N calls,
  with a chosen reason.
- Tests: search mapping + HTML unescape; privacy status; add; quotaExceeded →
  QuotaExceeded; other 404 HttpError → HttpError (not QuotaExceeded).

## Task 7: Sync pipeline

Files: `src/ipod2playlist/sync.py`, `tests/test_sync.py`.

- `sync(...)` per Shared interfaces:
  1. Reuse `progress.playlist_id(service.name)` or create one and save progress immediately.
  2. For each song: skip if it already has a status (unless status is `missing` and
     `retry_missing`) → `skipped`. Else search → `best_match` → `add` + record `added`,
     or record `missing`. Save progress after every song.
  3. `QuotaExceeded`: save and re-raise (caller reports). Any other exception for a
     single song: print a warning, count `failed`, leave it unrecorded, continue.
  4. Print one line per song (`+ added`, `- missing`, `! failed`).
- Tests with fakes: full run counts; second run skips everything and creates no new
  playlist; quota error after N songs → progress has N songs, re-run with a fresh fake
  finishes the rest into the SAME playlist id; `retry_missing` re-searches missing songs;
  transient error on one song → `failed=1`, others still processed.

## Task 8: CLI, missing-songs report, end-to-end test, remove old scripts

Files: `src/ipod2playlist/cli.py`, `tests/test_cli.py`; delete
`ipod_read_script.py`, `create_playlists.py`, `lost_songs.py`.

- argparse subcommands exactly as in Spec → Target behaviour. Common options:
  `--songs` (default `songs.json`), `--progress` (default `progress.json`).
  `scan` writes `songs.json` + `songs.tsv` (deduped) and prints counts (found, duplicates removed).
  `youtube` options `--client-secrets` (default env `YOUTUBE_CLIENT_SECRETS` or
  `client_secrets.json`) and `--token` (default `youtube_token.json`).
  `--only-spotify-missing` limits songs to keys with status `missing` under spotify.
  `missing --service S` writes `{S}_missing.tsv` from progress (no API).
  Default playlist names: "My iPod Playlist".
- `main(argv=None)` calls `load_dotenv()` first. QuotaExceeded → message "YouTube
  quota reached; progress saved. Re-run this command after the quota resets." and exit code 2.
- To make the CLI testable, service construction goes through a small
  module-level function (e.g. `_build_service(name, args)`) that tests monkeypatch to
  return services wrapping the fakes.
- End-to-end test: `scan` the `fake_ipod` → `spotify` (fake catalog missing some songs)
  → `missing --service spotify` → `youtube --only-spotify-missing` with a fake that hits
  quota part-way (exit code 2) → re-run finishes; assert the final progress and output files.

## Task 9: README

Rewrite `README.md`: what it does, install (`uv tool install .` or `uv run`),
Spotify + Google credential setup via `.env` / `client_secrets.json` (keep the
original author's no-dead-links philosophy: name the consoles, don't deep-link),
usage of each command, resume/quota behaviour (~66 songs/day on default YouTube quota:
search 100 units + insert 50 of 10,000), running tests (`uv run pytest`), and a
**manual verification checklist** for a real iPod + real accounts. Keep it short.
