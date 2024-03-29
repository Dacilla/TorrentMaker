import pymediainfo
import argparse
import logging
import configparser
import sys
import guessit
import os
import re
import json
import requests

from pprint import pformat
from datetime import datetime

from torrentmaker import get_tmdb_id, getInfoDump, getUserInput, get_season, get_episode, getResolution, get_audio_info

__VERSION = "1.0.0"
LOG_FORMAT = "%(asctime)s.%(msecs)03d %(levelname)-8s P%(process)06d.%(module)-12s %(funcName)-16sL%(lineno)04d %(message)s"
LOG_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

DUMPFILE = "mediainfo.txt"
BULK_DOWNLOAD_FILE = os.getcwd() + os.sep + "bulkProcess.txt"


def main():
    parser = argparse.ArgumentParser(
        description="Script to automate creation of torrent files, as well as grabbing mediainfo dump, screenshots, and tmdb description"
    )
    parser.add_argument(
        "--path",
        "-p",
        action="store",
        help="Path for file or folder to create .torrent file for",
        type=str
    )
    parser.add_argument(
        "-D", "--debug", action="store_true", help="debug mode", default=False
    )
    parser.add_argument(
        "-V", "--version", action="version", version="%(prog)s {version}".format(version=__VERSION),
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
        "--hardlink",
        action="store_true",
        default=False,
        help="Enable to hardlink the renamed files rather than renaming the originals"
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

    pathList = []
    if arg.path is None:
        if not arg.path:
            logging.info(f"No explicit path given, reading {BULK_DOWNLOAD_FILE}")
            if not os.path.exists(BULK_DOWNLOAD_FILE):
                logging.warning(f"No {BULK_DOWNLOAD_FILE} file found. Creating...")
                with open(BULK_DOWNLOAD_FILE, 'w') as f:
                    f.write("")
            with open(BULK_DOWNLOAD_FILE, 'r', encoding='utf-8') as dlFile:
                file_contents = dlFile.read()
                if len(file_contents) == 0:
                    logging.error(f"No path given in either arg.path or {BULK_DOWNLOAD_FILE}. Exiting...")
                    sys.exit(-1)
                print(f"File contents: {file_contents}")
                for line in file_contents.split('\n'):
                    pathList.append(line.strip().replace("\"", ""))
                    print(f"Added {line.strip()} to pathList")
            logging.info("Loaded " + str(len(pathList)) + " paths...")
        else:
            pathList.append(arg.path)

        pathList.sort()
    else:
        pathList.append(arg.path)

    for path in pathList:
        guessItOutput = dict(guessit.guessit(path))
        logging.info(pformat(guessItOutput))

        group = None
        if 'release_group' in str(guessItOutput):
            group = guessItOutput['release_group']
            # remove any kinds of brackets from group name
            group = re.sub(r"[\[\]\(\)\{\}]", " ", group)
            group = group.split()[0]
        else:
            group = "NOGRP"

        isMovie = False
        if 'type' in guessItOutput:
            if guessItOutput['type'] == 'movie':
                isMovie = True

        countryCode = None
        if arg.tmdb is None and 'title' in str(guessItOutput):
            logging.info("No TMDB ID given. Attempting to find it automatically...")
            title = guessItOutput['title']
            if 'country' in guessItOutput:
                countryCode = guessItOutput['country'].alpha2
                title = title + f" {guessItOutput['country'].alpha2}"
            # if 'year' in guessItOutput and guessItOutput['type'] == 'movie':
            #     title = title + f" {guessItOutput['year']}"
            tmdbID = get_tmdb_id(title, tmdb_api, isMovie)
            if tmdbID:
                logging.info(f"TMDB ID Found: {tmdbID}")
            else:
                tmdbID = input("Failed to find TMDB ID. Please input:\n")
        else:
            tmdbID = arg.tmdb

        isMovie = False
        if 'type' in guessItOutput:
            if guessItOutput['type'] == 'movie':
                isMovie = True

        if os.path.exists(DUMPFILE):
            os.remove(DUMPFILE)
        mediaInfoText = getInfoDump(path, os.getcwd())

        mediaInfoJson = json.loads(mediaInfoText.strip())
        logging.debug(pformat(mediaInfoJson))

        if tmdbID:
            if tmdb_api == "":
                logging.error("TMDB_API field not filled in settings.ini")
                sys.exit()
            # Get TMDB info
            logging.info("Getting TMDB info")

            # Build the URL for the API request
            if isMovie:
                url = f'https://api.themoviedb.org/3/movie/{tmdbID}?api_key={tmdb_api}'
            else:
                url = f'https://api.themoviedb.org/3/tv/{tmdbID}?api_key={tmdb_api}'

            # Make the GET request to the TMDb API
            response = requests.get(url)

            # Get the JSON data from the response
            tmdbData = response.json()
            try:
                originalLanguange = response.json()['original_language']
            except Exception as e:
                print(e)
                print(response.json())

        if isMovie:
            showName: str = tmdbData['title']
        else:
            showName: str = tmdbData['name']

        showName = showName.replace(":", "")

        logging.info("Name: " + str(showName))
        try:
            if isMovie:
                dateString = tmdbData['release_date']
            else:
                dateString = tmdbData['first_air_date']

            date = datetime.strptime(dateString, "%Y-%m-%d")
            year = str(date.year)
            logging.info("Year: " + year)
        except ValueError:
            logging.warning("Year not found. Not including...")
            year = ''

        if not isMovie:
            season = get_season(os.path.basename(path))
            logging.info("Season: " + season)
            episode = "E" + get_episode(os.path.basename(path))
            logging.info("Episode: " + episode)
            episodeNum = season + episode

        width = mediaInfoJson['media']['track'][1]['Width']
        height = mediaInfoJson['media']['track'][1]['Height']
        frameRate = mediaInfoJson['media']['track'][1]['FrameRate']
        resolution = getResolution(width=width, height=height, frameRate=frameRate)
        if "Interlaced" in str(mediaInfoJson):
            resolution = resolution.replace("p", "i")
        logging.info("Resolution: " + resolution)

        if 'HEVC' in mediaInfoJson['media']['track'][1]['Format']:
            if 'remux' in os.path.basename(path).lower().replace('.', ''):
                videoCodec = 'HEVC'
            elif 'h265' in os.path.basename(path).lower().replace('.', '') or 'hevc' in os.path.basename(path).lower().replace('.', ''):
                videoCodec = 'H.265'
            else:
                videoCodec = "x265"
        elif "VC-1" in mediaInfoJson['media']['track'][1]['Format']:
            videoCodec = "VC-1"
        elif "V_MPEG2" in mediaInfoJson['media']['track'][1]['CodecID']:
            videoCodec = "MPEG-2"
        elif 'remux' in os.path.basename(path).lower():
            videoCodec = "AVC"
        elif 'x264' in os.path.basename(path).lower():
            videoCodec = "x264"
        else:
            videoCodec = "H.264"

        logging.info("Video Codec: " + videoCodec)

        audio = get_audio_info(mediaInfoJson).replace(' ', '')
        logging.info("Audio: " + audio)

        if arg.source:
            source = arg.source
        else:
            source = ""
        logging.info("Source: " + source)

        container = 'mkv'
        if 'container' in guessItOutput:
            container = guessItOutput['container']
            logging.info("Container: " + container)

        if countryCode:
            showName = showName + ' ' + countryCode

        episodeTitle = None
        if 'episode_title' in guessItOutput:
            episodeTitle = guessItOutput['episode_title']
            episodeNum = episodeNum + ' ' + episodeTitle

        if isMovie:
            postFileName = ('.'.join([showName, year, resolution, source, audio, videoCodec]).replace(' ', '.') + '-' + arg.group + '.' + container).replace('\'', '').replace('..', '.')
        else:
            postFileName = ('.'.join([showName, year, episodeNum, resolution, source, audio, videoCodec]).replace(' ', '.') + '-' + arg.group + '.' + container).replace('\'', '').replace('..', '.')

        logging.info("Final file name:\n" + postFileName)

        if getUserInput("Is this acceptable?"):
            if os.path.exists(DUMPFILE):
                os.remove(DUMPFILE)
            if arg.hardlink:
                logging.info("Making renamed hardlink...")
                os.link(src=path, dst=os.path.dirname(path) + os.sep + postFileName)
                logging.info("Hardlink made to: " + os.path.dirname(path) + os.sep + postFileName)
            else:
                logging.info("Renaming files...")
                os.rename(src=path, dst=os.path.dirname(path) + os.sep + postFileName)
                logging.info("Rename made to: " + os.path.dirname(path) + os.sep + postFileName)


if __name__ == "__main__":
    main()
