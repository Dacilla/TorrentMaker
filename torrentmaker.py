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

from babel import Locale
from pprint import pprint, pformat
from base64 import b64encode
from pymediainfo import MediaInfo
from datetime import datetime

__VERSION = "1.0.0"
LOG_FORMAT = "%(asctime)s.%(msecs)03d %(levelname)-8s P%(process)06d.%(module)-12s %(funcName)-16sL%(lineno)04d %(message)s"
LOG_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

DUMPFILE = "mediainfo.txt"
SEEDING_DIR = f"S:{os.sep}Auto Downloads"

# TODO: Add detection of bluray extras
# TODO: Fix throttling of qbit upload speed to work with multiple instances of script
# TODO: Download Mediainfo if it's not found
# TODO: Add support for more trackers
# TODO: Add documentation to readme
# TODO: Support anime with MAL ID
# TODO: Support BD Raw Discs
# TODO: Add AV1 detection
# TODO: Add support for uploading images to ptpimg
# TODO: Add support for individual episodes
# TODO: Support music

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
    parser.add_argument(
        "-g", "--group",
        action="store",
        type=str,
        help="Group name of the torrent creator",
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
            'HUNO_URL': ''
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
    huno_url = config['DEFAULT']['HUNO_URL']

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
    result = FileOrFolder(path)

    if result not in [1, 2]:
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
    if result == 1:
        videoFile = path
        file = os.path.basename(path)
        mediaInfoText = getInfoDump(path, runDir)
    elif result == 2:
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
    mediaInfoText = mediaInfoText.strip()
    mediaInfoText = json.loads(mediaInfoText)
    if arg.tmdb:
        if tmdb_api == "":
            logging.error("TMDB_API field not filled in settings.ini")
            sys.exit()
        # Get TMDB info
        logging.info("Getting TMDB description")

        # Replace TV_SHOW_ID with the ID of the TV show you want to get the description for
        tv_show_id = arg.tmdb

        # Build the URL for the API request
        if arg.movie:
            url = f'https://api.themoviedb.org/3/movie/{tv_show_id}?api_key={tmdb_api}'
        else:
            url = f'https://api.themoviedb.org/3/tv/{tv_show_id}?api_key={tmdb_api}'

        # Make the GET request to the TMDb API
        response = requests.get(url)

        # Get the JSON data from the response
        tmdbData = response.json()
        logging.debug(pformat(tmdbData))
        # Print the description of the TV show
        logging.debug("description gotten: " + tmdbData['overview'])
        with open(runDir + "showDesc.txt", "w") as fb:
            fb.write(tmdbData['overview'] + "\n\n")
        logging.info("TMDB Description dumped to showDesc.txt")

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
                qb = qbittorrentapi.Client("http://192.168.1.114:8080", username=qbit_username, password=qbit_password)
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
        logging.info("Uploading screenshots to imgbb")
        api_endpoint = "https://api.imgbb.com/1/upload"
        images = os.listdir(f"{runDir}screenshots{os.sep}")
        logging.info("Screenshots loaded...")
        for image in images:
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
            # with tqdm(total=file_size, unit="B", unit_scale=True, unit_divisor=1024) as t:
            #     wrapped_file = CallbackIOWrapper(t.update, payload)
            #     requests.put(api_endpoint, data=wrapped_file)
            response = requests.post(api_endpoint, payload)
            # Get the image URL from the response
            image_url = response.json()
            logging.debug(image_url)
            try:
                image_url = response.json()["data"]["url"]
                image_url_viewer = response.json()["data"]["url_viewer"]
                # Print the image URL
                # Template: [url=https://ibb.co/0fbvMqH][img]https://i.ibb.co/0fbvMqH/screenshot-785-895652173913.png[/img][/url]
                bbcode = f"[url={image_url_viewer}][img]{image_url}[/img][/url]"
                with open(runDir + "showDesc.txt", "a") as fileAdd:
                    fileAdd.write(bbcode + "\n")
                logging.info(f"bbcode for image URL {image_url} added to showDesc.txt")
            except Exception as e:
                logging.critical("Unexpected Exception: " + e)
                continue
        if arg.upload:
            logging.info("Attempting to disable qbit upload speed limit")
            logging.info("Logging in to qbit...")
            qb = qbittorrentapi.Client("http://192.168.1.114:8080", username=qbit_username, password=qbit_password)
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

    logging.info("Creating torrent file")
    torrent = torf.Torrent()
    torrent.private = True
    torrent.source = "HUNO"
    torrent.path = path
    torrent.trackers = huno_url
    torrentFileName = "generatedTorrent.torrent"
    if arg.tmdb:
        # Create torrent file name from TMDB and Mediainfo
        # Template:
        # TV: ShowName (Year) S00 (1080p BluRay x265 SDR DD 5.1 Language - Group) [REPACK]
        # MOVIE: ShowName (Year) EDITION (1080p BluRay x265 SDR DD 5.1 Language - Group) [REPACK]
        # pprint(mediaInfoText)
        if arg.movie:
            showName: str = tmdbData['original_title']
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
            season = get_season(file)
            logging.info("Season: " + season)
        # Detect resolution
        acceptedResolutions = "2160p|1080p|720p"
        match = re.search(acceptedResolutions, file)
        if match:
            resolution = match.group()
        else:
            width = mediaInfoText['media']['track'][1]['Width']
            height = mediaInfoText['media']['track'][1]['Height']
            resolution = getResolution(width=width, height=height)
        if "Interlaced" in str(mediaInfoText):
            resolution = resolution.replace("p", "i")
        logging.info("Resolution: " + resolution)
        # Detect if file is HDR
        colourSpace = get_colour_space(mediaInfoText)
        logging.info("Colour Space: " + colourSpace)
        # Detect video codec
        if 'HEVC' in mediaInfoText['media']['track'][1]['Format']:
            if 'h265' in file.lower():
                videoCodec = 'H265'
            else:
                videoCodec = "x265"
        elif "VC-1" in mediaInfoText['media']['track'][1]['Format']:
            videoCodec = "VC-1"
        else:
            videoCodec = "H264"
        logging.info("Video Codec: " + videoCodec)
        # Detect audio codec
        audio = get_audio_info(mediaInfoText)
        logging.info("Audio: " + audio)
        # Get language
        language = get_language_name(mediaInfoText['media']['track'][2]['Language'])
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
        else:
            group = "NOGRP"
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
        # Construct torrent name
        if arg.movie:
            torrentFileName = f"{showName} ({year}){edition} ({resolution} {source} {videoCodec} {colourSpace} {audio} {language} - {group}){repack}.torrent"
        else:
            torrentFileName = f"{showName} ({year}) {season} ({resolution} {source} {videoCodec} {colourSpace} {audio} {language} - {group}){repack}.torrent"
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
    success = torrent.generate(callback=cb, interval=1)
    logging.info("Writing torrent file to disk...")
    torrent.write(runDir + torrentFileName)
    logging.info("Torrent file wrote to " + torrentFileName)

    if arg.huno:
        logging.info("Uploading to HUNO enabled")
        pathresult = FileOrFolder(path)
        if pathresult == 1 or arg.movie:
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
            case "480p":
                resolution_id = 8

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
        IMDB_ID = int(re.findall(r'\d+', IMDB_ID)[0])
        with open(runDir + "showDesc.txt", "r") as descFile:
            description = descFile.read()

        # Get MediaInfo Dump
        with open(runDir + "mediainfo.txt", "r") as infoFile:
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
            'tmdb': arg.tmdb,
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
            data["episode"] = 0
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
        logging.info("Logging in to qbit...")
        qb = qbittorrentapi.Client("http://192.168.1.114:8080", username=qbit_username, password=qbit_password)
        # try:
        #     qb.auth_log_in()
        # except qbittorrentapi.LoginFailed as e:
        #     print(e)
        #     sys.exit()
        # except Exception as e:
        #     print(e)
        #     sys.exit()
        logging.info("Logged in to qbit")
        torrent_file = runDir + torrentFileName
        torrent_file = rf"{torrent_file}"
        logging.info(f"Injecting {torrent_file} to qbit...")
        if arg.huno:
            paused = False
        else:
            paused = True
        try:
            result = qb.torrents_add(is_skip_checking=True, torrent_files=torrent_file, is_paused=paused, category="HUNO", tags="Self-Upload", rename=postName)
        except Exception as e:
            print(e)
        if result == "Ok.":
            logging.info("Torrent successfully injected.")
        else:
            logging.critical(result)


def get_colour_space(mediaInfo):
    if "HDR" not in mediaInfo:
        return "SDR"
    if "Dolby Vision" in mediaInfo['media']['track'][1]['HDR_Format']:
        if "HDR10" in mediaInfo['media']['track'][1]['HDR_Format_Compatibility']:
            return "DV HDR"
        else:
            return "DV"
    return "HDR"


def get_audio_info(mediaInfo):
    # Codec
    codecsDict = {
        "E-AC-3": "EAC3",
        "MLP FBA": "TrueHD",
        "DTS": "DTS",
        "AAC": "AAC",
        "PCM": "PCM",
        "AC-3": "DD"
    }
    audioFormat = None
    if 'Format_Commercial_IfAny' in str(mediaInfo['media']['track'][2]):
        if mediaInfo['media']['track'][2]['Format_Commercial_IfAny']:
            commercialFormat = mediaInfo['media']['track'][2]['Format_Commercial_IfAny']
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

    if audioFormat is None:
        if mediaInfo['media']['track'][2]['Format'] in codecsDict:
            audioFormat = codecsDict[mediaInfo['media']['track'][2]['Format']]

    if audioFormat is None:
        logging.error("Audio format was not found")
    # Channels
    channelsNum = mediaInfo['media']['track'][2]['Channels']
    channelsLayout = mediaInfo['media']['track'][2]['ChannelLayout']
    if "LFE" in channelsLayout:
        channelsNum = str(int(channelsNum) - 1)
        channelsNum2 = ".1"
    else:
        channelsNum2 = ".0"
    channelsNum = channelsNum + channelsNum2
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


def getResolution(width, height):
    width_to_height_dict = {"720": "576", "960": "540", "1280": "720", "1920": "1080", "4096": "2160", "3840": "2160", "692": "480", "1024": "576"}
    acceptedHeights = ['576', '480', '360', '240', '720', '1080', '1440', '2160']
    if width in width_to_height_dict:
        height = width_to_height_dict[width]
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
            os.link(src_item_path, dst_item_path)
        # If the item is a folder, recursively copy its contents
        elif os.path.isdir(src_item_path):
            copy_folder_structure(src_item_path, dst_item_path)


def getUserInput(question: str):
    question = question + " [y, n]"
    Userinput = None
    while Userinput not in ["y", "yes", "n", "no"]:
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


def get_season(filename):
    # Use a regex to match the season string
    match = re.search(r'S\d\d', filename)
    if match:
        # If a match is found, return the season string
        return match.group(0)
    else:
        # If no match is found, return an empty string
        return ''


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
    with open(runDir + DUMPFILE, "w") as f:
        f.write(output)
    with open(runDir + DUMPFILE, "r") as fi:
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
    with open(runDir + DUMPFILE, 'w') as fo:
        # Write the modified lines to the file
        for line in new_lines:
            fo.write(line)
    # Create a new mediainfo dump in JSON for parsing later
    output = MediaInfo.parse(filename=filePath, output="JSON", full=False)
    return output


if __name__ == "__main__":
    main()
