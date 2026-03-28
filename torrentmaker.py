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
    convert_sha1_hash, ensure_mediainfo_cli, upload_to_catbox, upload_to_imgbb
)
from torrent_utils.media import Movie, TVShow

__VERSION = "2.1.3"
HUNO_API_URL = "https://hawke.uno/api/torrents/upload"
LOG_FORMAT = "%(asctime)s.%(msecs)03d %(levelname)-8s P%(process)06d.%(module)-12s %(funcName)-16sL%(lineno)04d %(message)s"
LOG_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

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
    if 'web' in source_lower:
        return _HUNO_TYPE_WEB
    if video_codec in ('x264', 'x265', 'AV1'):
        return _HUNO_TYPE_ENCODE
    return _HUNO_TYPE_WEB  # Safe fallback


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
    elif re.search(r'\bWEBRIP\b|\bWEB[\.\-]RIP\b', name):
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


def print_huno_payload_preview(data: dict, torrent_name: str, source: str):
    """Prints a human-readable preview of the HUNO upload payload."""
    lines = [
        "",
        "=" * 62,
        "  HUNO UPLOAD PAYLOAD PREVIEW",
        "=" * 62,
        f"  Torrent name  : {torrent_name}",
        f"  Source string : {source or '(not set)'}",
        "-" * 62,
        f"  category_id   : {data.get('category_id')} ({_HUNO_CATEGORY_NAMES.get(data.get('category_id'), '?')})",
        f"  type_id       : {data.get('type_id')} ({_HUNO_TYPE_NAMES.get(data.get('type_id'), '?')})",
        f"  resolution_id : {data.get('resolution_id')} ({_HUNO_RESOLUTION_NAMES.get(data.get('resolution_id'), '?')})",
        f"  source_type   : {data.get('source_type', '(not sent)')}",
        f"  tmdb          : {data.get('tmdb')}",
        f"  imdb          : {data.get('imdb')}",
        f"  tvdb          : {data.get('tvdb', '(n/a)')}",
        f"  video_codec   : {data.get('video_codec')}",
        f"  video_format  : {data.get('video_format')}",
        f"  audio_format  : {data.get('audio_format')}",
        f"  audio_channels: {data.get('audio_channels')}",
        f"  season_pack   : {data.get('season_pack', '(n/a)')}",
    ]
    if 'season_number' in data:
        lines.append(f"  season_number : {data.get('season_number')}")
    if 'episode_number' in data:
        lines.append(f"  episode_number: {data.get('episode_number')}")
    if 'edition' in data:
        lines.append(f"  edition       : {data.get('edition')}")
    lines.append("=" * 62)
    print('\n'.join(lines))


HUNO_FILTER_URL = "https://hawke.uno/api/torrents/filter"


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
        return data if isinstance(data, list) else data.get('data', [])
    except requests.RequestException as e:
        logging.warning(f"HUNO dupe search failed: {e}")
        return []


def print_huno_dupes(dupes: list):
    """Print a formatted table of potential duplicate torrents found on HUNO."""
    lines = [
        "",
        "=" * 78,
        "  POTENTIAL DUPLICATES FOUND ON HUNO",
        "=" * 78,
        f"  {'Name':<42} {'Type':<7} {'Res':<7} {'Codec':<6} {'Seeds':>5}",
        "-" * 78,
    ]
    for t in dupes:
        name = (t.get('name') or '')[:42]
        type_name = (t.get('type') or {}).get('name', '?') if isinstance(t.get('type'), dict) else str(t.get('type', '?'))
        resolution = (t.get('resolution') or {}).get('name', '?') if isinstance(t.get('resolution'), dict) else str(t.get('resolution', '?'))
        codec = (t.get('video_codec') or {}).get('name', '?') if isinstance(t.get('video_codec'), dict) else str(t.get('video_codec', '?'))
        seeders = t.get('seeders', '?')
        lines.append(f"  {name:<42} {type_name:<7} {resolution:<7} {codec:<6} {str(seeders):>5}")
    lines.append("=" * 78)
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
    catbox_hash = settings.get('CATBOX_HASH')
    seeding_dir = settings.get('SEEDING_DIR')
    
    if ptpimg_api == '': ptpimg_api = None
    if catbox_hash == '': catbox_hash = None
    # --- END Settings Section ---

    if not arg.skipMICheck:
        ensure_mediainfo_cli()

    path = arg.path
    isFolder = FileOrFolder(path)

    if isFolder not in [1, 2]:
        logging.error("Input not a file or directory")
        sys.exit()

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
            has_screenshots = (os.path.isdir(prev_ss_dir) and
                               any(f.endswith('.png') for f in os.listdir(prev_ss_dir)))

            prev_desc_path = os.path.join(prev_run, "showDesc.txt")
            if os.path.exists(prev_desc_path):
                try:
                    with open(prev_desc_path, encoding='utf-8') as _df:
                        has_links = '[img]' in _df.read()
                except OSError:
                    pass

            available = [n for n, v in [("torrent file", has_torrent),
                                         ("screenshots", has_screenshots),
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
        else:
            logging.warning("Could not detect release group from filename.")
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
        if source:
            logging.info(f"Auto-detected source: '{source}'")
        else:
            logging.warning("Could not auto-detect source from filename.")
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

    try:
        torrentFileName = media_file.generate_name(source=source, group=group, huno_format=True, is_season_pack=is_season_pack)
    except RuntimeError as e:
        logging.error(e)
        sys.exit(1)
    
    if arg.edition:
        base, ext = os.path.splitext(torrentFileName)
        torrentFileName = f"{base} ({arg.edition}){ext}"
    if "repack" in path.lower() or 'v2' in path.lower():
        base, ext = os.path.splitext(torrentFileName)
        torrentFileName = f"{base} [REPACK]{ext}"
    
    torrentFileName = re.sub(r'[<>:"/\\|?*\x00-\x1F\x7F]', "", torrentFileName)
    torrentFileName = re.sub(r'\.(mkv|mp4|avi|ts|m2ts)$', '', torrentFileName, flags=re.IGNORECASE)
    torrentFileName += ".torrent"
    logging.info("Final name: " + torrentFileName)

    # --- Create mediainfo dump ---
    _prev_mi = os.path.join(prev_run, "mediainfo.txt") if prev_run else None
    if reusing and _prev_mi and os.path.exists(_prev_mi):
        shutil.copy2(_prev_mi, os.path.join(runDir, "mediainfo.txt"))
        logging.info("Reusing mediainfo from previous run.")
    else:
        getInfoDump(videoFile, runDir)

    # --- Screenshot and Upload Logic ---
    screenshot_success = False
    if reusing and has_screenshots:
        shutil.copytree(os.path.join(prev_run, "screenshots"), os.path.join(runDir, "screenshots"))
        logging.info(f"Reusing screenshots from {os.path.relpath(prev_run)}.")
        screenshot_success = True
    else:
        logging.info("Making screenshots...")
        screenshot_success = create_optimized_screenshots(videoFile, runDir)
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
            catbox_hash=catbox_hash
        )
        if bbcodes:
            with open(os.path.join(runDir, "showDesc.txt"), "w", encoding='utf-8') as desc_file:
                for bbcode in bbcodes:
                    desc_file.write(f"[center]{bbcode}[/center]\n")
            logging.info(f"Success: BBCode written to showDesc.txt ({len(bbcodes)} images)")

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
        if resolution not in RESOLUTION_ID_MAP:
            accepted = ", ".join(sorted(RESOLUTION_ID_MAP.keys()))
            logging.error(
                f"Resolution '{resolution}' is not supported by HUNO and cannot be uploaded. "
                f"Accepted HUNO resolutions: {accepted}"
            )
            sys.exit(1)
        resolution_id = RESOLUTION_ID_MAP[resolution]

        source_type_id = _resolve_source_type_id(source)

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

        generate_bbcode(media_file.tmdb_id, media_file.metadata.get('overview', ''), runDir, tmdb_api, arg.movie, arg.notes)

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
        if arg.edition:
            data['edition'] = arg.edition

        if not arg.movie:
            season_val = media_file.guessit_info.get("season", 0)
            data["season_number"] = int(re.sub(r'\D', '', str(season_val))) if season_val else 0
            if arg.episode:
                episode_val = media_file.guessit_info.get("episode", 0)
                data["episode_number"] = int(re.sub(r'\D', '', str(episode_val))) if episode_val else 0

        print_huno_payload_preview(data, torrentFileName, source)

        logging.info("Checking HUNO for existing releases...")
        dupes = search_huno_dupes(int(media_file.tmdb_id), 1 if arg.movie else 2, huno_api)
        if dupes:
            print_huno_dupes(dupes)
            print(f"\n  {len(dupes)} existing release(s) found for this title on HUNO.")
        else:
            print("\n  No existing releases found on HUNO for this title.")

        if arg.skipPrompt or getUserInput("Do you want to upload this to HUNO?"):
            desc_path = os.path.join(runDir, "showDesc.txt")
            mediainfo_path = os.path.join(runDir, "mediainfo.txt")
            torrent_path = os.path.join(runDir, torrentFileName)
            headers = {"Authorization": f"Bearer {huno_api}", "Accept": "application/json"}
            try:
                with open(desc_path, 'rb') as desc_f, \
                     open(mediainfo_path, 'rb') as mi_f, \
                     open(torrent_path, 'rb') as torrent_f:
                    files = {
                        'torrent': (torrentFileName, torrent_f, 'application/x-bittorrent'),
                        'description': ('description.txt', desc_f, 'text/plain'),
                        'mediainfo': ('mediainfo.txt', mi_f, 'text/plain'),
                    }
                    response = requests.post(
                        url=HUNO_API_URL,
                        headers=headers,
                        data=data,
                        files=files,
                        timeout=60,
                    )
                if response.status_code == 409:
                    result = response.json()
                    logging.warning(f"HUNO upload rejected — duplicate content: {result.get('message')}")
                    logging.warning(f"Details: {result.get('data')}")
                elif response.status_code == 422:
                    result = response.json()
                    logging.error(f"HUNO upload rejected — attribute mismatch: {result.get('message')}")
                    logging.error(f"Details: {result.get('data')}")
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

def generate_bbcode(tmdb_id, mediaDesc, runDir, api_key, isMovie, notes=None):
    prominent_color = get_prominent_color(tmdb_id, api_key, runDir, isMovie)
    hex_color = f"#{prominent_color[0]:02x}{prominent_color[1]:02x}{prominent_color[2]:02x}"
    bbcode = f'[color={hex_color}][center][b]Description[/b][/center][/color]\n' \
             f'[center][quote]{mediaDesc}[/quote][/center]\n\n'
    if notes:
        bbcode += f'[color={hex_color}][center][b]Notes[/b][/center][/color]\n' \
                  f'[center]{notes}[/center]\n\n'
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

def create_optimized_screenshots(videoFile, runDir):
    logging.info("Making optimized screenshots...")
    screenshots_dir = os.path.join(runDir, "screenshots")
    if not os.path.isdir(screenshots_dir):
        os.mkdir(screenshots_dir)

    video = cv2.VideoCapture(videoFile)
    if not video.isOpened():
        logging.error(f"Could not open video file: {videoFile}")
        return False

    total_duration = int(video.get(cv2.CAP_PROP_FRAME_COUNT)) / int(video.get(cv2.CAP_PROP_FPS))
    timestamps = [i * total_duration / 10 for i in range(1, 9)] # 8 screenshots
    successful_screenshots = 0

    for i, timestamp in enumerate(timestamps):
        video.set(cv2.CAP_PROP_POS_MSEC, timestamp * 1000)
        success, image = video.read()
        if success:
            temp_png = os.path.join(screenshots_dir, f"temp_{i:02d}.png")
            cv2.imwrite(temp_png, image)
            final_path = os.path.join(screenshots_dir, f"screenshot_{i:02d}.png")
            optimize_screenshot(temp_png, final_path)
            os.remove(temp_png)
            successful_screenshots += 1
            logging.info(f"Screenshot {i+1}/{len(timestamps)} created.")
        else:
            logging.warning(f"Failed to create screenshot at timestamp {timestamp:.2f}s")
            
    video.release()
    expected = len(timestamps)
    if successful_screenshots < expected:
        logging.error(
            f"Only {successful_screenshots} of {expected} screenshots were created successfully. "
            f"All {expected} are required."
        )
        return False
    logging.info(f"Created {successful_screenshots} optimized screenshots")
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

def upload_single_screenshot(image_path, imgbb_api, ptpimg_api, catbox_hash):
    image_name = os.path.basename(image_path)
    logging.info(f"Uploading {image_name}...")

    # --- Attempt 1: PTPImg (if API key is provided) ---
    if ptpimg_api:
        image_url = uploadToPTPIMG(image_path, ptpimg_api)
        if image_url:
            logging.info(f"Success: Successfully uploaded {image_name} to PTPImg.")
            return f"[url={image_url}][img]{image_url}[/img][/url]"
    
    # --- Attempt 2: ImgBB (if API key is provided) ---
    if imgbb_api:
        image_url, _ = upload_to_imgbb(image_path, imgbb_api) # We only need the direct URL
        if image_url:
            logging.info(f"Success: Successfully uploaded {image_name} to ImgBB.")
            return f"[url={image_url}][img]{image_url}[/img][/url]"

    # --- Attempt 3: Catbox (fallback) ---
    image_url = upload_to_catbox(image_path, catbox_hash)
    if image_url:
        logging.info(f"Success: Successfully uploaded {image_name} to Catbox.")
        return f"[url={image_url}][img]{image_url}[/img][/url]"

    logging.error(f"Failure: All upload methods failed for {image_name}.")
    return None

def upload_screenshots_concurrently(screenshot_dir, imgbb_api, ptpimg_api, catbox_hash, max_workers=5):
    images = sorted([f for f in os.listdir(screenshot_dir) if f.lower().endswith('.png')])
    if not images:
        logging.warning("No screenshots found to upload!")
        return []
    
    image_paths = [os.path.join(screenshot_dir, img) for img in images]
    bbcodes = [None] * len(images)

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_index = {executor.submit(upload_single_screenshot, path, imgbb_api, ptpimg_api, catbox_hash): i for i, path in enumerate(image_paths)}
        for future in as_completed(future_to_index):
            index = future_to_index[future]
            try:
                result = future.result(timeout=120)
                if result:
                    bbcodes[index] = result
            except Exception as e:
                logging.error(f"Upload task failed for {image_paths[index]}: {e}")
    
    successful_uploads = [b for b in bbcodes if b]
    logging.info(f"Success: Successfully uploaded {len(successful_uploads)} out of {len(images)} screenshots")
    return successful_uploads

if __name__ == "__main__":
    main()
