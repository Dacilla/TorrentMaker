import argparse
import os
import logging
import sys
import requests
import torf
import qbittorrentapi
import json
import re
import shutil
import configparser
import mutagen

from pprint import pprint, pformat
from base64 import b64encode
from pymediainfo import MediaInfo
from mutagen.mp3 import MP3
from mutagen.flac import FLAC

# Script to automate uploading music to RED

from torrentmaker import has_folders, cb, uploadToPTPIMG, SEEDING_DIR, copy_folder_structure

__VERSION = "1.0.0"
LOG_FORMAT = "%(asctime)s.%(msecs)03d %(levelname)-8s P%(process)06d.%(module)-12s %(funcName)-16sL%(lineno)04d %(message)s"
LOG_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


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
        "-s", "--source",
        action="store",
        type=str,
        help="Source of the torrent files (E.g. Bluray Remux, WEB-DL)",
        default="WEB"
    )
    parser.add_argument(
        "-c", "--cover",
        action="store",
        type=str,
        help="File path to cover image",
        default=None
    )
    parser.add_argument(
        "-i",
        "--inject",
        action="store_true",
        default=False,
        help="Enable to automatically inject torrent file to qbittorrent"
    )
    parser.add_argument(
        "-f",
        "--format",
        action="store_true",
        default=False,
        help="Enable to automatically format the file names of the songs"
    )
    parser.add_argument(
        "-D", "--debug", action="store_true", help="debug mode", default=False
    )
    parser.add_argument(
        "-V", "--version", action="version", version="%(prog)s {version}".format(version=__VERSION),
    )

    # Take in the path and make a torrent file
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
            'HUNO_URL': '',
            'PTPIMG_API': '',
            'RED_URL': ''
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
    ptpimg_api = config['DEFAULT']['PTPIMG_API']
    red_url = config['DEFAULT']['RED_URL']
    if ptpimg_api == '':
        ptpimg_api = None

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

    logging.info("Run directory: " + runDir)
    logging.info(f"Created folder for output in {os.path.relpath(runDir)}")

    if arg.format:
        logging.info("Formatting mode enabled...")
        add_track_position(arg.path)

    logging.info("Checking for missing tracks...")
    missingTracksList = check_missing_tracks(arg.path)
    if len(missingTracksList) > 0:
        logging.warning(f"Missing tracks found :{pformat(missingTracksList)} not allowed on RED")
        sys.exit(-1)
    logging.info("No missing tracks found.")
    logging.info("Generating track list...")
    create_track_list(arg.path, runDir + "trackData.txt")

    logging.info("Creating torrent file")
    torrent = torf.Torrent()
    torrent.private = True
    torrent.source = "RED"
    torrent.path = arg.path
    torrent.trackers = red_url
    torrentFileName = os.path.basename(arg.path).strip() + ".torrent"
    head, tail = os.path.split(arg.path)
    headBasename = os.path.basename(head)
    postName = os.path.basename(arg.path)
    if head != SEEDING_DIR:
        logging.info("Attempting to create hardlinks for easy seeding...")
        destination = os.path.join(SEEDING_DIR, postName.strip())
        copy_folder_structure(arg.path, destination)
        logging.info("Hardlinks created at " + destination)
        torrent.path = destination
    logging.info("Generating torrent file hash. This will take a long while...")
    success = torrent.generate(callback=cb, interval=0.25)
    logging.info("Writing torrent file to disk...")
    torrent.write(runDir + torrentFileName)
    logging.info("Torrent file wrote to " + torrentFileName)

    if (arg.cover or os.path.exists(arg.path + os.sep + "cover.jpg") or os.path.exists(arg.path + os.sep + "cover.png")) and ptpimg_api:
        if os.path.exists(arg.path + os.sep + "cover.jpg"):
            cover = arg.path + os.sep + "cover.jpg"
        elif os.path.exists(arg.path + os.sep + "cover.png"):
            cover = arg.path + os.sep + "cover.png"
        else:
            cover = arg.cover
        logging.info("Uploading cover image to ptpimg")
        logging.info("Cover image path: " + cover)
        coverImgURL = uploadToPTPIMG(cover, ptpimg_api)
        with open(runDir + "coverImgURL.txt", 'w') as file:
            file.write(coverImgURL)
        logging.info("Cover image uploaded and URL added to " + runDir + "coverImgURL.txt")
        logging.info("URL: " + coverImgURL)


def check_missing_tracks(directory):
    """Checks if there are any missing tracks in a directory of music files.

    Args:
        directory (str): The directory to search for music files.

    Returns:
        A list of missing track numbers, or an empty list if no tracks are missing.
    """
    # Create a list of all music files in the directory
    music_files = [f for f in os.listdir(directory) if f.endswith('.mp3') or f.endswith('.m4a') or f.endswith('.flac')]

    # Create a list of track numbers for each file
    track_numbers = []
    for file in music_files:
        # Extract the track number from the file's metadata
        file_path = os.path.join(directory, file)
        try:
            tags = mutagen.File(file_path)
            track_number = tags['tracknumber'][0].split('/')[0]
            if track_number.isdigit():
                track_numbers.append(int(track_number))
        except Exception:
            pass

    # Check if there are any missing track numbers
    missing_tracks = []
    for i in range(1, len(track_numbers) + 1):
        if i not in track_numbers:
            missing_tracks.append(i)

    return missing_tracks


def add_track_position(folder_path):
    """
    This function takes a folder path as input and adds the track position to the file name if it's not there already.
    The track position is added at the beginning of the file name, followed by a space and a dash.
    For example, if the file name is "song.mp3" and it's the third track in the folder, it will be renamed to "03 - song.mp3".
    """
    # Get a list of all the files in the folder
    files = os.listdir(folder_path)

    # Filter for only music files (you can customize this depending on the file extensions you want to look for)
    music_files = [f for f in files if f.endswith('.mp3') or f.endswith('.wav') or f.endswith('.flac')]

    # Loop over the music files and add the track position to the file name if it's not already there
    for i, file_name in enumerate(music_files):
        # Check if the track position is already in the file name (we assume it's a two-digit number)
        if file_name[0:2].isdigit():
            # If it is, skip this file
            continue

        # If the track position isn't already in the file name, add it
        track_position = str(i + 1).zfill(2)  # Add leading zeros if necessary
        new_file_name = f"{track_position} - {file_name}"
        old_path = os.path.join(folder_path, file_name)
        new_path = os.path.join(folder_path, new_file_name)
        os.rename(old_path, new_path)
        logging.info("File renamed: " + new_path)

    logging.info("Track positions added successfully!")


def create_track_list(folder_path, output_file):
    """
    This function takes a folder path and an output file name as input, and creates a formatted list of every track
    found in the folder along with its position and length, and writes the list to the output file.
    """
    # Get a list of all the files in the folder
    files = os.listdir(folder_path)

    # Filter for only music files (you can customize this depending on the file extensions you want to look for)
    music_files = [f for f in files if f.endswith('.mp3') or f.endswith('.wav') or f.endswith('.flac')]

    # Sort the music files alphabetically
    music_files.sort()

    # Initialize an empty list to store the track information
    track_list = []

    # Loop over the music files and extract the track information
    for i, file_name in enumerate(music_files):
        # Get the track position
        track_position = str(i + 1).zfill(2)

        # Get the track length in seconds
        if file_name.endswith('.mp3'):
            # For MP3 files, use Mutagen to extract the track length
            audio = MP3(os.path.join(folder_path, file_name))
            track_length = int(audio.info.length)
            title = audio.get('TIT2', [file_name])[0]
        elif file_name.endswith('.flac'):
            # For FLAC files, use Mutagen to extract the track length from the STREAMINFO block
            audio = FLAC(os.path.join(folder_path, file_name))
            track_length = int(audio.info.length)
            title = audio.get('title', [file_name])[0]
        else:
            # For other file types, use os.path.getsize() to get the file size in bytes and estimate the length
            file_size = os.path.getsize(os.path.join(folder_path, file_name))
            track_length = int(file_size / 1000000) * 4  # 4 seconds per MB, this is just an estimate
            title = file_name

        # Convert the track length from seconds to a formatted string (XX:XX)
        minutes = str(track_length // 60).zfill(2)
        seconds = str(track_length % 60).zfill(2)
        track_length_str = f"{minutes}:{seconds}"

        # Add the track information to the track_list
        track_list.append(f"{track_position}. {title} ({track_length_str})")

    # Write the track_list to the output file
    with open(output_file, 'w') as f:
        f.write('\n'.join(track_list))

    logging.info(f"Track list written to {output_file} successfully!")


if __name__ == "__main__":
    main()
