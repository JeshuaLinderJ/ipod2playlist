# ipod2playlist: future feature scope and prior art

Research date: 2026-10-28. Scope: design only; the repo was not modified.
Codebase read: `README.md`, `src/ipod2playlist/*.py` (537 lines: scan, library, matching, sync, progress,
spotify, youtube, cli), `pyproject.toml`.

Maintenance status comes from the PyPI JSON API (`https://pypi.org/pypi/<name>/json`), checked today, plus
the project pages linked below. "Py 3.10+" means `requires_python` and/or classifiers allow 3.10.

---

## 0. Findings that affect the project today, before any new feature

1. **Spotify Development Mode changed in February 2026.** A Development Mode app now needs its *owner* to
   have an active Spotify Premium subscription (the app stops working if it lapses). It also allows one
   Client ID per developer and at most 5 authorised users. Search `limit` is capped at 10, and some
   endpoints were renamed (`POST /me/playlists`, `/playlists/{id}/items`).
   - The current code is still compatible: `SEARCH_LIMIT = 5`, and spotipy 2.26.0 already calls
     `me/playlists` and `playlists/{id}/items` (checked in the installed `spotipy/client.py`).
   - The README does not mention the Premium requirement. A family member without Premium would get
     an unexplained failure, so step 2 of the README should say so.
   - Source: https://developer.spotify.com/documentation/web-api/tutorials/february-2026-migration-guide,
     https://developer.spotify.com/blog/2026-02-06-update-on-developer-access-and-platform-security
2. **rapidfuzz 3.14.6 (2026-08-30) requires Python >= 3.11.** The project declares `>=3.10` and
   `rapidfuzz>=3.14.5`. 3.14.5 still supports 3.10 and uv's resolver handles this, so nothing is broken.
   But a future floor bump would quietly drop 3.10. A CI job on 3.10, or a note, would catch it.
3. **`write_tsv` does not escape tabs or newlines in tags.** Using the stdlib `csv` module, with
   `delimiter="\t"` or plain CSV, fixes this for free. It is relevant to features 5c and 6c.
4. **Odesli/song.link API is retired.** `v1-alpha.1` was sunset on 2026-07-31 (it returns 410 Gone),
   and no new keys are being issued. Any "convert a Spotify link to a YouTube link without searching"
   plan based on it is dead. Source: https://linktree.notion.site/API-d0ebe08a5e304a55928405eb682f6741

---

## 1. Reading iTunesDB on an iPod Classic (revisits a non-goal)

**What it unlocks:** real titles and artists for WAV files, the iPod's own playlists (including on-the-go
playlists), star ratings, play counts and skip counts. It also gives a stable per-track database ID.

### Options surveyed

| Option | Status | Verdict |
|---|---|---|
| **libgpod Python bindings** (`python-gpod`) | Last upstream release 0.8.3, from about 2013. Distro packages depend on `python (<< 2.8)` and the deprecated `python-gobject-2`. No Python 3 port found. Source: https://packages.debian.org/buster/python-gpod | Dead. Do not use. |
| **pygpod** (Bionded/pygpod) | 0.2.3, released 2026-10-26. 7 releases since 2026-03-22. Pure Python. `requires_python >=3.8`, classifiers 3.8 to 3.14. LGPL-2.1-or-later. No required dependencies. "Development Status :: 4 - Beta". About 4 stars and 27 commits. Hardware-tested on Classic 6G/7G on Linux; macOS is "little tested". The README discloses AI-assisted development. Source: https://github.com/Bionded/pygpod, https://pypi.org/project/pygpod/ | The only maintained pure-Python reader. Promising, but young and has a single maintainer. |
| **iOpenPod** (TheRealSavi/iOpenPod) | 2.0.17, released 2026-10-27. GPL-3.0. `requires_python >=3.12,<3.13`. A PySide6 desktop app with heavy dependencies (librosa, numba, PySide6). Source: https://pypi.org/project/iOpenPod/ | Prior art and a possible end-user tool. Not a library to depend on. |
| Rust parsers (iPodControl/itunes-db-parser, raleighlittles/iTunesDB-Parser) | Partial coverage; playlists not documented. | Reference only. |
| wikiPodLinux iTunesDB format docs | Format reference. http://www.ipodlinux.org/ITunesDB/ | Reference only. |
| Hand-written parser | n/a | Against the principles ("don't reinvent"). |

`iTunesCDB` (the compressed/SQLite variant) applies to nano 5G to 7G, not to the Classic, and pygpod
declines those models. A Classic has a plain `iPod_Control/iTunes/iTunesDB`, and recent play counts in a
separate `Play Counts` file.

### Read-only safety (checked in the pygpod 0.2.3 source)

- `parse_itunesdb(data: bytes)` in `pygpod/db/parser.py` is a pure function. `Database.from_file(path)`
  parses a standalone file and never touches a mount point.
- `Database(mountpoint)` defaults to `recover=True`. That takes a writer lock under
  `iPod_Control/iTunes` and can *finish an interrupted save*, which deletes consumed `Play Counts` files
  (`remove_consumed_files` in `db/playcounts.py`).
- `with Database(...)` saves on a clean exit if anything changed. Merging play counts marks the database
  as modified.

**So the safe design is "copy first, parse the copy":**

- Copy `iPod_Control/iTunes/{iTunesDB, Play Counts, iTunesStats, PlayCounts.plist, OTGPlaylist*}` into
  a temporary folder that mirrors the `iPod_Control/iTunes` layout.
- Open it with `Database(tmp, recover=False)`, never in a `with` block, and never call `save()`.
- Nothing on the iPod is ever opened for writing.

Belt and braces: the README can suggest `diskutil unmount` followed by `diskutil mount readOnly <disk>`,
but that is optional with the copy-first design.

### Joining to the existing scan

`Track.ipod_path` (for example `:iPod_Control:Music:F12:ABCD.wav`) maps to the file path that `scan.py`
already reads. The rule is:
- mutagen tags win when present;
- iTunesDB fills gaps (WAVs, "Unknown Artist");
- ratings, play counts and playlist membership come only from iTunesDB.

| | |
|---|---|
| User value | High. WAVs stop showing as `QRST`, and "the playlists I made on my iPod" come back. |
| Library | pygpod (optional extra: `ipod2playlist[itunesdb]`), with a fallback to today's mutagen-only scan if parsing fails. |
| Effort | M |
| Risk | Library maturity: Beta, 7 months old, one maintainer. Mitigations: make it optional, pin the version, and fall back on any exception. Safety is solved by copy-first. Platform: macOS is little tested by pygpod, but the parsing is pure bytes, so the OS should not matter. LGPL is fine for a dependency. |
| Offline test | pygpod writes databases, so tests can build a fixture iTunesDB in `tmp_path` with a few tracks, a WAV, ratings and a playlist, then parse the copy. Also test that the source directory is byte-identical after a scan. |
| Fit | **Medium-high.** It reuses a library instead of writing a parser, which keeps to the spirit of the non-goal ("don't parse iTunesDB ourselves"). The cost is a young dependency. |

**Recommendation:** revisit the non-goal explicitly, in this narrow form: *read-only, via pygpod, on a
copy, optional, with a fallback.* Re-check pygpod's health before adopting it, for example whether it is
still releasing in 3 to 6 months.

---

## 2. Other destinations

| Destination | Python client (status) | Free path? | Verdict |
|---|---|---|---|
| **Apple Music** | No maintained official Python SDK. `apple-music-python` 1.0.6 (2024-12-28) covers the catalog only. The REST API `POST /v1/me/library/playlists` needs a developer token (Apple Developer Program, **US$99/year**, https://developer.apple.com/programs/) plus a *Music User Token*, which is only obtainable through MusicKit JS/MusicKit in a browser or app (https://developer.apple.com/documentation/applemusicapi/create-a-new-library-playlist). | No. | Not via the API. A free route exists, though: copy the audio off the iPod (6a), then use Music.app > File > Import plus the M3U (6b); Sync Library uploads or matches it to the user's iCloud library. Or use a CSV with TuneMyMusic/Soundiiz (6c). |
| **Tidal** | `tidalapi` 0.8.11 (2026-01-19, Py 3.8 to 3.14) is *unofficial* and uses TIDAL's private API (https://github.com/EbbLabs/python-tidal). The official TIDAL API (developer.tidal.com, `playlists.write` scope, authorization code + PKCE) has no official Python SDK; `minim` 1.1.0 (2026-04-09) wraps it. | Registration is free; the user needs a TIDAL subscription. | Possible later through the official API with plain HTTP. Low demand for this persona. `tidalapi` has ToS risk. |
| **Deezer** | `deezer-python` 7.4.0 (2026-08-07, Py 3.10+) is well maintained. However, Deezer **disabled new API app creation for individuals** (community manager post, October 2025, still not lifted as far as found). Source: https://en.deezercommunity.com/features-feedback-44/api-auth-impossible-80857 | No new apps. | Not feasible. Use the CSV route (6c). |
| **YouTube Music** | `ytmusicapi` 1.12.3 (2026-09-16, Py 3.10+, MIT, about 3.1k stars) is well maintained but *unofficial*: it "emulates YouTube Music web client requests". OAuth now needs your own Google Cloud client of type "TVs and Limited Input devices". Source: https://ytmusicapi.readthedocs.io/en/latest/setup/oauth.html | It costs nothing and is not limited by the Data API quota. | **ToS conflict, see section 3.** YouTube Music playlists made through the official Data API already appear in YouTube Music, so the current tool already covers it. |
| **Plex** | `plexapi` 4.18.3 (2026-09-28, Py 3.10+). `Playlist.create(server, title, items=... / smart=True / m3ufilepath=...)`. https://python-plexapi.readthedocs.io/en/latest/modules/playlist.html | Free (Plex server). | Only meaningful after the audio is copied off the iPod (6a). Plex imports M3U itself, so an M3U export (6b) covers it without a new integration. |
| **Jellyfin** | `jellyfin-apiclient-python` 1.20.2 (2026-10-14) is described by a Jellyfin forum maintainer as "clunky". `jellyfin-sdk` 0.3.0 (2025-09-10, Py 3.10+) is OpenAPI-generated. `POST /Playlists` exists. | Free. | Same as Plex: the M3U export is enough; no API client is needed. |

**Conclusion:** none of the new streaming destinations has a free, official, maintained path that beats
"export a good CSV/M3U and let an existing tool import it". The two existing destinations (Spotify, YouTube
Data API) remain the only first-class integrations worth keeping in code.

---

## 3. Getting past the YouTube quota legitimately

Today a search costs 100 units and an add costs 50, out of a 10,000/day budget, so about 66 songs a day.

| Approach | Legitimate? | Notes |
|---|---|---|
| **Request a quota extension** (YouTube API Services Audit and Quota Extension Form) | **Yes.** | Free. It needs a compliance audit first: describe the client and its use, give at least 200 characters of justification, and expect a review that can take weeks. A family-only desktop tool with test-user OAuth is plausible but not guaranteed. This needs no code, only a README section. Sources: https://developers.google.com/youtube/v3/guides/quota_and_compliance_audits, https://support.google.com/youtube/contact/yt_api_form |
| **Spend the quota on the songs that matter first** | Yes. | Order the YouTube queue by play count and rating (needs feature 1), so day one covers the most-loved songs. S effort once feature 1 exists. |
| **Only send Spotify-missing songs** | Yes, and already done. | `--only-spotify-missing` |
| **Estimate and tell the user** ("312 songs left, about 5 more days") | Yes. | S. Pure UX (see 5b). |
| **ytmusicapi for search** (no quota) **+ Data API for adds** (50 units, about 200/day) | **No: breaks the terms.** | YouTube ToS forbids "accessing the Service using any automated means (such as robots, botnets or scrapers)" without written permission (https://www.youtube.com/t/terms). For an API client, the YouTube Developer Policies III.D.7 say "You must not use undocumented APIs without express permission", and III.I.14 bars using "any technology other than YouTube API Services to access or retrieve API Data" (https://developers.google.com/youtube/terms/developer-policies). Mixing the two would put the family member's Google Cloud project at risk. |
| **ytmusicapi for everything** | **No: breaks the terms**, as above. | It also risks the family member's Google account, which is the opposite of "safe". |
| **Several Google Cloud projects to multiply quota** | **No: breaks the policy.** | Developer Policies III.D.1.c: "you must create exactly one (1) API Project for that API Client". Google is known to flag "multiple projects acting as one". |
| **Odesli link conversion** | Not available. | API retired 2026-07-31 (see section 0). |

**Recommendation:** document the quota-extension route, add the days-remaining estimate, and (with
feature 1) prioritise by play count. Do not ship ytmusicapi.

---

## 4. Better matching without hurting safety

The current design is strict: the artist gate and version words mean "missing" is preferred to "wrong".
Any addition must keep the rule *a new signal may add a candidate; only a strict check may accept it.*

### 4a. AcoustID fingerprinting for untagged files (mainly WAVs)

- **Library:** `pyacoustid` 1.3.1 (2026-04-09, Py 3.10 to 3.14, beetbox org, which also maintains beets).
  https://github.com/beetbox/pyacoustid. `acoustid.match(apikey, path)` returns
  `(score, recording_mbid, title, artist)` directly, so no separate MusicBrainz client is needed.
- **Needs:** the `fpcalc` binary (`brew install chromaprint`, an extra setup step) and a free AcoustID
  application key for non-commercial use (https://acoustid.org).
- **Safety:** accept only a high score (for example >= 0.9) where the top recordings agree on artist and
  title. Write the result to `songs.json` with `source: "acoustid"` so it shows up in the TSV/CSV review.
  Never write tags back to the iPod.
- Effort M. Risk: an extra binary to install (Homebrew) and network calls at about 3 requests per second.
  Offline test: inject a fake `match` function.
- **Fit: medium.** The case is weaker if feature 1 lands, because iTunesDB already has the WAV names, for
  free and exactly. Keep this as the fallback for iPods whose database is damaged.

### 4b. ISRC lookups

- ISRCs are rarely present in iPod-era files. iTunes purchases carry an Apple catalog ID (`cnID`), not an
  ISRC, and CD rips usually carry neither. Getting one means a MusicBrainz search by artist and title,
  which is itself fuzzy.
- Spotify does support an `isrc:` filter in search, one code per request.
- **Library status:** `musicbrainzngs` 0.7.1 was last released on **2020-01-11**. It works (beets depends
  on it) but upstream is dormant. `mbzero` 0.5 (2025-08-28) is the maintained alternative.
- **Verdict: low value for this library, M effort, fit low.** Skip, unless files are found that already
  carry `TSRC` (EasyID3 exposes it as `isrc`). In that case an `isrc:` Spotify search can be tried first
  for free (S effort).

### 4c. Smart playlists from play counts and ratings

- Needs feature 1. Build extra playlists such as "iPod Top 100 (most played)", "iPod 5 stars" and one
  per iPod playlist, from the data already matched. No extra searches are needed: reuse `progress.json`
  matches, which costs zero extra search quota.
- `progress.json` needs the matched item ID stored per song, not just a status, so a playlist can be
  assembled from existing matches. That is a schema change; migrate with a version field.
- Effort M. Offline test: fake service plus a fixture database.
- **Fit: high** once feature 1 exists, because it brings back what the family member actually curated.

---

## 5. Usability for a non-expert (no GUI)

### 5a. `doctor` / guided first run

- **What it checks:**
  - auto-detects the iPod by looking for `/Volumes/*/iPod_Control`, which removes the quoting pitfall in
    README step 4;
  - checks `.env` keys, `client_secrets.json` and the redirect URI;
  - warns about the Spotify Premium requirement;
  - checks the Python version;
  - prints the next command to run.
- **Implementation:** stdlib only: `pathlib`, plus `input()` for yes/no prompts. If prompts grow,
  `questionary` 2.1.1 (2025-08-28, Py 3.10 to 3.13) is the maintained choice, but stdlib is enough.
- Effort S. Risk: none. Offline test: `tmp_path` volumes and env monkeypatching.
- **Fit: high.** It removes the most error-prone steps with no new dependency.

### 5b. Dry run / preview

- **Spotify:** `--dry-run` searches (free) but does not create a playlist or add anything. It writes a
  preview list, `would add: X -> matched "Y" by Z`, and records nothing in `progress.json`, so it is
  easy to implement in `sync()` with a no-op `add`.
- **YouTube:** a dry run would burn 100 units per search, so it should only print the count and days
  remaining, never search.
- Effort S. Offline test: the fake service asserts no `create_playlist` or `add` calls.
- **Fit: high.** "See before it changes anything" is the safest UX.

### 5c. Missing-songs review step

- **Record near misses.** For songs below the threshold, keep the best candidate that passed the artist
  gate (for example score 60 to 79) in `progress.json` as `"maybe"` with its ID and title.
- **Review file.** `missing` writes a CSV with columns `Title, Artist, Best guess, Link, Add? (y/n)`
  using the stdlib `csv` module.
- **Apply.** `apply-review review.csv` adds only the rows marked `y`.
- A human makes every borderline decision, so safety is preserved and the strict auto-threshold is
  unchanged.
- Effort M (progress schema and one command). Offline test: fake service plus a fixture CSV.
- **Fit: high.**

### 5d. Reviewable HTML report

- **What it shows:** a single self-contained `report.html`, with no server and no JavaScript needed. It
  has a summary (added, missing, pending) and tables of added and missing songs. Every missing song gets
  click-through search links, `https://open.spotify.com/search/<q>` and
  `https://www.youtube.com/results?search_query=<q>`, so the family member can add the stragglers by
  hand. This costs **zero API quota**.
- **Implementation:** stdlib `html.escape` and `string.Template`. `jinja2` 3.1.6 (2025-03) is
  unnecessary for one page.
- It is a static file opened in a browser. It is not a GUI and fits the non-goal.
- Effort S. Offline test: snapshot or contains-assertions on the generated HTML.
- **Fit: high.**

---

## 6. Other features in this spirit

### 6a. Copy the audio files off the iPod (local backup)

- **What it does:** `backup DEST` copies every scanned file to `DEST/Artist/Album/Title.ext`, using the
  tags (and iTunesDB names if feature 1 lands).
- **Safety rules:**
  - read-only on the iPod;
  - never overwrites;
  - skips files already present with the same size, so it is resumable;
  - checks `shutil.disk_usage` first;
  - verifies the size after each copy.
- **Libraries:** stdlib `shutil.copy2`, plus `pathvalidate` 3.3.1 (2025-06-15, Py 3.9+) to make
  tag-derived filenames safe on every filesystem, which avoids hand-rolling a sanitiser.
- **Prior art:** beets (2.14.1, 2026-09-17) can `import` with copy and its own path templates, and
  iOpenPod is a GUI. Both are heavy for this persona and just for copying.
- **User value:** very high. iPod Classic hard drives are 15 to 20 years old and failing, and this is
  the only way to keep the actual music. It also unlocks Apple Music (Music.app import, Sync Library),
  Plex and Jellyfin with no API.
- **Risks:**
  - `.m4p` (FairPlay DRM) files copy fine but only play on authorised computers; say so.
  - Time: about 80 to 160 GB over USB 2.0 takes hours, so progress output and resumability matter.
- Effort S-M. Offline test: the existing virtual-iPod fixture, plus asserting the source is unchanged.
- **Fit: high.**

### 6b. Portable M3U8 export

- Write `My iPod.m3u8` (and one per iPod playlist with feature 1), with relative paths into the backup
  folder.
- M3U is a trivial text format, and stdlib is right; a library would be overkill.
- Music.app, VLC, Plex (`Playlist.create(m3ufilepath=...)`) and Jellyfin all import it.
- Effort S. Offline test: golden file.
- **Fit: high.**

### 6c. Universal CSV export for TuneMyMusic / Soundiiz

- Write `library.csv` (and `spotify_missing.csv`) with `Title, Artist, Album` (plus `ISRC` when known)
  via the stdlib `csv` module.
- The family member can upload it to TuneMyMusic (https://www.tunemymusic.com/transfer/csv-to-apple-music)
  or Soundiiz (https://soundiiz.com/tutorial/import-excel-to-soundiiz). Those services push to Apple
  Music, Tidal, Deezer, Amazon Music and others.
- This is the "don't reinvent" answer to section 2: one file covers every service that has no free API.
- **Caveats:**
  - Their matching is not ours, so it is less strict. Say so in the README.
  - Their free tiers are limited. TuneMyMusic sells "Unlimited Music Transfer" at about $2/month; check
    the exact free cap before documenting it.
  - The exact column layout matters, so test against their sample files before documenting.
- Effort S. Offline test: golden file. **Fit: high** (a small export instead of four integrations).

### 6d. Cross-platform check (Windows and Linux)

- mutagen and pygpod are pure Python, and the iPod mounts as a drive letter on Windows (iTunes or Apple
  Devices installed) or under `/media` on Linux.
- Mostly this means a CI matrix and a README line, plus making auto-detection in `doctor` look in the
  right places.
- Effort S-M. **Fit: medium.** The family member uses a Mac, but it costs little.

### 6e. Double-clickable macOS launcher (borderline, optional)

- A `ipod2playlist.command` file that runs `doctor` and then the next step. It is not a GUI, just a
  shell script Finder can open.
- Effort S. **Fit: medium.** It helps a non-terminal user, but adds a second entry point to maintain.

---

## 7. Summary table

| # | Feature | Value | Reuse | Effort | Main risk | Fit |
|---|---|---|---|---|---|---|
| 1 | Read-only iTunesDB enrichment | High | pygpod 0.2.3 (Beta) | M | Young library | Med-high |
| 2a | Apple Music via MusicKit | Med | none maintained | L | $99/yr, token flow | Low |
| 2b | Tidal | Low | official API / minim; tidalapi (unofficial) | M | ToS (tidalapi) | Low |
| 2c | Deezer | Low | deezer-python | n/a | API closed to individuals | n/a |
| 2d | YouTube Music via ytmusicapi | Med | ytmusicapi | S | **ToS violation** | Low |
| 2e | Plex/Jellyfin via API | Low | plexapi / jellyfin-sdk | M | Needs a server | Low (use M3U) |
| 3a | Quota-extension docs + days estimate | Med | none | S | None | High |
| 3b | Prioritise YouTube queue by plays/rating | Med | needs #1 | S | None | High |
| 4a | AcoustID for untagged files | Med | pyacoustid 1.3.1 + fpcalc | M | Extra binary, API key | Medium |
| 4b | ISRC lookups | Low | mbzero / musicbrainzngs (dormant) | M | Fuzzy upstream match | Low |
| 4c | Smart/iPod playlists | High | needs #1 | M | Progress schema change | High |
| 5a | `doctor` + iPod auto-detect | High | stdlib | S | None | High |
| 5b | Dry run / preview | High | stdlib | S | YouTube searches cost quota | High |
| 5c | Missing-songs review + apply | High | stdlib csv | M | Progress schema change | High |
| 5d | HTML report with search links | High | stdlib | S | None | High |
| 6a | Local audio backup | Very high | stdlib + pathvalidate | S-M | DRM .m4p, time | High |
| 6b | M3U8 export | High | stdlib | S | None | High |
| 6c | TuneMyMusic/Soundiiz CSV | High | stdlib csv | S | Third-party matching | High |
| 6d | Windows/Linux support | Low-med | CI | S-M | Untested paths | Medium |

---

## 8. Recommended shortlist (ranked)

1. **Local audio backup + M3U8 export (6a + 6b).** The iPod's drive is the only copy of this music and
   it is ageing. A read-only, resumable copy protects it permanently and opens Apple Music, Plex and
   Jellyfin with no new API.
2. **`doctor` with iPod auto-detection, plus Spotify dry run and days-remaining estimate (5a + 5b + 3a).**
   It removes the most error-prone setup steps (paths, credentials, the new Spotify Premium requirement)
   and shows what will happen before anything changes, using stdlib only.
3. **Missing-songs review: HTML report with click-through search links, plus a CSV accept/apply step
   (5d + 5c).** It turns the "missing" list into something the family member can finish, with a human
   making every borderline call, so strict matching stays intact.
4. **Read-only iTunesDB enrichment via pygpod, optional and copy-first (1, then 4c and 3b).** This is
   the only way to recover WAV names, the iPod's own playlists, ratings and play counts. It revisits a
   non-goal: it uses a library rather than our own parser, and adoption should wait until pygpod shows a
   few more months of health.
5. **TuneMyMusic/Soundiiz-compatible CSV export (6c).** One small export covers Apple Music, Tidal,
   Deezer and Amazon for free, instead of four fragile integrations.

## 9. Explicitly NOT doing, and why

- **ytmusicapi (search or playlists).** It breaks the YouTube ToS (automated access) and Developer
  Policies III.D.7 and III.I.14, and it could cost the family member their Google account or project.
- **Several Google Cloud projects to multiply quota.** This violates Developer Policies III.D.1.c (one
  project per API client).
- **Odesli/song.link link conversion.** The API was retired on 2026-07-31 and no new keys are issued.
- **Direct Apple Music (MusicKit) integration.** It needs a US$99/year developer membership and a
  browser-based Music User Token flow. The backup/M3U and CSV routes give the same result for free.
- **Deezer API integration.** Deezer stopped issuing API apps to individuals (October 2025).
- **tidalapi.** It is an unofficial private-API client. If Tidal is ever wanted, use the official API.
- **libgpod bindings.** They are Python 2 only and upstream has been dead since about 2013.
- **Writing a custom iTunesDB parser, or ever writing to the iPod.** pygpod exists, and any write path
  risks the user's only copy of their library.
- **Auto-accepting near-miss matches, or loosening thresholds.** This trades the project's core safety
  promise ("never add the wrong song") for a shorter missing list. Use human review (5c) instead.
- **An ISRC/MusicBrainz matching pipeline.** iPod-era files rarely carry ISRCs, so the lookup would
  itself be a fuzzy search. It adds complexity and rate limits for little gain.
- **AcoustID as a default step.** It needs Homebrew `fpcalc` and an API key, which is too much setup.
  Keep it as a possible fallback only if the iTunesDB route fails.
- **A GUI, a Docker image, or Plex/Jellyfin API clients.** They add maintenance with no benefit over a
  static HTML report, `uv run`, and M3U files those apps already import.
