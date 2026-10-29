# ipod2playlist

Reads the music off an iPod Classic and rebuilds it as Spotify and YouTube playlists. It can also back the
music up to your Mac, and export lists for other music services.
Tested on macOS.

## Quick start

You need Python 3.10 or newer, git, and uv (a web search finds the installer). Every step below is run in a
terminal from the project folder; everything the tool writes (`songs.json`, `progress.json`, tokens, reports)
lands there too, and is git-ignored.

### 1. Get the code

```
git clone https://github.com/JeshuaLinderJ/ipod-playlist-scripts.git
cd ipod-playlist-scripts
uv run ipod2playlist --help
```

The first `uv run` installs the dependencies; you should see the nine commands: `scan`, `spotify`, `youtube`,
`doctor`, `missing`, `review`, `apply-review`, `backup` and `export-csv`.

### 2. Spotify credentials

1. In the Spotify Developer Dashboard, create an app. When asked which API it uses, choose **Web API**.
2. Add the Redirect URI `http://127.0.0.1:8080/callback`. It must match the `.env` line below exactly, and it
   must say `127.0.0.1`, not `localhost` (Spotify rejects `localhost`).
3. In the app's settings, copy the Client ID and Client Secret into a file named `.env` in the project folder:

```
SPOTIPY_CLIENT_ID=...
SPOTIPY_CLIENT_SECRET=...
SPOTIPY_REDIRECT_URI=http://127.0.0.1:8080/callback
```

New Spotify apps run in "Development Mode" (see Spotify's "February 2026 migration guide"), which has two
rules that surprise people:

- **The owner of the app must have Spotify Premium.** If their Premium lapses, the app stops working until
  they subscribe again.
- **A new app allows at most 5 users.** Each family member who will log in must have their Spotify account
  added in the app's user settings on the Developer Dashboard. Otherwise Spotify refuses them with a message
  that the user may not be registered.

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

### 5. Check your setup

```
uv run ipod2playlist doctor
```

`doctor` looks at your setup and tells you what to do next. It makes no Spotify or YouTube calls and writes
nothing, so run it whenever you are unsure. You will see lines like:

```
ok   iPod found: /Volumes/Jo's iPod
ok   2375 songs in songs.json
ok   Spotify settings found
note client_secrets.json not found; only needed for YouTube (README step 3).
Next: ipod2playlist spotify --dry-run  (then ipod2playlist spotify)
```

`ok` means fine, `!!` means something needs fixing (the line says what), and `note` is only information.
The last line, `Next:`, is the one thing to do now. Before you have scanned, it says to scan the iPod, which is
the next step; run `doctor` again after each step to get the following one.

### 6. Scan it

```
uv run ipod2playlist scan "/Volumes/Jo's iPod"
```

You'll see something like:

```
Found 2412 songs, removed 37 duplicates; wrote 2375 to songs.json and songs.tsv
```

Open `songs.tsv` in a spreadsheet and check the artists and titles look right. You can eject the iPod now;
everything after this works from `songs.json`.

### 7. Try it on a few songs first

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

Two "dry run" commands show what would happen without changing anything:

```
uv run ipod2playlist spotify --dry-run
uv run ipod2playlist youtube --dry-run
```

`spotify --dry-run` still logs in and searches, but creates no playlist and adds nothing. It lists each song as
`would add` or `missing`, and ends with a line like `1 would be added / 1 missing / 0 skipped / 0 failed (dry
run: nothing was changed)`. `youtube --dry-run` searches nothing (searches use up your daily quota); it only
says how many songs it would search and about how many days of free quota that needs.

### 8. Do the real run

```
uv run ipod2playlist spotify
uv run ipod2playlist review --service spotify
# open spotify_review.csv, mark the good guesses y, save it (see below), then:
uv run ipod2playlist apply-review --service spotify
uv run ipod2playlist youtube --only-spotify-missing
```

`spotify` builds "My iPod Playlist". `review` then writes a report of the songs it couldn't find, so you can
check them; `apply-review` adds the ones you approved (next section). `youtube --only-spotify-missing` tries what is still missing on YouTube, about 66 a
day (see below). When it stops with "YouTube quota reached", re-run the same command the next day; it is done
when it finishes without that message.

The older `missing --service spotify` still works. It writes the songs Spotify couldn't find to
`spotify_missing.tsv`, a plain list with no checking.

#### Checking the near misses

When Spotify's best result is close but not good enough (say, the same song by "Miles Davis Quintet"), the song
is marked missing and the close result is remembered, as in `- missing: Miles Davis - So What (close match
saved for review)`. `review --service spotify` writes two files:

- `spotify_review.html`: open it in your browser. Each missing song shows its saved guess with a link to listen,
  and links to search for it yourself.
- `spotify_review.csv`: open it in Excel or Numbers. In the `Add? (y/n)` column type **y** for guesses that are
  right and **n** for wrong ones. Leave a row empty to decide later. Save it as **CSV UTF-8** (Excel's name for
  it; if you save it another way, `apply-review` says so and tells you to export it again). The
  `Key` column must stay as it is. Cells that start with `=`, `+`, `-` or `@` get a leading `'` so the
  spreadsheet shows them as text.

Then `apply-review --service spotify` adds the songs you marked y and prints a summary such as
`1 added / 1 rejected / 0 skipped / 0 failed`. Only the guess that was saved during the search is ever added;
the links and titles in the file are never read back, so editing them changes nothing. A song with no saved
guess is skipped (`skipped (no saved guess)`), and an n makes the tool forget the guess. Running it twice is
safe. The same works for YouTube (`--service youtube`).

## Things worth knowing

- **You can stop and re-run anything.** `progress.json` records every result; re-running continues into the
  same playlist and skips finished songs. A Ctrl-C may leave at most one song added twice.
- **If you deleted the playlist online**, the tool notices before searching anything, so no YouTube quota is
  spent, and stops with a message saying the playlist no longer exists. Run `ipod2playlist spotify --new-playlist`
  (or `youtube --new-playlist`) to start a fresh one. This forgets the saved playlist and results of that one
  service only; the other service's progress is kept.
- **After upgrading from 1.5, Spotify asks you to log in once more.** Version 1.7 asks for one more permission
  (`user-library-read`), which it needs to check whether your playlist still exists. Log in again in the
  browser and carry on; your playlist and progress are untouched.
- **One-way upgrade.** After you scan with 1.7, the new `songs.json` will not load in 1.5. If you ever go back,
  scan again.
- **When it stops, it says why.** Instead of a wall of text, you get one line, and the command's exit code
  tells scripts what happened: 0 fine, 1 an error with the message printed (a missing file, a Spotify or
  YouTube login or permission problem, no network), 2 YouTube quota reached ("YouTube quota reached; progress
  saved. Re-run this command after the quota resets."; also used for a mistyped option), 3 the saved playlist no
  longer exists, 130 you pressed Ctrl-C ("Stopped. Progress is saved; re-run the same command to continue.").
- **YouTube quota.** The free quota (10,000 units a day) fits about 66 songs: a search costs 100 units, adding
  one costs 50. When it runs out the command saves progress and stops; re-run it the next day.
- **Strict matching.** The artist must match, and live, karaoke, cover and remix versions are never swapped in.
  When it isn't sure, the song goes on the missing list instead of the wrong song going into your playlist.
- **Near misses go to review.** A close but not good enough result is never added by itself; it is saved so you
  can approve it with `review` and `apply-review`.
- **Untagged songs are not searched.** A song with no artist (shown as "Unknown Artist") can't be matched
  safely, so it is marked missing without a search, with no quota spent. `scan --itunesdb` (below) can
  recover many of these names.
- **Playlists are private.** Pass `--public` when the playlist is first created to make it public.
- **WAV files** carry no tags on an iPod (iTunes keeps their details in its own database), so they show up
  under scrambled names like `QRST`. See "The iPod's own database" below for a way to get the real names.

## Back up the music

```
uv run ipod2playlist backup "/Volumes/Jo's iPod" ~/Music/"iPod backup"
```

Copies every song off the iPod into folders like `Artist/Album/Title.mp3` in the destination, and writes
playlist files. It prints one line per copied file, then a summary such as
`5 copied / 0 already there / 0 left alone; wrote 1 playlist file(s) to ...`.

- **It only reads the iPod.** Nothing is ever written to it.
- **You can stop and re-run it.** Files already copied (same size and date) are counted as "already there".
- **It never overwrites a file.** If a different file already has the name, the new song is copied with a
  name like `Title (2).mp3`, and the summary counts it under "left alone". Nothing is lost.
- **Songs whose tags could not be read** are still copied, into an `Unreadable/` folder in the backup.
- **Playlists:** `My iPod.m3u8` lists every song. The `.m3u8` files are rewritten on every run (the music
  files never are). To use one, import it in Music.app (File > Import) or open it in VLC.
- **`.m4p` files** were bought from iTunes with copy protection. They are copied, but only play on a computer
  authorised with the Apple ID that bought them; the summary says how many there are.
- If a few files could not be copied, it ends with `N files could not be copied; run the same backup again
  to retry.` Check there is enough space: it stops early if the destination is too small.
- Add `--itunesdb` (below) to also get the iPod's own playlists and the real names of untagged songs.

## The iPod's own database (optional)

The iPod keeps its own database of what is on it. Reading it recovers things the song files don't have:
the real names of untagged songs (including the scrambled WAV names), star ratings, play counts, and the
playlists you made on the iPod. It needs one extra package, so run it from the project folder like this:

```
uv run --extra itunesdb ipod2playlist scan "/Volumes/Jo's iPod" --itunesdb
```

You'll see an extra line such as `Read the iPod's database: 37 untagged songs named, 4 playlists saved to
ipod_playlists.json`. The playlists go into `ipod_playlists.json`, and `songs.json` lists the most-played songs
first, so a day-limited YouTube run does your favourites first. `backup --itunesdb` uses the same data, and `export-csv` turns
the saved playlists into CSV files. Without the extra package, the command stops and prints the install command; if the database can't
be read, you get a warning and a normal scan.

It works on a copy of the database and never writes to the iPod. The package that reads it, pygpod, is young
(Beta), so treat the result as a bonus and check a few names against the iPod's screen.

Prefer one global command? From the project folder, `uv tool install '.[itunesdb]'` installs `ipod2playlist`
with this support. Songs recorded as missing earlier because they were untagged are only searched again with
`--retry-missing` after you re-scan with `--itunesdb`.

## Other music services

```
uv run ipod2playlist export-csv
```

Writes `library.csv` (title, artist, album) of every scanned song, plus one `playlist_<name>.csv` for each
playlist from `ipod_playlists.json`. Upload one at Soundiiz or TuneMyMusic (a web search finds them) to
rebuild it on Apple Music, Deezer, Tidal and others. `export-csv --service spotify` writes only the songs
Spotify couldn't find, to `spotify_missing.csv`.

- **Try a 3-song file first.** Soundiiz's sample file has more columns than ours, and whether it accepts
  ours is unverified; TuneMyMusic's format is unverified too. Make a small CSV and check it imports before you
  upload the real one.
- **Their matching is looser** than ipod2playlist's, so check the result for wrong songs.

## Command reference

| Command | What it does |
|---|---|
| `scan ROOT` | Reads the iPod into `songs.json` and `songs.tsv`, removing duplicates. `--itunesdb` also reads the iPod's own database (names, ratings, play counts, playlists to `ipod_playlists.json`). |
| `spotify` | Searches Spotify for each song and adds matches to a playlist. |
| `youtube` | Same on YouTube. `--only-spotify-missing` limits it to songs Spotify couldn't find. |
| `doctor` | Checks the setup and says what to do next. No API calls, writes nothing. |
| `missing --service spotify\|youtube` | Writes `<service>_missing.tsv` from saved results; no API calls. |
| `review --service spotify\|youtube` | Writes `<service>_review.html` and `<service>_review.csv` of missing songs and close guesses; no API calls. |
| `apply-review --service spotify\|youtube` | Adds the close guesses marked y in the review CSV. `--file` uses another CSV. |
| `backup ROOT DEST` | Copies every song to DEST with M3U8 playlists. `--itunesdb` adds the iPod's playlists and names. |
| `export-csv` | Writes `library.csv` (and playlist CSVs) for Soundiiz or TuneMyMusic. `--service` exports only that service's missing songs; `--out FILE` picks the file. |

`spotify` and `youtube` also take:

- `--name` (playlist name), `--public`,
- `--retry-missing` (search again for songs marked missing),
- `--dry-run` (show what would happen, change nothing),
- `--new-playlist` (start a new playlist, forgetting only that service's saved results; can't be combined with
  `--dry-run`).

`youtube`, `doctor` and `apply-review` also take `--client-secrets` (the Google client file) and `--token`
(where the YouTube login is saved, default `youtube_token.json`). The default client file is
`client_secrets.json`; setting the `YOUTUBE_CLIENT_SECRETS` environment variable to another path changes that
default. Most commands take `--songs` and `--progress` to use other files (`scan` takes only `--songs`, `backup` neither, and `apply-review` only `--progress`). `uv run ipod2playlist COMMAND --help` lists everything.

Prefer a global command? From the project folder, `uv tool install .` installs `ipod2playlist`; then run it
from whichever folder holds your `.env` and `client_secrets.json`.

Files the tool writes in the current folder, all git-ignored: `songs.json`, `songs.tsv`, `progress.json`,
`ipod_playlists.json`, `<service>_missing.tsv`, `<service>_review.csv`, `<service>_review.html`, `library.csv`,
`<service>_missing.csv`, `playlist_<name>.csv`.

## Limits

- On a backup drive formatted FAT, running `backup` again right after a daylight-saving change may copy the
  library again (FAT stores local time). This is unverified; `rsync` has the same limitation.
- Accented folder names on HFS+ or FAT drives may be stored in a different Unicode form in the playlist files.
  That is fine on a Mac; some non-Mac players may not match them.
- Python 3.10 works, but Google's library prints a warning; Python 3.11 or newer avoids it.

## Manual checks before a release

These need a real iPod and real accounts, so no automated test covers them:

1. Delete a test playlist in the Spotify app, re-run `spotify`, and expect the "no longer exists" message.
2. Do the same on YouTube.
3. Run `scan --itunesdb` on the real iPod and compare the WAV names with the iPod's screen.
4. Run `backup` on the real iPod and compare the file counts.
5. Upload `library.csv` with 3 songs to Soundiiz and to TuneMyMusic.

## Development

`uv run pytest`. No test touches the network: they use a virtual iPod and fake Spotify and YouTube clients.

## Background

The original scripts were written with LLM assistance as a favour for family, then debugged by hand; this is
the tidied-up, tested rewrite. Consoles are named rather than linked, since links go stale.
