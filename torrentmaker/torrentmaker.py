import argparse
import logging
import os
import sys
import qbittorrentapi
import random

from pprint import pprint, pformat

from config import SetupConfig, SetupRunFolder
from mediaInfo import downloadMediaInfo, generateMIDump
from tmdb import getDesc
from screenshots import uploadScreenshots

__VERSION = "1.0.0"
LOG_FORMAT = "%(asctime)s.%(msecs)03d %(levelname)-8s P%(process)06d.%(module)-12s %(funcName)-16sL%(lineno)04d %(message)s"
LOG_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

DUMPFILE = "mediainfo.txt"
SEEDING_DIR = f"S:{os.sep}Auto Downloads"

global dataFile


def main():
    global dataFile
    dataFile = {}
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

    boolCheckList = [arg.episode, arg.movie]
    if sum(boolCheckList) >= 2:
        logging.error("Movie and Episode arguments can't be enabled at the same time. Please remove one.")

    logging.basicConfig(datefmt=LOG_DATE_FORMAT, format=LOG_FORMAT, level=level)
    logging.info(f"Version {__VERSION} starting...")

    logging.info("Reading settings.ini...")
    SetupConfig()

    pprint(dataFile)

    # if not arg.skipMICheck:
    #     downloadMediaInfo()

    path = arg.path
    isFolder = FileOrFolder(path)

    if isFolder not in [1, 2]:
        logging.error("Input not a file or directory")
        sys.exit()

    dataFile['isFolder'] = isFolder
    dataFile['path'] = path

    logging.info("Creating output folder...")
    SetupRunFolder()
    logging.info(f"Created folder for output in {os.path.relpath(dataFile['runDir'])}")

    logging.info(f"Creating mediainfo dump in {dataFile['runDir'] + DUMPFILE}...")
    generateMIDump()
    logging.info("Mediainfo dump created")

    dataFile['inject'] = arg.inject
    dataFile['isMovie'] = arg.movie
    dataFile['isEpisode'] = arg.episode
    if arg.source:
        dataFile['source'] = arg.source
    else:
        dataFile['source'] = None
    if arg.group:
        dataFile['group'] = arg.group
    else:
        dataFile['group'] = None
    if arg.huno:
        dataFile['huno'] = arg.huno
    else:
        dataFile['huno'] = None
    if arg.edition:
        dataFile['edition'] = arg.edition
    else:
        dataFile['edition'] = None

    if arg.tmdb:
        dataFile['tmdbId'] = arg.tmdb
        # Get TMDB info
        logging.info("Getting TMDB description")
        getDesc()

    if arg.upload:
        if (arg.throttle and arg.upload) or arg.hardlink:
            enableQbitThrottle()
        uploadScreenshots()
        if (arg.throttle and arg.upload) or arg.hardlink:
            disableQbitThrottle()


def FileOrFolder(path: str):
    # returns 1 if file, 2 if folder, 0 if neither
    if os.path.isfile(path):
        return 1
    elif os.path.isdir(path):
        return 2
    else:
        return 0


def enableQbitThrottle():
    global dataFile
    if dataFile["qbitUser"] != "" and dataFile["qbitPass"] != "":
        logging.info("Attempting to enable qbit upload speed limit")
        logging.info("Logging in to qbit...")
        qb = qbittorrentapi.Client("http://192.168.1.114:8080", username=dataFile["qbitUser"], password=dataFile["qbitPass"])
        transfer_info = qb.transfer_info()
        dataFile['uniqueUploadLimit'] = random.randint(900000, 1000000)
        if qb.transfer_upload_limit() == 0:
            qb.transfer_set_upload_limit(limit=dataFile['uniqueUploadLimit'])
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


def disableQbitThrottle():
    global dataFile
    logging.info("Attempting to disable qbit upload speed limit")
    logging.info("Logging in to qbit...")
    qb = qbittorrentapi.Client("http://192.168.1.114:8080", username=dataFile["qbitUser"], password=dataFile["qbitPass"])
    transfer_info = qb.transfer_info()
    logging.info("Qbit upload limit: " + str(qb.transfer_upload_limit()))
    logging.info("Comparing to: " + str(dataFile['uniqueUploadLimit']))
    if qb.transfer_upload_limit() == dataFile['uniqueUploadLimit']:
        qb.transfer_set_upload_limit(limit=0)
        uploadLimitEnabled = False
        logging.info("Qbit upload limit successfully disabled.")
    else:
        logging.info("Qbit upload limit has already been changed. Continuing...")
        uploadLimitEnabled = True