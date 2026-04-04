# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

TorrentMaker is a Python automation suite for creating, managing, and uploading torrent files for video and music content to private trackers (HUNO, REDacted/RED, Orpheus/OPS). It handles screenshot generation, metadata enrichment via TMDB and MusicBrainz APIs, and qBittorrent injection.

## Setup & Running

```bash
# Install dependencies
pip install -r requirements.txt

# Run any script — settings.ini is auto-generated on first run
python torrentmaker.py
# Edit the generated settings.ini with your API keys and host settings
```

## Common Commands

```bash
# Video torrent (movie)
python torrentmaker.py -m "C:\Videos\Movie.2023.1080p.mkv" -i --huno -u -s "WEB-DL" -g "GROUP"

# Video torrent (single episode)
python torrentmaker.py "C:\Videos\Show.S01E05.mkv" --episode --huno -i -t <tmdb_id>

# Music torrent
python musicTorrentMaker.py -p "C:\Music\Artist\Album" --upload --groupid <id>

# Bulk process (create bulkProcess.txt with paths first)
python musicTorrentMaker.py --upload

# Rename media files using TMDB metadata
python fileRenamer.py -p "C:\Videos\file.mkv" -m

# Edit torrent source field
python torrentEdit.py file.torrent -s "BluRay"

# Debug logging
python torrentmaker.py "path" -D
```

## Architecture

### Entry Points
- **`torrentmaker.py`** — Movies and TV shows. Creates `.torrent` files, captures 8 screenshots, uploads images concurrently (PTPImg → ImgBB → Catbox fallback chain), queries TMDB, generates BBCode descriptions, optionally uploads to HUNO/Aither and injects into qBittorrent.
- **`musicTorrentMaker.py`** — Music albums. Integrates with MusicBrainz, handles FLAC checksums, uploads to RED/OPS, supports FTP seedbox copy.
- **`fileRenamer.py`** — Renames files using TMDB + Guessit + Levenshtein similarity matching.
- **`torrentEdit.py`** — Patches source field in existing `.torrent` files.

### `torrent_utils/` Module
- **`config_loader.py`** — Reads `settings.ini`, auto-generates it from template if missing, updates missing fields while preserving user values, validates required fields per feature.
- **`media.py`** — `MediaFile` base class with `Movie` and `TVShow` subclasses. Uses pymediainfo (JSON output) for codec/resolution/audio detection, guessit for filename parsing, TMDB API for metadata. Key methods: `get_resolution()`, `get_video_codec()`, `get_audio_info()`, `get_colour_space()`, `fetch_metadata()`, `generate_name()`.
- **`helpers.py`** — 30+ utility functions: screenshot capture (OpenCV), image uploads, slow.pics comparison upload (session bootstrap, XSRF handling, `/upload/comparison` + `/upload/image` flow, rate-limit retry, explicit `DAILY_LIMIT_UPLOAD` handling), torrent hashing callbacks, qBittorrent injection (`qbitInject()`), MediaInfo/FLAC CLI auto-install, `get_path_list()` for CLI arg or bulk file loading.
- **`HUNOInfo.py`** — Static data: banned encoder groups and trusted encoder group→member mappings for HUNO tracker.

### Data Flow (Video)
1. Parse args → detect largest video file in path
2. `MediaInfo` extraction → codec/resolution/audio
3. TMDB query → title/year/genre/poster
4. Generate standardized filename (optionally HUNO format)
5. Capture 8 screenshots at distributed timestamps
6. Concurrent upload to image hosts
7. Hash torrent (torf) → write `.torrent` to `runs/NNN/`
8. Optional: hardlink to seeding dir, upload to tracker API, inject into qBittorrent

### Output Structure
Each run creates `runs/NNN/` containing:
- `[name].torrent` — generated torrent file
- `mediainfo.txt` — MediaInfo text dump
- `screenshots/` — `screenshot_00.png` through `screenshot_07.png`
- `showDesc.txt` — BBCode description with embedded image URLs
- `poster.jpg` — downloaded TMDB poster

### Bulk Processing
Scripts accept a `bulkProcess.txt` file (one path per line) when no `-p`/`-m` argument is given. `torrentEdit.py` uses `bulkEdit.txt` similarly.

## Key Dependencies

| Library | Purpose |
|---------|---------|
| `torf` | `.torrent` file creation and hashing |
| `pymediainfo` | Media technical specs (called as JSON) |
| `cv2` (opencv-python) | Video frame capture for screenshots |
| `guessit` | Parse title/season/episode from filenames |
| `python-Levenshtein` | Title similarity scoring against TMDB results |
| `qbittorrent-api` | Control local and remote qBittorrent |
| `musicbrainzngs` | MusicBrainz album metadata |
| `mutagen` | Audio file tag read/write |
| `colorthief` | Dominant color extraction from posters (for BBCode theming) |

## API Documentation

Local reference docs are checked into the repo root — consult these before guessing at API fields or endpoints:

| File | Contents |
|------|----------|
| `huno-api-docs.md` | HUNO tracker upload API — endpoint, field names, accepted values |
| `huno-upload-guide.md` | HUNO upload guide — category/type/source enums, torrent naming rules |
| `red-api-docs.md` | REDacted (RED) API — torrent upload, group create, format/encoding enums |
| `ops-api-docs.md` | Orpheus (OPS) API — same structure as RED docs |

## Configuration

All settings live in `settings.ini` under `[DEFAULT]`. Key sections: torrent client (QBIT_*), image hosts (PTPIMG_API, IMGBB_API, CATBOX_HASH), optional slow.pics auth cookies (`SLOWPICS_REMEMBER_ME`, `SLOWPICS_SESSION`), tracker APIs (HUNO_API, RED_API, OPS_API), tracker announce URLs, seeding directory path, and seedbox FTP/qBit credentials. `config_loader.py` is the single source of truth for field names — add new config fields there.
