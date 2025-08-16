import pymediainfo
import argparse
import logging
import sys
import guessit
import os
import re
import json
import requests

from pprint import pformat
from datetime import datetime

from torrent_utils.helpers import (
    get_tmdb_id, getInfoDump, getUserInput, get_season, get_episode, 
    getResolution, get_audio_info, get_colour_space, get_language_name
)
from torrent_utils.config_loader import load_settings, validate_settings

__VERSION = "1.1.1" # Incremented version
LOG_FORMAT = "%(asctime)s.%(msecs)03d %(levelname)-8s P%(process)06d.%(module)-12s %(funcName)-16sL%(lineno)04d %(message)s"
LOG_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

DUMPFILE = "mediainfo.txt"
BULK_DOWNLOAD_FILE = os.path.join(os.getcwd(), "bulkProcess.txt")


def main():
    parser = argparse.ArgumentParser(
        description="A script to intelligently rename media files based on metadata."
    )
    parser.add_argument(
        "--path",
        "-p",
        action="store",
        help="Path for file or folder to rename.",
        type=str
    )
    parser.add_argument(
        "-D", "--debug", action="store_true", help="Enable debug mode.", default=False
    )
    parser.add_argument(
        "-V", "--version", action="version", version=f"%(prog)s {__VERSION}",
    )
    parser.add_argument(
        "-t", "--tmdb",
        action="store",
        type=int,
        help="TMDB ID for the media.",
        default=None
    )
    parser.add_argument(
        "-g", "--group",
        action="store",
        type=str,
        help="Release group name.",
        default=None
    )
    parser.add_argument(
        "-s", "--source",
        action="store",
        type=str,
        help="Source of the media (e.g., Blu-ray, WEB-DL).",
        default=None
    )
    parser.add_argument(
        "--hardlink",
        action="store_true",
        default=False,
        help="Create a hardlink for the renamed file instead of renaming the original."
    )
    parser.add_argument(
        "--skip-prompts",
        action="store_true",
        default=False,
        help="Skip all user confirmation prompts."
    )
    parser.add_argument(
        "--huno-format",
        action="store_true",
        default=False,
        help="Use the HUNO-specific filename format (includes color space and language)."
    )

    arg = parser.parse_args()
    level = logging.INFO
    if arg.debug:
        level = logging.DEBUG

    logging.basicConfig(datefmt=LOG_DATE_FORMAT, format=LOG_FORMAT, level=level)
    logging.info(f"Version {__VERSION} starting...")

    # --- Load and Validate Settings ---
    settings = load_settings()
    required_settings = ['TMDB_API']
    validate_settings(settings, required_settings)
    tmdb_api = settings.get('TMDB_API')
    # --- END Settings Section ---

    pathList = []
    if arg.path is None:
        logging.info(f"No explicit path given, reading {BULK_DOWNLOAD_FILE}")
        if not os.path.exists(BULK_DOWNLOAD_FILE):
            logging.warning(f"No {BULK_DOWNLOAD_FILE} file found. Creating...")
            with open(BULK_DOWNLOAD_FILE, 'w') as f:
                f.write("")
        with open(BULK_DOWNLOAD_FILE, 'r', encoding='utf-8') as dlFile:
            file_contents = dlFile.read()
            if not file_contents:
                logging.error(f"No path given via arguments or in {BULK_DOWNLOAD_FILE}. Exiting...")
                sys.exit(-1)
            
            for line in file_contents.split('\n'):
                if line.strip(): # Ensure we don't add empty lines
                    pathList.append(line.strip().replace("\"", ""))
        logging.info(f"Loaded {len(pathList)} paths...")
    else:
        pathList.append(arg.path)

    pathList.sort()

    for path in pathList:
        guessItOutput = dict(guessit.guessit(os.path.basename(path)))
        logging.info(pformat(guessItOutput))

        group = arg.group
        if not group:
            if 'release_group' in guessItOutput:
                group = guessItOutput['release_group']
                group = re.sub(r"[\[\]\(\)\{\}]", " ", group).split()[0]
            else:
                group = "NOGRP"

        isMovie = guessItOutput.get('type') == 'movie'

        countryCode = None
        tmdbID = arg.tmdb
        if tmdbID is None and 'title' in guessItOutput:
            logging.info("No TMDB ID given. Attempting to find it automatically...")
            title = guessItOutput['title']
            if 'country' in guessItOutput:
                countryCode = guessItOutput['country'].alpha2
                title = f"{title} {countryCode}"
            
            tmdbID = get_tmdb_id(title, tmdb_api, isMovie)
            if tmdbID:
                logging.info(f"TMDB ID Found: {tmdbID}")
            else:
                tmdbID = input("Failed to find TMDB ID. Please input manually:\n")

        if os.path.exists(DUMPFILE):
            os.remove(DUMPFILE)

        logging.info("Reading MediaInfo...")
        mediaInfoText = getInfoDump(path, os.getcwd())
        mediaInfoJson = json.loads(mediaInfoText.strip())
        logging.debug(pformat(mediaInfoJson))

        tmdbData = None
        if tmdbID:
            logging.info("Getting TMDB info...")
            api_path = 'movie' if isMovie else 'tv'
            url = f'https://api.themoviedb.org/3/{api_path}/{tmdbID}?api_key={tmdb_api}'
            try:
                response = requests.get(url)
                response.raise_for_status()
                tmdbData = response.json()
            except requests.RequestException as e:
                logging.error(f"Failed to get TMDB data: {e}")
                continue # Skip to the next file

        showName = tmdbData.get('title' if isMovie else 'name', 'Unknown Show').replace(":", "")
        logging.info(f"Name: {showName}")

        date_key = 'release_date' if isMovie else 'first_air_date'
        year = ''
        if date_str := tmdbData.get(date_key):
            try:
                year = str(datetime.strptime(date_str, "%Y-%m-%d").year)
                logging.info(f"Year: {year}")
            except (ValueError, TypeError):
                logging.warning("Could not parse year from date string.")
        
        episodeNum = ""
        episodeTitle = guessItOutput.get('episode_title')
        if not isMovie:
            season = get_season(os.path.basename(path))
            episode = "E" + get_episode(os.path.basename(path))
            episodeNum = f"{season}{episode}"
            if episodeTitle:
                episodeNum += f" - {episodeTitle}"

        video_track = next((t for t in mediaInfoJson['media']['track'] if t['@type'] == 'Video'), None)
        if not video_track:
            logging.error(f"No video track found in {path}. Skipping.")
            continue
            
        width = video_track.get('Width')
        height = video_track.get('Height')
        frameRate = video_track.get('FrameRate')
        resolution = getResolution(width=width, height=height, frameRate=frameRate)
        if "Interlaced" in str(mediaInfoJson):
            resolution = resolution.replace("p", "i")
        logging.info(f"Resolution: {resolution}")

        videoCodec = "H264" # Default
        if 'HEVC' in video_track.get('Format', ''):
            if 'remux' in os.path.basename(path).lower(): videoCodec = 'HEVC'
            elif 'h265' in os.path.basename(path).lower() or 'hevc' in os.path.basename(path).lower(): videoCodec = 'H265'
            else: videoCodec = "x265"
        elif "VC-1" in video_track.get('Format', ''): videoCodec = "VC-1"
        elif "V_MPEG2" in video_track.get('CodecID', ''): videoCodec = "MPEG-2"
        elif 'remux' in os.path.basename(path).lower(): videoCodec = "AVC"
        elif 'x264' in os.path.basename(path).lower(): videoCodec = "x264"
        logging.info(f"Video Codec: {videoCodec}")

        audio = get_audio_info(mediaInfoJson)
        logging.info(f"Audio: {audio}")

        source = arg.source or ""
        logging.info(f"Source: {source}")

        container = guessItOutput.get('container', 'mkv')
        logging.info(f"Container: {container}")

        if countryCode:
            showName = f"{showName} {countryCode}"

        # --- Filename Construction ---
        if arg.huno_format:
            # HUNO-specific format
            colourSpace = get_colour_space(mediaInfoJson)
            logging.info(f"Colour Space: {colourSpace}")
            
            audio_track = next((t for t in mediaInfoJson['media']['track'] if t['@type'] == 'Audio'), None)
            language = "Eng" # Default
            if audio_track and 'Language' in audio_track:
                language = get_language_name(audio_track['Language'])
            else:
                language = input("No language found. Please input language:\n")
            logging.info(f"Language: {language}")

            if isMovie:
                base_name = f"{showName} ({year})"
                details = f"{resolution} {source} {videoCodec} {colourSpace} {audio} {language} - {group}"
                postFileName = f"{base_name} ({details}).{container}"
            else:
                base_name = f"{showName} ({year}) - {episodeNum}"
                details = f"{resolution} {source} {videoCodec} {colourSpace} {audio} {language} - {group}"
                postFileName = f"{base_name} ({details}).{container}"

        else:
            # Standard format
            # Adjust video codec format for standard naming
            if videoCodec == "H264":
                videoCodec = "H.264"
            elif videoCodec == "H265":
                videoCodec = "H.265"

            if isMovie:
                parts = [showName, year, resolution, source, audio.replace(' ', ''), videoCodec]
                postFileName = '.'.join(filter(None, parts)) + f"-{group}.{container}"
            else:
                parts = [showName, year, episodeNum, resolution, source, audio.replace(' ', ''), videoCodec]
                postFileName = '.'.join(filter(None, parts)) + f"-{group}.{container}"
            
            # Replace all spaces with dots for standard naming
            postFileName = postFileName.replace(' ', '.')

        # Clean up filename
        postFileName = postFileName.replace('..', '.').replace('\'', '').replace('é', 'e').replace('--', '-')
        logging.info("Final file name:\n" + postFileName)
        
        if arg.skip_prompts or getUserInput("Is this acceptable?"):
            if os.path.exists(DUMPFILE):
                os.remove(DUMPFILE)
            
            destination_path = os.path.join(os.path.dirname(path), postFileName)
            
            try:
                if arg.hardlink:
                    logging.info("Creating renamed hardlink...")
                    os.link(src=path, dst=destination_path)
                    logging.info(f"Hardlink created at: {destination_path}")
                else:
                    logging.info("Renaming file...")
                    os.rename(src=path, dst=destination_path)
                    logging.info(f"File renamed to: {destination_path}")
            except OSError as e:
                logging.error(f"Failed to rename/link file: {e}")


if __name__ == "__main__":
    main()
