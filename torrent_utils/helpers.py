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
import winsound
import uuid
import contextlib
import time
import random
from base64 import b64encode
from pprint import pformat
from urllib.parse import unquote

from babel import Locale
from pymediainfo import MediaInfo

DUMPFILE = "mediainfo.txt"
_SLOWPICS_CONTEXT = {
    "session": None,
    "browser_id": None,
    "xsrf_token": None,
    "bootstrapped_at": 0.0,
    "auth_fingerprint": None,
}
_SLOWPICS_CONTEXT_TTL_SECONDS = 300

def get_path_list(arg_path, bulk_file_name):
    """
    Gets a list of paths from either a direct command-line argument or a bulk file.
    
    Args:
        arg_path (str or None): The path provided via a command-line argument.
        bulk_file_name (str): The name of the file to read for bulk processing.

    Returns:
        list: A sorted list of paths to be processed.
    """
    pathList = []
    if arg_path:
        pathList.append(arg_path)
    else:
        logging.info(f"No explicit path given, reading {bulk_file_name}")
        if not os.path.exists(bulk_file_name):
            logging.warning(f"No {bulk_file_name} file found. Creating a blank one.")
            with open(bulk_file_name, 'w', encoding='utf-8') as f:
                f.write("")
            return []  # Return an empty list as there's nothing to process

        with open(bulk_file_name, 'r', encoding='utf-8') as f:
            lines = [line.strip().replace("\"", "") for line in f if line.strip()]
            if not lines:
                logging.error(f"No paths found in {bulk_file_name}. Please add paths to the file.")
                sys.exit(-1)
            pathList.extend(lines)
            
    if not pathList:
        logging.error("No input paths were found to process. Exiting.")
        sys.exit(-1)

    logging.info(f"Loaded {len(pathList)} path(s) to process.")
    return sorted(pathList)


def download_mediainfo():
    """Downloads and extracts the MediaInfo CLI tool as a last resort."""
    url = "https://mediaarea.net/download/binary/mediainfo/22.12/MediaInfo_CLI_22.12_Windows_x64.zip"
    destination_folder = "Mediainfo"
    zip_path = "MediaInfo_CLI_temp.zip"

    logging.info(f"Downloading MediaInfo CLI from {url}...")
    try:
        response = requests.get(url, stream=True, timeout=30)
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

def _install_with_winget(package_id: str, binary_name: str) -> bool:
    """Attempts to install a package using winget on Windows. Returns True on success."""
    if platform.system() != "Windows" or not shutil.which("winget"):
        return False
    try:
        logging.info(f"Running: winget install {package_id} -e --accept-source-agreements --accept-package-agreements")
        subprocess.run(
            ["winget", "install", package_id, "-e", "--accept-source-agreements", "--accept-package-agreements"],
            check=True,
        )
        if shutil.which(binary_name):
            logging.info(f"{package_id} installed successfully via winget.")
            return True
        logging.error(f"Winget install appeared to succeed but '{binary_name}' is still not in PATH. You may need to restart your terminal.")
        return False
    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        logging.error(f"Winget installation failed: {e}")
        return False


def install_mediainfo_with_package_manager():
    """Attempts to install MediaInfo using a detected package manager."""
    if platform.system() == "Windows" and shutil.which("winget"):
        prompt = (
            "MediaInfo is required to read technical data from media files for accurate torrent naming. "
            "It was not found on your system. Attempt to install it now using winget? (This may require administrator privileges)"
        )
        if getUserInput(prompt):
            return _install_with_winget("MediaInfo.MediaInfo", "mediainfo")
        return False
    logging.info("Windows Package Manager (winget) not found.")
    return False

def ensure_mediainfo_cli():
    """
    Checks if MediaInfo CLI is available. If not, prompts the user to install it.
    """
    if shutil.which("mediainfo") or os.path.exists(os.path.join("Mediainfo", "mediainfo.exe")):
        logging.info("MediaInfo CLI found.")
        return

    logging.warning("MediaInfo CLI not found in PATH or locally.")
    if install_mediainfo_with_package_manager():
        return

    logging.info("Package manager installation failed or was skipped.")
    prompt = (
        "As a last resort, the script can download and extract MediaInfo locally. "
        "MediaInfo is required to read technical data from media files. Do you want to proceed with the local download?"
    )
    if getUserInput(prompt):
        download_mediainfo()
    else:
        logging.error("MediaInfo is required to proceed. Exiting.")
        sys.exit(1)

def download_flac():
    """Downloads and extracts the LATEST FLAC command-line tools."""
    download_page_url = "https://ftp.osuosl.org/pub/xiph/releases/flac/"
    latest_zip_filename = None
    
    try:
        logging.info(f"Checking for the latest FLAC version at {download_page_url}...")
        response = requests.get(download_page_url, timeout=15)
        response.raise_for_status()
        
        win_zip_pattern = r'href="(flac-[\d\.]+-win\.zip)"'
        found_files = re.findall(win_zip_pattern, response.text)
        
        if not found_files:
            raise ValueError("No Windows FLAC zip files found on the download page.")
            
        latest_version_tuple = (0, 0, 0)
        
        for filename in found_files:
            version_str_match = re.search(r'flac-([\d\.]+)-win\.zip', filename)
            if version_str_match:
                version_str = version_str_match.group(1)
                current_version_tuple = tuple(map(int, version_str.split('.')))
                
                if current_version_tuple > latest_version_tuple:
                    latest_version_tuple = current_version_tuple
                    latest_zip_filename = filename
                    
        if not latest_zip_filename:
             raise ValueError("Could not determine the latest FLAC version.")
             
        logging.info(f"Found latest FLAC version: {'.'.join(map(str, latest_version_tuple))}")
        
    except (requests.exceptions.RequestException, ValueError) as e:
        logging.error(f"Could not automatically find the latest FLAC version: {e}")
        logging.warning("Falling back to a known recent version.")
        latest_zip_filename = "flac-1.4.3-win.zip"

    url = f"https://ftp.osuosl.org/pub/xiph/releases/flac/{latest_zip_filename}"
    destination_folder = "FLAC"
    zip_path = "flac_temp.zip"

    logging.info(f"Downloading FLAC tools from {url}...")
    try:
        response = requests.get(url, stream=True, timeout=30)
        response.raise_for_status()
        with open(zip_path, "wb") as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)
        
        logging.info(f"Unpacking to ./{destination_folder}/")
        with zipfile.ZipFile(zip_path, "r") as zip_ref:
            temp_extract_folder = "flac_temp_extract"
            zip_ref.extractall(temp_extract_folder)
            
            extracted_dir_name = os.listdir(temp_extract_folder)[0]
            source_dir = os.path.join(temp_extract_folder, extracted_dir_name)
            
            if os.path.exists(destination_folder):
                shutil.rmtree(destination_folder)
            shutil.move(source_dir, destination_folder)
            
            shutil.rmtree(temp_extract_folder)

        logging.info("FLAC tools downloaded and unpacked successfully.")

    except requests.exceptions.RequestException as e:
        logging.error(f"Failed to download FLAC: {e}")
        sys.exit("Could not download required dependency.")
    except (zipfile.BadZipFile, IndexError) as e:
        logging.error(f"Failed to unpack FLAC: {e}. The downloaded file may be corrupt.")
        sys.exit("Could not unpack required dependency.")
    finally:
        if os.path.exists(zip_path):
            os.remove(zip_path)
        if os.path.exists("flac_temp_extract"):
            shutil.rmtree("flac_temp_extract")

def install_flac_with_package_manager():
    """Attempts to install FLAC using a detected package manager."""
    if platform.system() == "Windows" and shutil.which("winget"):
        prompt = (
            "The FLAC command-line tool is required for the --fixMD5 feature. It was not found on your system. "
            "Attempt to install it now using winget? (This may require administrator privileges)"
        )
        if getUserInput(prompt):
            return _install_with_winget("Xiph.Flac", "flac")
        return False
    return False

def ensure_flac_cli():
    """
    Checks if FLAC CLI is available. If not, prompts the user to install it.
    """
    local_flac_path = os.path.join("FLAC", "win64", "flac.exe")
    if shutil.which("flac"):
        logging.info("FLAC CLI found in system PATH.")
        return
    if os.path.exists(local_flac_path):
        logging.info(f"FLAC CLI found locally at '{local_flac_path}'.")
        os.environ["PATH"] += os.pathsep + os.path.join(os.getcwd(), "FLAC", "win64")
        return

    logging.warning("FLAC CLI not found in PATH or locally.")
    if install_flac_with_package_manager():
        return

    logging.info("Package manager installation failed or was skipped.")
    prompt = (
        "As a last resort, the script can download and extract the FLAC tools locally. "
        "These are required for the --fixMD5 feature. Do you want to proceed with the local download?"
    )
    if getUserInput(prompt):
        download_flac()
        if os.path.exists(local_flac_path):
            os.environ["PATH"] += os.pathsep + os.path.join(os.getcwd(), "FLAC", "win64")
    else:
        logging.error("FLAC CLI is required for the --fixMD5 feature. Exiting.")
        sys.exit(1)


def get_tmdb_id(name, api_key, isMovie, year=None):
    """
    Returns (tmdb_id, candidates) where tmdb_id is the confident match (or None)
    and candidates is a list of dicts with keys: id, name, year, similarity.
    If year is provided, it is used as a tiebreaker: a high-similarity match whose
    year does not match will not be auto-accepted and will fall through to prompting.
    """
    logging.info("Looking for title: " + name)

    endpoint = 'movie' if isMovie else 'tv'
    url = f'https://api.themoviedb.org/3/search/{endpoint}'
    try:
        response = requests.get(url, params={'query': name, 'api_key': api_key}, timeout=15)
        response.raise_for_status()
        results = response.json().get("results", [])

        if not results:
            return None, []

        candidates = []
        for result in results[:10]:
            try:
                if isMovie:
                    title = result.get('title', '')
                    original_title = result.get('original_title', '')
                    logging.info(f"Comparing {name} to {original_title}, ID {result.get('id')}")
                    titleSimilarity = max(similarity(name, original_title), similarity(name, title))
                    display_name = title or original_title
                    result_year = (result.get('release_date') or '')[:4]
                else:
                    show_name = result.get('name', '')
                    original_name = result.get('original_name', '')
                    logging.info(f"Comparing {name} to {show_name}, aka {original_name}, ID {result.get('id')}")
                    titleSimilarity = max(similarity(name, original_name), similarity(name, show_name))
                    display_name = show_name or original_name
                    result_year = (result.get('first_air_date') or '')[:4]

                logging.info("Similarity: " + str(titleSimilarity))
                candidates.append({
                    'id': result.get('id'),
                    'name': display_name,
                    'year': result_year,
                    'similarity': titleSimilarity,
                })
                if titleSimilarity > 85:
                    # If a year hint was provided, only auto-accept if it matches
                    if year and result_year and str(year) != result_year:
                        logging.info(f"High similarity but year mismatch: expected {year}, got {result_year} — skipping auto-accept")
                        continue
                    return result.get('id'), candidates
            except (KeyError, TypeError):
                continue

        candidates.sort(key=lambda c: c['similarity'], reverse=True)
        return None, candidates[:5]
    except requests.exceptions.RequestException as e:
        logging.error(f"Failed to search TMDB for '{name}': {e}")
        return None, []


def getInfoDump(filePath: str, runDir: str, filename: str = DUMPFILE):
    output = MediaInfo.parse(filename=filePath, output="", full=False)
    logging.debug(output)
    # don't ask, the output looks fine in the terminal, but writing it
    # to a file adds empty lines every second line. This deletes them
    output_path = os.path.join(runDir, filename)
    logging.info("Creating mediainfo dump at " + output_path)
    with open(output_path, "w", encoding='utf-8') as f:
        f.write(output)
    with open(output_path, "r", encoding='utf-8') as fi:
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
    with open(output_path, 'w', encoding='utf-8') as fo:
        # Write the modified lines to the file
        for line in new_lines:
            fo.write(line)
    # Create a new mediainfo dump in JSON for parsing later
    output = MediaInfo.parse(filename=filePath, output="JSON", full=False)
    return output


_last_alert_time = 0.0
TORRENT_DONE_ALERT_SECONDS = 10.0

def _alerts_disabled() -> bool:
    return (
        os.environ.get("PYTEST_CURRENT_TEST") is not None
        or os.environ.get("TORRENTMAKER_DISABLE_ALERTS", "").lower() in {"1", "true", "yes", "on"}
    )


def _terminal_is_focused() -> bool:
    """Returns True if the console window associated with this process is the foreground window.
    Note: unreliable under Windows Terminal, which uses a hidden conhost window."""
    try:
        hwnd_console = ctypes.windll.kernel32.GetConsoleWindow()
        hwnd_foreground = ctypes.windll.user32.GetForegroundWindow()
        return hwnd_console != 0 and hwnd_console == hwnd_foreground
    except Exception:
        return False


def play_alert(kind: str = "input"):
    """Play a system sound. kind='input' for prompts, 'done' for hashing complete.
    Suppressed if called within 10 seconds of the last alert, or if the terminal is in focus."""
    global _last_alert_time
    import time
    if _alerts_disabled():
        return
    now = time.monotonic()
    if now - _last_alert_time < 10.0:
        return
    if _terminal_is_focused():
        return
    _last_alert_time = now
    try:
        if kind == "done":
            winsound.MessageBeep(winsound.MB_ICONASTERISK)
        else:
            winsound.MessageBeep(winsound.MB_ICONEXCLAMATION)
    except Exception:
        pass


def make_torrent_progress_callback(alert_after_seconds: float = TORRENT_DONE_ALERT_SECONDS):
    started_at = time.monotonic()

    def progress_callback(torrent, filepath, pieces_done, pieces_total):
        if pieces_total:
            print(f'{pieces_done/pieces_total*100:3.0f} % done', end="\r")
        else:
            print('  0 % done', end="\r")

        if pieces_done == pieces_total and time.monotonic() - started_at > alert_after_seconds:
            play_alert("done")

    return progress_callback


def getUserInput(question: str, alert: bool = True):
    question = question + " [y, n]"
    Userinput = None
    while Userinput not in ["y", "yes", "n", "no"]:
        if alert:
            play_alert("input")
        Userinput = input(question)
        if Userinput in ["y", "yes"]:
            return True
        if Userinput in ["n", "no"]:
            return False
        logging.warning("Given input is not valid. Must be one of [y,n]\n")

def get_season(filename: str) -> str:
    """Returns the season string (e.g. 'S03') from a filename, or raises ValueError."""
    match = re.search(r'S(\d{1,3})', filename.upper())
    if match:
        return f"S{match.group(1).zfill(2)}"
    raise ValueError(f"Season number not found in filename: {filename}")


def get_episode(filename: str) -> str:
    """Returns the zero-padded episode number string (e.g. '05') from a filename, or raises ValueError."""
    match = re.search(r'S\d{1,3}E(\d{1,3})', filename.upper())
    if match:
        return match.group(1).zfill(2)
    raise ValueError(f"Episode number not found in filename: {filename}")

def similarity(s1, s2):
    distance = Levenshtein.distance(s1, s2)
    max_len = max(len(s1), len(s2))
    if max_len == 0: return 100.0
    return 100 * (1 - distance / max_len)

def has_folders(path_to_parent):
    folders = list(folders_in(path_to_parent))
    return len(folders) != 0

def folders_in(path_to_parent):
    for fname in os.listdir(path_to_parent):
        if os.path.isdir(os.path.join(path_to_parent, fname)):
            yield os.path.join(path_to_parent, fname)

def cb(torrent, filepath, pieces_done, pieces_total):
    if pieces_total:
        print(f'{pieces_done/pieces_total*100:3.0f} % done', end="\r")
    else:
        print('  0 % done', end="\r")

def uploadToPTPIMG(imageFile: str, api_key: str):
    """Uploads an image to PTPImg with robust error handling."""
    try:
        with open(imageFile, 'rb') as f:
            file_payload = {"file-upload[0]": f.read()}

        response = requests.post(
            url="https://ptpimg.me/upload.php",
            data={"api_key": api_key},
            files=file_payload,
            timeout=30,
        )
        response.raise_for_status()

        response_data = response.json()
        return f"https://ptpimg.me/{response_data[0]['code']}.{response_data[0]['ext']}"

    except requests.exceptions.RequestException as e:
        logging.error(f"PTPImg upload failed for {os.path.basename(imageFile)}: {e}")
        return None
    except (json.JSONDecodeError, IndexError, KeyError) as e:
        logging.error(f"PTPImg returned invalid data for {os.path.basename(imageFile)}: {e}")
        return None

def upload_to_onlyimage(file_path: str, api_key: str):
    """Uploads an image to OnlyImage (Chevereto) with robust error handling."""
    api_endpoint = "https://onlyimage.org/api/1/upload"
    try:
        with open(file_path, 'rb') as f:
            files = {'source': (os.path.basename(file_path), f)}
            data = {'key': api_key}
            response = requests.post(api_endpoint, data=data, files=files, timeout=30)
        response.raise_for_status()

        response_data = response.json()
        if response_data.get('status_code') == 200:
            image_url = response_data['image']['url']
            return image_url
        else:
            error_msg = response_data.get('error', {}).get('message', 'Unknown error')
            logging.error(f"OnlyImage upload failed for {os.path.basename(file_path)}: {error_msg}")
            return None

    except requests.exceptions.RequestException as e:
        logging.error(f"OnlyImage upload failed for {os.path.basename(file_path)}: {e}")
        return None
    except (json.JSONDecodeError, KeyError) as e:
        logging.error(f"OnlyImage returned invalid data for {os.path.basename(file_path)}: {e}")
        return None

def upload_to_hawkepics(file_path: str, api_key: str):
    """Uploads an image to hawke.pics (Chevereto) with robust error handling."""
    api_endpoint = "https://hawke.pics/api/1/upload"
    try:
        with open(file_path, 'rb') as f:
            files = {'source': (os.path.basename(file_path), f)}
            headers = {'X-API-Key': api_key}
            response = requests.post(api_endpoint, headers=headers, files=files, timeout=30)
        response.raise_for_status()

        response_data = response.json()
        if response_data.get('status_code') == 200:
            image_url = response_data['image']['url']
            return image_url
        else:
            error_msg = response_data.get('error', {}).get('message', 'Unknown error')
            logging.error(f"hawke.pics upload failed for {os.path.basename(file_path)}: {error_msg}")
            return None

    except requests.exceptions.RequestException as e:
        logging.error(f"hawke.pics upload failed for {os.path.basename(file_path)}: {e}")
        return None
    except (json.JSONDecodeError, KeyError) as e:
        logging.error(f"hawke.pics returned invalid data for {os.path.basename(file_path)}: {e}")
        return None

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
        logging.error(f"qBittorrent injection failed: {e}")
        return
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

def upload_to_imgbb(file_path: str, apiKey: str):
    """Uploads an image to ImgBB with robust error handling."""
    api_endpoint = "https://api.imgbb.com/1/upload"
    try:
        with open(file_path, "rb") as imagefile:
            payload = {
                "key": apiKey,
                "image": b64encode(imagefile.read()),
            }
        response = requests.post(api_endpoint, payload, timeout=20)
        response.raise_for_status()
        
        response_data = response.json()
        image_url = response_data["data"]["url"]
        image_url_viewer = response_data["data"]["url_viewer"]
        return image_url, image_url_viewer
            
    except requests.exceptions.RequestException as e:
        logging.error(f"ImgBB upload failed for {os.path.basename(file_path)}: {e}")
        return None, None
    except (json.JSONDecodeError, KeyError) as e:
        logging.error(f"ImgBB returned invalid data for {os.path.basename(file_path)}: {e}")
        return None, None


def upload_to_catbox(file_path: str, user_hash: str = None):
    """Uploads a file to Catbox with robust error handling."""
    url = "https://catbox.moe/user/api.php"
    data = {'reqtype': 'fileupload'}
    if user_hash:
        data['userhash'] = user_hash

    try:
        with open(file_path, 'rb') as f:
            files = {'fileToUpload': (os.path.basename(file_path), f)}
            response = requests.post(url, data=data, files=files, timeout=20)
        response.raise_for_status()
        
        direct_link = response.text
        if "catbox.moe" in direct_link:
             return direct_link
        else:
             logging.error(f"Catbox returned an error message: {direct_link}")
             return None

    except requests.exceptions.RequestException as e:
        logging.error(f"Catbox upload failed for {os.path.basename(file_path)}: {e}")
        return None

def upload_to_slowpics(
    image_pairs,
    collection_name,
    labels=None,
    hdr_type="SDR",
    remember_me=None,
    session_cookie=None,
    return_status=False,
):
    """
    Upload source/encode frame pairs to slow.pics comparison.

    Args:
        image_pairs: list of (source_path, encode_path) tuples, one per frame in order
        collection_name: the torrent name string used as collection title
        labels: list of 2 labels, defaults to ["Source", "Encode"]
        hdr_type: HDR type string (e.g. "SDR", "HDR10+", "DV")
        remember_me: optional slow.pics remember-me cookie value
        session_cookie: optional slow.pics SLP-SESSION cookie value
        return_status: if True, returns dict with success/url/error_code/error_message

    Returns:
        When return_status=False (default): slow.pics URL string or None.
        When return_status=True: dict with keys success, url, error_code, error_message.
    """
    if labels is None:
        labels = ["Source", "Encode"]

    if len(labels) < 2:
        labels = ["Source", "Encode"]

    def _result(url=None, error_code=None, error_message=None):
        status = {
            "success": bool(url),
            "url": url,
            "error_code": error_code,
            "error_message": error_message,
        }
        if return_status:
            return status
        return url

    def _log_error_response(stage, response):
        snippet = (response.text or "").strip().replace("\n", " ")[:350]
        logging.debug(
            "slow.pics %s failed | status=%s | content-type=%s | cf-ray=%s | body=%s",
            stage,
            response.status_code,
            response.headers.get("content-type"),
            response.headers.get("cf-ray"),
            snippet,
        )

    def _extract_api_error(response):
        try:
            payload = response.json()
            if isinstance(payload, dict):
                return payload.get("error"), payload.get("message")
        except Exception:
            pass
        return None, None

    def _retry_after_seconds(response, fallback_seconds):
        retry_after = response.headers.get("Retry-After")
        if retry_after and retry_after.isdigit():
            return max(1, int(retry_after))
        return fallback_seconds

    def _request_with_retry(session, method, url, stage, **kwargs):
        max_attempts = 4
        response = None
        for attempt in range(max_attempts):
            response = session.request(method, url, **kwargs)
            if response.status_code != 429:
                return response
            wait_seconds = _retry_after_seconds(response, min(12, 2 + (attempt * 3)))
            wait_seconds += random.uniform(0.0, 0.5)
            logging.warning(
                "slow.pics rate-limited during %s (attempt %s/%s). Waiting %.1fs and retrying.",
                stage,
                attempt + 1,
                max_attempts,
                wait_seconds,
            )
            time.sleep(wait_seconds)
        return response

    def _bootstrap_context(force_refresh=False):
        now = time.monotonic()
        auth_fingerprint = (
            "remember" if remember_me else "",
            "session" if session_cookie else "",
        )
        cached_session = _SLOWPICS_CONTEXT.get("session")
        cached_age = now - _SLOWPICS_CONTEXT.get("bootstrapped_at", 0.0)
        if (
            not force_refresh
            and cached_session is not None
            and cached_age < _SLOWPICS_CONTEXT_TTL_SECONDS
            and _SLOWPICS_CONTEXT.get("auth_fingerprint") == auth_fingerprint
        ):
            return (
                cached_session,
                _SLOWPICS_CONTEXT.get("browser_id"),
                _SLOWPICS_CONTEXT.get("xsrf_token"),
            )

        session = requests.Session()
        if remember_me or session_cookie:
            logging.info(
                "slow.pics authenticated mode enabled (cookies: remember-me=%s, SLP-SESSION=%s)",
                "set" if remember_me else "unset",
                "set" if session_cookie else "unset",
            )
        if remember_me:
            session.cookies.set("remember-me", remember_me, domain="slow.pics", path="/")
        if session_cookie:
            session.cookies.set("SLP-SESSION", session_cookie, domain="slow.pics", path="/")
        bootstrap_headers = {
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:149.0) "
                "Gecko/20100101 Firefox/149.0"
            ),
        }
        bootstrap = _request_with_retry(
            session,
            "GET",
            "https://slow.pics/comparison",
            stage="bootstrap GET /comparison",
            headers=bootstrap_headers,
            timeout=30,
        )
        if bootstrap.status_code >= 400:
            _log_error_response("bootstrap GET /comparison", bootstrap)
        bootstrap.raise_for_status()

        xsrf_token = session.cookies.get("XSRF-TOKEN")
        if not xsrf_token:
            raise RuntimeError("missing XSRF-TOKEN cookie")
        xsrf_token = unquote(xsrf_token)

        browser_id = str(uuid.uuid4())
        session.cookies.set("BROWSER-ID", browser_id, domain="slow.pics", path="/")
        if remember_me:
            session.cookies.set("remember-me", remember_me, domain="slow.pics", path="/")
        if session_cookie:
            session.cookies.set("SLP-SESSION", session_cookie, domain="slow.pics", path="/")
        _SLOWPICS_CONTEXT["session"] = session
        _SLOWPICS_CONTEXT["browser_id"] = browser_id
        _SLOWPICS_CONTEXT["xsrf_token"] = xsrf_token
        _SLOWPICS_CONTEXT["bootstrapped_at"] = time.monotonic()
        _SLOWPICS_CONTEXT["auth_fingerprint"] = auth_fingerprint
        return session, browser_id, xsrf_token

    try:
        for attempt in range(2):
            force_refresh = attempt == 1
            session, browser_id, xsrf_token = _bootstrap_context(force_refresh=force_refresh)

            headers = {
                "Accept": "*/*",
                "Accept-Language": "en-US,en;q=0.9",
                "Origin": "https://slow.pics",
                "Referer": "https://slow.pics/comparison",
                "Sec-Fetch-Dest": "empty",
                "Sec-Fetch-Mode": "cors",
                "Sec-Fetch-Site": "same-origin",
                "X-XSRF-TOKEN": xsrf_token,
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:149.0) "
                    "Gecko/20100101 Firefox/149.0"
                ),
            }

            create_form = {
                "collectionName": collection_name,
                "browserId": browser_id,
                "optimizeImages": "true",
                "desiredFileType": "image/webp",
                "hentai": "false",
                "public": "true",
                "visibility": "PUBLIC",
                "removeAfter": "",
                "canvasMode": "none",
                "imageFit": "none",
                "imagePosition": "center",
            }

            for i, _ in enumerate(image_pairs):
                create_form[f"comparisons[{i}].name"] = f"{i:02d}"
                create_form[f"comparisons[{i}].hentai"] = "false"
                create_form[f"comparisons[{i}].sortOrder"] = str(i)
                for j, label in enumerate(labels[:2]):
                    create_form[f"comparisons[{i}].images[{j}].name"] = label.lower()
                    create_form[f"comparisons[{i}].images[{j}].sortOrder"] = str(j)

            create_response = _request_with_retry(
                session,
                "POST",
                "https://slow.pics/upload/comparison",
                stage="create comparison",
                headers=headers,
                data=create_form,
                timeout=120,
            )
            if create_response.status_code >= 400:
                _log_error_response("create comparison", create_response)
            create_error_code, create_error_msg = _extract_api_error(create_response)
            if create_error_code == "DAILY_LIMIT_UPLOAD":
                logging.warning(
                    "slow.pics daily upload limit reached. Message: %s",
                    create_error_msg or create_error_code,
                )
                return _result(error_code=create_error_code, error_message=create_error_msg)
            if create_response.status_code in (401, 403) and attempt == 0:
                logging.warning("slow.pics rejected current session; refreshing session context and retrying once.")
                continue
            create_response.raise_for_status()
            create_data = create_response.json()

            key = create_data.get("key")
            collection_uuid = create_data.get("collectionUuid")
            image_uuid_sections = create_data.get("images")

            if not key:
                logging.warning("slow.pics returned no key in create response")
                return _result(error_code="MISSING_KEY", error_message="slow.pics returned no key in create response")
            if not collection_uuid or not isinstance(image_uuid_sections, list):
                url = f"https://slow.pics/c/{key}"
                logging.info(f"slow.pics comparison uploaded: {url}")
                return _result(url=url)

            with contextlib.ExitStack() as stack:
                for i, (src_path, enc_path) in enumerate(image_pairs):
                    uuids = image_uuid_sections[i] if i < len(image_uuid_sections) else None
                    if not uuids or len(uuids) < 2:
                        continue

                    for j, image_path in enumerate([src_path, enc_path]):
                        image_file = stack.enter_context(open(image_path, "rb"))
                        upload_form = {
                            "collectionUuid": collection_uuid,
                            "imageUuid": uuids[j],
                            "browserId": browser_id,
                        }
                        upload_files = {"file": (os.path.basename(image_path), image_file, "image/png")}
                        upload_response = _request_with_retry(
                            session,
                            "POST",
                            "https://slow.pics/upload/image",
                            stage="upload image",
                            headers=headers,
                            data=upload_form,
                            files=upload_files,
                            timeout=120,
                        )
                        if upload_response.status_code >= 400:
                            _log_error_response("upload image", upload_response)
                        upload_error_code, upload_error_msg = _extract_api_error(upload_response)
                        if upload_error_code == "DAILY_LIMIT_UPLOAD":
                            logging.warning(
                                "slow.pics daily upload limit reached during image upload. Message: %s",
                                upload_error_msg or upload_error_code,
                            )
                            return _result(error_code=upload_error_code, error_message=upload_error_msg)
                        if upload_response.status_code in (401, 403) and attempt == 0:
                            logging.warning("slow.pics rejected image upload session; refreshing session context and retrying once.")
                            break
                        upload_response.raise_for_status()
                    else:
                        continue
                    break
                else:
                    url = f"https://slow.pics/c/{key}"
                    logging.info(f"slow.pics comparison uploaded: {url}")
                    return _result(url=url)

        logging.warning("slow.pics upload failed: session refresh retry exhausted")
        return _result(
            error_code="SESSION_RETRY_EXHAUSTED",
            error_message="slow.pics upload failed after session refresh retry",
        )

    except Exception as e:
        logging.warning(f"slow.pics upload failed: {e}")
        return _result(error_code="EXCEPTION", error_message=str(e))
