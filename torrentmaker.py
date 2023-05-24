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
import colorsys

from babel import Locale
from pprint import pprint, pformat
from base64 import b64encode
from pymediainfo import MediaInfo
from datetime import datetime
from PIL import Image
from colorthief import ColorThief

from HUNOInfo import bannedEncoders, encoderGroups

__VERSION = "1.0.0"
LOG_FORMAT = "%(asctime)s.%(msecs)03d %(levelname)-8s P%(process)06d.%(module)-12s %(funcName)-16sL%(lineno)04d %(message)s"
LOG_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

DUMPFILE = "mediainfo.txt"
SEEDING_DIR = f"S:{os.sep}Auto Downloads"

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
        help="Enable to upload torrent to HUNO, using api key found in hunoAPI.txt"
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

    if not os.path.exists('settings.ini'):
        logging.info("No settings.ini file found. Generating...")
        config = configparser.ConfigParser()

        config['DEFAULT'] = {
            'HUNO_API': '',
            'TMDB_API': '',
            'IMGBB_API': '',
            'QBIT_USERNAME': '',
            'QBIT_PASSWORD': '',
            'QBIT_HOST': '',
            'HUNO_URL': '',
            'PTPIMG_API': ''
        }

        with open('settings.ini', 'w') as configfile:
            config.write(configfile)

        sys.exit("settings.ini file generated. Please fill out before running again")

    # Load the INI file
    config = configparser.ConfigParser()
    config.read('settings.ini')
    huno_api = config['DEFAULT']['HUNO_API']
    tmdb_api = config['DEFAULT']['TMDB_API']
    imgbb_api = config['DEFAULT']['IMGBB_API']
    qbit_username = config['DEFAULT']['QBIT_USERNAME']
    qbit_password = config['DEFAULT']['QBIT_PASSWORD']
    qbit_host = config['DEFAULT']['QBIT_HOST']
    huno_url = config['DEFAULT']['HUNO_URL']
    ptpimg_api = config['DEFAULT']['PTPIMG_API']
    if ptpimg_api == '':
        ptpimg_api = None

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
        os.mkdir("runs" + os.sep + maxValue)
        runDir = os.getcwd() + os.sep + "runs" + os.sep + maxValue + os.sep

    logging.info(f"Created folder for output in {os.path.relpath(runDir)}")
    logging.info(f"Creating mediainfo dump in {runDir + DUMPFILE}...")
    if isFolder == 1:
        videoFile = path
        file = os.path.basename(path)
        mediaInfoText = getInfoDump(path, runDir)
    elif isFolder == 2:
        # List all files in the folder
        data = os.listdir(path)
        # Sort the files alphabetically
        data.sort()

        # Look for the first video file
        for file in data:
            # Check the file extension
            name, ext = os.path.splitext(file)
            if ext in ['.mp4', '.avi', '.mkv']:
                # Found a video file
                videoFile = path + os.sep + file
                mediaInfoText = getInfoDump(path + os.sep + file, runDir)
                logging.debug(pformat(json.loads(mediaInfoText)))
                break
    logging.info("Mediainfo dump created")
    guessItOutput = dict(guessit.guessit(videoFile, ))
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
        tmdbID = get_tmdb_id(title, tmdb_api)
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
        # Set the video position to the timestamp
        video.set(cv2.CAP_PROP_POS_MSEC, timestamp * 1000)
        # Read the frame at the current position
        success, image = video.read()
        if success:
            # Save the image to a file
            cv2.imwrite(runDir + f"screenshots{os.sep}" + "screenshot_{}.png".format(timestamp), image)
            logging.info(f"Screenshot made at {runDir}screenshots{os.sep}" + "screenshot_{}.png".format(timestamp))
    video.release()
    if arg.upload:
        if (arg.throttle and arg.upload) or arg.hardlink:
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
        api_endpoint = "https://api.imgbb.com/1/upload"
        images = os.listdir(f"{runDir}screenshots{os.sep}")
        logging.info("Screenshots loaded...")
        imgbb_brokey = False
        for image in images:
            ptpupload = False
            logging.info(f"Uploading {image}")
            # Open the file and read the data
            filePath = runDir + "screenshots" + os.sep + image
            with open(filePath, "rb") as imagefile:
                file_data = imagefile.read()
            # Set the payload for the POST request
            payload = {
                "key": imgbb_api,
                "image": b64encode(file_data),
            }
            try:
                if imgbb_brokey:
                    raise Exception
                response = requests.post(api_endpoint, payload)
                # Get the image URL from the response
                image_url = response.json()
                if response.status_code != 200:
                    logging.warning(pformat(image_url))
                    raise Exception
            except Exception:
                if not imgbb_brokey:
                    logging.error("Failed to upload to imgbb. It's probably down.")
                    logging.info("PTPImg API exists. Attempting to upload there...")
                imgbb_brokey = True
                if ptpimg_api:
                    image_url = uploadToPTPIMG(filePath, ptpimg_api)
                    ptpupload = True
            logging.debug(image_url)
            try:
                if ptpupload:
                    bbcode = f"[url={image_url}][img]{image_url}[/img][/url]"
                else:
                    image_url = response.json()["data"]["url"]
                    image_url_viewer = response.json()["data"]["url_viewer"]
                    # Print the image URL
                    # Template: [url=https://ibb.co/0fbvMqH][img]https://i.ibb.co/0fbvMqH/screenshot-785-895652173913.png[/img][/url]
                    bbcode = f"[url={image_url_viewer}][img]{image_url}[/img][/url]"
                with open(runDir + "showDesc.txt", "a") as fileAdd:
                    fileAdd.write(bbcode + "\n")
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
            frameRate = mediaInfoText['media']['track'][1]['FrameRate']
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
            elif 'h265' in file.lower().replace('.', '') or 'hevc' in file.lower().replace('.', ''):
                videoCodec = 'H265'
            else:
                videoCodec = "x265"
        elif "VC-1" in mediaInfoText['media']['track'][1]['Format']:
            videoCodec = "VC-1"
        elif "V_MPEG2" in mediaInfoText['media']['track'][1]['CodecID']:
            videoCodec = "MPEG-2"
        elif 'remux' in file.lower():
            videoCodec = "AVC"
        elif 'x264' in file.lower():
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
        if "REPACK" in file:
            repack = " [REPACK]"
        else:
            repack = ""
        # Get if hybrid
        if "hybrid" in file.lower():
            hybrid = " Hybrid"
        else:
            hybrid = ""
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

        if arg.huno and arg.inject:
            head, tail = os.path.split(path)
            headBasename = os.path.basename(head)
            postName = torrentFileName.replace(".torrent", "")
            if head != SEEDING_DIR:
                logging.info("Attempting to create hardlinks for easy seeding...")
                destination = os.path.join(SEEDING_DIR, postName)
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
            IMDB_ID = int(re.findall(r'\d+', IMDB_ID)[0])
        except Exception:
            if arg.movie:
                logging.info(f"Failed to find the IMDB ID from '{IMDB_ID}'. Please input just the numbers of the IMDB ID:")
            else:
                logging.info(f"Failed to find the IMDB ID from '{tmdbtoIMDDdata['imdb_id']}'. Please input just the numbers of the IMDB ID:")
            IMDB_ID = input()
        description = generate_bbcode(tmdbID, mediaDescription, runDir, tmdb_api)

        # Get MediaInfo Dump
        with open(runDir + "mediainfo.txt", "r", encoding='UTF-8') as infoFile:
            mediaInfoDump = infoFile.read()

        # Get post name
        postName = torrentFileName.replace(".torrent", "")
        torrent_file = runDir + torrentFileName
        torrent_file = {'torrent': open(torrent_file, 'rb')}
        data = {
            'season_pack': season_pack,
            'stream': 1,
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
            paused = True
        qbitInject(qbit_host=qbit_host, qbit_username=qbit_username, qbit_password=qbit_password, category=category, runDir=runDir, torrentFileName=torrentFileName, paused=paused, postName=postName)


def qbitInject(qbit_host, qbit_username, qbit_password, category, runDir, torrentFileName, paused, postName):
    logging.info("Logging in to qbit...")
    qb = qbittorrentapi.Client(qbit_host, username=qbit_username, password=qbit_password, REQUESTS_ARGS={'timeout': (60, 60)})
    logging.info("Logged in to qbit")
    torrent_file = runDir + torrentFileName
    torrent_file = rf"{torrent_file}"
    logging.info(f"Injecting {torrent_file} to qbit...")
    try:
        result = qb.torrents_add(is_skip_checking=True, torrent_files=torrent_file, is_paused=paused, category=category, tags="Self-Upload", rename=postName)
    except Exception as e:
        print(e)
    if result == "Ok.":
        logging.info("Torrent successfully injected.")
    else:
        logging.critical(result)


def get_prominent_color(tmdb_id, api_key, directory):
    logging.info(f"Fetching poster for TMDB ID: {tmdb_id}")

    # Make a request to the TMDB API to get the poster URL
    response = requests.get(f'https://api.themoviedb.org/3/movie/{tmdb_id}?api_key={api_key}')
    data = response.json()

    # Get the poster path from the API response
    poster_path = data['poster_path']
    poster_url = f'https://image.tmdb.org/t/p/w500/{poster_path}'

    logging.info(f"Downloading poster from URL: {poster_url}")

    # Download and save the poster image
    response = requests.get(poster_url, stream=True)
    response.raise_for_status()
    poster_path = os.path.join(directory, 'poster.jpg')
    with open(poster_path, 'wb') as file:
        for chunk in response.iter_content(chunk_size=8192):
            file.write(chunk)

    logging.info("Poster downloaded and saved successfully")
    logging.info("Opening poster...")

    color_thief = ColorThief(poster_path)
    # get the dominant color
    dominant_colour = color_thief.get_color(quality=1)
    return dominant_colour


def generate_bbcode(tmdb_id, mediaDesc, runDir, api_key, notes=None):
    # average_color, prominent_color, prominent_color_hsv = get_prominent_color(tmdb_id, api_key, runDir)
    prominent_color = get_prominent_color(tmdb_id, api_key, runDir)

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


def convert_sha1_hash(hash_str):
    """Converts a SHA-1 hash value to the format used by torf."""
    hash_bytes = bytes.fromhex(hash_str)
    hash_pieces = [hash_bytes[i:i+20] for i in range(0, len(hash_bytes), 20)]
    return b''.join(hash_pieces)


def is_valid_torf_hash(hash_str):
    """Checks if a string is a valid SHA-1 hash value for torf."""
    try:
        hash_bytes = bytes.fromhex(hash_str)
        if len(hash_bytes) != 20:
            return False
        return True
    except ValueError:
        return False


def get_tmdb_id(name, api_key):
    """
    Returns the TMDB ID of a TV show or movie given its name.
    """
    # The base URL for the TMDB API
    logging.info("Looking for title: " + name)

    base_url = "https://api.themoviedb.org/3"

    # The endpoint for searching for TV shows or movies by name
    search_endpoint = "/search/multi"

    # Construct the full URL for the search endpoint, with the query parameters
    url = f"{base_url}{search_endpoint}?api_key={api_key}&query={name}"

    # Send a GET request to the API to search for the TV show or movie
    response = requests.get(url)

    # Parse the response JSON to get the TMDB ID of the first result
    logging.debug(pformat(response.json()))
    results = response.json()["results"]
    if len(results) > 0:
        tmdb_id = results[0]["id"]
        return tmdb_id

    # If there are no results, return None
    return None


def notifyTaskbarIcon():
    # Define the path to the executable file
    executable_path = os.path.abspath(__file__)

    # Define the FLASHW_TRAY flag to flash the taskbar button
    FLASHW_TRAY = 0x00000002

    # Define the FLASHW_TIMERNOFG flag to flash continuously
    FLASHW_TIMERNOFG = 0x0000000C

    # Define the structure for the FLASHWINFO object
    class FLASHWINFO(ctypes.Structure):
        _fields_ = [
            ('cbSize', ctypes.c_uint),
            ('hwnd', ctypes.c_void_p),
            ('dwFlags', ctypes.c_uint),
            ('uCount', ctypes.c_uint),
            ('dwTimeout', ctypes.c_uint),
        ]

    # Get a handle to the current process window
    hwnd = ctypes.windll.kernel32.GetConsoleWindow()

    # Define the FLASHWINFO object with the appropriate parameters
    flash = FLASHWINFO(
        ctypes.sizeof(FLASHWINFO),
        hwnd,
        FLASHW_TRAY | FLASHW_TIMERNOFG,
        0,
        0,
    )

    # Call the FlashWindowEx function to flash the taskbar button
    ctypes.windll.user32.FlashWindowEx(ctypes.byref(flash))


def uploadToPTPIMG(imageFile: str, api_key):
    # Stole this code from https://github.com/DeadNews/images-upload-cli
    response = requests.post(
        url="https://ptpimg.me/upload.php",
        data={"api_key": api_key},
        files={"file-upload[0]": open(imageFile, 'rb').read()},
    )
    if not response.ok:
        raise Exception(response.json())

    logging.debug(response.json())

    return f"https://ptpimg.me/{response.json()[0]['code']}.{response.json()[0]['ext']}"


def get_episode(filename: str):
    import re
    match = re.search(r'S\d{2}E\d{2}', filename.upper())
    if match:
        return match.group().split('E')[1]
    return input("Episode number can't be found. Please enter episode number in format 'E00'\n")


def check_folder_for_episode(folder_path):
    # list all files in folder
    files = os.listdir(folder_path)
    video_files = [f for f in files if f.endswith('.mp4') or f.endswith('.mkv') or f.endswith('.avi')]
    # check if there is only one video file
    if len(video_files) != 1:
        return None
    # check if the video file name has format S00E00
    episode_pattern = re.compile(r'S\d{2}E\d{2}')
    match = episode_pattern.search(video_files[0])
    if match:
        return match.group()
    return None


def get_colour_space(mediaInfo):
    if "HDR" not in str(mediaInfo):
        return "SDR"
    try:
        if "Dolby Vision" in mediaInfo['media']['track'][1]['HDR_Format']:
            if "HDR10" in mediaInfo['media']['track'][1]['HDR_Format_Compatibility']:
                if "HDR10+" in mediaInfo['media']['track'][1]['HDR_Format_Compatibility']:
                    return "DV HDR10+"
                return "DV HDR"
            else:
                return "DV"
    except KeyError:
        logging.debug("Keyerror when looking for DV format")
        if mediaInfo['media']['track'][1]['colour_primaries'] in ['BT.2020', 'DCI-P3'] or mediaInfo['media']['track'][1]['transfer_characteristics'] in ['PQ', 'HLG']:
            return "HDR"
    if "HDR10+" in mediaInfo['media']['track'][1]['HDR_Format_Compatibility']:
        return "HDR10+"
    return "HDR"


def get_audio_info(mediaInfo):
    # Codec
    codecsDict = {
        "E-AC-3": "EAC3",
        "MLP FBA": "TrueHD",
        "DTS": "DTS",
        "AAC": "AAC",
        "PCM": "PCM",
        "AC-3": "DD",
        "FLAC": "FLAC",
        "Opus": "OPUS"
    }
    audioFormat = None
    trackNum = None
    for num, track in enumerate(mediaInfo['media']['track']):
        if track['@type'] == "Audio":
            trackNum = num
            break

    if trackNum is None:
        logging.warning("No audio track found!")
        return ""

    if 'Format_Commercial_IfAny' in str(mediaInfo['media']['track'][trackNum]):
        if mediaInfo['media']['track'][trackNum]['Format_Commercial_IfAny']:
            commercialFormat = mediaInfo['media']['track'][trackNum]['Format_Commercial_IfAny']
            if "Dolby Digital" in commercialFormat:
                if "Plus" in commercialFormat:
                    audioFormat = "DDP"
                else:
                    audioFormat = "DD"
            elif "TrueHD" in commercialFormat:
                audioFormat = "TrueHD"
            elif "DTS" in commercialFormat:
                if "HD High Resolution" in commercialFormat:
                    audioFormat = "DTS-HD HR"
                elif "Master Audio" in commercialFormat:
                    audioFormat = "DTS-HD MA"
                elif "DTS-ES" in commercialFormat:
                    audioFormat = "DTS-ES"
            if 'Atmos' in commercialFormat:
                audioFormat = audioFormat + " Atmos"

    if audioFormat is None:
        if mediaInfo['media']['track'][trackNum]['Format'] in codecsDict:
            audioFormat = codecsDict[mediaInfo['media']['track'][trackNum]['Format']]

    if audioFormat is None:
        logging.error("Audio format was not found")

    # Channels
    channelsNum = mediaInfo['media']['track'][trackNum]['Channels']
    try:
        channelsLayout = mediaInfo['media']['track'][trackNum]['ChannelLayout']
        if "LFE" in channelsLayout:
            channelsNum = str(int(channelsNum) - 1)
            channelsNum2 = ".1"
        else:
            channelsNum2 = ".0"
        channelsNum = channelsNum + channelsNum2
    except KeyError:
        logging.info("Couldn't find channel layout. Assuming no sub tracks.")
        channelsNum = channelsNum + ".0"
    audioInfo = audioFormat + " " + channelsNum
    return audioInfo


def downloadMediainfo():
    # Set the URL for the mediainfo download
    url = "https://mediaarea.net/download/binary/mediainfo/22.12/MediaInfo_CLI_22.12_Windows_x64.zip"

    # Set the destination folder
    destination_folder = "Mediainfo"

    # Create the destination folder if it doesn't already exist
    if not os.path.exists(destination_folder):
        os.makedirs(destination_folder)

    # Download the file
    response = requests.get(url)
    open("MediaInfo_CLI_22.12_Windows_x64.zip", "wb").write(response.content)
    logging.info("MediaInfo_CLI_22.12_Windows_x64.zip downloaded. Unpacking in to ./Mediainfo/")
    # Unpack the zip file
    with zipfile.ZipFile("MediaInfo_CLI_22.12_Windows_x64.zip", "r") as zip_ref:
        zip_ref.extractall(destination_folder)

    # Delete the zip file
    os.remove("MediaInfo_CLI_22.12_Windows_x64.zip")


def getResolution(width, height, frameRate):
    width_to_height_dict = {"720": "576", "960": "540", "1280": "720", "1920": "1080", "4096": "2160", "3840": "2160", "692": "480", "1024": "576"}
    acceptedHeights = ['576', '480', '360', '240', '720', '1080', '1440', '2160']
    if width in width_to_height_dict:
        height = width_to_height_dict[width]
        if height == "576" and "29" in frameRate:
            logging.info("NTSC detected. Changed resolution to 480")
            height = "480"
        return f"{str(height)}p"

    if height is not None and height in acceptedHeights:
        return f"{str(height)}p"

    return input("Resolution could not be found. Please input the resolution manually (e.g. 1080p, 2160p, 720p)\n")


def copy_folder_structure(src_path, dst_path):
    # Create the destination folder if it doesn't exist
    if not os.path.exists(dst_path):
        os.makedirs(dst_path)

    # Iterate over all the files and folders in the source path
    for item in os.listdir(src_path):
        src_item_path = os.path.join(src_path, item)
        dst_item_path = os.path.join(dst_path, item)
        # If the item is a file, hardlink it to the destination
        if os.path.isfile(src_item_path):
            try:
                os.link(src_item_path, dst_item_path)
            except FileExistsError:
                continue
        # If the item is a folder, recursively copy its contents
        elif os.path.isdir(src_item_path):
            copy_folder_structure(src_item_path, dst_item_path)


def getUserInput(question: str):
    question = question + " [y, n]"
    Userinput = None
    while Userinput not in ["y", "yes", "n", "no"]:
        # notifyTaskbarIcon()
        Userinput = input(question)
        if Userinput in ["y", "yes"]:
            return True
        if Userinput in ["n", "no"]:
            return False
        logging.warning("Given input is not valid. Must be one of [y,n]\n")


def delete_if_no_torrent(dirpath):
    # Runs through contents of a directory, and deletes directory if there's no .torrent files.
    # Returns true if directory was deleted, false otherwise
    # Use os.listdir() to get the list of files in the directory
    files = os.listdir(dirpath)
    # Check if there are any .torrent files in the list
    if not any(f.endswith('.torrent') for f in files):
        # If no .torrent files are found, delete the directory
        shutil.rmtree(dirpath)
        return True
    return False


def get_season(filename: str):
    # Use a regex to match the season string
    match = re.search(r'S\d\d', filename.upper())
    if match:
        # If a match is found, return the season string
        return match.group(0)
    else:
        # If no match is found, return an empty string
        return input('Season number was not found. Please input in the format S00\n')


def get_language_name(language_code):
    try:
        # Create a Locale instance with the given language code
        locale = Locale(language_code)
        # Return the language name in english
        return locale.get_display_name('en')
    except Exception:
        # If the language code is invalid or the name cannot be determined, return an empty string
        return ''


def folders_in(path_to_parent):
    for fname in os.listdir(path_to_parent):
        if os.path.isdir(os.path.join(path_to_parent, fname)):
            yield os.path.join(path_to_parent, fname)


def has_folders(path_to_parent):
    folders = list(folders_in(path_to_parent))
    return len(folders) != 0


def cb(torrent, filepath, pieces_done, pieces_total):
    print(f'{pieces_done/pieces_total*100:3.0f} % done', end="\r")


def FileOrFolder(path: str):
    # returns 1 if file, 2 if folder, 0 if neither
    if os.path.isfile(path):
        return 1
    elif os.path.isdir(path):
        return 2
    else:
        return 0


def getInfoDump(filePath: str, runDir: str):
    output = MediaInfo.parse(filename=filePath, output="", full=False)
    logging.debug(output)
    # don't ask, the output looks fine in the terminal, but writing it
    # to a file adds empty lines every second line. This deletes them
    logging.info("Creating mediainfo dump at " + runDir + DUMPFILE)
    with open(runDir + DUMPFILE, "w", encoding='utf-8') as f:
        f.write(output)
    with open(runDir + DUMPFILE, "r", encoding='utf-8') as fi:
        # Get the lines from the file
        lines = fi.readlines()

        # Create an empty list to store the modified lines
        new_lines = []

        # Iterate over the lines in the file
        for i, line in enumerate(lines):
            # Check if the line number is even
            if i % 2 == 0:
                # If the line number is even, add the line to the new list
                new_lines.append(line)

    # Open the file in write mode
    with open(runDir + DUMPFILE, 'w', encoding='utf-8') as fo:
        # Write the modified lines to the file
        for line in new_lines:
            fo.write(line)
    # Create a new mediainfo dump in JSON for parsing later
    output = MediaInfo.parse(filename=filePath, output="JSON", full=False)
    return output


if __name__ == "__main__":
    main()
