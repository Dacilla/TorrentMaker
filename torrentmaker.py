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
    convert_sha1_hash, ensure_mediainfo_cli, upload_to_catbox
)
from torrent_utils.media import Movie, TVShow # <-- Import our new classes

__VERSION = "2.1.1" # Incremented version for the fix
LOG_FORMAT = "%(asctime)s.%(msecs)03d %(levelname)-8s P%(process)06d.%(module)-12s %(funcName)-16sL%(lineno)04d %(message)s"
LOG_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

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
        "--aither",
        action="store_true",
        default=False,
        help="Enable to upload torrent to Aither, using api key found in settings.ini"
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
        required_settings.extend(['HUNO_API', 'HUNO_URL'])
    if arg.inject or arg.throttle:
        required_settings.extend(['QBIT_HOST', 'QBIT_USERNAME', 'QBIT_PASSWORD'])
    if arg.hardlink or (arg.huno and arg.inject):
        required_settings.append('SEEDING_DIR')

    validate_settings(settings, required_settings)
    
    # Assign settings to variables
    huno_api = settings.get('HUNO_API')
    tmdb_api = settings.get('TMDB_API')
    imgbb_api = settings.get('IMGBB_API')
    qbit_username = settings.get('QBIT_USERNAME')
    qbit_password = settings.get('QBIT_PASSWORD')
    qbit_host = settings.get('QBIT_HOST')
    huno_url = settings.get('HUNO_URL')
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

    # --- Create Run Directory ---
    if not os.path.isdir("runs"): os.makedirs("runs/001")
    run_dirs = [d for d in os.listdir("runs") if d.isdigit()]
    next_run_num = max([int(d) for d in run_dirs]) + 1 if run_dirs else 1
    runDir = os.path.join("runs", str(next_run_num).zfill(3))
    os.makedirs(runDir)
    logging.info(f"Created folder for output in {os.path.relpath(runDir)}")
    
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
    group = arg.group or media_file.guessit_info.get('release_group', 'NOGRP')
    if isinstance(group, list): group = group[0]
    group = re.sub(r"[\[\]\(\)\{\}]", " ", group).split()[0]
    
    source = arg.source or ""
    if source.lower() == 'blu-ray': source = 'BluRay'

    torrentFileName = media_file.generate_name(source=source, group=group, huno_format=True)
    
    if arg.edition:
        base, ext = os.path.splitext(torrentFileName)
        torrentFileName = f"{base} ({arg.edition}){ext}"
    if "repack" in path.lower() or 'v2' in path.lower():
        base, ext = os.path.splitext(torrentFileName)
        torrentFileName = f"{base} [REPACK]{ext}"
    
    torrentFileName = re.sub(r'[<>:"/\\|?*\x00-\x1F\x7F]', "", torrentFileName)
    logging.info("Final name: " + torrentFileName)

    # --- Create mediainfo dump ---
    getInfoDump(videoFile, runDir)
    
    # --- Screenshot and Upload Logic ---
    logging.info("Making screenshots...")
    screenshot_success = create_optimized_screenshots(videoFile, runDir)
    if not screenshot_success:
        logging.error("Failed to create screenshots. Continuing without uploads...")
        arg.upload = False

    if arg.upload and screenshot_success:
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
            logging.info(f"✓ BBCode written to showDesc.txt ({len(bbcodes)} images)")

    # --- Create Torrent File ---
    logging.info("Creating torrent file")
    torrent = torf.Torrent()
    torrent.private = True
    torrent.source = "HUNO"
    torrent.path = path
    torrent.trackers.append(huno_url)

    postName = os.path.splitext(torrentFileName)[0]
    if (arg.huno and arg.inject) or arg.hardlink:
        if os.path.dirname(path) != seeding_dir:
            logging.info("Attempting to create hardlinks for easy seeding...")
            destination = os.path.join(seeding_dir, postName)
            copy_folder_structure(path, destination)
            logging.info(f"Hardlinks created at {destination}")
            torrent.path = destination

    logging.info("Generating torrent file hash. This will take a long while...")
    torrent.generate(callback=cb, interval=0.25)
    torrent.write(os.path.join(runDir, torrentFileName))
    logging.info(f"Torrent file wrote to {torrentFileName}")
    
    # --- HUNO Upload Logic (Now using media_file object) ---
    if arg.huno:
        logging.info("Preparing HUNO upload...")
        
        videoCodec = media_file.get_video_codec(source)
        resolution = media_file.get_resolution()
        
        type_id = 3 # Default to Encode
        if videoCodec == "x265": type_id = 15
        elif "remux" in source.lower(): type_id = 2

        resolution_map = {"4320p": 1, "2160p": 2, "1080p": 3, "1080i": 4, "720p": 5, "576p": 6, "576i": 7, "480p": 8, "480i": 9}
        resolution_id = resolution_map.get(resolution, 10) # Default to Other

        IMDB_ID = media_file.metadata.get("imdb_id", "0")
        TVDB_ID = 0
        if not arg.movie:
            try:
                external_ids_url = f'https://api.themoviedb.org/3/tv/{media_file.tmdb_id}/external_ids?api_key={tmdb_api}'
                response = requests.get(external_ids_url)
                response.raise_for_status()
                external_ids = response.json()
                IMDB_ID = external_ids.get("imdb_id", "0")
                TVDB_ID = external_ids.get("tvdb_id", 0)
            except requests.RequestException as e:
                logging.warning(f"Could not fetch external IDs: {e}")

        media_description = media_file.metadata.get('overview', '')
        description = generate_bbcode(media_file.tmdb_id, media_description, runDir, tmdb_api, arg.movie, arg.notes)
        
        with open(os.path.join(runDir, "mediainfo.txt"), "r", encoding='UTF-8') as infoFile:
            mediaInfoDump = infoFile.read()

        data = {
            'season_pack': 0 if (isFolder == 1 or arg.movie or arg.episode) else 1,
            'stream': 1 if "DD" in media_file.get_audio_info() or "AAC" in media_file.get_audio_info() else 0,
            'anonymous': 0, 'internal': 0,
            'category_id': 1 if arg.movie else 2,
            'type_id': type_id,
            'resolution_id': resolution_id,
            'tmdb': int(media_file.tmdb_id),
            'imdb': re.sub(r'\D', '', IMDB_ID or "0"),
            'tvdb': TVDB_ID or 0,
            'description': description,
            'mediainfo': mediaInfoDump,
            'name': postName,
        }
        
        if not arg.movie:
            data["season"] = int(re.sub(r'\D', '', media_file.guessit_info.get("season", "0")))
            if arg.episode:
                data["episode"] = int(re.sub(r'\D', '', media_file.guessit_info.get("episode", "0")))

        if arg.skipPrompt or getUserInput("Do you want to upload this to HUNO?"):
            url = f"https://hawke.uno/api/torrents/upload?api_token={huno_api}"
            torrent_payload = {'torrent': open(os.path.join(runDir, torrentFileName), 'rb')}
            response = requests.post(url=url, data=data, files=torrent_payload)
            logging.info(f"HUNO Upload Status: {response.status_code}")
            logging.info(f"HUNO Response: {response.json()}")

    # --- qBitTorrent Injection ---
    if arg.inject:
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
    response = requests.get(f'https://api.themoviedb.org/3/{api_path}/{tmdb_id}?api_key={api_key}')
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
    return dominant_colour

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
            final_path = os.path.join(screenshots_dir, f"screenshot_{i:02d}.jpg")
            optimize_screenshot(temp_png, final_path)
            os.remove(temp_png)
            successful_screenshots += 1
            logging.info(f"Screenshot {i+1}/{len(timestamps)} created.")
        else:
            logging.warning(f"Failed to create screenshot at timestamp {timestamp:.2f}s")
            
    video.release()
    logging.info(f"Created {successful_screenshots} optimized screenshots")
    return successful_screenshots > 0

def optimize_screenshot(input_path, output_path, max_width=1920, quality=85):
    try:
        with Image.open(input_path) as img:
            if img.mode in ('RGBA', 'LA', 'P'): img = img.convert('RGB')
            if img.width > max_width:
                ratio = max_width / img.width
                new_height = int(img.height * ratio)
                img = img.resize((max_width, new_height), Image.Resampling.LANCZOS)
            img.save(output_path, 'JPEG', quality=quality, optimize=True)
    except Exception as e:
        logging.error(f"Failed to optimize screenshot {input_path}: {e}")
        shutil.copy(input_path, output_path)

def upload_single_screenshot(image_path, imgbb_api, ptpimg_api, catbox_hash):
    image_name = os.path.basename(image_path)
    logging.info(f"Uploading {image_name}")
    
    # Try PTPImg first if available
    if ptpimg_api:
        try:
            image_url = uploadToPTPIMG(image_path, ptpimg_api)
            if image_url:
                return f"[url={image_url}][img]{image_url}[/img][/url]"
        except Exception as e:
            logging.warning(f"PTPIMG upload failed for {image_name}: {e}")
    
    # Try Catbox
    try:
        image_url = upload_to_catbox(image_path, catbox_hash)
        if image_url and not image_url.startswith("Upload failed"):
            return f"[url={image_url}][img]{image_url}[/img][/url]"
    except Exception as e:
        logging.error(f"Catbox upload failed for {image_name}: {e}")
    
    logging.error(f"✗ All upload methods failed for {image_name}")
    return None

def upload_screenshots_concurrently(screenshot_dir, imgbb_api, ptpimg_api, catbox_hash, max_workers=5):
    images = sorted([f for f in os.listdir(screenshot_dir) if f.lower().endswith('.jpg')])
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
    logging.info(f"✓ Successfully uploaded {len(successful_uploads)} out of {len(images)} screenshots")
    return successful_uploads

if __name__ == "__main__":
    main()
