import argparse
import os
import logging
import sys
import requests
import cv2
import torf
import qbittorrentapi
import json
import re
import shutil
import random
import zipfile
import configparser
import guessit
import ctypes
import Levenshtein
import numpy as np
import concurrent.futures
import time

from concurrent.futures import ThreadPoolExecutor, as_completed
from PIL import Image
from pprint import pprint
from pprint import pformat
from base64 import b64encode
from pymediainfo import MediaInfo
from datetime import datetime
from colorthief import ColorThief

from torrent_utils.config_loader import load_settings, validate_settings
from torrent_utils.HUNOInfo import bannedEncoders, encoderGroups
from torrent_utils.helpers import (
    getInfoDump, getUserInput, has_folders, cb, uploadToPTPIMG,
    copy_folder_structure, qbitInject, FileOrFolder, is_valid_torf_hash,
    convert_sha1_hash, ensure_mediainfo_cli, upload_to_catbox, upload_to_imgbb,
    upload_to_onlyimage, play_alert, upload_to_slowpics
)
from torrent_utils.media import Movie, TVShow

__VERSION = "2.1.3"
HUNO_API_URL = "https://hawke.uno/api/torrents/upload"
LOG_FORMAT = "%(asctime)s.%(msecs)03d %(levelname)-8s P%(process)06d.%(module)-12s %(funcName)-16sL%(lineno)04d %(message)s"
LOG_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

# TODO: Improve detection of AV1 WEB Encodes
# TODO: Sound alert when screenshot uploading fails
# TODO: Check qbit for existing torrent for given path to skip hash calculation
# TODO: Automatically detect TV vs movie to make -m argument unnecessary
# TODO: When featurettes are included, add their inclusion as an automatic note in the description
# TODO: Add argument for personal releases to add a note like 'Please don't upload elsewhere without asking, thanks!'
# TODO: Filter HUNO dupes check by same codec, resolution, and season number (for TV) to better identify true duplicates
# TODO: Support bulk paths input to upload multiple season packs sequentially
# TODO: Add personal release flag to add a note like 'Please don't upload elsewhere without asking, thanks!' and/or a custom note field for this
# TODO: Find a more reliable alternative to slow.pics for screenshot comparison

# Maps --source argument (case-insensitive) to HUNO source_type IDs
SOURCE_TYPE_MAP = {
    'uhd bluray': 1, 'uhd blu-ray': 1, 'uhd bluray hybrid': 2, 'uhd blu-ray hybrid': 2,
    'bluray': 3, 'blu-ray': 3, 'bluray hybrid': 4, 'blu-ray hybrid': 4,
    'hd-dvd': 5, 'hd dvd': 5, 'hd-dvd hybrid': 6,
    'dvd9': 7, 'dvd5': 8, 'dvd': 13,
    'web-dl': 9, 'webdl': 9, 'web-dl hybrid': 10, 'webdl hybrid': 10,
    'hdtv': 11, 'sdtv': 12,
}

# Maps resolution string to HUNO resolution_id
RESOLUTION_ID_MAP = {
    "4320p": 1, "2160p": 2, "1080p": 3, "1080i": 4,
    "720p": 5, "576p": 6, "576i": 7, "540p": 11, "480p": 8, "480i": 9,
}

# Maps audio channel string (from get_audio_info) to HUNO audio_channel_id
AUDIO_CHANNEL_ID_MAP = {
    "13.1": 1, "12.1": 2, "11.1": 3, "10.1": 4, "9.1": 5,
    "7.1": 6, "6.1": 7, "5.1": 8, "5.0": 9, "4.0": 10,
    "2.1": 11, "2.0": 12, "1.0": 13,
}

# Known streaming service filename tokens → canonical abbreviation
STREAMING_SERVICES = {
    'amzn': 'AMZN', 'amazon': 'AMZN',
    'nf': 'NF', 'netflix': 'NF',
    'dsnp': 'DSNP',
    'hmax': 'HMAX',
    'pcok': 'PCOK', 'peacock': 'PCOK',
    'atvp': 'ATVP',
    'hulu': 'HULU',
    'vudu': 'VUDU',
    'pmtp': 'PMTP',
    'stan': 'STAN',
    'crav': 'CRAV',
    'cr': 'CR',
    'itunes': 'iTunes', 'itunes': 'iT',
}

# HUNO type_id values
_HUNO_TYPE_DISC = 1
_HUNO_TYPE_REMUX = 2
_HUNO_TYPE_WEB = 3
_HUNO_TYPE_ENCODE = 15


def _get_huno_type_id(source: str, video_codec: str) -> int:
    """Determines the HUNO type_id from the source and video codec.

    type_id represents the *content type* (DISC/REMUX/WEB/ENCODE),
    not the codec. Codec is sent as a separate field.
    """
    source_lower = source.lower() if source else ""
    if 'remux' in source_lower:
        return _HUNO_TYPE_REMUX
    if video_codec in ('x264', 'x265', 'AV1'):
        return _HUNO_TYPE_ENCODE
    if 'web' in source_lower:
        return _HUNO_TYPE_WEB
    return _HUNO_TYPE_WEB  # Safe fallback


# Ordered by specificity (longer/more-specific phrases first to avoid partial matches)
# Maps abbreviations/alternate spellings found in filenames to their canonical edition string
_EDITION_ALIASES: dict[str, str] = {
    "Anniv": "Anniversary",
}

_HUNO_EDITIONS = [
    "4K Remaster",
    "Directors Cut",
    "Director's Cut",
    "Open Matte",
    "Final Cut",
    "Anniversary",
    "Remastered",
    "Theatrical",
    "Collectors",
    "Assembly",
    "Extended",
    "Ultimate",
    "Restored",
    "Unrated",
    "Special",
    "Limited",
    "Superbit",
    "Redux",
    "IMAX",
    "Uncut",
    "3D",
]


def detect_edition_from_path(path: str) -> str | None:
    """Detects a HUNO-recognised edition tag from a file or folder path.
    Returns the canonical edition string (e.g. 'Unrated') or None if not found.
    Director's Cut is normalised to 'Directors Cut' for HUNO compatibility.
    """
    # Search both the basename and any parent folder name
    haystack = os.path.basename(os.path.normpath(path))
    # Also include parent directory name in case file is inside a named folder
    parent = os.path.basename(os.path.dirname(os.path.normpath(path)))
    combined = f"{parent} {haystack}"
    for edition in _HUNO_EDITIONS:
        # Case-insensitive whole-word match
        pattern = r'(?<![A-Za-z])' + re.escape(edition) + r'(?![A-Za-z])'
        if re.search(pattern, combined, re.IGNORECASE):
            # Normalise Director's Cut → Directors Cut
            return edition.replace("Director's Cut", "Directors Cut")
    # Check abbreviation/alias list
    for alias, canonical in _EDITION_ALIASES.items():
        pattern = r'(?<![A-Za-z])' + re.escape(alias) + r'(?![A-Za-z])'
        if re.search(pattern, combined, re.IGNORECASE):
            return canonical
    return None


def detect_release_tag_from_path(path: str) -> str | None:
    """Detects release tags such as PROPER/REPACK from a file or folder path."""
    haystack = os.path.basename(os.path.normpath(path))
    parent = os.path.basename(os.path.dirname(os.path.normpath(path)))
    combined = f"{parent} {haystack}".upper()

    repack_match = re.search(r'(?<![A-Z0-9])REPACK[ ._-]?(\d+)?(?![A-Z0-9])', combined)
    if repack_match:
        repack_num = repack_match.group(1)
        if repack_num and int(repack_num) > 1:
            return f"REPACK{repack_num}"
        return "REPACK"

    # Common scene form like "...v2" usually signals a repack revision.
    revision_match = re.search(r'(?<![A-Z0-9])V([2-9]\d*)(?![A-Z0-9])', combined)
    if revision_match:
        return f"REPACK{revision_match.group(1)}"

    if re.search(r'(?<![A-Z0-9])PROPER(?![A-Z0-9])', combined):
        return "PROPER"

    return None


def detect_source_from_filename(filename: str) -> str:
    """Attempts to detect source type (and streaming service) from a filename.
    Returns e.g. 'AMZN WEB-DL', 'BluRay Remux', 'NF WEB-DL', or '' on failure.
    """
    name = filename.upper()
    tokens_upper = set(re.split(r'[\.\s\-_\(\)\[\]]', name))

    base_source = ''
    if re.search(r'\bUHD[\.\s]BLU[\-\s]?RAY\b|\bUHD[\.\s]BLURAY\b', name):
        base_source = 'UHD BluRay'
        if 'REMUX' in tokens_upper:
            base_source = 'UHD BluRay Remux'
    elif re.search(r'\bBLU[\-\s]?RAY\b|\bBLURAY\b|\bBDREMUX\b', name):
        base_source = 'BluRay'
        if 'REMUX' in tokens_upper or 'BDREMUX' in tokens_upper:
            base_source = 'BluRay Remux'
    elif re.search(r'\bBDRIP\b', name):
        base_source = 'BluRay'
    elif re.search(r'\bWEB[\.\-]DL\b|\bWEBDL\b', name):
        base_source = 'WEB-DL'
    elif re.search(r'\bWEB\b', name):
        base_source = 'WEB-DL'
    elif re.search(r'\bWEBRIP\b|\bWEB[\.\-]RIP\b', name):
        # DS4K ("DownScaled 4K") means the encode was made from a 4K source, downscaled to 1080p
        if re.search(r'\bDS4K\b', name):
            base_source = 'WEB-DL'
        else:
            base_source = 'WEBRip'
    elif re.search(r'\bHDTV\b', name):
        base_source = 'HDTV'
    elif re.search(r'\bSDTV\b', name):
        base_source = 'SDTV'
    elif re.search(r'\bHD[\.\-]DVD\b|\bHDDVD\b', name):
        base_source = 'HD-DVD'
    elif re.search(r'\bDVD\b', name):
        base_source = 'DVD'

    if not base_source:
        return ''

    streaming_service = ''
    for token in re.split(r'[\.\s\-_\(\)\[\]]', filename):
        svc = STREAMING_SERVICES.get(token.lower())
        if svc:
            streaming_service = svc
            break

    return f"{streaming_service} {base_source}" if streaming_service else base_source


def find_previous_run(canonical_path: str, runs_dir: str = "runs") -> str | None:
    """Searches for the most recent run directory that processed the same source path."""
    if not os.path.isdir(runs_dir):
        return None
    canonical = os.path.normpath(canonical_path)
    matching = []
    for d in os.listdir(runs_dir):
        meta_path = os.path.join(runs_dir, d, "source_path.txt")
        if os.path.exists(meta_path):
            try:
                with open(meta_path, 'r', encoding='utf-8') as f:
                    if os.path.normpath(f.read().strip()) == canonical:
                        matching.append(os.path.join(runs_dir, d))
            except OSError:
                continue
    return sorted(matching)[-1] if matching else None


def _resolve_source_type_id(source: str) -> int | None:
    """Resolves a source string to a HUNO source_type_id.
    Handles service prefixes ('AMZN WEB-DL' → 'WEB-DL' → 9) and
    remux suffixes ('BluRay Remux' → 'BluRay' → 3).
    """
    if not source:
        return None
    s = source.lower().strip()
    if s in SOURCE_TYPE_MAP:
        return SOURCE_TYPE_MAP[s]
    tokens = s.split()
    candidates = [s]
    if len(tokens) > 1:
        candidates.append(' '.join(tokens[1:]))  # strip leading service token
    final_candidates = []
    for c in candidates:
        final_candidates.append(c)
        without_remux = re.sub(r'\s*remux\s*$', '', c).strip()
        if without_remux != c:
            final_candidates.append(without_remux)
    for candidate in final_candidates:
        if candidate in SOURCE_TYPE_MAP:
            return SOURCE_TYPE_MAP[candidate]
    logging.warning(f"Source '{source}' not in SOURCE_TYPE_MAP — source_type won't be sent. "
                    f"Valid values: {', '.join(sorted(SOURCE_TYPE_MAP.keys()))}")
    return None


_HUNO_TYPE_NAMES = {1: 'DISC', 2: 'REMUX', 3: 'WEB', 15: 'ENCODE'}
_HUNO_CATEGORY_NAMES = {1: 'Movie', 2: 'TV Show'}
_HUNO_RESOLUTION_NAMES = {v: k for k, v in RESOLUTION_ID_MAP.items()}
_HUNO_SOURCE_TYPE_NAMES = {
    1: 'UHD BluRay', 2: 'UHD BluRay Hybrid', 3: 'BluRay', 4: 'BluRay Hybrid',
    5: 'HD-DVD', 6: 'HD-DVD Hybrid', 7: 'DVD9', 8: 'DVD5',
    9: 'WEB-DL', 10: 'WEB-DL Hybrid', 11: 'HDTV', 12: 'SDTV', 13: 'DVD',
}
_HUNO_AUDIO_CHANNEL_NAMES = {v: k for k, v in AUDIO_CHANNEL_ID_MAP.items()}


def print_huno_payload_preview(data: dict, torrent_name: str, source: str, include_source_mediainfo: bool = False):
    """Prints a human-readable preview of the HUNO upload payload."""
    is_manual = data.get('mode') == 'manual'
    header = "  HUNO UPLOAD PAYLOAD PREVIEW (MANUAL MODE)" if is_manual else "  HUNO UPLOAD PAYLOAD PREVIEW"
    lines = [
        "",
        "=" * 62,
        header,
        "=" * 62,
        f"  Torrent name  : {torrent_name}",
        f"  Source string : {source or '(not set)'}",
    ]
    if include_source_mediainfo:
        lines.append(f"  Source file   : (included)")
    lines += [
        "-" * 62,
        f"  category_id   : {data.get('category_id')} ({_HUNO_CATEGORY_NAMES.get(data.get('category_id'), '?')})",
        f"  type_id       : {data.get('type_id')} ({_HUNO_TYPE_NAMES.get(data.get('type_id'), '?')})",
        f"  resolution_id : {data.get('resolution_id')} ({_HUNO_RESOLUTION_NAMES.get(data.get('resolution_id'), '?')})",
    ]
    # source field name differs between auto and manual mode
    if 'source_type_id' in data:
        sid = data.get('source_type_id')
        lines.append(f"  source_type_id: {sid} ({_HUNO_SOURCE_TYPE_NAMES.get(sid, '?')})")
    else:
        st = data.get('source_type')
        st_label = f" ({_HUNO_SOURCE_TYPE_NAMES.get(st, '?')})" if st is not None else ''
        lines.append(f"  source_type   : {st if st is not None else '(not sent)'}{st_label}")
    lines += [
        f"  tmdb          : {data.get('tmdb')}",
        f"  imdb          : {data.get('imdb')}",
        f"  tvdb          : {data.get('tvdb', '(n/a)')}",
        f"  mal           : {data.get('mal', '(n/a)')}",
    ]
    # codec/format field names differ between auto and manual mode
    if 'video_codec_id' in data:
        lines.append(f"  video_codec_id: {data.get('video_codec_id')}")
    else:
        lines.append(f"  video_codec   : {data.get('video_codec')}")
    if 'video_format_id' in data:
        lines.append(f"  video_format_id:{data.get('video_format_id')}")
    else:
        lines.append(f"  video_format  : {data.get('video_format')}")
    if 'audio_format_id' in data:
        lines.append(f"  audio_format_id:{data.get('audio_format_id')}")
    else:
        lines.append(f"  audio_format  : {data.get('audio_format')}")
    # audio channel field name differs between auto and manual mode
    if 'audio_channel_id' in data:
        cid = data.get('audio_channel_id')
        lines.append(f"  audio_channel_id:{cid} ({_HUNO_AUDIO_CHANNEL_NAMES.get(cid, '?')})")
    else:
        lines.append(f"  audio_channels: {data.get('audio_channels')}")
    lines.append(f"  season_pack   : {data.get('season_pack', '(n/a)')}")
    if 'season_number' in data:
        lines.append(f"  season_number : {data.get('season_number')}")
    if 'episode_number' in data:
        lines.append(f"  episode_number: {data.get('episode_number')}")
    if 'edition' in data:
        lines.append(f"  edition       : {data.get('edition')}")
    if 'release_tag' in data:
        lines.append(f"  release_tag   : {data.get('release_tag')}")
    if 'scaling_type' in data:
        _scaling_names = {1: 'DS4K', 2: 'AIUS'}
        st_val = data.get('scaling_type')
        lines.append(f"  scaling_type  : {st_val} ({_scaling_names.get(st_val, '?')})")
    # manual-mode-only fields
    if is_manual:
        lines += [
            "-" * 62,
            f"  name          : {data.get('name')}",
            f"  release_group : {data.get('release_group')}",
            f"  media_language: {data.get('media_language_id')}",
        ]
    lines.append("=" * 62)
    print('\n'.join(lines))


HUNO_FILTER_URL = "https://hawke.uno/api/torrents/filter"
JIKAN_API_URL = "https://api.jikan.moe/v4"


def is_anime(metadata: dict, is_movie: bool) -> bool:
    """Detects whether TMDB metadata represents an anime title.
    Anime is defined as Animation (genre 16) with Japanese origin/language.
    """
    genres = metadata.get('genres', [])
    genre_ids = {g.get('id') for g in genres}
    if 16 not in genre_ids:
        return False
    if is_movie:
        if metadata.get('original_language') == 'ja':
            return True
        countries = [c.get('iso_3166_1') for c in metadata.get('production_countries', [])]
        return 'JP' in countries
    else:
        origin_countries = metadata.get('origin_country', [])
        return 'JP' in origin_countries or metadata.get('original_language') == 'ja'


def lookup_mal_id(title: str, is_movie: bool) -> int | None:
    """Searches the Jikan (MAL) API for the best-matching anime title.
    Returns the MAL ID (int) or None if not found / request fails.
    """
    media_type = 'movie' if is_movie else 'tv'
    params = {'q': title, 'type': media_type, 'limit': 10}
    try:
        resp = requests.get(f"{JIKAN_API_URL}/anime", params=params, timeout=15)
        resp.raise_for_status()
        results = resp.json().get('data', [])
        if not results:
            return None
        # Pick the result with the lowest Levenshtein distance to the title
        title_lower = title.lower()
        best_id = None
        best_dist = float('inf')
        for entry in results:
            candidate = entry.get('title', '')
            dist = Levenshtein.distance(title_lower, candidate.lower())
            if dist < best_dist:
                best_dist = dist
                best_id = entry.get('mal_id')
        logging.info(f"Jikan MAL lookup: best match distance={best_dist}, mal_id={best_id}")
        return best_id
    except requests.RequestException as e:
        logging.warning(f"Jikan MAL lookup failed: {e}")
        return None


def search_huno_dupes(tmdb_id: int, category_id: int, huno_api: str) -> list:
    """Search HUNO for existing torrents matching the given TMDB ID and category.
    Returns a list of torrent dicts from the API response, or [] on failure.
    """
    params = {
        'tmdbId': tmdb_id,
        'categories[]': category_id,
        'perPage': 100,
        'sortField': 'created_at',
        'sortDirection': 'desc',
    }
    headers = {"Authorization": f"Bearer {huno_api}", "Accept": "application/json"}
    try:
        resp = requests.get(HUNO_FILTER_URL, headers=headers, params=params, timeout=15)
        resp.raise_for_status()
        body = resp.json()
        data = body.get('data', [])
        if not isinstance(data, list):
            data = data.get('data', [])
        # Unwrap JSON:API format: {"type": "torrents", "attributes": {...}}
        unwrapped = []
        for item in data:
            if isinstance(item, dict) and 'attributes' in item:
                merged = {**item.get('attributes', {}), 'id': item.get('id')}
                unwrapped.append(merged)
            else:
                unwrapped.append(item)
        return unwrapped
    except requests.RequestException as e:
        logging.warning(f"HUNO dupe search failed: {e}")
        return []


def _format_size(size_bytes) -> str:
    """Convert a byte count to a human-readable string (e.g. '4.72 GB')."""
    try:
        n = float(size_bytes)
    except (TypeError, ValueError):
        return '?'
    for unit in ('B', 'KB', 'MB', 'GB', 'TB'):
        if abs(n) < 1024.0:
            return f"{n:.2f} {unit}"
        n /= 1024.0
    return f"{n:.2f} PB"


def print_huno_dupes(dupes: list, target_size: int = None, target_file_count: int = None):
    """Print a formatted table of potential duplicate torrents found on HUNO."""
    names = [(t.get('name') or '') for t in dupes]
    name_col = max((len(n) for n in names), default=4)
    name_col = max(name_col, 4)
    size_col = 9   # e.g. "4.72 GB"
    files_col = 5  # "Files"
    total = 2 + name_col + 1 + 7 + 7 + 6 + size_col + 1 + files_col + 6
    lines = [
        "",
        "=" * total,
        "  POTENTIAL DUPLICATES FOUND ON HUNO",
        "=" * total,
        f"  {'Name':<{name_col}} {'Type':<7} {'Res':<7} {'Codec':<6} {'Size':>{size_col}} {'Files':>{files_col}} {'Seeds':>5}",
        "-" * total,
    ]
    for t, name in zip(dupes, names):
        type_name = (t.get('type') or {}).get('name', '?') if isinstance(t.get('type'), dict) else str(t.get('type', '?'))
        resolution = (t.get('resolution') or {}).get('name', '?') if isinstance(t.get('resolution'), dict) else str(t.get('resolution', '?'))
        codec = (t.get('video_codec') or {}).get('name', '?') if isinstance(t.get('video_codec'), dict) else str(t.get('video_codec', '?'))
        seeders = t.get('seeders', '?')
        size_str = _format_size(t.get('size')) if t.get('size') is not None else '?'
        num_files = t.get('num_files')
        files_str = str(num_files) if num_files is not None else '?'
        lines.append(f"  {name:<{name_col}} {type_name:<7} {resolution:<7} {codec:<6} {size_str:>{size_col}} {files_str:>{files_col}} {str(seeders):>5}")
    lines.append("=" * total)
    if target_size is not None or target_file_count is not None:
        parts = []
        if target_size is not None:
            parts.append(f"size: {_format_size(target_size)}")
        if target_file_count is not None:
            parts.append(f"files: {target_file_count}")
        lines.append(f"  Upload target — {', '.join(parts)}")
    print('\n'.join(lines))


def main():
    parser = argparse.ArgumentParser(
        description="Script to automate creation of torrent files, as well as grabbing mediainfo dump, screenshots, and tmdb description"
    )
    # Arguments are unchanged
    parser.add_argument(
        "path", action="store",
        help="Path for file or folder to create .torrent file for",
        type=str
    )
    parser.add_argument(
        "-t", "--tmdb",
        action="store",
        type=int,
        help="TMDB ID for media",
        default=None
    )
    parser.add_argument(
        "-g", "--group",
        action="store",
        type=str,
        help="Group name of the torrent creator",
        default=None
    )
    parser.add_argument(
        "-n", "--notes",
        action="store",
        type=str,
        help="Add any release notes",
        default=None
    )
    parser.add_argument(
        "--hash",
        action="store",
        type=str,
        help="Pre-made hash of the torrent file. Will skip the hashing process.",
        default=None
    )
    parser.add_argument(
        "-s", "--source",
        action="store",
        type=str,
        help="Source of the torrent files (E.g. Bluray Remux, WEB-DL)",
        default=None
    )
    parser.add_argument(
        "-e",
        "--edition",
        action="store",
        type=str,
        help="Set an Edition tag",
        default=None
    )
    parser.add_argument(
        "-u",
        "--upload",
        action="store_true",
        default=False,
        help="Enable to upload generated screenshots to imgbb automatically"
    )
    parser.add_argument(
        "-m",
        "--movie",
        action="store_true",
        default=False,
        help="Enable if input is a movie"
    )
    parser.add_argument(
        "--huno",
        action="store_true",
        default=False,
        help="Enable to upload torrent to HUNO, using api key found in settings.ini"
    )
    parser.add_argument(
        "--manual",
        action="store_true",
        default=False,
        help="Upload to HUNO in manual mode immediately, bypassing auto-parsing (requires --huno)"
    )
    parser.add_argument(
        "--throttle",
        action="store_true",
        default=False,
        help="Enable to throttle qbit upload speed if it's not already throttled while uploading screenshots"
    )
    parser.add_argument(
        "-i",
        "--inject",
        action="store_true",
        default=False,
        help="Enable to automatically inject torrent file to qbittorrent"
    )
    parser.add_argument(
        "--skipPrompt",
        action="store_true",
        default=False,
        help="Enable to skip being asked if you want to upload to HUNO"
    )
    parser.add_argument(
        "--hardlink",
        action="store_true",
        default=False,
        help="Enable to hardlink files no matter if they're already in the seeding directory"
    )
    parser.add_argument(
        "--episode",
        action="store_true",
        default=False,
        help="Enable when processing an individual episode rather than a movie or season"
    )
    parser.add_argument(
        "--skipMICheck",
        action="store_true",
        default=False,
        help="Enable to skip checking for MediaInfo CLI install"
    )
    parser.add_argument(
        "--force",
        action="store_true",
        default=False,
        help="Force a full run even if a previous run for this content is detected"
    )
    parser.add_argument(
        "--mal",
        action="store",
        type=int,
        help="MyAnimeList ID — auto-detected for anime, or provide manually to override",
        default=None
    )
    parser.add_argument(
        "--source-file",
        action="store",
        type=str,
        help="Path to source file/folder for encode uploads (validates release is an encode)",
        default=None
    )
    parser.add_argument(
        "-D", "--debug", action="store_true", help="debug mode", default=False
    )
    parser.add_argument(
        "-V", "--version", action="version", version="%(prog)s {version}".format(version=__VERSION),
    )

    arg = parser.parse_args()
    level = logging.INFO
    if arg.debug:
        level = logging.DEBUG

    if arg.episode and arg.movie:
        logging.error("Movie and Episode arguments can't be enabled at the same time. Please remove one.")
        sys.exit(1)

    logging.basicConfig(datefmt=LOG_DATE_FORMAT, format=LOG_FORMAT, level=level)
    logging.info(f"Version {__VERSION} starting...")

    # --- Load and Validate Settings ---
    settings = load_settings()
    
    required_settings = ['TMDB_API']
    if arg.huno:
        required_settings.extend(['HUNO_API', 'HUNO_ANNOUNCE_URL'])
    if arg.inject or arg.throttle:
        required_settings.extend(['QBIT_HOST', 'QBIT_USERNAME', 'QBIT_PASSWORD'])
    if arg.hardlink or (arg.huno and arg.inject):
        required_settings.append('SEEDING_DIR')

    validate_settings(settings, required_settings)
    
    # Assign settings to variables
    huno_api = settings.get('HUNO_API')
    huno_announce_url = settings.get('HUNO_ANNOUNCE_URL')
    tmdb_api = settings.get('TMDB_API')
    imgbb_api = settings.get('IMGBB_API')
    qbit_username = settings.get('QBIT_USERNAME')
    qbit_password = settings.get('QBIT_PASSWORD')
    qbit_host = settings.get('QBIT_HOST')
    ptpimg_api = settings.get('PTPIMG_API')
    onlyimage_api = settings.get('ONLYIMAGE_API')
    catbox_hash = settings.get('CATBOX_HASH')
    slowpics_remember_me = settings.get('SLOWPICS_REMEMBER_ME')
    slowpics_session = settings.get('SLOWPICS_SESSION')
    seeding_dir = settings.get('SEEDING_DIR')

    if ptpimg_api == '': ptpimg_api = None
    if onlyimage_api == '': onlyimage_api = None
    if catbox_hash == '': catbox_hash = None
    if slowpics_remember_me == '': slowpics_remember_me = None
    if slowpics_session == '': slowpics_session = None
    # --- END Settings Section ---

    if not arg.skipMICheck:
        ensure_mediainfo_cli()

    path = arg.path
    isFolder = FileOrFolder(path)

    if isFolder not in [1, 2]:
        logging.error("Input not a file or directory")
        sys.exit()

    # Compute target size and file count for dupe comparison display
    if isFolder == 1:
        target_size = os.path.getsize(path)
        target_file_count = 1
    else:
        target_size = 0
        target_file_count = 0
        for _root, _, _files in os.walk(path):
            for _f in _files:
                try:
                    target_size += os.path.getsize(os.path.join(_root, _f))
                    target_file_count += 1
                except OSError:
                    pass

    # --- Check for a previous run of the same content ---
    prev_run = None
    reusing = False
    has_torrent = has_screenshots = has_links = False
    prev_torrent_filename = None

    if not arg.force:
        prev_run = find_previous_run(os.path.abspath(path))
        if prev_run:
            prev_torrent_files = [f for f in os.listdir(prev_run) if f.endswith('.torrent')]
            prev_torrent_filename = prev_torrent_files[0] if prev_torrent_files else None
            has_torrent = prev_torrent_filename is not None

            prev_ss_dir = os.path.join(prev_run, "screenshots")
            prev_screenshot_count = 0
            if os.path.isdir(prev_ss_dir):
                for f in os.listdir(prev_ss_dir):
                    if f.startswith('screenshot_') and f.endswith('.png'):
                        fpath = os.path.join(prev_ss_dir, f)
                        if is_screenshot_valid(fpath):
                            prev_screenshot_count += 1
                        else:
                            logging.warning(f"Skipping invalid/blank screenshot from previous run: {f}")
            has_screenshots = prev_screenshot_count > 0

            prev_desc_path = os.path.join(prev_run, "showDesc.txt")
            if os.path.exists(prev_desc_path):
                try:
                    with open(prev_desc_path, encoding='utf-8') as _df:
                        has_links = '[img]' in _df.read()
                except OSError:
                    pass

            ss_label = (f"{prev_screenshot_count}/8 screenshots (incomplete)"
                        if has_screenshots and prev_screenshot_count < 8
                        else "screenshots")
            available = [n for n, v in [("torrent file", has_torrent),
                                         (ss_label, has_screenshots),
                                         ("image links", has_links)] if v]
            if available:
                msg = (f"Previous run found at {os.path.relpath(prev_run)} "
                       f"with: {', '.join(available)}. Reuse these? (--force skips this check)")
                if arg.skipPrompt or getUserInput(msg):
                    reusing = True
                    logging.info("Reusing assets from previous run.")

    # --- Create Run Directory ---
    if not os.path.isdir("runs"): os.makedirs("runs/001")
    run_dirs = [d for d in os.listdir("runs") if d.isdigit()]
    next_run_num = max([int(d) for d in run_dirs]) + 1 if run_dirs else 1
    runDir = os.path.join("runs", str(next_run_num).zfill(3))
    os.makedirs(runDir)
    logging.info(f"Created folder for output in {os.path.relpath(runDir)}")

    # Write source path so future runs can detect and reuse this run
    with open(os.path.join(runDir, "source_path.txt"), 'w', encoding='utf-8') as _spf:
        _spf.write(os.path.normpath(os.path.abspath(path)))

    # --- Find the primary video file ---
    videoFile = None
    if isFolder == 1:
        videoFile = path
    elif isFolder == 2:
        largest_file = ""
        largest_size = 0
        for file in os.listdir(path):
            if file.lower().endswith(('.mp4', '.avi', '.mkv')):
                file_path = os.path.join(path, file)
                size = os.path.getsize(file_path)
                if size > largest_size:
                    largest_size = size
                    largest_file = file_path
        if largest_file:
            videoFile = largest_file
            logging.info(f"Found primary video file: {os.path.basename(videoFile)}")
        else:
            logging.error(f"No video files found in directory: {path}")
            sys.exit(1)

    # --- Use MediaFile classes for parsing and naming ---
    try:
        if arg.movie:
            media_file = Movie(videoFile, tmdb_api, arg.tmdb)
        else:
            media_file = TVShow(videoFile, tmdb_api, arg.tmdb)
    except ValueError as e:
        logging.error(e)
        sys.exit(1)

    if not media_file.metadata:
        logging.error("Failed to fetch metadata. Cannot proceed.")
        sys.exit(1)

    # --- Generate Torrent Name ---
    is_season_pack = (isFolder == 2 and not arg.episode and not arg.movie)

    if arg.group:
        group = arg.group
    else:
        if isFolder == 2:
            # For folder inputs, prefer the folder name for group detection (more reliable than episode filename)
            folder_name = os.path.basename(path)
            video_format = media_file.video_track.get('Format', '') if media_file.video_track else ''
            if 'AV1' in video_format:
                folder_name = re.sub(r'[. ]AV1(?![A-Za-z0-9])', '', folder_name, flags=re.IGNORECASE)
            folder_guessit = guessit.guessit(folder_name)
            detected_group = folder_guessit.get('release_group') or media_file.guessit_info.get('release_group')
        else:
            detected_group = media_file.guessit_info.get('release_group')

        if detected_group:
            group = detected_group[0] if isinstance(detected_group, list) else detected_group
            group = re.sub(r"[\[\]\(\)\{\}]", " ", group).split()[0]
            if '-' in group:
                group = group.rsplit('-', 1)[-1]
        else:
            logging.warning("Could not detect release group from filename.")
            play_alert("input")
            group_input = input(
                "Could not detect release group. Enter group name, or press Enter to use 'NOGRP': "
            ).strip()
            group = group_input if group_input else 'NOGRP'

    # If the group is a member encoder of a known encoding group, append the parent group name
    for parent_group, members in encoderGroups.items():
        if group in members:
            group = f"{group} {parent_group}"
            break

    source = arg.source or ""
    if not source:
        source = detect_source_from_filename(media_file.filename)
        if not source:
            source = detect_source_from_filename(os.path.basename(path))
        # WEBRip + encode codec means the encoder's source was a WEB-DL; upgrade accordingly
        if source.endswith('WEBRip'):
            video_format = media_file.video_track.get('Format', '') if media_file.video_track else ''
            folder_upper = os.path.basename(path).upper()
            is_encode = (
                'AV1' in video_format
                or re.search(r'\bX265\b|\bX264\b', folder_upper)
                or re.search(r'\bX265\b|\bX264\b', media_file.filename.upper())
            )
            if is_encode:
                service = source[:-len('WEBRip')].strip()
                source = f"{service} WEB-DL".strip() if service else 'WEB-DL'
                logging.info(f"Upgraded WEBRip → WEB-DL (encode codec detected: {video_format or 'x265/x264'})")
        if source:
            logging.info(f"Auto-detected source: '{source}'")
        else:
            logging.warning("Could not auto-detect source from filename.")
            play_alert("input")
            _source_options = (
                "UHD BluRay, UHD BluRay Hybrid, BluRay, BluRay Hybrid, "
                "HD-DVD, HD-DVD Hybrid, DVD9, DVD5, DVD, "
                "WEB-DL, WEB-DL Hybrid, HDTV, SDTV"
            )
            source = input(
                f"Could not detect source. Enter the source type\n"
                f"  Accepted values: {_source_options}\n> "
            ).strip()
            if not source:
                logging.error("No source provided. Cannot continue.")
                sys.exit(1)
    if source.lower() == 'blu-ray': source = 'BluRay'

    # --- Source File Validation and Processing ---
    source_file_path = None
    if arg.source_file:
        # Validate that source file is only used with ENCODE releases
        source_lower = source.lower()
        if not any(x in source_lower for x in ['encode', 'x265', 'x264', 'av1']):
            logging.error(f"Source file can only be provided for ENCODE releases. Current source: {source}")
            sys.exit(1)

        # Resolve source file/folder path
        source_file_arg = arg.source_file
        if not os.path.exists(source_file_arg):
            logging.error(f"Source file/folder does not exist: {source_file_arg}")
            sys.exit(1)

        # If source is a folder and we're processing a season pack, find matching episode
        if os.path.isdir(source_file_arg):
            if is_season_pack:
                # Extract episode number from the main media file
                main_episode = media_file.guessit_info.get("episode")
                if main_episode is None:
                    logging.error("Cannot determine episode number from main file for season pack source matching")
                    sys.exit(1)

                # Find corresponding episode file in source folder
                source_files = sorted([f for f in os.listdir(source_file_arg)
                                      if os.path.isfile(os.path.join(source_file_arg, f))
                                      and f.lower().endswith(('.mkv', '.mp4', '.avi', '.ts', '.m2ts'))])

                matching_source_file = None
                for src_file in source_files:
                    src_guessit = guessit.guessit(src_file)
                    if src_guessit.get("episode") == main_episode:
                        matching_source_file = os.path.join(source_file_arg, src_file)
                        break

                if not matching_source_file:
                    logging.error(f"Could not find matching episode {main_episode} in source folder: {source_file_arg}")
                    sys.exit(1)

                source_file_path = matching_source_file
                logging.info(f"Found matching source episode {main_episode}: {os.path.basename(matching_source_file)}")
            else:
                # For single files/episodes, use largest video file in source folder
                video_files = [f for f in os.listdir(source_file_arg)
                              if os.path.isfile(os.path.join(source_file_arg, f))
                              and f.lower().endswith(('.mkv', '.mp4', '.avi', '.ts', '.m2ts'))]

                if not video_files:
                    logging.error(f"No video files found in source folder: {source_file_arg}")
                    sys.exit(1)

                source_file_path = os.path.join(source_file_arg,
                                               max(video_files,
                                                   key=lambda f: os.path.getsize(os.path.join(source_file_arg, f))))
                logging.info(f"Using largest video file from source folder: {os.path.basename(source_file_path)}")
        else:
            # Source is a file
            source_file_path = source_file_arg
            logging.info(f"Using source file: {os.path.basename(source_file_path)}")

    edition = arg.edition
    if not edition:
        edition = detect_edition_from_path(path)
        if edition:
            logging.info(f"Auto-detected edition: '{edition}'")

    try:
        torrentFileName = media_file.generate_name(source=source, group=group, huno_format=True, is_season_pack=is_season_pack, edition=edition)
    except RuntimeError as e:
        logging.error(e)
        sys.exit(1)

    release_tag = detect_release_tag_from_path(path)
    base_name = re.sub(r'[<>:"/\\|?*\x00-\x1F\x7F]', "", torrentFileName)
    base_name = re.sub(r'\.(mkv|mp4|avi|ts|m2ts)$', '', base_name, flags=re.IGNORECASE)
    if release_tag:
        logging.info(f"Detected release tag: '{release_tag}'")
        display_torrent_name = f"{base_name} [{release_tag}].torrent"
    else:
        display_torrent_name = f"{base_name}.torrent"
    torrentFileName = f"{base_name}.torrent"
    logging.info("Final name: " + display_torrent_name)

    # --- Create mediainfo dumps ---
    _prev_mi = os.path.join(prev_run, "mediainfo.txt") if prev_run else None
    source_mediainfo_path = None

    # Extract source mediainfo first (if provided)
    if source_file_path:
        getInfoDump(source_file_path, runDir, filename="source_mediainfo.txt")
        source_mediainfo_path = os.path.join(runDir, "source_mediainfo.txt")
        logging.info(f"Source mediainfo extracted: {source_mediainfo_path}")

    # Create main mediainfo dump
    if reusing and _prev_mi and os.path.exists(_prev_mi):
        shutil.copy2(_prev_mi, os.path.join(runDir, "mediainfo.txt"))
        logging.info("Reusing mediainfo from previous run.")
    else:
        getInfoDump(videoFile, runDir)

    # --- Screenshot and Upload Logic ---
    screenshot_success = False
    encode_timestamps = []
    encode_bbcodes = None
    source_bbcodes = None
    comparison_url = None
    comparison_bbcodes = None

    if reusing and has_screenshots:
        prev_ss_src = os.path.join(prev_run, "screenshots")
        screenshots_dir = os.path.join(runDir, "screenshots")
        os.makedirs(screenshots_dir, exist_ok=True)
        # Copy only valid screenshot_*.png files — skip leftover temp files and blank/corrupt captures
        for f in os.listdir(prev_ss_src):
            if f.startswith('screenshot_') and f.endswith('.png'):
                src_path = os.path.join(prev_ss_src, f)
                if is_screenshot_valid(src_path):
                    shutil.copy2(src_path, os.path.join(screenshots_dir, f))
                # Invalid files are simply not copied; they will be regenerated as missing indices

        if prev_screenshot_count < 8:
            existing_indices = {
                int(f[len('screenshot_'):len('screenshot_') + 2])
                for f in os.listdir(screenshots_dir)
                if f.startswith('screenshot_') and f.endswith('.png')
            }
            missing = sorted(i for i in range(8) if i not in existing_indices)
            logging.info(
                f"Previous run had {prev_screenshot_count}/8 screenshots. "
                f"Generating {len(missing)} missing screenshot(s) "
                f"(indices: {', '.join(str(i) for i in missing)})."
            )
            screenshot_success, encode_timestamps = create_optimized_screenshots(videoFile, runDir, skip_indices=existing_indices)
            if not screenshot_success:
                logging.error("Failed to generate missing screenshots. Aborting.")
                sys.exit(1)
        else:
            logging.info(f"Reusing all 8 screenshots from {os.path.relpath(prev_run)}.")
            screenshot_success = True
            # Recompute timestamps from video file for source screenshot capture if needed
            if source_file_path:
                _v = cv2.VideoCapture(videoFile)
                if _v.isOpened():
                    _dur = int(_v.get(cv2.CAP_PROP_FRAME_COUNT)) / int(_v.get(cv2.CAP_PROP_FPS))
                    encode_timestamps = [i * _dur / 10 for i in range(1, 9)]
                _v.release()
    else:
        logging.info("Making screenshots...")
        screenshot_success, encode_timestamps = create_optimized_screenshots(videoFile, runDir)
        if not screenshot_success:
            logging.error("Failed to create screenshots. Aborting.")
            sys.exit(1)

    if reusing and has_links:
        with open(os.path.join(prev_run, "showDesc.txt"), encoding='utf-8') as _df:
            screenshot_lines = [line for line in _df if '[img]' in line]
        if screenshot_lines:
            with open(os.path.join(runDir, "showDesc.txt"), 'w', encoding='utf-8') as _df:
                _df.writelines(screenshot_lines)
            logging.info(f"Reused {len(screenshot_lines)} image link(s) from {os.path.relpath(prev_run)}.")
    elif arg.upload and screenshot_success:
        bbcodes = upload_screenshots_concurrently(
            screenshot_dir=os.path.join(runDir, "screenshots"),
            imgbb_api=imgbb_api,
            ptpimg_api=ptpimg_api,
            catbox_hash=catbox_hash,
            onlyimage_api=onlyimage_api
        )
        if bbcodes is None:
            return
        if bbcodes:
            with open(os.path.join(runDir, "showDesc.txt"), "w", encoding='utf-8') as desc_file:
                for bbcode in bbcodes:
                    desc_file.write(f"[center]{bbcode}[/center]\n")
            logging.info(f"Success: BBCode written to showDesc.txt ({len(bbcodes)} images)")

    # --- Comparison Screenshots (source_file_path only) ---
    if bbcodes:
        encode_bbcodes = bbcodes

    if source_file_path and screenshot_success and encode_timestamps:
        source_ok = capture_source_screenshots(source_file_path, encode_timestamps, runDir)
        if source_ok and arg.upload:
            source_bbcodes = upload_screenshots_concurrently(
                screenshot_dir=os.path.join(runDir, "screenshots"),
                imgbb_api=imgbb_api,
                ptpimg_api=ptpimg_api,
                catbox_hash=catbox_hash,
                onlyimage_api=onlyimage_api,
                file_pattern="source_"
            )
            if source_bbcodes and encode_bbcodes:
                # Interleave: src_00, enc_00, src_01, enc_01...
                comparison_bbcodes = [val for pair in zip(source_bbcodes, encode_bbcodes) for val in pair]

                # Build image_pairs for slow.pics: [(source_path, encode_path), ...]
                ss_dir = os.path.join(runDir, "screenshots")
                image_pairs = [
                    (os.path.join(ss_dir, f"source_{i:02d}.png"),
                     os.path.join(ss_dir, f"screenshot_{i:02d}.png"))
                    for i in range(8)
                ]
                colour_space = media_file.get_colour_space()  # "SDR", "HDR", etc.
                slowpics_result = upload_to_slowpics(
                    image_pairs,
                    collection_name=os.path.splitext(torrentFileName)[0],
                    labels=["Source", "Encode"],
                    hdr_type=colour_space,
                    remember_me=slowpics_remember_me,
                    session_cookie=slowpics_session,
                    return_status=True,
                )
                comparison_url = slowpics_result.get("url")
                if comparison_url:
                    logging.info(f"slow.pics comparison: {comparison_url}")
                else:
                    error_code = slowpics_result.get("error_code")
                    error_message = slowpics_result.get("error_message")
                    if error_code:
                        logging.warning(
                            "slow.pics upload failed (%s: %s) — description will include inline frames only.",
                            error_code,
                            error_message,
                        )
                    else:
                        logging.warning("slow.pics upload failed — description will include inline frames only.")
        elif source_ok and not arg.upload:
            logging.info("Source screenshots captured but --upload not set; skipping comparison upload.")
        else:
            logging.warning("Source screenshot capture failed — skipping comparison section.")

    # --- Create Torrent File ---
    postName = os.path.splitext(torrentFileName)[0]
    if reusing and has_torrent:
        shutil.copy2(os.path.join(prev_run, prev_torrent_filename), os.path.join(runDir, torrentFileName))
        logging.info(f"Reusing torrent file from {os.path.relpath(prev_run)}.")
        if (arg.huno and arg.inject) or arg.hardlink:
            if seeding_dir and os.path.dirname(path) != seeding_dir:
                destination = os.path.join(seeding_dir, postName)
                copy_folder_structure(path, destination)
                logging.info(f"Hardlinks ensured at {destination}")
    else:
        logging.info("Creating torrent file")
        torrent = torf.Torrent()
        torrent.private = True
        torrent.source = "HUNO"
        torrent.piece_size_max = 4 * 1024 * 1024  # 4MB max — prevents Windows [Errno 22] on large reads
        torrent.path = path
        torrent.trackers.append(huno_announce_url)

        if (arg.huno and arg.inject) or arg.hardlink:
            if seeding_dir and os.path.dirname(path) != seeding_dir:
                logging.info("Attempting to create hardlinks for easy seeding...")
                destination = os.path.join(seeding_dir, postName)
                copy_folder_structure(path, destination)
                logging.info(f"Hardlinks created at {destination}")
                torrent.path = destination

        logging.info("Generating torrent file hash. This will take a long while...")
        torrent.generate(callback=cb, interval=0.25)
        torrent.write(os.path.join(runDir, torrentFileName))
        logging.info(f"Torrent file wrote to {torrentFileName}")
    
    # --- HUNO Upload Logic ---
    upload_succeeded = False
    if arg.huno:
        logging.info("Preparing HUNO upload...")

        try:
            videoCodec = media_file.get_video_codec(source)
            resolution = media_file.get_resolution()
        except RuntimeError as e:
            logging.error(e)
            sys.exit(1)
        type_id = _get_huno_type_id(source, videoCodec)
        # AV1 is used by both encode groups and streaming services natively (e.g. Netflix).
        # For WEB sources only, ask the user to clarify — non-WEB sources (BluRay etc.) are always encodes.
        if videoCodec == 'AV1' and type_id == _HUNO_TYPE_ENCODE and 'web' in source.lower():
            play_alert("input")
            answer = input(
                "AV1 detected — is this a direct WEB release or an encode?\n"
                "  1) Encode  2) Direct WEB\n> "
            ).strip()
            if answer == '2':
                type_id = _HUNO_TYPE_WEB
        if resolution not in RESOLUTION_ID_MAP:
            accepted = ", ".join(sorted(RESOLUTION_ID_MAP.keys()))
            logging.error(
                f"Resolution '{resolution}' is not supported by HUNO and cannot be uploaded. "
                f"Accepted HUNO resolutions: {accepted}"
            )
            sys.exit(1)
        resolution_id = RESOLUTION_ID_MAP[resolution]

        source_type_id = _resolve_source_type_id(source)

        # --- Streaming service (WEB sources only) ---
        streaming_service_val = None
        if 'web' in source.lower():
            # Extract service prefix from source string (e.g., "AMZN" from "AMZN WEB-DL")
            for _wb in ('WEB-DL', 'WEBDL', 'WEBRIP', 'WEB-RIP', 'WEB'):
                if source.upper().endswith(_wb):
                    _prefix = source[:len(source) - len(_wb)].strip()
                    if _prefix:
                        streaming_service_val = _prefix
                    break
            if not streaming_service_val:
                play_alert("input")
                print(
                    "\n  No streaming service detected. Providing one is optional but heavily recommended.\n"
                    "  Common services: NF, AMZN, DSNP, ATVP, MAX, HULU, PCOK, HMAX, HBO, CR, STAN, CRAV ...\n"
                    "  Press Enter to skip (will submit as 'NADA' — no streaming service)."
                )
                _svc_input = input("  Streaming service abbreviation: ").strip().upper()
                streaming_service_val = _svc_input if _svc_input else "NADA"
                logging.info(f"Streaming service set to: '{streaming_service_val}'")
            else:
                logging.info(f"Streaming service detected: '{streaming_service_val}'")

        audio_info = media_file.get_audio_info()
        # Split "DDP 5.1" → audio_format="DDP", audio_channels="5.1"
        audio_parts = audio_info.split(' ', 1)
        audio_format = audio_parts[0] if audio_parts else ""
        audio_channels = audio_parts[1] if len(audio_parts) > 1 else ""
        video_format = media_file.get_colour_space()

        IMDB_ID = media_file.metadata.get("imdb_id", "0")
        TVDB_ID = 0
        if not arg.movie:
            try:
                ext_url = f'https://api.themoviedb.org/3/tv/{media_file.tmdb_id}/external_ids'
                ext_resp = requests.get(ext_url, params={'api_key': tmdb_api}, timeout=15)
                ext_resp.raise_for_status()
                external_ids = ext_resp.json()
                IMDB_ID = external_ids.get("imdb_id", "0")
                TVDB_ID = external_ids.get("tvdb_id", 0)
            except requests.RequestException as e:
                logging.warning(f"Could not fetch external IDs: {e}")

        # --- Anime detection and MAL ID resolution ---
        MAL_ID = arg.mal  # Start with manually supplied value (may be None)
        title_for_mal = (
            media_file.metadata.get('title') if arg.movie
            else media_file.metadata.get('name', '')
        )
        if MAL_ID is None:
            if is_anime(media_file.metadata, arg.movie):
                logging.info(f"Anime detected for '{title_for_mal}'. Searching Jikan for MAL ID...")
                MAL_ID = lookup_mal_id(title_for_mal, arg.movie)
                if MAL_ID:
                    logging.info(f"MAL ID found: {MAL_ID}")
                else:
                    logging.warning("Could not find MAL ID via Jikan. You can provide it manually with --mal.")
            else:
                logging.debug("Not detected as anime — skipping MAL lookup.")

        generate_bbcode(media_file.tmdb_id, media_file.metadata.get('overview', ''), runDir, tmdb_api, arg.movie, arg.notes,
                        comparison_url=comparison_url, comparison_bbcodes=comparison_bbcodes)

        is_season_pack = 1 if (not arg.movie and not arg.episode and isFolder == 2) else 0

        data = {
            'anonymous': 0,
            'internal': 0,
            'category_id': 1 if arg.movie else 2,
            'type_id': type_id,
            'resolution_id': resolution_id,
            'tmdb': int(media_file.tmdb_id),
            'imdb': re.sub(r'\D', '', IMDB_ID or "0"),
            'tvdb': TVDB_ID or 0,
            'video_codec': videoCodec,
            'video_format': video_format,
            'audio_format': audio_format,
            'audio_channels': audio_channels,
            'season_pack': is_season_pack,
        }
        if source_type_id is not None:
            data['source_type'] = source_type_id
        if streaming_service_val:
            data['streaming_service'] = streaming_service_val
        if edition:
            data['edition'] = edition
        if release_tag:
            data['release_tag'] = release_tag
        if MAL_ID:
            data['mal'] = MAL_ID
        if media_file.is_ds4k():
            data['scaling_type'] = 1

        if not arg.movie:
            season_val = media_file.guessit_info.get("season", 0)
            data["season_number"] = int(re.sub(r'\D', '', str(season_val))) if season_val else 0
            if arg.episode:
                episode_val = media_file.guessit_info.get("episode", 0)
                data["episode_number"] = int(re.sub(r'\D', '', str(episode_val))) if episode_val else 0

        desc_path = os.path.join(runDir, "showDesc.txt")
        mediainfo_path = os.path.join(runDir, "mediainfo.txt")
        torrent_path = os.path.join(runDir, torrentFileName)
        headers = {"Authorization": f"Bearer {huno_api}", "Accept": "application/json"}

        def _build_manual_data():
            release_name = re.sub(r'\.torrent$', '', torrentFileName, flags=re.IGNORECASE)
            release_group = release_name.rsplit('-', 1)[-1].strip().rstrip(')') if '-' in release_name else ''
            try:
                media_language = media_file.get_language_name()
            except Exception:
                media_language = "English"
            audio_channel_id = AUDIO_CHANNEL_ID_MAP.get(audio_channels, audio_channels)
            md = {**data, 'mode': 'manual', 'name': release_name,
                  'release_group': release_group,
                  'media_language_id': media_language}
            for old_key, new_key in [
                ('video_codec', 'video_codec_id'),
                ('video_format', 'video_format_id'),
                ('audio_format', 'audio_format_id'),
                ('source_type', 'source_type_id'),
                ('streaming_service', 'streaming_service_id'),
            ]:
                if old_key in md:
                    md[new_key] = md.pop(old_key)
            md.pop('audio_channels', None)
            md['audio_channel_id'] = audio_channel_id
            return md

        def _do_manual_upload(manual_data=None):
            if manual_data is None:
                manual_data = _build_manual_data()
            print_huno_payload_preview(manual_data, torrentFileName, source, include_source_mediainfo=bool(source_mediainfo_path))
            if getUserInput("Do you want to upload this to HUNO?"):
                files_to_open = [
                    ('desc', desc_path, 'application/json'),
                    ('mediainfo', mediainfo_path, 'text/plain'),
                    ('torrent', torrent_path, 'application/x-bittorrent'),
                ]
                if source_mediainfo_path and os.path.exists(source_mediainfo_path):
                    files_to_open.append(('source_mediainfo', source_mediainfo_path, 'text/plain'))

                open_files = [open(p, 'rb') for _, p, _ in files_to_open]
                try:
                    files = {
                        'torrent': (torrentFileName, open_files[2], 'application/x-bittorrent'),
                        'description': ('description.txt', open_files[0], 'text/plain'),
                        'mediainfo': ('mediainfo.txt', open_files[1], 'text/plain'),
                    }
                    if len(open_files) > 3:
                        files['source_mediainfo'] = ('source_mediainfo.txt', open_files[3], 'text/plain')

                    resp = requests.post(
                        url=HUNO_API_URL,
                        headers=headers,
                        data=manual_data,
                        files=files,
                        timeout=60,
                    )
                finally:
                    for f in open_files:
                        f.close()
                if resp.status_code == 422:
                    res = resp.json()
                    logging.error(f"HUNO manual upload rejected: {res.get('message')}")
                    logging.error(f"Details: {res.get('data')}")
                    return False
                else:
                    resp.raise_for_status()
                    res = resp.json()
                    if res.get("success"):
                        logging.info(f"HUNO upload successful (manual mode): {res.get('message')}")
                        if res.get("data", {}).get("warnings"):
                            logging.warning(f"HUNO warnings: {res['data']['warnings']}")
                        return True
                    else:
                        logging.error(f"HUNO manual upload failed: {res.get('message')}")
                        logging.error(f"Details: {res.get('data')}")
            return False

        if arg.manual:
            print("\n  *** WARNING: In manual mode you are solely responsible for ensuring")
            print("  *** the upload complies with all HUNO rules. Rule violations are your liability.")

        manual_data = _build_manual_data() if arg.manual else None
        if not arg.manual:
            print_huno_payload_preview(data, torrentFileName, source, include_source_mediainfo=bool(source_mediainfo_path))

        logging.info("Checking HUNO for existing releases...")
        dupes = search_huno_dupes(int(media_file.tmdb_id), 1 if arg.movie else 2, huno_api)
        if dupes:
            print_huno_dupes(dupes, target_size, target_file_count)
            print(f"\n  {len(dupes)} existing release(s) found for this title on HUNO.")
        else:
            print("\n  No existing releases found on HUNO for this title.")

        if arg.manual:
            upload_succeeded = _do_manual_upload(manual_data)
        elif arg.skipPrompt or getUserInput("Do you want to upload this to HUNO?"):
            try:
                files_to_open = [
                    ('desc', desc_path, 'text/plain'),
                    ('mediainfo', mediainfo_path, 'text/plain'),
                    ('torrent', torrent_path, 'application/x-bittorrent'),
                ]
                if source_mediainfo_path and os.path.exists(source_mediainfo_path):
                    files_to_open.append(('source_mediainfo', source_mediainfo_path, 'text/plain'))

                open_files = [open(p, 'rb') for _, p, _ in files_to_open]
                try:
                    files = {
                        'torrent': (torrentFileName, open_files[2], 'application/x-bittorrent'),
                        'description': ('description.txt', open_files[0], 'text/plain'),
                        'mediainfo': ('mediainfo.txt', open_files[1], 'text/plain'),
                    }
                    if len(open_files) > 3:
                        files['source_mediainfo'] = ('source_mediainfo.txt', open_files[3], 'text/plain')

                    response = requests.post(
                        url=HUNO_API_URL,
                        headers=headers,
                        data=data,
                        files=files,
                        timeout=60,
                    )
                finally:
                    for f in open_files:
                        f.close()
                if response.status_code == 409:
                    result = response.json()
                    logging.warning(f"HUNO upload rejected — duplicate content: {result.get('message')}")
                    logging.warning(f"Details: {result.get('data')}")
                elif response.status_code == 422:
                    result = response.json()
                    logging.error(f"HUNO upload rejected — attribute mismatch: {result.get('message')}")
                    logging.error(f"Details: {result.get('data')}")
                    api_message = result.get('message') or ''
                    if 'mode=manual' in api_message:
                        print("\n  The API suggests retrying with manual mode, which bypasses auto-parsing.")
                        print("  *** WARNING: In manual mode you are solely responsible for ensuring")
                        print("  *** the upload complies with all HUNO rules. Rule violations are your liability.")
                        if getUserInput("Retry upload with manual mode?"):
                            upload_succeeded = _do_manual_upload()
                else:
                    response.raise_for_status()
                    result = response.json()
                    if result.get("success"):
                        upload_succeeded = True
                        logging.info(f"HUNO upload successful: {result.get('message')}")
                        if result.get("data", {}).get("warnings"):
                            logging.warning(f"HUNO warnings: {result['data']['warnings']}")
                    else:
                        logging.error(f"HUNO upload failed: {result.get('message')}")
                        logging.error(f"Details: {result.get('data')}")
            except requests.exceptions.HTTPError as e:
                logging.error(f"HUNO HTTP error {e.response.status_code}: {e.response.text[:500]}")
            except requests.exceptions.RequestException as e:
                logging.error(f"HUNO upload request failed: {e}")

    # --- qBitTorrent Injection ---
    if arg.inject and (not arg.huno or upload_succeeded):
        logging.info("Qbittorrent injection enabled")
        category = "HUNO" if arg.huno else ""
        paused = not arg.huno
        qbitInject(qbit_host=qbit_host, qbit_username=qbit_username, qbit_password=qbit_password, category=category, runDir=runDir, torrentFileName=torrentFileName, paused=paused, postName=postName)

def generate_bbcode(tmdb_id, mediaDesc, runDir, api_key, isMovie, notes=None, comparison_url=None, comparison_bbcodes=None):
    prominent_color = get_prominent_color(tmdb_id, api_key, runDir, isMovie)
    hex_color = f"#{prominent_color[0]:02x}{prominent_color[1]:02x}{prominent_color[2]:02x}"
    bbcode = f'[color={hex_color}][center][b]Description[/b][/center][/color]\n' \
             f'[center][quote]{mediaDesc}[/quote][/center]\n\n'
    if notes:
        bbcode += f'[color={hex_color}][center][b]Notes[/b][/center][/color]\n' \
                  f'[center]{notes}[/center]\n\n'

    if comparison_bbcodes:
        bbcode += f'[color={hex_color}][center][b]Comparison[/b][/center][/color]\n'
        if comparison_url:
            bbcode += f'[center][url={comparison_url}]View on slow.pics[/url][/center]\n'
        bbcode += '\n'
        bbcode += f'[color={hex_color}][center][b]Source vs Encode[/b][/center][/color]\n'
        for cb_item in comparison_bbcodes:
            bbcode += f'[center]{cb_item}[/center]\n'
        bbcode += '\n'

    bbcode += f'[color={hex_color}][center][b]Screens[/b][/center][/color]\n'
    
    desc_file_path = os.path.join(runDir, "showDesc.txt")
    if os.path.exists(desc_file_path):
        with open(desc_file_path) as f:
            bbcode += f.read()
            
    with open(desc_file_path, 'w', encoding='utf-8') as fi:
        fi.write(bbcode)
    logging.info(f"Final bbcode written to {desc_file_path}")
    return bbcode

def get_prominent_color(tmdb_id, api_key, directory, isMovie):
    logging.info(f"Fetching poster for TMDB ID: {tmdb_id}")
    api_path = 'movie' if isMovie else 'tv'
    response = requests.get(f'https://api.themoviedb.org/3/{api_path}/{tmdb_id}', params={'api_key': api_key})
    data = response.json()
    poster_path = data.get('poster_path')
    if not poster_path:
        logging.warning("No poster found on TMDB.")
        return (255, 255, 255) # Default to white
        
    poster_url = f'https://image.tmdb.org/t/p/w500/{poster_path}'
    logging.info(f"Downloading poster from URL: {poster_url}")
    response = requests.get(poster_url, stream=True)
    response.raise_for_status()
    poster_file_path = os.path.join(directory, 'poster.jpg')
    with open(poster_file_path, 'wb') as file:
        for chunk in response.iter_content(chunk_size=8192):
            file.write(chunk)
    logging.info("Poster downloaded. Analyzing colors...")
    color_thief = ColorThief(poster_file_path)
    dominant_colour = color_thief.get_color(quality=1)
    return _ensure_readable_on_dark(dominant_colour)


def _ensure_readable_on_dark(rgb):
    """Shift a color's lightness up so it reads well on a dark background,
    while preserving the hue and saturation from the source poster."""
    import colorsys
    r, g, b = (c / 255.0 for c in rgb)
    h, l, s = colorsys.rgb_to_hls(r, g, b)
    # Minimum lightness of 0.65 keeps text comfortably readable on dark backgrounds.
    # Cap at 0.88 to avoid washed-out near-white that loses its identity.
    l = max(0.65, min(l, 0.88))
    r2, g2, b2 = colorsys.hls_to_rgb(h, l, s)
    return (round(r2 * 255), round(g2 * 255), round(b2 * 255))

def is_screenshot_valid(path, white_threshold=0.90):
    """Return True if the image looks like a real frame rather than a blank/corrupt capture.

    Rejects images where more than *white_threshold* fraction of pixels are
    near-white (>= 245 in all channels), which catches partially-written files
    that render as a white canvas with only a sliver of real content.
    Also rejects files that cv2 cannot decode at all.
    """
    try:
        img = cv2.imread(path)
        if img is None:
            return False
        near_white = np.all(img >= 245, axis=2)
        if near_white.mean() >= white_threshold:
            return False
        return True
    except Exception:
        return False


def create_optimized_screenshots(videoFile, runDir, skip_indices=None):
    logging.info("Making optimized screenshots...")
    screenshots_dir = os.path.join(runDir, "screenshots")
    if not os.path.isdir(screenshots_dir):
        os.mkdir(screenshots_dir)

    # Suppress ffmpeg/libav stderr (e.g. "Unsupported encoding type") that leaks through OpenCV
    devnull = os.open(os.devnull, os.O_WRONLY)
    saved_stderr = os.dup(2)
    os.dup2(devnull, 2)
    os.close(devnull)
    video = cv2.VideoCapture(videoFile)
    os.dup2(saved_stderr, 2)
    os.close(saved_stderr)
    if not video.isOpened():
        logging.error(f"Could not open video file: {videoFile}")
        return False, []

    total_duration = int(video.get(cv2.CAP_PROP_FRAME_COUNT)) / int(video.get(cv2.CAP_PROP_FPS))
    timestamps = [i * total_duration / 10 for i in range(1, 9)] # 8 screenshots
    successful_screenshots = 0
    active_temp = None

    try:
        for i, timestamp in enumerate(timestamps):
            if skip_indices and i in skip_indices:
                successful_screenshots += 1
                continue
            video.set(cv2.CAP_PROP_POS_MSEC, timestamp * 1000)
            success, image = video.read()
            if success:
                temp_png = os.path.join(screenshots_dir, f"temp_{i:02d}.png")
                active_temp = temp_png
                cv2.imwrite(temp_png, image)
                final_path = os.path.join(screenshots_dir, f"screenshot_{i:02d}.png")
                optimize_screenshot(temp_png, final_path)
                os.remove(temp_png)
                active_temp = None
                successful_screenshots += 1
                logging.info(f"Screenshot {i+1}/{len(timestamps)} created.")
            else:
                logging.warning(f"Failed to create screenshot at timestamp {timestamp:.2f}s")
    except KeyboardInterrupt:
        logging.warning("Screenshot generation interrupted. Cleaning up temporary files.")
        raise
    finally:
        if active_temp and os.path.exists(active_temp):
            os.remove(active_temp)
        video.release()

    expected = len(timestamps)
    if successful_screenshots < expected:
        logging.error(
            f"Only {successful_screenshots} of {expected} screenshots were created successfully. "
            f"All {expected} are required."
        )
        return False, []
    logging.info(f"Created {successful_screenshots} optimized screenshots")
    return True, timestamps

def capture_source_screenshots(source_path: str, timestamps: list[float], run_dir: str) -> bool:
    logging.info("Capturing source screenshots for comparison...")
    screenshots_dir = os.path.join(run_dir, "screenshots")
    if not os.path.isdir(screenshots_dir):
        os.mkdir(screenshots_dir)

    # Suppress ffmpeg/libav stderr
    devnull = os.open(os.devnull, os.O_WRONLY)
    saved_stderr = os.dup(2)
    os.dup2(devnull, 2)
    os.close(devnull)
    video = cv2.VideoCapture(source_path)
    os.dup2(saved_stderr, 2)
    os.close(saved_stderr)
    if not video.isOpened():
        logging.error(f"Could not open source file: {source_path}")
        return False

    successful_screenshots = 0
    active_temp = None

    try:
        for i, timestamp in enumerate(timestamps):
            video.set(cv2.CAP_PROP_POS_MSEC, timestamp * 1000)
            success, image = video.read()
            if success:
                temp_png = os.path.join(screenshots_dir, f"source_temp_{i:02d}.png")
                active_temp = temp_png
                cv2.imwrite(temp_png, image)
                final_path = os.path.join(screenshots_dir, f"source_{i:02d}.png")
                optimize_screenshot(temp_png, final_path)
                os.remove(temp_png)
                active_temp = None
                successful_screenshots += 1
                logging.info(f"Source screenshot {i+1}/{len(timestamps)} created.")
            else:
                logging.warning(f"Failed to create source screenshot at timestamp {timestamp:.2f}s")
    except KeyboardInterrupt:
        logging.warning("Source screenshot generation interrupted. Cleaning up temporary files.")
        raise
    finally:
        if active_temp and os.path.exists(active_temp):
            os.remove(active_temp)
        video.release()

    expected = len(timestamps)
    if successful_screenshots < expected:
        logging.error(
            f"Only {successful_screenshots} of {expected} source screenshots were created successfully. "
            f"All {expected} are required."
        )
        return False
    logging.info(f"Created {successful_screenshots} source screenshots for comparison")
    return True

def optimize_screenshot(input_path, output_path, max_width=1920, quality=85):
    try:
        with Image.open(input_path) as img:
            if img.mode in ('RGBA', 'LA', 'P'): img = img.convert('RGB')
            if img.width > max_width:
                ratio = max_width / img.width
                new_height = int(img.height * ratio)
                img = img.resize((max_width, new_height), Image.Resampling.LANCZOS)
            img.save(output_path, 'PNG', quality=quality, optimize=True)
    except Exception as e:
        logging.error(f"Failed to optimize screenshot {input_path}: {e}")
        shutil.copy(input_path, output_path)

def upload_single_screenshot(image_path, imgbb_api, ptpimg_api, catbox_hash, onlyimage_api=None):
    image_name = os.path.basename(image_path)
    logging.info(f"Uploading {image_name}...")

    # --- Attempt 1: PTPImg (if API key is provided) ---
    if ptpimg_api:
        image_url = uploadToPTPIMG(image_path, ptpimg_api)
        if image_url:
            logging.info(f"Success: Successfully uploaded {image_name} to PTPImg.")
            return f"[url={image_url}][img]{image_url}[/img][/url]"

    # --- Attempt 2: OnlyImage (if API key is provided) ---
    if onlyimage_api:
        image_url = upload_to_onlyimage(image_path, onlyimage_api)
        if image_url:
            logging.info(f"Success: Successfully uploaded {image_name} to OnlyImage.")
            return f"[url={image_url}][img]{image_url}[/img][/url]"

    # --- Attempt 3: ImgBB (if API key is provided) ---
    if imgbb_api:
        image_url, _ = upload_to_imgbb(image_path, imgbb_api) # We only need the direct URL
        if image_url:
            logging.info(f"Success: Successfully uploaded {image_name} to ImgBB.")
            return f"[url={image_url}][img]{image_url}[/img][/url]"

    # --- Attempt 4: Catbox (fallback) ---
    image_url = upload_to_catbox(image_path, catbox_hash)
    if image_url:
        logging.info(f"Success: Successfully uploaded {image_name} to Catbox.")
        return f"[url={image_url}][img]{image_url}[/img][/url]"

    logging.error(f"Failure: All upload methods failed for {image_name}.")
    return None

def upload_screenshots_concurrently(screenshot_dir, imgbb_api, ptpimg_api, catbox_hash, onlyimage_api=None, max_workers=5, file_pattern="screenshot_"):
    images = sorted([f for f in os.listdir(screenshot_dir)
                     if f.startswith(file_pattern) and f.lower().endswith('.png')])
    if not images:
        logging.warning("No screenshots found to upload!")
        return []

    image_paths = [os.path.join(screenshot_dir, img) for img in images]
    bbcodes = [None] * len(images)

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_index = {executor.submit(upload_single_screenshot, path, imgbb_api, ptpimg_api, catbox_hash, onlyimage_api): i for i, path in enumerate(image_paths)}
        for future in as_completed(future_to_index):
            index = future_to_index[future]
            try:
                result = future.result(timeout=120)
                if result:
                    bbcodes[index] = result
            except Exception as e:
                logging.error(f"Upload task failed for {image_paths[index]}: {e}")
    
    successful_uploads = [b for b in bbcodes if b]
    if len(successful_uploads) < len(images):
        failed = len(images) - len(successful_uploads)
        logging.error(f"Failure: {failed} out of {len(images)} screenshots failed to upload. Aborting.")
        return None
    logging.info(f"Success: Successfully uploaded {len(successful_uploads)} out of {len(images)} screenshots")
    return successful_uploads

if __name__ == "__main__":
    main()
