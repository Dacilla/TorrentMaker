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
            prompt = (
                "MediaInfo is required to read technical data from media files for accurate torrent naming. "
                "It was not found on your system. Attempt to install it now using winget? (This may require administrator privileges)"
            )
            if getUserInput(prompt):
                try:
                    logging.info("Running: winget install MediaInfo.MediaInfo -e --accept-source-agreements --accept-package-agreements")
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
        response = requests.get(download_page_url)
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
        response = requests.get(url, stream=True)
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
            try:
                logging.info("Running: winget install Xiph.Flac -e --accept-source-agreements --accept-package-agreements")
                subprocess.run(["winget", "install", "Xiph.Flac", "-e", "--accept-source-agreements", "--accept-package-agreements"], check=True, shell=True)
                if shutil.which("flac"):
                    logging.info("FLAC installed successfully via winget.")
                    return True
                else:
                    logging.error("Winget installation appeared to succeed, but 'flac' is still not in the PATH. You may need to restart your terminal.")
                    return False
            except (subprocess.CalledProcessError, FileNotFoundError) as e:
                logging.error(f"Winget installation failed: {e}")
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
