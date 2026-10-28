# ipod2playlist

Reads the music off an iPod Classic and rebuilds it as Spotify and YouTube playlists.
Tested on macOS.

## Quick start

You need Python 3.10 or newer, git, and uv (a web search finds the installer). Every step below is run in a
terminal from the project folder; everything the tool writes (`songs.json`, `progress.json`, tokens) lands
there too, and is git-ignored.

### 1. Get the code

```
git clone https://github.com/JeshuaLinderJ/ipod-playlist-scripts.git
cd ipod-playlist-scripts
uv run ipod2playlist --help
```

The first `uv run` installs the dependencies; you should see the four commands: `scan`, `spotify`, `youtube`,
`missing`.

### 2. Spotify credentials

1. In the Spotify Developer Dashboard, create an app. When asked which API it uses, choose **Web API**.
2. Add the Redirect URI `http://127.0.0.1:8080/callback`. It must match the `.env` line below exactly.
3. In the app's settings, copy the Client ID and Client Secret into a file named `.env` in the project folder:

```
SPOTIPY_CLIENT_ID=...
SPOTIPY_CLIENT_SECRET=...
SPOTIPY_REDIRECT_URI=http://127.0.0.1:8080/callback
```

### 3. YouTube credentials (optional; only for songs Spotify can't find)

1. In Google Cloud Console, create a project and enable **YouTube Data API v3**.
2. Configure the OAuth consent screen, and add your own Google account as a **test user**.
3. Create an OAuth client ID of type **Desktop app** and download its JSON.
4. Move it into the project folder and rename it to `client_secrets.json`
   (Google names it `client_secret_<long id>.json`).

### 4. Connect the iPod

1. Plug in the iPod and select it in Finder's sidebar.
2. Tick **Enable disk use** in its options and apply, so it shows up as a drive.
3. Find its path with `ls /Volumes`. It's usually the iPod's name, e.g. `/Volumes/Jo's iPod`. Keep the quotes
   when the name has spaces or an apostrophe, or drag the drive from Finder into the terminal to paste its path.

### 5. Scan it

```
uv run ipod2playlist scan "/Volumes/Jo's iPod"
```

You'll see something like:

```
Found 2412 songs, removed 37 duplicates; wrote 2375 to songs.json and songs.tsv
```

Open `songs.tsv` in a spreadsheet and check the artists and titles look right. You can eject the iPod now;
everything after this works from `songs.json`.

### 6. Try it on a few songs first

```
cp songs.json tiny.json          # then edit tiny.json down to 3-4 songs
uv run ipod2playlist spotify --songs tiny.json --progress tiny_progress.json --name "ipod2playlist test"
```

A browser opens once to log in to Spotify. Then you'll see one line per song and a summary:

```
+ added: Radiohead - Karma Police
- missing: Some Band - Rare B-Side
1 added / 1 missing / 0 skipped / 0 failed
```

Check the "ipod2playlist test" playlist in Spotify, then delete it. Do the same with `youtube` if you set it up.

### 7. Do the real run

```
uv run ipod2playlist spotify
uv run ipod2playlist missing --service spotify
uv run ipod2playlist youtube --only-spotify-missing
```

`spotify` builds "My iPod Playlist". `missing` writes the songs it couldn't find to `spotify_missing.tsv`.
`youtube --only-spotify-missing` tries those on YouTube, about 66 a day (see below). When it stops with
"YouTube quota reached", re-run the same command the next day; it is done when it finishes without that message.

## Things worth knowing

- **You can stop and re-run anything.** `progress.json` records every result; re-running continues into the
  same playlist and skips finished songs. A Ctrl-C may leave at most one song added twice. If you deleted the
  playlist online, delete `progress.json` to start a new one.
- **YouTube quota.** The free quota (10,000 units a day) fits about 66 songs: a search costs 100 units, adding
  one costs 50. When it runs out the command saves progress and stops; re-run it the next day.
- **Strict matching.** The artist must match, and live, karaoke, cover and remix versions are never swapped in.
  When it isn't sure, the song goes on the missing list instead of the wrong song going into your playlist.
- **Playlists are private.** Pass `--public` when the playlist is first created to make it public.
- **WAV files** carry no tags on an iPod (iTunes keeps their details in its own database), so they show up
  under scrambled names like `QRST`.

## Command reference

| Command | What it does |
|---|---|
| `scan PATH` | Reads the iPod into `songs.json` and `songs.tsv`, removing duplicates. |
| `spotify` | Searches Spotify for each song and adds matches to a playlist. |
| `youtube` | Same on YouTube. `--only-spotify-missing` limits it to songs Spotify couldn't find. |
| `missing --service spotify\|youtube` | Writes `<service>_missing.tsv` from saved results; no API calls. |

`spotify` and `youtube` also take `--name`, `--public`, and `--retry-missing` (search again for songs marked
missing). Every command takes `--songs` and `--progress` to use other files.
`uv run ipod2playlist COMMAND --help` lists everything.

Prefer a global command? `uv tool install .` installs `ipod2playlist`; then run it from whichever folder holds
your `.env` and `client_secrets.json`.

## Development

`uv run pytest`. No test touches the network: they use a virtual iPod and fake Spotify and YouTube clients.

## Background

The original scripts were written with LLM assistance as a favour for family, then debugged by hand; this is
the tidied-up, tested rewrite. Consoles are named rather than linked, since links go stale.
