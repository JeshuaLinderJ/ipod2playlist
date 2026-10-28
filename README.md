# ipod2playlist

Reads the music off an iPod Classic and rebuilds it as Spotify and YouTube playlists.

The original scripts were written with LLM assistance, as a favour for family, and then debugged by hand
where the LLM's lack of real reasoning showed. This is the tidied-up rewrite.

As before, I name the consoles rather than link them: links go stale, and shells differ.

## Install

Needs Python and uv (a web search finds the installer).

- `uv tool install .` gives you an `ipod2playlist` command, or
- `uv run ipod2playlist ...` from the project folder, with no install.

Run commands from a folder of your choice: `.env`, `songs.json`, `progress.json` and friends are read and
written in the current working directory.

## Credentials

**Spotify.** In the Spotify Developer Dashboard, create an app and add a Redirect URI (any `http://127.0.0.1:PORT/...`
address). Put its details in a `.env` file:

```
SPOTIPY_CLIENT_ID=...
SPOTIPY_CLIENT_SECRET=...
SPOTIPY_REDIRECT_URI=http://127.0.0.1:8080/callback
```

The first run opens a browser to log in; spotipy caches the token in `.cache`.

**YouTube.** In Google Cloud Console, create a project, enable YouTube Data API v3, and create an
OAuth client ID of type "Desktop app". Download its JSON as `client_secrets.json` into the folder you run from
(or point `YOUTUBE_CLIENT_SECRETS` in `.env`, or `--client-secrets`, at it). While the app is in testing, add your
Google account as a test user. The first run opens a browser; the token is saved to `youtube_token.json`
(owner-only permissions).

`.env`, `client_secrets.json`, `youtube_token.json` and `.cache` are git-ignored.

## Usage

Recommended flow:

```
ipod2playlist scan /Volumes/IPOD
ipod2playlist spotify
ipod2playlist missing --service spotify
ipod2playlist youtube --only-spotify-missing
```

- `scan ROOT` reads the iPod (its mount point) into `songs.json` and `songs.tsv`, removing duplicates.
- `spotify` / `youtube` search each song and add it to a playlist (named "My iPod Playlist" unless you pass `--name`).
  Playlists are **private**; pass `--public` to make them public (it only takes effect when the playlist is first created). `--retry-missing` searches again for songs
  previously marked missing. `youtube --only-spotify-missing` restricts it to songs Spotify could not find.
- `missing --service spotify|youtube` writes `spotify_missing.tsv` / `youtube_missing.tsv` (no API calls).
- `--songs` and `--progress` override `songs.json` and `progress.json` on every command.
  `ipod2playlist COMMAND --help` lists everything.

## Things worth knowing

- **Resumable.** `progress.json` records every result. Re-running continues into the same playlist and skips
  finished songs. If you deleted the playlist online, delete `progress.json` too (or just re-run if the failure
  was a transient error). A Ctrl-C may leave at most one song added twice.
- **YouTube quota.** The default quota (10,000 units a day) fits about 66 songs: a search costs 100 units, an
  insert 50. When it runs out the command saves progress and exits with code 2. Re-run the next day.
  This is why Spotify goes first.
- **Strict matching.** The artist must match, and live, karaoke, cover and remix versions are not substituted.
  If it isn't sure, the song goes to the missing list rather than the wrong song into your playlist.
- **WAV files** carry no tags on an iPod (iTunes keeps their metadata only in iTunesDB), so they show up under
  their scrambled filename.

## Development

`uv run pytest`. No test touches the network: they use a virtual iPod and fake Spotify and YouTube clients.

## Manual check with a real iPod and real accounts

1. Mount the iPod, run `scan` on it, and open `songs.tsv`: do the artists and titles look right?
2. Copy `songs.json` to `tiny.json`, keep only a few entries, and run `spotify --songs tiny.json --progress tiny_progress.json`. The separate progress file keeps this test playlist apart from the real run.
3. Run `youtube` on a couple of songs the same way (same `--songs` and `--progress`).
4. Re-run both commands: nothing should be added again, and the same playlist is used.
5. In Spotify and YouTube, confirm the playlists are private.
6. Run `missing --service spotify` and check that the listed songs really are absent.
