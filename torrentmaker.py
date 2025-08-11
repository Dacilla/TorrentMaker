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

from pprint import pprint, pformat
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
    upload_to_imgbb, upload_to_catbox
)

__VERSION = "1.0.0"
LOG_FORMAT = "%(asctime)s.%(msecs)03d %(levelname)-8s P%(process)06d.%(module)-12s %(funcName)-16sL%(lineno)04d %(message)s"
LOG_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

# TODO: Add support for providing a torrent hash to skip the hashing process
# TODO: Support anime with MAL ID (HUNO API Doesn't support MAL atm)
# TODO: Add detection of bluray extras
# TODO: Download Mediainfo if it's not found
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
        default=True,
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
        if not os.path.isdir("Mediainfo"):
            os.mkdir("Mediainfo")
        # Iterate through all the files in the root folder and its subfolders
        mediainfoExists = False
        for root, dirs, files in os.walk("Mediainfo"):
            for file in files:
                if file.lower == "mediainfo.exe":
                    mediainfoExists = True
                    logging.info("Mediainfo CLI found!")
                    break
            if mediainfoExists:
                break
        if not mediainfoExists:
            logging.info("Mediainfo CLI not found. Downloading...")
            downloadMediainfo()

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
    if not os.path.isdir(runDir + "screenshots"):
        os.mkdir(runDir + "screenshots")
    else:
        data = os.listdir(runDir + "screenshots")
        for i in data:
            os.remove(runDir + "screenshots" + os.sep + i)

    video = cv2.VideoCapture(videoFile)
    # Get the total duration of the video in seconds
    total_duration = int(video.get(cv2.CAP_PROP_FRAME_COUNT)) / int(video.get(cv2.CAP_PROP_FPS))

    # Define the timestamps for the screenshots
    timestamps = [i * total_duration / 10 for i in range(10)]
    # remove the first and last items from the list so we don't get totally black screenshots and/or screenshots of the first and last frames
    timestamps.pop(0)
    timestamps.pop(-1)

    # Iterate over the timestamps and create a screenshot at each timestamp
    for timestamp in timestamps:
        while True:
            # Set the video position to the timestamp
            video.set(cv2.CAP_PROP_POS_MSEC, timestamp * 1000)
            # Read the frame at the current position
            success, image = video.read()
            if success:
                # Save the image to a temporary file
                temp_image_path = runDir + f"screenshots{os.sep}" + "temp_screenshot.png"
                cv2.imwrite(temp_image_path, image)

                # Check the size of the image
                image_size_kb = os.path.getsize(temp_image_path) / 1024

                if image_size_kb < 100:
                    # Delete the small image
                    os.remove(temp_image_path)
                    # Move the timestamp one second along
                    timestamp += 1
                else:
                    # Save the image with the correct filename
                    os.rename(temp_image_path, runDir + f"screenshots{os.sep}" + "screenshot_{}.png".format(timestamp))
                    logging.info(f"Screenshot made at {runDir}screenshots{os.sep}" + "screenshot_{}.png".format(timestamp))
                    break  # Break the loop if the image is of sufficient size
            else:
                break  # Break the loop if we can't read the frame

    video.release()
    if arg.upload:
        if (arg.throttle and arg.upload):
            if qbit_username != "" and qbit_password != "":
                logging.info("Attempting to enable qbit upload speed limit")
                logging.info("Logging in to qbit...")
                try:
                    qb = qbittorrentapi.Client(qbit_host, username=qbit_username, password=qbit_password, REQUESTS_ARGS={'timeout': (60, 60)})
                    transfer_info = qb.transfer_info()
                    uniqueUploadLimit = random.randint(900000, 1000000)
                    if qb.transfer_upload_limit() == 0:
                        qb.transfer_set_upload_limit(limit=uniqueUploadLimit)
                        uploadLimitEnabled = True
                        uniqueUploadLimit = qb.transfer_upload_limit()
                        logging.info("Qbit upload limit set to 1MB/s. Will disable once screenshots have been uploaded.")
                    elif 900000 <= qb.transfer_upload_limit() <= 1000000:
                        logging.info("Another instance of this script has already changed the upload limit. Overwriting...")
                        qb.transfer_set_upload_limit(limit=uniqueUploadLimit)
                        uploadLimitEnabled = True
                        uniqueUploadLimit = qb.transfer_upload_limit()
                        logging.info("Qbit upload limit set to 1MB/s. Will disable once screenshots have been uploaded.")
                    else:
                        logging.info("Qbit upload limit already exists. Continuing...")
                        uploadLimitEnabled = False
                except qbittorrentapi.APIConnectionError:
                    logging.error("Failed to connect to Qbit API. Continuing anyway...")
        logging.info("Uploading screenshots to imgbb")
        images = os.listdir(f"{runDir}screenshots{os.sep}")
        logging.info("Screenshots loaded...")
        imgbb_brokey = False
        ptpimg_brokey = False
        for image in images:
            logging.info(f"Uploading {image}")
            image_url = None
            # Open the file and read the data
            filePath = runDir + "screenshots" + os.sep + image
            if not imgbb_brokey:
                image_url, image_url_viewer = upload_to_imgbb(file_path=filePath, apiKey=imgbb_api)
                if image_url is None or image_url_viewer is None:
                    imgbb_brokey = True
            if ptpimg_api and not ptpimg_brokey:
                logging.info("PTPImg API exists. Attempting to upload there...")
                image_url = uploadToPTPIMG(filePath, ptpimg_api)
                if not image_url:
                    ptpimg_brokey = True
            if ptpimg_brokey and imgbb_brokey:
                logging.info("Attempting to upload to catbox...")
                image_url = upload_to_catbox(file_path=filePath, user_hash=catbox_hash)
                if not image_url:
                    logging.error("Uploading to catbox failed. Exiting..")
                    exit(-1)
            logging.debug(image_url)
            try:
                if not imgbb_brokey:
                    # Print the image URL
                    # Template: [url=https://ibb.co/0fbvMqH][img]https://i.ibb.co/0fbvMqH/screenshot-785-895652173913.png[/img][/url]
                    bbcode = f"[url={image_url_viewer}][img]{image_url}[/img][/url]"
                else:
                    bbcode = f"[url={image_url}][img]{image_url}[/img][/url]"
                with open(runDir + "showDesc.txt", "a") as fileAdd:
                    fileAdd.write("[center]" + bbcode + "[/center]\n")
                logging.info(f"bbcode for image URL {image_url} added to showDesc.txt")
            except Exception as e:
                logging.critical("Unexpected Exception: " + str(e))
                continue
        if arg.throttle:
            logging.info("Attempting to disable qbit upload speed limit")
            logging.info("Logging in to qbit...")
            try:
                qb = qbittorrentapi.Client(qbit_host, username=qbit_username, password=qbit_password, REQUESTS_ARGS={'timeout': (60, 60)})
                transfer_info = qb.transfer_info()
                logging.info("Qbit upload limit: " + str(qb.transfer_upload_limit()))
                logging.info("Comparing to: " + str(uniqueUploadLimit))
                if qb.transfer_upload_limit() == uniqueUploadLimit:
                    qb.transfer_set_upload_limit(limit=0)
                    uploadLimitEnabled = False
                    logging.info("Qbit upload limit successfully disabled.")
                else:
                    logging.info("Qbit upload limit has already been changed. Continuing...")
                    uploadLimitEnabled = True
            except qbittorrentapi.APIConnectionError:
                logging.error("Failed to connect to Qbit API. Continuing anyway...")
            except UnboundLocalError:
                logging.error("Failed to find uniqueUploadLimit. Continuing anyway...")

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

def downloadMediainfo():
    url = "https://mediaarea.net/download/binary/mediainfo/22.12/MediaInfo_CLI_22.12_Windows_x64.zip"
    destination_folder = "Mediainfo"
    if not os.path.exists(destination_folder):
        os.makedirs(destination_folder)
    response = requests.get(url)
    open("MediaInfo_CLI_22.12_Windows_x64.zip", "wb").write(response.content)
    logging.info("MediaInfo_CLI_22.12_Windows_x64.zip downloaded. Unpacking in to ./Mediainfo/")
    with zipfile.ZipFile("MediaInfo_CLI_22.12_Windows_x64.zip", "r") as zip_ref:
        zip_ref.extractall(destination_folder)
    os.remove("MediaInfo_CLI_22.12_Windows_x64.zip")

if __name__ == "__main__":
    main()
