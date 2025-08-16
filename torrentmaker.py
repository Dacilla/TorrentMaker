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
    get_tmdb_id, getInfoDump, getUserInput, get_season, get_episode, 
    getResolution, get_audio_info, get_colour_space, get_language_name,
    similarity, has_folders, cb, uploadToPTPIMG, copy_folder_structure, 
    qbitInject, FileOrFolder, is_valid_torf_hash, convert_sha1_hash,
    ensure_mediainfo_cli
)

__VERSION = "1.0.0"
LOG_FORMAT = "%(asctime)s.%(msecs)03d %(levelname)-8s P%(process)06d.%(module)-12s %(funcName)-16sL%(lineno)04d %(message)s"
LOG_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

# TODO: Add support for providing a torrent hash to skip the hashing process
# TODO: Support anime with MAL ID (HUNO API Doesn't support MAL atm)
# TODO: Add detection of bluray extras
# TODO: Add support for more trackers
# TODO: Add documentation to readme
# TODO: Support BD Raw Discs
# TODO: Add AV1 detection
# TODO: Support music
# TODO: Add function to stop multiple instances from reading off the same drive, slowing it down for both

# https://qbittorrent-api.readthedocs.io/en/latest/apidoc/torrents.html#qbittorrentapi.torrents.TorrentDictionary.rename_file

def main():
    parser = argparse.ArgumentParser(
        description="Script to automate creation of torrent files, as well as grabbing mediainfo dump, screenshots, and tmdb description"
    )
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
    # parser.add_argument(
    #     "--mal",
    #     action="store",
    #     type=int,
    #     help="MAL ID for anime",
    #     default=None
    # )
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
    
    # Assign settings to variables to maintain original script structure
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
    
    if ptpimg_api == '':
        ptpimg_api = None
    if catbox_hash == '':
        catbox_hash = None
    # --- END Settings Section ---

    if not arg.skipMICheck:
        ensure_mediainfo_cli()

    path = arg.path
    isFolder = FileOrFolder(path)

    if arg.hash:
        if is_valid_torf_hash(arg.hash):
            torrentHash = convert_sha1_hash(arg.hash)
        else:
            logging.warning("Given hash is not valid. Will regenerate valid hash.")
    else:
        torrentHash = None

    if isFolder not in [1, 2]:
        logging.error("Input not a file or directory")
        sys.exit()
    if not os.path.isdir("runs"):
        os.mkdir("runs")
        os.mkdir(f"runs{os.sep}001")
        runDir = os.getcwd() + os.sep + "runs" + os.sep + "001" + os.sep
    elif not has_folders("runs"):
        os.mkdir(f"runs{os.sep}001")
        runDir = os.getcwd() + os.sep + "runs" + os.sep + "001" + os.sep
    else:
        fileList = os.listdir("runs")
        maxValue = max(int(dirname) for dirname in fileList)
        logging.info("Last run number found: " + str(maxValue))
        # if not delete_if_no_torrent(os.getcwd() + os.sep + "runs" + os.sep + str(maxValue).zfill(3)):
        #     maxValue = maxValue + 1
        #     logging.info("Found directory does not have finished .torrent file. Directory Deleted.")
        maxValue = maxValue + 1
        maxValue = str(maxValue).zfill(3)
        while True:
            try:
                os.mkdir("runs" + os.sep + maxValue)
                break
            except FileExistsError:
                logging.error("Folder exists. Adding one and trying again...")
                maxValue = str(int(maxValue) + 1)
        runDir = os.getcwd() + os.sep + "runs" + os.sep + maxValue + os.sep

    logging.info(f"Created folder for output in {os.path.relpath(runDir)}")
    logging.info(f"Creating mediainfo dump in {runDir}...")
    if isFolder == 1:
        videoFile = path
        file = os.path.basename(path)
        mediaInfoText = getInfoDump(path, runDir)
    elif isFolder == 2:
        # List all files in the folder
        data = os.listdir(path)
        # Sort the files by size descending
        # data.sort(key=lambda f: os.path.getsize(os.path.join(path, f)), reverse=True)
        data.sort()
        # Look for the first video file
        for file in data:
            # Check the file extension
            name, ext = os.path.splitext(file)
            if ext in ['.mp4', '.avi', '.mkv']:
                # Found a video file
                logging.info("Video found: " + file)
                guessItOutput = dict(guessit.guessit(os.path.join(path, file).replace('- ', '')))
                if 'year' in guessItOutput or 'episode' in guessItOutput:
                    videoFile = path + os.sep + file
                    mediaInfoText = getInfoDump(path + os.sep + file, runDir)
                    logging.debug(pformat(json.loads(mediaInfoText)))
                    break
                else:
                    pprint(guessItOutput)
                    answer = getUserInput("Is this file an episode or movie?")
                    if answer:
                        videoFile = path + os.sep + file
                        mediaInfoText = getInfoDump(path + os.sep + file, runDir)
                        logging.debug(pformat(json.loads(mediaInfoText)))
                        break
    logging.info("Mediainfo dump created")
    guessItOutput = dict(guessit.guessit(videoFile.replace('- ', '')))
    logging.info(pformat(guessItOutput))
    if 'release_group' in str(guessItOutput):
        group = guessItOutput['release_group']
        # remove any kinds of brackets from group name
        group = re.sub(r"[\[\]\(\)\{\}]", " ", group)
        group = group.split()[0]
    else:
        group = "NOGRP"
    if arg.tmdb is None and 'title' in str(guessItOutput):
        logging.info("No TMDB ID given. Attempting to find it automatically...")
        if type(guessItOutput['title']) == list:
            title = guessItOutput['title'][0]
        else:
            title = guessItOutput['title']
        if 'country' in guessItOutput:
            title = title + f" {guessItOutput['country'].alpha2}"
        # if 'year' in guessItOutput and guessItOutput['type'] == 'movie':
        #     title = title + f" {guessItOutput['year']}"
        tmdbID = get_tmdb_id(title, tmdb_api, arg.movie)
        if tmdbID:
            logging.info(f"TMDB ID Found: {tmdbID}")
        else:
            tmdbID = input("Failed to find TMDB ID. Please input:\n")
    else:
        tmdbID = arg.tmdb

    mediaInfoText = mediaInfoText.strip()
    mediaInfoText = json.loads(mediaInfoText)
    mediaDescription = ""
    if tmdbID:
        if tmdb_api == "":
            logging.error("TMDB_API field not filled in settings.ini")
            sys.exit()
        # Get TMDB info
        logging.info("Getting TMDB description")

        # Replace TV_SHOW_ID with the ID of the TV show you want to get the description for
        tv_show_id = tmdbID

        # Build the URL for the API request
        if arg.movie:
            url = f'https://api.themoviedb.org/3/movie/{tv_show_id}?api_key={tmdb_api}'
        else:
            url = f'https://api.themoviedb.org/3/tv/{tv_show_id}?api_key={tmdb_api}'

        # Make the GET request to the TMDb API
        response = requests.get(url)

        # Get the JSON data from the response
        tmdbData = response.json()
        # originalLanguange = response.json()['original_language']
        logging.debug(pformat(tmdbData))
        # Print the description of the TV show
        logging.debug("description gotten: " + tmdbData['overview'])
        mediaDescription = tmdbData['overview']

    logging.info("Making screenshots...")
    # Create optimized screenshots
    screenshot_success = create_optimized_screenshots(videoFile, runDir)
    
    if not screenshot_success:
        logging.error("Failed to create screenshots. Continuing without uploads...")
        arg.upload = False  # Disable upload if no screenshots

    # Handle screenshot uploads
    if arg.upload and screenshot_success:
        # Set up qBittorrent throttling if requested
        upload_limit_enabled = False
        unique_upload_limit = None
        
        if arg.throttle and qbit_username and qbit_password:
            logging.info("Setting up qBittorrent upload throttling...")
            try:
                qb = qbittorrentapi.Client(qbit_host, username=qbit_username, password=qbit_password, 
                                         REQUESTS_ARGS={'timeout': (60, 60)})
                
                import random
                unique_upload_limit = random.randint(900000, 1000000)
                current_limit = qb.transfer_upload_limit()
                
                if current_limit == 0:
                    qb.transfer_set_upload_limit(limit=unique_upload_limit)
                    upload_limit_enabled = True
                    logging.info("qBit upload limit set to ~1MB/s during screenshot upload")
                elif 900000 <= current_limit <= 1000000:
                    logging.info("Another instance detected. Overwriting upload limit...")
                    qb.transfer_set_upload_limit(limit=unique_upload_limit)
                    upload_limit_enabled = True
                else:
                    logging.info("qBit upload limit already exists. Continuing...")
                    upload_limit_enabled = False
                    
            except Exception as e:
                logging.warning(f"Failed to set qBit throttling: {e}")
                upload_limit_enabled = False

        # Upload screenshots concurrently
        logging.info("Starting concurrent screenshot upload...")
        start_time = time.time()
        
        bbcodes = upload_screenshots_concurrently(
            screenshot_dir=os.path.join(runDir, "screenshots"),
            imgbb_api=imgbb_api,
            ptpimg_api=ptpimg_api,
            catbox_hash=catbox_hash,
            max_workers=5  # Adjust this based on your connection speed
        )
        
        upload_time = time.time() - start_time
        logging.info(f"Screenshot upload completed in {upload_time:.1f} seconds")
        
        # Write BBCodes to file
        if bbcodes:
            with open(os.path.join(runDir, "showDesc.txt"), "w", encoding='utf-8') as desc_file:
                for bbcode in bbcodes:
                    desc_file.write(f"[center]{bbcode}[/center]\n")
            logging.info(f"✓ BBCode written to showDesc.txt ({len(bbcodes)} images)")
        else:
            logging.warning("No screenshots were successfully uploaded!")
        
        # Disable qBittorrent throttling
        if upload_limit_enabled and arg.throttle:
            try:
                qb = qbittorrentapi.Client(qbit_host, username=qbit_username, password=qbit_password,
                                         REQUESTS_ARGS={'timeout': (60, 60)})
                
                if qb.transfer_upload_limit() == unique_upload_limit:
                    qb.transfer_set_upload_limit(limit=0)
                    logging.info("✓ qBit upload limit disabled")
                else:
                    logging.info("Upload limit was changed externally, leaving as-is")
                    
            except Exception as e:
                logging.warning(f"Failed to disable qBit throttling: {e}")

    logging.info("Creating torrent file")
    torrent = torf.Torrent()
    torrent.private = True
    torrent.source = "HUNO"
    torrent.path = path
    torrent.trackers = huno_url
    torrentFileName = "generatedTorrent.torrent"
    if torrentHash:
        torrent.hashes = torrentHash
    if tmdbID:
        # Create torrent file name from TMDB and Mediainfo
        # Template:
        # TV: ShowName (Year) S00 (1080p BluRay x265 SDR DD 5.1 Language - Group) [REPACK]
        # MOVIE: ShowName (Year) EDITION (1080p BluRay x265 SDR DD 5.1 Language - Group) [REPACK]
        # pprint(mediaInfoText)
        if arg.movie:
            showName: str = tmdbData['title']
        else:
            showName: str = tmdbData['name']
        showName = showName.replace(":", " -")
        logging.info("Name: " + str(showName))
        if arg.movie:
            dateString = tmdbData['release_date']
        else:
            dateString = tmdbData['first_air_date']
        date = datetime.strptime(dateString, "%Y-%m-%d")
        year = str(date.year)
        logging.info("Year: " + year)
        logging.debug(file)
        if not arg.movie:
            # if isFolder == 2:
            #     episodeNum = check_folder_for_episode(file)
            # else:
            #     filename = os.path.basename(file)
            #     episodeNum = re.compile(r'S\d{2}E\d{2}').search(filename)
            #     if match:
            #         season = episodeNum.g
            season = get_season(file)
            logging.info("Season: " + season)
        if arg.episode:
            episode = "E" + get_episode(file)
            logging.info("Episode: " + episode)
        # Detect resolution
        acceptedResolutions = "2160p|1080p|720p"
        match = re.search(acceptedResolutions, file)
        if match:
            resolution = match.group()
        else:
            width = mediaInfoText['media']['track'][1]['Width']
            height = mediaInfoText['media']['track'][1]['Height']
            try:
                frameRate = mediaInfoText['media']['track'][1]['FrameRate']
            except Exception:
                frameRate = mediaInfoText['media']['track'][1]['FrameRate_Original']
            resolution = getResolution(width=width, height=height, frameRate=frameRate)
        if "Interlaced" in str(mediaInfoText):
            resolution = resolution.replace("p", "i")
        logging.info("Resolution: " + resolution)
        # Detect if file is HDR
        colourSpace = get_colour_space(mediaInfoText)
        logging.info("Colour Space: " + colourSpace)
        # Detect video codec
        if 'HEVC' in mediaInfoText['media']['track'][1]['Format']:
            if 'remux' in file.lower().replace('.', ''):
                videoCodec = 'HEVC'
            elif ('h265' in file.lower().replace('.', '') or ('hevc' in file.lower().replace('.', '') and 'x265' not in os.path.join(path, file).lower().replace('.', ''))) and 'BluRay' not in arg.source:
                videoCodec = 'H265'
            else:
                videoCodec = "x265"
        elif "VC-1" in mediaInfoText['media']['track'][1]['Format']:
            videoCodec = "VC-1"
        elif "V_MPEG2" in mediaInfoText['media']['track'][1]['CodecID']:
            videoCodec = "MPEG-2"
        elif 'remux' in file.lower() or 'remux' in arg.source.lower():
            videoCodec = "AVC"
        elif 'x264' in file.lower() and 'WEB-DL' not in arg.source:
            videoCodec = "x264"
        else:
            videoCodec = "H264"
        logging.info("Video Codec: " + videoCodec)
        # Detect audio codec
        audio = get_audio_info(mediaInfoText)
        logging.info("Audio: " + audio)
        # Get language
        trackNum = None
        for num, track in enumerate(mediaInfoText['media']['track']):
            if track['@type'] == "Audio":
                trackNum = num
                break
        if 'Language' in mediaInfoText['media']['track'][trackNum]:
            language = get_language_name(mediaInfoText['media']['track'][trackNum]['Language'])
        else:
            language = input("No language found in audio data. Please input language:\n")
        logging.info("Language: " + language)
        # Get source
        if arg.source:
            source = arg.source
        else:
            source = ""
        logging.info("Source: " + source)
        # Get group
        if arg.group:
            group = arg.group

        # Check for banned group
        if 'WEB' in videoCodec:
            if group in bannedEncoders['WEB']:
                logging.info(f"Group '{group}' is banned on HUNO. Cannot upload there")
                if arg.huno:
                    sys.exit()
        if 'remux' in file.lower():
            if group in bannedEncoders['REMUX']:
                logging.info(f"Group '{group}' is banned on HUNO. Cannot upload there")
                if arg.huno:
                    sys.exit()
        if group in bannedEncoders['ENCODE']:
            logging.info(f"Group '{group}' is banned on HUNO. Cannot upload there")
            if arg.huno:
                sys.exit()

        # Get group tag
        for encodeGroup, members in encoderGroups.items():
            if group in members:
                group = group + ' ' + encodeGroup
                logging.info("Group found: " + encodeGroup)
                break

        logging.info("Group: " + group)
        # Get Edition
        if arg.edition:
            edition = " " + arg.edition
        else:
            edition = ""
        # Get if repack
        if "repack" in os.path.join(path, file).lower() or 'v2' in os.path.join(path, file).lower():
            repack = " [REPACK]"
        else:
            repack = ""
        # Get if hybrid
        hybrid = ""
        # if "hybrid" in file.lower():
        #     hybrid = " Hybrid"
        # else:
        #     hybrid = ""
        # Construct torrent name
        if arg.movie:
            torrentFileName = f"{showName} ({year}){edition} ({resolution} {source}{hybrid} {videoCodec} {colourSpace} {audio} {language} - {group}){repack}.torrent"
        elif arg.episode:
            torrentFileName = f"{showName} ({year}) {season}{episode}{edition} ({resolution} {source}{hybrid} {videoCodec} {colourSpace} {audio} {language} - {group}){repack}.torrent"
        else:
            torrentFileName = f"{showName} ({year}) {season}{edition} ({resolution} {source}{hybrid} {videoCodec} {colourSpace} {audio} {language} - {group}){repack}.torrent"

        # Define the regular expression pattern to match invalid characters
        pattern = r'[<>:"/\\|?*\x00-\x1F\x7F]'

        # Use the re.sub() method to remove any invalid characters from the filename
        torrentFileName = re.sub(pattern, "", torrentFileName)

        logging.info("Final name: " + torrentFileName)

        if (arg.huno and arg.inject) or arg.hardlink:
            head, tail = os.path.split(path)
            postName = torrentFileName.replace(".torrent", "")
            if (head != seeding_dir) or arg.hardlink:
                logging.info("Attempting to create hardlinks for easy seeding...")
                destination = os.path.join(seeding_dir, postName)
                copy_folder_structure(path, destination)
                logging.info("Hardlinks created at " + destination)
                torrent.path = destination

    logging.info("Generating torrent file hash. This will take a long while...")
    success = torrent.generate(callback=cb, interval=0.25)
    logging.info("Writing torrent file to disk...")
    torrent.write(runDir + torrentFileName)
    logging.info("Torrent file wrote to " + torrentFileName)

    if arg.huno:
        logging.info("Uploading to HUNO enabled")
        pathresult = FileOrFolder(path)
        if pathresult == 1 or arg.movie or arg.episode:
            season_pack = 0
        else:
            season_pack = 1

        if arg.movie:
            category = 1
        else:
            category = 2

        if videoCodec == "x265":
            type_id = 15
        elif "remux" in source.lower():
            type_id = 2
        else:
            type_id = 3

        match resolution:
            case "4320p":
                resolution_id = 1
            case "2160p":
                resolution_id = 2
            case "1080p":
                resolution_id = 3
            case "1080i":
                resolution_id = 4
            case "720p":
                resolution_id = 5
            case "576p":
                resolution_id = 6
            case "576i":
                resolution_id = 7
            case "480p":
                resolution_id = 8
            case "480i":
                resolution_id = 9
            case _:
                resolution_id = 10

        # Get IMDB ID from TVDB API
        if arg.movie:
            IMDB_ID = tmdbData["imdb_id"]
            TVDB_ID = 0
        else:
            url = f'https://api.themoviedb.org/3/tv/{tv_show_id}/external_ids?api_key={tmdb_api}'
            # Make the GET request to the TMDb API
            response = requests.get(url)

            # Get the JSON data from the response
            tmdbtoIMDDdata = response.json()
            IMDB_ID = tmdbtoIMDDdata['imdb_id']
            TVDB_ID = tmdbtoIMDDdata['tvdb_id']
        # Get description
        try:
            IMDB_ID = re.findall(r'\d+', IMDB_ID)[0]
        except Exception:
            if arg.movie:
                logging.info(f"Failed to find the IMDB ID from '{IMDB_ID}'. Please input just the numbers of the IMDB ID:")
            else:
                logging.info(f"Failed to find the IMDB ID from '{tmdbtoIMDDdata['imdb_id']}'. Please input just the numbers of the IMDB ID:")
            IMDB_ID = input()
        notes = arg.notes
        if os.path.isdir(os.path.join(path, "Featurettes")):
            if notes is not None:
                notes += "\nIncludes featurettes"
            else:
                notes = "Includes featurettes"
        description = generate_bbcode(tmdbID, mediaDescription, runDir, tmdb_api, arg.movie, notes)

        # Get MediaInfo Dump
        with open(runDir + "mediainfo.txt", "r", encoding='UTF-8') as infoFile:
            mediaInfoDump = infoFile.read()

        # Check for stream friendly audio
        streamFriendly = 1
        if trackNum:
            if 'Format' in str(mediaInfoText['media']['track'][trackNum]):
                try:
                    if mediaInfoText['media']['track'][trackNum]['Format'] in ['DTS', 'MLP FBA', 'FLAC', 'PCM']:
                        streamFriendly = 0
                except Exception:
                    logging.error("Unable to find format in audio track")
        else:
            if mediaInfoText['media']['track'][1]['Format'] in ['DTS', 'MLP FBA', 'FLAC', 'PCM']:
                streamFriendly = 0

        # Get post name
        postName = torrentFileName.replace(".torrent", "")
        torrent_file = {'torrent': open(runDir + torrentFileName, 'rb')}
        data = {
            'season_pack': season_pack,
            'stream': streamFriendly,
            'anonymous': 0,
            'internal': 0,
            'category_id': category,
            'type_id': type_id,
            'resolution_id': resolution_id,
            'tmdb': int(tmdbID),
            'imdb': IMDB_ID,
            'tvdb': TVDB_ID,
            'description': f'''{description}''',
            'mediainfo': f'''{mediaInfoDump}''',
            'name': postName,
        }

        # Get the season number
        if not arg.movie:
            seasonNum = int(re.findall(r'\d+', season)[0])
            data["season"] = seasonNum
            if arg.episode:
                seasonNum = int(re.findall(r'\d+', episode)[0])
            else:
                data["episode"] = 0
        # if arg.mal:
        #     data['mal'] = int(arg.mal)
        # pprint(headers)
        print(data)
        print("\n-------------------------\n")
        pprint(data)

        # print(headers)
        if arg.skipPrompt or getUserInput("Do you want to upload this to HUNO?"):
            # Make API requests
            logging.info("HUNO API KEY: " + huno_api)
            url = f"https://hawke.uno/api/torrents/upload?api_token={huno_api}"
            logging.info("API URL: " + url)
            response = requests.post(url=url, data=data, files=torrent_file)
            print(response.status_code)
            print(response.json())

    if arg.inject:
        logging.info("Qbittorrent injection enabled")
        if arg.huno:
            category = "HUNO"
            paused = False
        else:
            category = ""
            paused = True
        postName = torrentFileName.replace(".torrent", "")
        qbitInject(qbit_host=qbit_host, qbit_username=qbit_username, qbit_password=qbit_password, category=category, runDir=runDir, torrentFileName=torrentFileName, paused=paused, postName=postName)

def get_prominent_color(tmdb_id, api_key, directory, isMovie):
    logging.info(f"Fetching poster for TMDB ID: {tmdb_id}")
    if isMovie:
        response = requests.get(f'https://api.themoviedb.org/3/movie/{tmdb_id}?api_key={api_key}')
    else:
        response = requests.get(f'https://api.themoviedb.org/3/tv/{tmdb_id}?api_key={api_key}')
    data = response.json()
    logging.debug(data)
    poster_path = data['poster_path']
    poster_url = f'https://image.tmdb.org/t/p/w500/{poster_path}'
    logging.info(f"Downloading poster from URL: {poster_url}")
    response = requests.get(poster_url, stream=True)
    response.raise_for_status()
    poster_path = os.path.join(directory, 'poster.jpg')
    with open(poster_path, 'wb') as file:
        for chunk in response.iter_content(chunk_size=8192):
            file.write(chunk)
    logging.info("Poster downloaded and saved successfully")
    logging.info("Opening poster...")
    color_thief = ColorThief(poster_path)
    dominant_colour = color_thief.get_color(quality=1)
    return dominant_colour

def generate_bbcode(tmdb_id, mediaDesc, runDir, api_key, isMovie, notes=None):
    prominent_color = get_prominent_color(tmdb_id, api_key, runDir, isMovie)
    bbcode = f'[color=#{prominent_color[0]:02x}{prominent_color[1]:02x}{prominent_color[2]:02x}][center][b]Description[/b][/center][/color]\n' \
             f'[center][quote]{mediaDesc}[/quote][/center]\n\n'
    if notes:
        bbcode += f'[color=#{prominent_color[0]:02x}{prominent_color[1]:02x}{prominent_color[2]:02x}][center][b]Notes[/b][/center][/color]\n' \
                  f'[center]{notes}[/center]\n\n'
    bbcode += f'[color=#{prominent_color[0]:02x}{prominent_color[1]:02x}{prominent_color[2]:02x}][center][b]Screens[/b][/center][/color]\n'
    with open(runDir + "showDesc.txt") as f:
        bbcode += f.read()
    with open(runDir + "showDesc.txt", 'w', encoding='utf-8') as fi:
        fi.write(bbcode)
    logging.info("Final bbcode written to " + runDir + "showDesc.txt")
    return bbcode

def upload_to_imgbb(file_path, apiKey):
    api_endpoint = "https://api.imgbb.com/1/upload"
    logging.info("Uploading " + file_path + " to imgbb...")
    with open(file_path, "rb") as imagefile:
        file_data = imagefile.read()
        # Set the payload for the POST request
        payload = {
            "key": apiKey,
            "image": b64encode(file_data),
        }
        try:
            response = requests.post(api_endpoint, payload)
            # Get the image URL from the response
            if response.status_code != 200:
                logging.warning(pformat(response.json()))
                return None, None
            image_url = response.json()["data"]["url"]
            image_url_viewer = response.json()["data"]["url_viewer"]
            return image_url, image_url_viewer
        except Exception:
            return None, None


def upload_to_catbox(file_path, user_hash=None):
    # Catbox API endpoint for file upload
    url = "https://catbox.moe/user/api.php"

    # Prepare the file to be uploaded
    files = {'fileToUpload': (file_path, open(file_path, 'rb'))}

    # Prepare the request parameters (user hash)
    data = {
        'reqtype': 'fileupload',
    }

    if user_hash:
        data['userhash']: user_hash

    try:
        # Send the POST request to Catbox API
        response = requests.post(url, data=data, files=files)

        # Check if the upload was successful and return the direct link
        if response.status_code == 200:
            direct_link = str(response.content.decode())
            return direct_link
        else:
            # If upload failed, return an error message or handle the error accordingly
            error_message = str(response.content)
            return f"Upload failed: {error_message}"

    except Exception as e:
        logging.error(f"Error occurred: {e}\nResponse data: {response.content}")
        return None

def optimize_screenshot(input_path, output_path=None, max_width=1920, quality=85):
    """
    Optimize screenshot for faster upload while maintaining good quality
    """
    if output_path is None:
        output_path = input_path
        
    try:
        with Image.open(input_path) as img:
            # Convert to RGB if necessary (some screenshots might be RGBA)
            if img.mode in ('RGBA', 'LA', 'P'):
                img = img.convert('RGB')
            
            # Resize if too large
            if img.width > max_width:
                ratio = max_width / img.width
                new_height = int(img.height * ratio)
                img = img.resize((max_width, new_height), Image.Resampling.LANCZOS)
                logging.info(f"Resized screenshot from {img.width}x{img.height} to {max_width}x{new_height}")
            
            # Save with optimized settings
            img.save(output_path, 'JPEG', quality=quality, optimize=True)
            
        return output_path
    except Exception as e:
        logging.error(f"Failed to optimize screenshot {input_path}: {e}")
        return input_path  # Return original if optimization fails

def upload_single_screenshot(image_path, imgbb_api, ptpimg_api, catbox_hash):
    """Upload a single screenshot and return the bbcode"""
    image_name = os.path.basename(image_path)
    logging.info(f"Uploading {image_name}")
    
    # Try imgbb first
    if imgbb_api:
        try:
            image_url, image_url_viewer = upload_to_imgbb(image_path, imgbb_api)
            if image_url and image_url_viewer:
                bbcode = f"[url={image_url_viewer}][img]{image_url}[/img][/url]"
                logging.info(f"✓ Successfully uploaded {image_name} to imgbb")
                return bbcode
        except Exception as e:
            logging.warning(f"ImgBB upload failed for {image_name}: {e}")
    
    # Try ptpimg if imgbb failed or unavailable
    if ptpimg_api:
        try:
            image_url = uploadToPTPIMG(image_path, ptpimg_api)
            if image_url:
                bbcode = f"[url={image_url}][img]{image_url}[/img][/url]"
                logging.info(f"✓ Successfully uploaded {image_name} to ptpimg")
                return bbcode
        except Exception as e:
            logging.warning(f"PTPIMG upload failed for {image_name}: {e}")
    
    # Try catbox as last resort
    try:
        image_url = upload_to_catbox(image_path, catbox_hash)
        if image_url and not image_url.startswith("Upload failed"):
            bbcode = f"[url={image_url}][img]{image_url}[/img][/url]"
            logging.info(f"✓ Successfully uploaded {image_name} to catbox")
            return bbcode
    except Exception as e:
        logging.error(f"Catbox upload failed for {image_name}: {e}")
    
    logging.error(f"✗ All upload methods failed for {image_name}")
    return None

def upload_screenshots_concurrently(screenshot_dir, imgbb_api, ptpimg_api, catbox_hash, max_workers=5):
    """Upload all screenshots concurrently"""
    # Get all image files (both PNG and JPG)
    all_files = os.listdir(screenshot_dir)
    images = [f for f in all_files if f.lower().endswith(('.png', '.jpg', '.jpeg'))]
    images.sort()  # Ensure consistent ordering
    
    if not images:
        logging.warning("No screenshots found to upload!")
        return []
    
    image_paths = [os.path.join(screenshot_dir, img) for img in images]
    
    bbcodes = []
    failed_uploads = []
    
    logging.info(f"Starting concurrent upload of {len(images)} screenshots with {max_workers} workers...")
    
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        # Submit all upload tasks
        future_to_info = {}
        for i, path in enumerate(image_paths):
            future = executor.submit(upload_single_screenshot, path, imgbb_api, ptpimg_api, catbox_hash)
            future_to_info[future] = {'path': path, 'index': i, 'name': os.path.basename(path)}
        
        # Collect results as they complete
        completed = 0
        results = {}  # Store results with their original index to maintain order
        
        for future in as_completed(future_to_info):
            info = future_to_info[future]
            completed += 1
            
            try:
                bbcode = future.result(timeout=120)  # 2 minute timeout per upload
                if bbcode:
                    results[info['index']] = bbcode
                    logging.info(f"Progress: {completed}/{len(images)} - {info['name']} uploaded successfully")
                else:
                    failed_uploads.append(info['path'])
                    logging.warning(f"Progress: {completed}/{len(images)} - {info['name']} failed")
            except Exception as e:
                logging.error(f"Upload task failed for {info['name']}: {e}")
                failed_uploads.append(info['path'])
        
        # Convert results dict to ordered list
        for i in sorted(results.keys()):
            bbcodes.append(results[i])
    
    if failed_uploads:
        logging.warning(f"Failed to upload {len(failed_uploads)} screenshots")
    
    logging.info(f"✓ Successfully uploaded {len(bbcodes)} out of {len(images)} screenshots")
    return bbcodes

def create_optimized_screenshots(videoFile, runDir):
    """
    Create and optimize screenshots for faster upload
    """
    logging.info("Making optimized screenshots...")
    screenshots_dir = os.path.join(runDir, "screenshots")
    
    if not os.path.isdir(screenshots_dir):
        os.mkdir(screenshots_dir)
    else:
        # Clean existing screenshots
        for file in os.listdir(screenshots_dir):
            os.remove(os.path.join(screenshots_dir, file))

    video = cv2.VideoCapture(videoFile)
    
    # Get the total duration of the video in seconds
    total_duration = int(video.get(cv2.CAP_PROP_FRAME_COUNT)) / int(video.get(cv2.CAP_PROP_FPS))

    # Define the timestamps for the screenshots (same as before)
    timestamps = [i * total_duration / 10 for i in range(10)]
    timestamps.pop(0)  # Remove first timestamp
    timestamps.pop(-1)  # Remove last timestamp

    successful_screenshots = 0
    
    for i, timestamp in enumerate(timestamps):
        attempts = 0
        max_attempts = 5
        
        while attempts < max_attempts:
            video.set(cv2.CAP_PROP_POS_MSEC, (timestamp + attempts) * 1000)
            success, image = video.read()
            
            if success:
                # Save as temporary PNG first
                temp_png = os.path.join(screenshots_dir, f"temp_{i:02d}.png")
                cv2.imwrite(temp_png, image)
                
                # Check if image is too small (likely black frame)
                if os.path.getsize(temp_png) / 1024 < 100:
                    os.remove(temp_png)
                    attempts += 1
                    continue
                
                # Optimize and save as JPEG
                final_path = os.path.join(screenshots_dir, f"screenshot_{i:02d}.jpg")
                optimized_path = optimize_screenshot(temp_png, final_path, max_width=1920, quality=85)
                
                # Remove temp PNG
                if os.path.exists(temp_png):
                    os.remove(temp_png)
                
                # Log file size reduction
                original_size = os.path.getsize(temp_png) if os.path.exists(temp_png) else 0
                optimized_size = os.path.getsize(optimized_path)
                
                logging.info(f"Screenshot {i+1}/{len(timestamps)} created: {os.path.basename(optimized_path)} "
                          f"({optimized_size/1024:.1f}KB)")
                successful_screenshots += 1
                break
            else:
                attempts += 1
        
        if attempts >= max_attempts:
            logging.warning(f"Failed to create screenshot {i+1} after {max_attempts} attempts")

    video.release()
    logging.info(f"Created {successful_screenshots} optimized screenshots")
    return successful_screenshots > 0

if __name__ == "__main__":
    main()
