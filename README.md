# TorrentMaker

A personal collection of Python scripts for automating torrent creation, metadata gathering, and uploads to private trackers. Written for my own use — no guarantees it works on your machine or with your setup.

## Scripts

### torrentmaker.py

The main script for video content (movies and TV shows).

**What it does:**

1. Finds the largest video file in the given path
2. Extracts technical specs via MediaInfo (codec, resolution, audio format, colour space)
3. Queries TMDB for title, year, genre, and poster
4. Generates a standardized filename, optionally in HUNO tracker format
5. Captures 8 screenshots at distributed timestamps using OpenCV
6. Uploads screenshots concurrently to image hosts (PTPImg first, then ImgBB, then Catbox as fallback)
7. Hashes the torrent using torf and writes it to `runs/NNN/`
8. Optionally: creates a hardlink to the seeding directory, uploads to HUNO, injects into qBittorrent
9. For source-vs-encode workflows, can create slow.pics comparisons (`/upload/comparison` + `/upload/image`) with optional authenticated cookies to reduce anonymous throttling

For HUNO uploads, it checks for potential duplicate uploads via the HUNO filter API, detects anime and looks up the MAL ID via Jikan, and shows a payload preview before uploading. It supports both HUNO's automatic and manual upload modes.

If a previous run was detected for the same source path, it can skip re-hashing and reuse the existing `.torrent` file.

**Usage:**

```
python torrentmaker.py [path] [options]

Options:
  -m, --movie PATH          Path to movie file or folder
  --episode                 Treat as a single TV episode
  -s, --source SOURCE       Source type (e.g. WEB-DL, BluRay)
  -g, --group GROUP         Release group name
  -t, --tmdb ID             TMDB ID (skips search)
  -i, --inject              Inject torrent into qBittorrent
  -u, --upload              Upload to HUNO
  --huno                    Use HUNO-specific filename format
  --manual                  Use HUNO manual upload mode
  --aither                  Upload to Aither (not implemented yet)
  --hardlink                Hardlink to seeding directory instead of copy
  --skip-prompts            Skip all confirmation prompts
  -D, --debug               Enable debug logging
```

**Output** (written to `runs/NNN/`):
- `[name].torrent`
- `mediainfo.txt`
- `screenshots/screenshot_00.png` through `screenshot_07.png`
- `showDesc.txt` — BBCode description with embedded image URLs
- `poster.jpg`
- `source_path.txt` — records the source path for run deduplication

---

### musicTorrentMaker.py

For music albums. Handles FLAC and MP3, single-disc and multi-disc albums.

**What it does:**

1. Reads tags from the first track to determine artist and album name
2. Queries MusicBrainz to find the release group and release type
3. Uses Levenshtein similarity to confirm the match (or asks for confirmation)
4. Generates a `.torrent` file and uploads to REDacted (RED) and/or Orpheus (OPS)
5. Optionally uploads the cover image to PTPImg for the tracker description
6. Optionally copies the album folder to a seedbox via FTPS and injects into a remote qBittorrent
7. Can fix unset FLAC MD5 signatures (`--fixMD5`)
8. Can rename track files to a standard format (`--format`)

**Usage:**

```
python musicTorrentMaker.py [options]

Options:
  -p, --path PATH           Path to album folder (or omit to use bulkProcess.txt)
  -s, --source SOURCE       Source (e.g. WEB, CD)
  -c, --cover PATH          Path to cover image
  --groupid ID              RED group ID if uploading to an existing group
  --ogyear YEAR             Original release year
  -i, --inject              Inject torrent into local qBittorrent
  --sbcopy                  Copy to seedbox and inject into seedbox qBittorrent
  -u, --upload              Upload to REDacted
  --ops                     Upload to Orpheus (OPS)
  -f, --format              Rename track files to standard format
  --nodesc                  Don't overwrite existing album description on RED
  --fixMD5                  Fix unset MD5 signatures in FLAC files
  --skipPrompts             Skip all prompts (no MusicBrainz matching, upload immediately)
  --skip-flac-check         Skip check for the FLAC CLI tool
  -D, --debug               Enable debug logging
```

---

### fileRenamer.py

Renames video files to a standardized format based on TMDB metadata.

**What it does:**

Uses guessit to parse the filename, queries TMDB for canonical title and year, then constructs a properly formatted name. Levenshtein distance is used to score TMDB search results. Asks for confirmation before renaming unless `--skip-prompts` is set.

**Usage:**

```
python fileRenamer.py [options]

Options:
  -p, --path PATH           Path to file or folder (or omit to use bulkProcess.txt)
  -t, --tmdb ID             TMDB ID (skips search)
  -g, --group GROUP         Override release group name
  -s, --source SOURCE       Override source string
  --hardlink                Create a hardlink to the renamed name instead of renaming
  --huno-format             Use HUNO-specific filename format
  --skip-prompts            Skip confirmation prompts
  -D, --debug               Enable debug logging
```

---

### torrentEdit.py

Patches the source field in an existing `.torrent` file in place.

**Usage:**

```
python torrentEdit.py [file.torrent] -s "SOURCE"

# Or use bulkEdit.txt with one .torrent path per line and omit the file argument
```

---

## Bulk Processing

All scripts except `torrentEdit.py` support bulk processing. If no path argument is provided, they look for `bulkProcess.txt` in the working directory (one path per line). `torrentEdit.py` uses `bulkEdit.txt`.

---

## Configuration

On first run, `settings.ini` is auto-generated from a template. Edit it with your API keys and host settings. The fields used by each script are validated at startup — if a required field is missing, the script will tell you.

Key settings:

| Setting | Used by |
|---------|---------|
| `TMDB_API` | torrentmaker.py, fileRenamer.py |
| `HUNO_API` | torrentmaker.py |
| `RED_API`, `RED_ANNOUNCE_URL` | musicTorrentMaker.py |
| `OPS_API`, `OPS_ANNOUNCE_URL` | musicTorrentMaker.py |
| `PTPIMG_API` | torrentmaker.py, musicTorrentMaker.py |
| `IMGBB_API` | torrentmaker.py (fallback image host) |
| `CATBOX_HASH` | torrentmaker.py (fallback image host) |
| `SLOWPICS_REMEMBER_ME`, `SLOWPICS_SESSION` | torrentmaker.py (optional slow.pics authenticated uploads) |
| `QBIT_HOST`, `QBIT_USERNAME`, `QBIT_PASSWORD` | torrentmaker.py, musicTorrentMaker.py |
| `SEEDING_DIR` | torrentmaker.py, musicTorrentMaker.py |
| `SEEDBOX_*` | musicTorrentMaker.py |

### slow.pics Optional Auth

If you use the slow.pics comparison upload feature and get frequent anonymous limits/rate-limits, set these optional fields in `settings.ini`:

- `SLOWPICS_REMEMBER_ME`: value of the `remember-me` cookie from your browser session
- `SLOWPICS_SESSION`: value of the `SLP-SESSION` cookie from your browser session

How to get them:
1. Log in at `https://slow.pics`
2. Open browser DevTools -> Storage/Application -> Cookies -> `https://slow.pics`
3. Copy the cookie values for `remember-me` and `SLP-SESSION` into `settings.ini`

Notes:
- Leave these blank to use anonymous slow.pics uploads.
- slow.pics can still return API quota errors like `DAILY_LIMIT_UPLOAD`; TorrentMaker now logs this explicitly.

---

## Dependencies

```
pip install -r requirements.txt
```

| Library | Purpose |
|---------|---------|
| `torf` | `.torrent` file creation and hashing |
| `pymediainfo` | Media technical specs |
| `opencv-python` | Video frame capture for screenshots |
| `guessit` | Parse title/season/episode from filenames |
| `python-Levenshtein` | Title similarity scoring |
| `qbittorrent-api` | Control qBittorrent |
| `musicbrainzngs` | MusicBrainz album metadata |
| `mutagen` | Audio tag read/write |
| `colorthief` | Dominant colour extraction from posters |
| `Pillow` | Image processing |
| `tqdm` | Progress bars for FTP uploads |

MediaInfo CLI and the `flac` CLI tool are also required for full functionality. The scripts will prompt to install them automatically if missing (Windows only for MediaInfo).
