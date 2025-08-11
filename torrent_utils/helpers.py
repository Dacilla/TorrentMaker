import os
import logging
import sys
import requests
import cv2
import json
import re
import shutil
import ctypes
import Levenshtein
import numpy as np
import zipfile

from babel import Locale
from pymediainfo import MediaInfo

DUMPFILE = "mediainfo.txt"

def get_tmdb_id(name, api_key, isMovie):
    """
    Returns the TMDB ID of a TV show or movie given its name.
    """
    # The base URL for the TMDB API
    logging.info("Looking for title: " + name)

    if isMovie:
        url = f'https://api.themoviedb.org/3/search/movie?query={name}&api_key={api_key}'
    else:
        url = f'https://api.themoviedb.org/3/search/tv?query={name}&api_key={api_key}'

    # Send a GET request to the API to search for the TV show or movie
    response = requests.get(url)
    tmdb_id = None
    # Parse the response JSON to get the TMDB ID of the first result
    logging.debug(json.dumps(response.json(), indent=4))
    results = response.json()["results"]
    if len(results) > 0:
        for result in results:
            try:
                if isMovie:
                    logging.info(f"Comparing {name} to {result['original_title']}, ID {result['id']}")
                    titleSimilarity = max(similarity(name, result['original_title']), similarity(name, result['title']))
                else:
                    if 'name' in result:
                        logging.info(f"Comparing {name} to {result['name']}, aka {result['original_name']}, ID {result['id']}")
                        titleSimilarity = max(similarity(name, result['original_name']), similarity(name, result['name']))
                    else:
                        logging.info(f"Comparing {name} to {result['original_name']}, ID {result['id']}")
                        titleSimilarity = similarity(name, result['original_name'])
                logging.info("Similarity: " + str(titleSimilarity))
                if titleSimilarity > 85:
                    tmdb_id = result["id"]
                    break
            except KeyError:
                continue
        return tmdb_id

    # If there are no results, return None
    return tmdb_id


def getInfoDump(filePath: str, runDir: str):
    output = MediaInfo.parse(filename=filePath, output="", full=False)
    logging.debug(output)
    # don't ask, the output looks fine in the terminal, but writing it
    # to a file adds empty lines every second line. This deletes them
    logging.info("Creating mediainfo dump at " + os.path.join(runDir, DUMPFILE))
    with open(os.path.join(runDir, DUMPFILE), "w", encoding='utf-8') as f:
        f.write(output)
    with open(os.path.join(runDir, DUMPFILE), "r", encoding='utf-8') as fi:
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
    with open(os.path.join(runDir, DUMPFILE), 'w', encoding='utf-8') as fo:
        # Write the modified lines to the file
        for line in new_lines:
            fo.write(line)
    # Create a new mediainfo dump in JSON for parsing later
    output = MediaInfo.parse(filename=filePath, output="JSON", full=False)
    return output


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

def get_season(filename: str):
    # Use a regex to match the season string
    match = re.search(r'S\d\d', filename.upper())
    if match:
        # If a match is found, return the season string
        return match.group(0)
    else:
        # If no match is found, return an empty string
        return input('Season number was not found. Please input in the format S00\n')


def get_episode(filename: str):
    import re
    match = re.search(r'S\d{2}E\d{2}', filename.upper())
    if match:
        return match.group().split('E')[1]
    return input("Episode number can't be found. Please enter episode number in format 'E00'\n")


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

    print(f"Width: {width}p\nHeight: {height}p")
    return input("Resolution could not be found. Please input the resolution manually (e.g. 1080p, 2160p, 720p)\n")


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
        elif mediaInfo['media']['track'][trackNum]['Format'] == "MPEG Audio":
            if mediaInfo['media']['track'][trackNum]['Format_Profile'] == 'Layer 3':
                audioFormat = "MP3"
        elif 'Format_Settings_Endianness' in mediaInfo['media']['track'][trackNum]:
            if mediaInfo['media']['track'][trackNum]['Format_Settings_Endianness'] == "Little":
                audioFormat = "LPCM"
        elif 'Vorbis' in mediaInfo['media']['track'][trackNum]['Format']:
            audioFormat = "Vorbis"

    if audioFormat is None:
        logging.error("Audio format was not found")

    # Channels
    if 'Channels_Original' in mediaInfo['media']['track'][trackNum]:
        if int(mediaInfo['media']['track'][trackNum]['Channels']) > int(mediaInfo['media']['track'][trackNum]['Channels_Original']):
            channelsNum = mediaInfo['media']['track'][trackNum]['Channels']
        else:
            channelsNum = mediaInfo['media']['track'][trackNum]['Channels_Original']
    else:
        channelsNum = mediaInfo['media']['track'][trackNum]['Channels']
    try:
        if 'ChannelLayout_Original' in mediaInfo['media']['track'][trackNum]:
            channelsLayout = mediaInfo['media']['track'][trackNum]['ChannelLayout_Original']
        else:
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

def get_colour_space(mediaInfo):
    if "HDR" not in str(mediaInfo):
        return "SDR"
    try:
        if "Dolby Vision" in mediaInfo['media']['track'][1]['HDR_Format']:
            try:
                if "HDR10" in mediaInfo['media']['track'][1]['HDR_Format_Compatibility']:
                    if "HDR10+" in mediaInfo['media']['track'][1]['HDR_Format_Compatibility']:
                        return "DV HDR10+"
                    return "DV HDR"
                else:
                    return "DV"
            except KeyError:
                return "DV"
    except KeyError:
        logging.debug("Keyerror when looking for DV format")
        if mediaInfo['media']['track'][1]['colour_primaries'] in ['BT.2020', 'DCI-P3'] or mediaInfo['media']['track'][1]['transfer_characteristics'] in ['PQ', 'HLG']:
            return "HDR"
    if "HDR10+" in mediaInfo['media']['track'][1]['HDR_Format_Compatibility']:
        return "HDR10+"
    return "HDR"

def get_language_name(language_code):
    try:
        # Create a Locale instance with the given language code
        locale = Locale(language_code)
        # Return the language name in english
        return locale.get_display_name('en')
    except Exception:
        # If the language code is invalid or the name cannot be determined, return an empty string
        return ''

def similarity(s1, s2):
    distance = Levenshtein.distance(s1, s2)
    max_len = max(len(s1), len(s2))
    return 100 * (1 - distance / max_len)

def has_folders(path_to_parent):
    folders = list(folders_in(path_to_parent))
    return len(folders) != 0

def folders_in(path_to_parent):
    for fname in os.listdir(path_to_parent):
        if os.path.isdir(os.path.join(path_to_parent, fname)):
            yield os.path.join(path_to_parent, fname)

def cb(torrent, filepath, pieces_done, pieces_total):
    print(f'{pieces_done/pieces_total*100:3.0f} % done', end="\r")

def uploadToPTPIMG(imageFile: str, api_key):
    # Stole this code from https://github.com/DeadNews/images-upload-cli
    response = requests.post(
        url="https://ptpimg.me/upload.php",
        data={"api_key": api_key},
        files={"file-upload[0]": open(imageFile, 'rb').read()},
    )
    if not response.ok:
        try:
            logging.error("Upload to ptpimg failed, trying again...")
            response = requests.post(
                url="https://ptpimg.me/upload.php",
                data={"api_key": api_key},
                files={"file-upload[0]": open(imageFile, 'rb').read()},
            )
            if not response.ok:
                logging.error("Upload failed again. Something is probably wrong with ptpimg")
                raise Exception(response.json())
        except Exception:
            return None

    logging.debug(response.json())

    return f"https://ptpimg.me/{response.json()[0]['code']}.{response.json()[0]['ext']}"

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

def qbitInject(qbit_host, qbit_username, qbit_password, category, runDir, torrentFileName, paused, postName, seedTimeLimit=None):
    import qbittorrentapi
    logging.info("Logging in to qbit...")
    qb = qbittorrentapi.Client(qbit_host, username=qbit_username, password=qbit_password, REQUESTS_ARGS={'timeout': (60, 60)})
    logging.info("Logged in to qbit")
    torrent_file = os.path.join(runDir, torrentFileName)
    logging.info(f"Injecting {torrent_file} to qbit...")
    try:
        result = qb.torrents_add(is_skip_checking=True, torrent_files=torrent_file, is_paused=paused, category=category, tags="Self-Upload", rename=postName, seeding_time_limit=seedTimeLimit)
    except Exception as e:
        print(e)
    if result == "Ok.":
        logging.info("Torrent successfully injected.")
    else:
        logging.critical(result)

def FileOrFolder(path: str):
    # returns 1 if file, 2 if folder, 0 if neither
    if os.path.isfile(path):
        return 1
    elif os.path.isdir(path):
        return 2
    else:
        return 0
