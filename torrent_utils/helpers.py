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
import platform
import subprocess
from base64 import b64encode
from pprint import pformat

from babel import Locale
from pymediainfo import MediaInfo

DUMPFILE = "mediainfo.txt"

def download_mediainfo():
    """Downloads and extracts the MediaInfo CLI tool as a last resort."""
    url = "https://mediaarea.net/download/binary/mediainfo/22.12/MediaInfo_CLI_22.12_Windows_x64.zip"
    destination_folder = "Mediainfo"
    zip_path = "MediaInfo_CLI_temp.zip"

    logging.info(f"Downloading MediaInfo CLI from {url}...")
    try:
        response = requests.get(url, stream=True)
        response.raise_for_status()
        with open(zip_path, "wb") as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)
        
        logging.info(f"Unpacking to ./{destination_folder}/")
        with zipfile.ZipFile(zip_path, "r") as zip_ref:
            zip_ref.extractall(destination_folder)
        
        logging.info("MediaInfo CLI downloaded and unpacked successfully.")

    except requests.exceptions.RequestException as e:
        logging.error(f"Failed to download MediaInfo: {e}")
        sys.exit("Could not download required dependency.")
    except zipfile.BadZipFile:
        logging.error("Failed to unpack MediaInfo. The downloaded file may be corrupt.")
        sys.exit("Could not unpack required dependency.")
    finally:
        if os.path.exists(zip_path):
            os.remove(zip_path)

def install_mediainfo_with_package_manager():
    """Attempts to install MediaInfo using a detected package manager."""
    system = platform.system()
    if system == "Windows":
        if shutil.which("winget"):
            if getUserInput("MediaInfo not found. Attempt to install it using winget? (This may require administrator privileges)"):
                try:
                    logging.info("Running: winget install MediaInfo.MediaInfo -e --accept-source-agreements --accept-package-agreements")
                    # Using '-e' for exact match and agreements to reduce user interaction
                    subprocess.run(["winget", "install", "MediaInfo.MediaInfo", "-e", "--accept-source-agreements", "--accept-package-agreements"], check=True, shell=True)
                    if shutil.which("mediainfo"):
                        logging.info("MediaInfo installed successfully via winget.")
                        return True
                    else:
                        logging.error("Winget installation appeared to succeed, but 'mediainfo' is still not in the PATH. You may need to restart your terminal.")
                        return False
                except (subprocess.CalledProcessError, FileNotFoundError) as e:
                    logging.error(f"Winget installation failed: {e}")
                    return False
        else:
            logging.info("Windows Package Manager (winget) not found.")
            return False
    # Placeholder for other OSs
    elif system == "Darwin": # macOS
        logging.info("macOS detected, but Homebrew installation is not yet implemented.")
        return False
    elif system == "Linux":
        logging.info("Linux detected, but package manager installation is not yet implemented.")
        return False
    return False

def ensure_mediainfo_cli():
    """
    Checks if MediaInfo CLI is available. If not, attempts to install it
    via a package manager, falling back to a local download.
    """
    # 1. Best case: Check if 'mediainfo' is in the system's PATH
    if shutil.which("mediainfo"):
        logging.info("MediaInfo CLI found in system PATH.")
        return

    # 2. Second best case: Check for a local executable
    local_mediainfo_path = os.path.join("Mediainfo", "mediainfo.exe")
    if os.path.exists(local_mediainfo_path):
        logging.info(f"MediaInfo CLI found locally at '{local_mediainfo_path}'.")
        return

    # 3. Attempt to install with a package manager
    logging.warning("MediaInfo CLI not found in PATH or locally.")
    if install_mediainfo_with_package_manager():
        return # Success!

    # 4. If all else fails, fall back to local download
    logging.info("Package manager installation failed or was skipped. Falling back to local download.")
    download_mediainfo()

def get_video_codec(mediaInfo, filename, source):
    """Determines the video codec based on MediaInfo and filename."""
    video_track = next((t for t in mediaInfo['media']['track'] if t['@type'] == 'Video'), {})
    file_lower = filename.lower()
    source_lower = source.lower()
    
    video_format = video_track.get('Format', '')

    if 'AV1' in video_format:
        return "AV1"
    elif 'HEVC' in video_format:
        if 'remux' in source_lower:
            return 'HEVC'
        elif 'h265' in file_lower or 'hevc' in file_lower:
            return 'H265'
        else:
            return "x265"
    elif "VC-1" in video_format:
        return "VC-1"
    elif "V_MPEG2" in video_track.get('CodecID', ''):
        return "MPEG-2"
    elif 'remux' in source_lower:
        return "AVC"
    elif 'x264' in file_lower:
        return "x264"
    else:
        return "H264"

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

def is_valid_torf_hash(hash_str):
    """Checks if a string is a valid SHA-1 hash value for torf."""
    try:
        hash_bytes = bytes.fromhex(hash_str)
        if len(hash_bytes) % 20 != 0:
            return False
        return True
    except (ValueError, TypeError):
        return False

def convert_sha1_hash(hash_str):
    """Converts a SHA-1 hash value to the format used by torf."""
    hash_bytes = bytes.fromhex(hash_str)
    hash_pieces = [hash_bytes[i:i+20] for i in range(0, len(hash_bytes), 20)]
    return b''.join(hash_pieces)

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
