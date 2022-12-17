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

from babel import Locale
from pprint import pprint, pformat
from base64 import b64encode
from pymediainfo import MediaInfo
from datetime import datetime

__VERSION = "1.0.0"
LOG_FORMAT = "%(asctime)s.%(msecs)03d %(levelname)-8s P%(process)06d.%(module)-12s %(funcName)-16sL%(lineno)04d %(message)s"
LOG_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

DUMPFILE = "mediainfo.txt"
APIKEYFILE = "tmdbApi.txt"


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
        "--audio",
        action="store",
        type=str,
        help="Audio Codec. Will be replaced for auto detection soon",
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
        if not os.path.isfile(os.getcwd() + os.sep + APIKEYFILE):
            logging.error(f"{APIKEYFILE} does not exist")
            sys.exit()
        # Get TMDB info
        logging.info("Getting TMDB description")
        with open(APIKEYFILE) as fa:
            api_key = fa.read()

        # Replace TV_SHOW_ID with the ID of the TV show you want to get the description for
        tv_show_id = arg.tmdb

        # Build the URL for the API request
        if arg.movie:
            url = f'https://api.themoviedb.org/3/movie/{tv_show_id}?api_key={api_key}'
        else:
            url = f'https://api.themoviedb.org/3/tv/{tv_show_id}?api_key={api_key}'

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

    if arg.upload:
        logging.info("Uploading screenshots to imgbb")
        if not os.path.isfile("imgbbApi.txt"):
            logging.error("No imgbbApi.txt file found")
            sys.exit()
        with open("imgbbApi.txt", "r") as bb:
            imgbbAPI = bb.read()
        api_endpoint = "https://api.imgbb.com/1/upload"
        images = os.listdir(f"{runDir}screenshots{os.sep}")
        logging.info("Screenshots loaded...")
        for image in images:
            logging.info(f"Uploading {image}")
            # Open the file and read the data
            filePath = runDir + "screenshots" + os.sep + image
            with open(filePath, "rb") as file:
                file_data = file.read()
            # Set the payload for the POST request
            payload = {
                "key": imgbbAPI,
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

    logging.info("Creating torrent file")
    torrent = torf.Torrent()
    torrent.private = True
    torrent.source = "HUNO"
    torrent.path = path
    with open("trackerURL.txt", "r") as t:
        torrent.trackers = t.readlines()
    torrentFileName = "generatedTorrent.torrent"
    if arg.tmdb:
        # Create torrent file name from TMDB and Mediainfo
        # Template:
        # ShowName (Year) S00 (1080p BluRay x265 SDR DD 5.1 Language - Group)
        # pprint(mediaInfoText)
        if arg.movie:
            showName = tmdbData['original_title']
        else:
            showName = tmdbData['name']
        logging.info("Name: " + str(showName))
        if arg.movie:
            dateString = tmdbData['release_date']
        else:
            dateString = tmdbData['first_air_date']
        date = datetime.strptime(dateString, "%Y-%m-%d")
        year = str(date.year)
        logging.info("Year: " + year)
        logging.debug(videoFile)
        season = get_season(videoFile)
        logging.info("Season: " + season)
        # Detect resolution
        # TODO: Detect whether it's progressive or interlaced
        resolution = mediaInfoText['media']['track'][1]['Height'] + "p"
        logging.info("Resolution: " + resolution)
        # Detect if file is HDR
        HDR = False
        DV = False
        SDR = False
        if 'HDR' in mediaInfoText['media']['track'][1]['ColorSpace']:
            HDR = True
        if 'DV' in mediaInfoText['media']['track'][1]['ColorSpace']:
            DV = True
        if not HDR and not DV:
            SDR = True
        if SDR:
            colourSpace = 'SDR'
        else:
            colourSpace = mediaInfoText['media']['track'][1]['ColorSpace']
        logging.info("Colour Space: " + colourSpace)
        # Detect video codec
        if 'HEVC' in mediaInfoText['media']['track'][1]['Format']:
            videoCodec = "x265"
        else:
            videoCodec = "x264"
        logging.info("Video Codec: " + videoCodec)
        # TODO: Detect audio codec
        if arg.audio:
            audio = arg.audio
        else:
            audio = ""
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
            group = ""
        logging.info("Group: " + group)
        # Construct torrent name
        if arg.movie:
            torrentFileName = f"{showName} ({year}) ({resolution} {source} {videoCodec} {colourSpace} {audio} {language} - {group}).torrent"
        else:
            torrentFileName = f"{showName} ({year}) {season} ({resolution} {source} {videoCodec} {colourSpace} {audio} {language} - {group}).torrent"
        logging.info("Final name: " + torrentFileName)

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
            url = f'https://api.themoviedb.org/3/tv/{tv_show_id}/external_ids?api_key={api_key}'
            # Make the GET request to the TMDb API
            response = requests.get(url)

            # Get the JSON data from the response
            tmdbtoIMDDdata = response.json()
            IMDB_ID = tmdbtoIMDDdata['imdb_id']
            TVDB_ID = tmdbtoIMDDdata['tvdb_id']
            IMDB_ID = int(re.findall(r'\d+', IMDB_ID)[0])
        # Get description
        with open(runDir + "showDesc.txt", "r") as descFile:
            description = descFile.read()

        # Get MediaInfo Dump
        with open(runDir + "mediainfo.txt", "r") as infoFile:
            mediaInfoDump = infoFile.read()

        # Get post name
        postName = torrentFileName.replace(".torrent", "")
        torrent_file = runDir + torrentFileName
        torrent_file = {'torrent': open(torrent_file, 'rb')}
        # headers = {
        #     'Content-Type': 'multipart/form-data',
        #     'Accept': 'application/json',
        # }
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
        pprint(data)
        print("-------------------------")
        # print(headers)
        print(data)
        if arg.skipPrompt or getUserInput("Do you want to upload this to HUNO?"):
            # Make API requests
            with open("hunoAPI.txt", "r") as hAPI:
                hunoAPI = hAPI.read()
            logging.info("HUNO API KEY: " + hunoAPI)
            url = f"https://hawke.uno/api/torrents/upload?api_token={hunoAPI}"
            logging.info("API URL: " + url)
            response = requests.post(url=url, data=data, files=torrent_file)
            print(response.status_code)
            print(response.json())

    if arg.inject:
        logging.info("Qbittorrent injection enabled")
        with open("qbitDetails.txt", "r") as d:
            lines = d.readlines()
            username = lines[0].strip()
            password = lines[1].strip()
        logging.info("Username: " + username)
        logging.info("Password: " + password)
        logging.info("Logging in to qbit...")
        qb = qbittorrentapi.Client("http://192.168.1.114:8080", username=username, password=password)
        # try:
        #     qb.auth_log_in()
        # except qbittorrentapi.LoginFailed as e:
        #     print(e)
        #     sys.exit()
        # except Exception as e:
        #     print(e)
        #     sys.exit()
        logging.info("Logged in to qbit")
        # with open(runDir + "generatedTorrent.torrent", 'rb') as torrent_file:
        torrent_file = runDir + torrentFileName
        torrent_file = rf"{torrent_file}"
        logging.info(f"Injecting {torrent_file} to qbit...")
        if arg.huno:
            paused = False
        else:
            paused = True
        try:
            result = qb.torrents_add(is_skip_checking=True, torrent_files=torrent_file, is_paused=paused, category="HUNO", tags="Self-Upload")
        except Exception as e:
            print(e)
        if result == "Ok.":
            logging.info("Torrent successfully injected.")
        else:
            logging.critical(result)


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
        # Return the language name in the locale's native language
        return locale.get_language_name(locale.language)
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
