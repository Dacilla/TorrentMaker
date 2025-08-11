import argparse
import os
import logging
import sys
from time import sleep
import requests
import torf
import qbittorrentapi
import json
import re
import shutil
import configparser
import mutagen
import glob
import Levenshtein
import subprocess

from pprint import pprint, pformat
from base64 import b64encode
from pymediainfo import MediaInfo
from mutagen.mp3 import MP3
from mutagen.flac import FLAC
from mutagen.easyid3 import EasyID3
from mutagen import File
import musicbrainzngs as mb
from urllib.parse import unquote
from ftplib import FTP_TLS
from tqdm import tqdm
from concurrent import futures

from torrent_utils.helpers import has_folders, cb, uploadToPTPIMG, copy_folder_structure, getUserInput, qbitInject
from torrent_utils.config_loader import load_settings, validate_settings

__VERSION = "1.0.0"
LOG_FORMAT = "%(asctime)s.%(msecs)03d %(levelname)-8s P%(process)06d.%(module)-12s %(funcName)-16sL%(lineno)04d %(message)s"
LOG_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

BULK_DOWNLOAD_FILE = os.getcwd() + os.sep + "bulkProcess.txt"


def main():
    parser = argparse.ArgumentParser(
        description="Script to automate creation of torrent files, as well as grabbing mediainfo dump, screenshots, and tmdb description"
    )
    parser.add_argument(
        "-p", "--path", action="store",
        help="Path for file or folder to create .torrent file for",
        type=str
    )
    parser.add_argument(
        "-s", "--source",
        action="store",
        type=str,
        help="Source of the torrent files (E.g. WEB, CD)",
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
        "--groupid",
        action="store",
        type=int,
        help="RED group ID of existing album",
        default=None
    )
    parser.add_argument(
        "--ogyear",
        action="store",
        type=int,
        help="Original release year of the content",
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
        "--sbcopy",
        action="store_true",
        default=False,
        help="Enable to automatically copy given folder to seedbox if given in settings"
    )
    parser.add_argument(
        "-u",
        "--upload",
        action="store_true",
        default=False,
        help="Enable to automatically upload to RED"
    )
    parser.add_argument(
        "-f",
        "--format",
        action="store_true",
        default=False,
        help="Enable to automatically format the file names of the songs"
    )
    parser.add_argument(
        "--nodesc",
        action="store_true",
        default=False,
        help="Disables sending an album description to RED. Useful to not overwrite what's already there."
    )
    parser.add_argument(
        "--fixMD5",
        action="store_true",
        default=False,
        help="Enable to fix unset MD5 signatures"
    )
    parser.add_argument(
        "--skipPrompts",
        action="store_true",
        default=False,
        help="Enable to skip all user prompts. It won't try to match to musicbrainz, and it'll upload immediately"
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

    # --- Load and Validate Settings ---
    settings = load_settings()
    
    required_settings = []
    if arg.upload:
        required_settings.extend(['RED_API', 'RED_URL', 'PTPIMG_API'])
    if arg.inject:
        required_settings.extend(['QBIT_HOST', 'QBIT_USERNAME', 'QBIT_PASSWORD'])
    if arg.sbcopy:
        required_settings.extend([
            'SEEDBOX_HOST', 'SEEDBOX_PORT', 'SEEDBOX_FTP_USER', 'SEEDBOX_FTP_PASSWORD',
            'SEEDBOX_QBIT_HOST', 'SEEDBOX_QBIT_USER', 'SEEDBOX_QBIT_PASSWORD'
        ])
    # All music torrents need a seeding dir for hardlinking
    required_settings.append('SEEDING_DIR')


    validate_settings(settings, required_settings)
    
    # Assign settings to variables to maintain original script structure
    qbit_username = settings.get('QBIT_USERNAME')
    qbit_password = settings.get('QBIT_PASSWORD')
    qbit_host = settings.get('QBIT_HOST')
    ptpimg_api = settings.get('PTPIMG_API')
    red_url = settings.get('RED_URL')
    red_api = settings.get('RED_API')
    seedbox_host = settings.get('SEEDBOX_HOST')
    seedbox_port = settings.getint('SEEDBOX_PORT') if settings.get('SEEDBOX_PORT') else 0
    seedbox_qbit_host = settings.get('SEEDBOX_QBIT_HOST')
    seedbox_qbit_user = settings.get('SEEDBOX_QBIT_USER')
    seedbox_qbit_password = settings.get('SEEDBOX_QBIT_PASSWORD')
    seedbox_ftp_user = settings.get('SEEDBOX_FTP_USER')
    seedbox_ftp_password = settings.get('SEEDBOX_FTP_PASSWORD')
    seeding_dir = settings.get('SEEDING_DIR')

    if ptpimg_api == '':
        ptpimg_api = None
    # --- END Settings Section ---

    pathList = []
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

    # Initialise musicbrainz agent
    mb.set_useragent("My Music App", "1.0", "https://www.example.com")

    lastGroupID = None
    lastAlbumTitle = None

    for path in pathList:
        if not check_file_path_length(path):
            logging.info("A file path is too long in path: " + path)
            if arg.skipPrompts:
                logging.info("Skipping...")
            else:
                sys.exit()
        discsArr = []
        if os.path.exists(os.path.join(path, 'Disc 1')):
            discsArr = find_disc_folders(path)
            artist = get_first_song_artist(os.path.join(path, 'Disc 1'))
            album = get_first_song_album(os.path.join(path, 'Disc 1'))
        else:
            artist = get_first_song_artist(path)
            album = get_first_song_album(path)
        logging.info("Gotten artist: " + artist)
        logging.info("Gotten album: " + album)
        releaseForm = None
        releaseGroupID = None
        if lastAlbumTitle != album or not arg.skipPrompts:
            logging.info("Finding artist info...")
            musicBrainzAlbumInfo = find_album_match(artist, album)
            if musicBrainzAlbumInfo:
                similarityPercent = similarity(musicBrainzAlbumInfo['release-group']['title'], album)
                logging.info("Similarity between album names: " + str(similarityPercent))
                input_response = False
                if similarityPercent < 90 and not arg.skipPrompts:
                    input_response = getUserInput(f"The two found albums aren't similar enough. Are these equal?\n'{musicBrainzAlbumInfo['release-group']['title']}', '{album}'")
                if input_response or musicBrainzAlbumInfo['release-group']['title'] == album:
                    releaseGroupID = musicBrainzAlbumInfo['release-group']['id']
                else:
                    releaseGroupID = None
            else:
                releaseGroupID = None
                input_response = None

            releaseForm = None
            if input_response:
                if 'type' in musicBrainzAlbumInfo['release-group']:
                    releaseForm = musicBrainzAlbumInfo['release-group']['type']
                    if musicBrainzAlbumInfo['release-group'] == 'Other':
                        releaseForm = musicBrainzAlbumInfo['release-group']['secondary-type-list'][0]
                elif 'primary-type' in musicBrainzAlbumInfo['release-group']:
                    releaseForm = musicBrainzAlbumInfo['release-group']['primary-type']
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
            maxValue = maxValue + 1
            maxValue = str(maxValue).zfill(3)
            while True:
                try:
                    os.mkdir("runs" + os.sep + maxValue)
                    break
                except FileExistsError:
                    logging.error("Folder exists. Adding one and trying again...")
                    maxValue = str(int(maxValue) + 1)
            runDir = os.getcwd() + os.sep + "runs" + os.sep + maxValue + os.sep

        logging.info("Run directory: " + runDir)
        logging.info(f"Created folder for output in {os.path.relpath(runDir)}")

        if arg.format:
            logging.info("Formatting mode enabled...")
            if len(discsArr) > 0:
                for discPath in discsArr:
                    add_track_position(discPath)
            else:
                add_track_position(path)

        logging.info("Checking for missing tracks...")
        missingTracksList = check_missing_tracks(path)
        if len(missingTracksList) > 0:
            logging.warning(f"Missing tracks found :{pformat(missingTracksList)} not allowed on RED")
            continue
        logging.info("No missing tracks found.")
        logging.info("Checking for invalid characters in filenames...")
        # sanitize_filenames(path)
        if arg.fixMD5:
            logging.info("Fixing any unset MD5 signatures...")
            if len(discsArr) > 0:
                for discPath in discsArr:
                    oldCwd = os.getcwd()
                    fixMD5(discPath)
                    os.chdir(oldCwd)
                    logging.info("All flac files fixed")
            else:
                oldCwd = os.getcwd()
                fixMD5(path)
                os.chdir(oldCwd)
                logging.info("All flac files fixed")
        logging.info("Generating track list...")
        if len(discsArr) > 0:
            create_track_list(discsArr, runDir + "trackData.txt")
        else:
            create_track_list(path, runDir + "trackData.txt")

        if ptpimg_api:
            if os.path.exists(path + os.sep + "cover.jpg"):
                cover = path + os.sep + "cover.jpg"
            elif os.path.exists(path + os.sep + "cover.png"):
                cover = path + os.sep + "cover.png"
            elif arg.cover:
                cover = arg.cover
            else:
                logging.info("No cover file found. Attempting to extract one from file metadata...")
                if len(discsArr) > 0:
                    cover = extract_album_art(discsArr[0])
                else:
                    cover = extract_album_art(path)
            logging.info("Uploading cover image to ptpimg")
            logging.info("Cover image path: " + cover)
            coverImgURL = uploadToPTPIMG(cover, ptpimg_api)
            with open(runDir + "coverImgURL.txt", 'w') as file:
                file.write(coverImgURL)
            logging.info("Cover image uploaded and URL added to " + runDir + "coverImgURL.txt")
            logging.info("URL: " + coverImgURL)

        logging.info("Creating torrent file")
        torrent = torf.Torrent()
        torrent.private = True
        torrent.source = "RED"
        torrent.path = path
        torrent.trackers.append(red_url)
        torrentFileName = os.path.basename(path).strip() + ".torrent"
        head, tail = os.path.split(path)
        headBasename = os.path.basename(head)
        postName = os.path.basename(path)
        if head != seeding_dir:
            logging.info("Attempting to create hardlinks for easy seeding...")
            destination = os.path.join(seeding_dir, postName.strip())
            copy_folder_structure(path, destination)
            logging.info("Hardlinks created at " + destination)
            torrent.path = destination
        logging.info("Generating torrent file hash. This will take a long while...")
        torrent.generate(callback=cb, interval=0.25)
        logging.info("Writing torrent file to disk...")
        torrent.write(runDir + torrentFileName)
        logging.info("Torrent file wrote to " + torrentFileName)

        if red_api and arg.upload:
            logging.info("Attempting to upload to RED...")
            if len(discsArr) > 0:
                for discPath in discsArr:
                    print_all_metadata_path(discPath)
            else:
                print_all_metadata_path(path)
            if releaseForm is None:
                if len(discsArr) > 0:
                    releaseType = get_album_type(discsArr)
                else:
                    releaseType = get_album_type(path)
            else:
                releaseType = releaseForm
            logging.info("Release type: " + releaseType)
            if len(discsArr) > 0:
                audioFormat = detect_audio_format(discsArr[0])
                logging.info("Audio format: " + audioFormat)
                bitrate = get_bitrate_or_lossless(discsArr[0])
            else:
                audioFormat = detect_audio_format(path)
                logging.info("Audio format: " + audioFormat)
                bitrate = get_bitrate_or_lossless(path)
            if bitrate == "Other":
                logging.error("No bitrate found. Passing to next album")
                continue
            logging.info("Bitrate: " + bitrate)
            if len(discsArr) > 0:
                genre = get_genre(discsArr[0])
            else:
                genre = get_genre(path)
            logging.info("Genre: " + str(genre))
            original_release_year = None
            if arg.ogyear:
                original_release_year = arg.ogyear
                logging.info("Original release year: " + str(original_release_year))

            if len(discsArr) > 0:
                release_year = get_release_year(discsArr[0])
            else:
                release_year = get_release_year(path)
            logging.info("Release year: " + str(release_year))
            recordLabel = None
            if len(discsArr) > 0:
                recordLabel = extract_label(discsArr[0])
            else:
                recordLabel = extract_label(path)
            if recordLabel:
                logging.info("Record Label: " + recordLabel)
            groupId = None
            noDesc = False
            if arg.nodesc:
                noDesc = True
                logging.info("Album description disabled.")
            if lastAlbumTitle == album:
                logging.info("Album name match to last upload. Using same group ID...")
                groupId = lastGroupID
            if arg.groupid:
                groupId = arg.groupid
                logging.info("RED Group ID: " + str(groupId))
            lastAlbumTitle = album
            if arg.sbcopy and seedbox_port and seedbox_host and seedbox_ftp_password and seedbox_ftp_user:
                logging.info("Seedbox copy enabled")
                ftp_copy_folder(path, seedbox_host, seedbox_port, seedbox_ftp_user, seedbox_ftp_password)

            response = upload_music_data(runDir=runDir,
                                         torrent_file=runDir + torrentFileName,
                                         artists=artist,
                                         title=album,
                                         year=release_year,
                                         ogyear=original_release_year,
                                         releasetype=releaseType,
                                         audioFormat=audioFormat,
                                         bitrate=bitrate,
                                         media="WEB",
                                         tags=genre,
                                         recordLabel=recordLabel,
                                         image=coverImgURL,
                                         api=red_api,
                                         releaseGroup=releaseGroupID,
                                         redGroupId=groupId,
                                         noDesc=noDesc,
                                         skipPrompts=arg.skipPrompts)
            if response is None:
                continue
            pprint(response.json())
            if response.status_code == 200:
                lastGroupID = response.json()['response']['groupid']
                logging.info("Downloading torrent file to dir: " + runDir)
                downloadedTorrent = download_torrent(runDir=runDir, torrent_id=response.json()['response']['torrentid'], api_key=red_api)
                if downloadedTorrent is not None:
                    logging.info("Torrent downloaded to: " + downloadedTorrent)
                    if arg.inject:
                        logging.info("Injecting to qbit...")
                        paused = False
                        if arg.sbcopy:
                            qbitInject(qbit_host=seedbox_qbit_host, qbit_username=seedbox_qbit_user, qbit_password=seedbox_qbit_password, runDir=runDir, torrentFileName=os.path.basename(downloadedTorrent), paused=paused, postName=postName, category="Redacted", seedTimeLimit=-1)
                        qbitInject(qbit_host=qbit_host, qbit_username=qbit_username, qbit_password=qbit_password, runDir=runDir, torrentFileName=os.path.basename(downloadedTorrent), paused=paused, postName=postName, category="Redacted", seedTimeLimit=-1)
                    logging.info("Copying torrent to ubuntu VM...")
                    # Destination directory path
                    dst_dir_path = r'U:\home\alex\redcurry\torrent-files'

                    # Copy the file to the destination directory
                    copyDest = shutil.copy(downloadedTorrent, dst_dir_path)
                    logging.info("Torrent file successfully copied to: " + copyDest)
            else:
                if not getUserInput("Upload failed. Continue anyway?"):
                    exit()


def extract_album_art(folder_path):
    for root, dirs, files in os.walk(folder_path):
        for file in files:
            if file.lower().endswith(('.mp3', '.flac', '.ogg', '.m4a', '.wav')):
                audio_file_path = os.path.join(root, file)
                audio = File(audio_file_path)
                if 'APIC:' in audio:
                    # For MP3 files
                    cover = audio.tags['APIC:'].data
                elif 'covr' in audio:
                    # For M4A files
                    cover = audio['covr'][0]
                elif file.lower().endswith('.flac'):
                    pics = audio.pictures
                    for p in pics:
                        if p.type == 3:
                            logging.info("Found cover art")
                            cover = p.data
                else:
                    continue
                cover_path = os.path.join(folder_path, 'cover.jpg')
                with open(cover_path, 'wb') as cover_file:
                    cover_file.write(cover)

                return cover_path
    logging.info("No cover art found")
    return None


def fixMD5(folder_path):
    # Change to the specified folder
    os.chdir(folder_path)

    # Define the command as a list of strings
    command = ['flac', '-f8', '*.flac']

    # Use subprocess.Popen to execute the command and capture its output
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, universal_newlines=True)

    # Loop through the output and print each line as it is generated
    for line in process.stdout:
        print(line, end='')

    for root, dirs, files in os.walk(folder_path):
        for file in files:
            if '.tmp' in file:
                file_path = os.path.join(root, file)
                os.remove(file_path)
                logging.info(f"Deleted file: {file_path}")


def find_disc_folders(folder_path):
    disc_folders = []

    for root, dirs, files in os.walk(folder_path):
        for dir_name in dirs:
            if dir_name.startswith('Disc'):
                disc_folders.append(os.path.join(root, dir_name))

    return disc_folders


def extract_label(path):
    label = None
    copyright_string = None
    for filename in os.listdir(path):
        if filename.endswith(".mp3"):
            try:
                audio = EasyID3(os.path.join(path, filename))
                copyright_string = audio.get('copyright')[0]
                break
            except Exception:
                continue
        elif filename.endswith(".flac"):
            try:
                audio = FLAC(os.path.join(path, filename))
                copyright_string = audio['copyright'][0]
                break
            except Exception:
                continue
        else:
            continue  # Skip files that are not MP3 or FLAC
    if copyright_string:
        label = process_string(copyright_string)

    # Split the string based on 'Under Exclusive License'
    if label is not None:
        parts = label.lower().split('under exclusive')

        # Return the portion of the string before the occurrence
        if len(parts) > 0:
            label = parts[0].strip()

    return label


def process_string(input_string):
    # Remove any series of 4 digits
    output_string = re.sub(r'\b\d{4}\b', '', input_string)
    # Split the string into words
    words = output_string.split()
    # Initialize a list to keep track of unique words
    unique_words = []
    # Iterate over the words in the string
    for word in words:
        # Check if the word is already in the unique_words list
        if word not in unique_words:
            # If it's not, add it to the list
            unique_words.append(word)
    # Join the unique words back together into a string
    output_string = ' '.join(unique_words)

    # Remove copyright characters
    output_string = re.sub(r'[™©®℗]', '', output_string)

    output_string = output_string.split(', ')[0].strip()

    return output_string


def similarity(s1, s2):
    distance = Levenshtein.distance(s1, s2)
    max_len = max(len(s1), len(s2))
    return 100 * (1 - distance / max_len)


def download_torrent(runDir, torrent_id, api_key):
    url = 'https://redacted.ch/ajax.php?action=download'
    headers = {'Authorization': api_key}

    params = {'id': torrent_id}

    response = requests.get(url, params=params, headers=headers)

    if response.status_code == 200:
        # Extract the filename from the Content-Disposition header
        header = response.headers.get('Content-Disposition')
        if header:
            filename = unquote(header.split('filename=')[1])
        else:
            filename = 'file.torrent'
        file_path = os.path.join(runDir, filename.replace('"', ''))
        with open(file_path, 'wb') as f:
            f.write(response.content)
            return file_path
    else:
        print('Error downloading file')
        return None


def get_release_year(path):
    release_year = None
    for filename in os.listdir(path):
        if filename.endswith(".mp3"):
            audio = EasyID3(os.path.join(path, filename))
            release_year = int(audio.get('date')[0][:4])
            break
        elif filename.endswith(".flac"):
            audio = FLAC(os.path.join(path, filename))
            if 'year' in audio:
                release_year = int(audio['year'][0])
            else:
                if 'date' in audio:
                    if len(audio['date'][0]) == 4:
                        release_year = int(audio['date'][0])
            break
        else:
            continue  # Skip files that are not MP3 or FLAC

    if release_year is None:
        logging.error("No release year found please enter 4 digit release year")
        release_year = int(input())
    return release_year


def get_genre(path):
    for filename in os.listdir(path):
        if filename.endswith(".mp3"):
            audio = EasyID3(os.path.join(path, filename))
            break
        elif filename.endswith(".flac"):
            audio = FLAC(os.path.join(path, filename))
            break
        else:
            continue  # Skip files that are not MP3 or FLAC
    try:
        genre = audio['genre'][0]
        genre = genre.replace('Alternatif et Indé', 'Alternative, Indie')
        genre = genre.replace('Bandes originales de films', 'Stage and Screen')
    except KeyError:
        logging.error("No genre found, please give genres comma separated")
        genre = input()
    return genre.lower()


def detect_audio_format(path):
    mp3_extensions = {'.mp3', '.mp2', '.mpga'}
    flac_extensions = {'.flac'}
    mp3_mime_types = {'audio/mpeg', 'audio/mp3'}
    flac_mime_types = {'audio/flac', 'audio/x-flac'}

    for filename in os.listdir(path):
        filepath = os.path.join(path, filename)
        if os.path.isfile(filepath):
            ext = os.path.splitext(filename)[1].lower()
            mime_type = mutagen.File(filepath).mime[0].lower()

            if ext in mp3_extensions or mime_type in mp3_mime_types:
                return "MP3"
            elif ext in flac_extensions or mime_type in flac_mime_types:
                return "FLAC"
    return None


def get_album_type(folder_path):
    """Determine if a folder of audio files is an album, EP, or single.

    Parameters:
    folder_path (str or list): Path to the folder(s) containing audio files, or an array of folder paths.

    Returns:
    str: 'Album', 'EP', or 'Single'.
    """
    if isinstance(folder_path, list):
        # If folder_path is an array, consider all the songs in all the given paths
        audio_files = []
        for path in folder_path:
            for filename in os.listdir(path):
                if filename.endswith('.mp3') or filename.endswith('.flac'):
                    audio_files.append(os.path.join(path, filename))
    else:
        # If folder_path is a single folder path, consider the songs in that path only
        audio_files = []
        for filename in os.listdir(folder_path):
            if filename.endswith('.mp3') or filename.endswith('.flac'):
                audio_files.append(os.path.join(folder_path, filename))

    if not audio_files:
        raise ValueError(f"No audio files found in {folder_path}")

    track_numbers = set()
    for audio_file in audio_files:
        try:
            if audio_file.endswith(".mp3"):
                audio = EasyID3(audio_file)
            elif audio_file.endswith(".flac"):
                audio = FLAC(audio_file)
            track_numbers.add(audio.get("tracknumber", [])[0])
        except Exception:
            pass

    if not track_numbers:
        raise ValueError("No track numbers found in audio files")

    newTrackNums = []
    for num, track in enumerate(track_numbers):
        if '/' in track:
            track = track.split('/')[0]
        newTrackNums.append(track)

    if len(track_numbers) < 3:
        return "Single"
    elif all(int(track_number) <= 5 for track_number in newTrackNums):
        return "EP"
    else:
        return "Album"


def get_audio_files(path):
    audio_files = []
    for root, dirs, files in os.walk(path):
        for file in files:
            if file.endswith(".mp3") or file.endswith(".flac"):
                audio_files.append(os.path.join(root, file))
    return audio_files


def get_bitrate_or_lossless(path):
    audio_files = get_audio_files(path)
    print(audio_files)
    if not audio_files:
        return None

    for file_path in audio_files:
        audio = mutagen.File(file_path)
        print(audio)
        if audio is None:
            continue
        if audio.mime[0] == "audio/mp3":
            bitrate = audio.info.bitrate // 1000
            if bitrate == 320 or bitrate == 256 or bitrate == 192:
                return str(bitrate)
        elif audio.mime[0] == "audio/flac":
            bit_depth = audio.info.bits_per_sample
            if bit_depth == 16:
                return "Lossless"
            elif bit_depth == 24:
                return "24bit Lossless"
    return None


def check_file_path_length(folder_path):
    for root, dirs, files in os.walk(folder_path):
        for file_name in files:
            path_length = len(os.path.basename(root)) + len(file_name)
            if path_length > 180:
                return False
    return True


def upload_music_data(runDir, releaseGroup, torrent_file, artists: str, title: str, year, releasetype, audioFormat, bitrate, media, tags, image, api, recordLabel=None, redGroupId=None, ogyear=None, noDesc=False, skipPrompts=False):
    url = "https://redacted.ch/ajax.php?action=upload"

    albumDesc = open(runDir + "trackData.txt", 'r', encoding='UTF-8').read()
    albumDesc = albumDesc.replace('\u2008', ' ')
    if releaseGroup:
        musicBrainzURL = "https://musicbrainz.org/release-group/" + releaseGroup

        albumDesc = albumDesc + "\n\n\n" + f"[url={musicBrainzURL}]MusicBrainz Release Group[/url]"

    if 'remix' in title.lower():
        releasetype = 'Remix'

    release_types = {
        'Album': 1,
        'Soundtrack': 3,
        'EP': 5,
        'Anthology': 6,
        'Compilation': 7,
        'Single': 9,
        'Live album': 11,
        'Remix': 13,
        'Bootleg': 14,
        'Interview': 15,
        'Mixtape': 16,
        'Demo': 17,
        'Concert Recording': 18,
        'DJ Mix': 19,
        'Unknown': 21
    }

    releasetype = release_types.get(releasetype, None)

    tags: str = format_genres(tags)
    if len(tags) > 0:
        tags += ", " + str(year)[:3] + '0s'
    else:
        tags = str(year)[:3] + '0s'
    logging.info("Tags: " + tags)
    artists = artists.split(', ')
    print(artists)
    if len(artists) == 1:
        importance = ['Main']
    else:
        importance = ['Main' for _ in range(len(artists))]

    importance = convert_roles_to_int(importance)
    remasteryear = year
    if ogyear:
        year = ogyear

    headers = {
        "Authorization": api,
    }

    data = {
        'type': 0,
        'title': title,
        'year': year,
        'remaster_year': remasteryear,
        'releasetype': releasetype,
        'format': audioFormat,
        'bitrate': bitrate,
        'media': media,
        'image': image,
        'tags': tags,
        'album_desc': albumDesc
    }

    if noDesc:
        data.pop('album_desc')

    if redGroupId:
        data['groupid'] = redGroupId

    if recordLabel:
        if len(recordLabel) < 2 or len(recordLabel) > 80:
            recordLabel = input("Gotten record label too long or too short for RED\nGotten label: " + recordLabel + "\nPlease input a record label:\n")
        if 'records dk' in recordLabel.lower():
            logging.info("Distro Kid release detected. Setting to Self-Released")
            recordLabel = 'Self-Released'
        if artists[0].lower() == recordLabel.lower():
            logging.info("Self release detected. Setting to Self-Released")
            recordLabel = 'Self-Released'

        data['remaster_record_label'] = recordLabel

    if len(artists) == 1:
        data["artists[0]"] = artists[0]
    else:
        for num, artist in enumerate(artists):
            data[f"artists[{num}]"] = artist

    for num, importNum in enumerate(importance):
        data[f"importance[{num}]"] = importNum

    torrent_file = {'file_input': open(torrent_file, 'rb')}

    pprint(data)
    if skipPrompts or getUserInput("Do you want to upload this to RED?"):
        response = requests.post(headers=headers, url=url, data=data, files=torrent_file)
        return response
    else:
        return None


def sanitize_filename(filename):
    """
    Sanitizes a filename by removing any Unicode characters that are not allowed in file names
    and replacing them with an underscore.
    """
    # Define a regular expression that matches any Unicode character that is not allowed in file names
    # The expression matches any character that is not a letter, digit, space, or one of the following symbols: -._~()
    pattern = r'[^\w\d\s\-._~()]'

    # Replace any matching characters with an underscore
    sanitized = re.sub(pattern, '_', filename)

    return sanitized


def sanitize_filenames(directory):
    """
    Sanitizes the filenames in the specified directory by removing any Unicode characters that are not allowed
    in file names and replacing them with an underscore.
    """
    # Get list of filenames in the directory
    filenames = os.listdir(directory.encode('utf-8'))

    # Iterate over filenames and sanitize them
    for filename in filenames:
        sanitized_filename = sanitize_filename(filename)
        if sanitized_filename != filename:
            logging.info("Renaming file: " + sanitized_filename)
            os.rename(os.path.join(directory, filename), os.path.join(directory, sanitized_filename))


def format_genres(genre_str):
    genres = genre_str.split(', ')
    formatted_genres = []
    for genre in genres:
        split_genres = genre.split('/')
        for split_genre in split_genres:
            formatted_genres.append(split_genre.replace(' ', '.').lower())
    return ', '.join(formatted_genres)


def convert_roles_to_int(roles_list):
    roles_dict = {
        "Main": 1,
        "Guest": 2,
        "Composer": 4,
        "Conductor": 5,
        "DJ / Compiler": 6,
        "Remixer": 3,
        "Producer": 7
    }
    return [roles_dict.get(role, None) for role in roles_list]


def get_first_song_album(folder_path):
    # Loop through all files in the folder
    for file_name in os.listdir(folder_path):
        # Check if the file is an MP3 or FLAC file
        if file_name.endswith(".mp3"):
            audio = EasyID3(os.path.join(folder_path, file_name))
        elif file_name.endswith(".flac"):
            audio = FLAC(os.path.join(folder_path, file_name))
        else:
            continue  # Skip files that are not MP3 or FLAC

        # Check if the file is the first track in the album
        if audio.get("tracknumber", [])[0] == "01" or "1/" in audio.get("tracknumber", [])[0]:
            # Get the album name from the metadata
            album = audio.get("album", [])
            if isinstance(album, list) and len(album) > 0 and isinstance(album[0], str):
                return album[0]

    # Return None if no first track is found
    return None


def print_all_metadata_path(path):
    music_files = [f for f in os.listdir(path) if f.endswith('.mp3') or f.endswith('.m4a') or f.endswith('.flac')]

    for file in music_files:
        print_all_metadata(os.path.join(path, file))


def print_all_metadata(file_path):
    # Check the file extension and load the appropriate metadata format
    if file_path.endswith(".mp3"):
        audio = EasyID3(file_path)
    elif file_path.endswith(".flac"):
        audio = FLAC(file_path)
    else:
        print("Unsupported file type:", file_path)
        return

    # Loop through all the metadata fields and print their names and values
    pprint(audio)
    # for key, value in audio.items():
    #     print(key + ": " + str(value))


def get_first_song_artist(folder_path):
    # Loop through all files in the folder
    for file_name in os.listdir(folder_path):
        # Check if the file is an MP3 or FLAC file
        if file_name.endswith(".mp3"):
            audio = EasyID3(os.path.join(folder_path, file_name))
        elif file_name.endswith(".flac"):
            audio = FLAC(os.path.join(folder_path, file_name))
        else:
            continue  # Skip files that are not MP3 or FLAC

        # Check if the file is the first track in the album
        if audio.get("tracknumber", [])[0] == "01" or "1/" in audio.get("tracknumber", [])[0]:
            # Get the artist name from the metadata
            artist = audio.get("albumartist", [])
            if isinstance(artist, list) and len(artist) > 0 and isinstance(artist[0], str):
                return artist[0]
            if audio.get("artist"):
                return audio.get("artist")[0]

    # Return None if no first track is found
    logging.error("No suitable track found. This is the metadata of the files for debugging...")
    for file_name in os.listdir(folder_path):
        if file_name.endswith(".mp3") or file_name.endswith(".flac"):
            logging.info("Scanning metadata of file: " + os.path.join(folder_path, file_name))
            print_all_metadata(os.path.join(folder_path, file_name))


def find_album_match(artist_name, album_name):
    # Search for the artist on MusicBrainz
    try:
        search_results = mb.search_artists(artist_name)

        # Check if any results were found
        if len(search_results["artist-list"]) == 0:
            print("No results found for artist:", artist_name)
            return None

        # Get the ID of the best match artist
        foundArtistName = None
        for result in search_results["artist-list"]:
            resultArtistName = mb.get_artist_by_id(result['id'])
            if similarity(resultArtistName['artist']['name'], artist_name) > 95:
                logging.info("Artist name match found: " + resultArtistName['artist']['name'])
                foundArtistName = resultArtistName['artist']['name']
                break

        if not foundArtistName:
            logging.info("No sufficient artist name found.")
            return None

        artist_id = resultArtistName['artist']['id']
        print("Best match artist ID:", artist_id)

        # Search for the album by the artist on MusicBrainz
        album_results = mb.search_releases(artist=resultArtistName['artist']['name'], release=album_name)

        # Check if any results were found
        if len(album_results["release-list"]) == 0:
            print("No results found for album:", album_name)
            return None

        # Get the ID of the best match album
        best_match = None
        for result in album_results['release-list']:
            if resultArtistName['artist']['name'] in str(result):
                best_match = result
        if not best_match:
            logging.info("No album with correct artist found.")
            return None

        album_id = best_match["id"]
        print("Best match album ID:", album_id)

        # Get the release group ID from the album information
        release_group_id = best_match["release-group"]["id"]
        print("Release group ID:", release_group_id)

        # Get the full release group information from MusicBrainz
        release_group_info = mb.get_release_group_by_id(release_group_id)
        pprint(release_group_info)
    except Exception:
        logging.error("Error hit. SKipping matching...")
        return None

    return release_group_info


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
    This function takes a folder path (or an array of folder paths) and an output file name as input, and creates a
    formatted list of every track found in the folders along with its position and length, and writes the list to the
    output file.
    """
    # Check if folder_path is an array
    if isinstance(folder_path, list):
        # Initialize an empty list to store all the track information
        track_list = []

        # Loop over each folder path in the array
        for path in folder_path:
            # Get the disc number from the folder path
            disc_number = os.path.basename(path).split(" ")[-1]

            # Get a list of all the files in the folder
            files = os.listdir(path)

            # Filter for only music files (you can customize this depending on the file extensions you want to look for)
            music_files = [f for f in files if f.endswith('.mp3') or f.endswith('.wav') or f.endswith('.flac')]

            # Sort the music files alphabetically
            music_files.sort()

            track_list.append(f"Disk {disc_number}:")

            # Loop over the music files and extract the track information
            for i, file_name in enumerate(music_files):
                # Get the track position
                track_position = str(i + 1).zfill(2)

                # Get the track length in seconds
                if file_name.endswith('.mp3'):
                    # For MP3 files, use Mutagen to extract the track length
                    audio = MP3(os.path.join(path, file_name))
                    track_length = int(audio.info.length)
                    title = audio.get('TIT2', [file_name])[0]
                elif file_name.endswith('.flac'):
                    # For FLAC files, use Mutagen to extract the track length from the STREAMINFO block
                    audio = FLAC(os.path.join(path, file_name))
                    track_length = int(audio.info.length)
                    title = audio.get('title', [file_name])[0]
                else:
                    # For other file types, use os.path.getsize() to get the file size in bytes and estimate the length
                    file_size = os.path.getsize(os.path.join(path, file_name))
                    track_length = int(file_size / 1000000) * 4  # 4 seconds per MB, this is just an estimate
                    title = file_name

                # Convert the track length from seconds to a formatted string (XX:XX)
                minutes = str(track_length // 60).zfill(2)
                seconds = str(track_length % 60).zfill(2)
                track_length_str = f"{minutes}:{seconds}"

                # Add the track information to the track_list, including the disc number
                track_list.append(f"\n\t{track_position}. {title} ({track_length_str})")

    else:
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
    with open(output_file, 'w', encoding='UTF-8') as f:
        f.write('\n'.join(track_list))

    logging.info(f"Track list written to {output_file} successfully!")


def ftp_copy_folder(local_folder_path, host, port, username, password):
    remote_folder_path = '/downloads/qbittorrent'  # Destination folder on the remote host

    logging.info("Local path: " + local_folder_path)
    logging.info("Host: " + host)
    logging.info("Port: " + str(port))
    logging.info("Username: " + username)
    logging.info("Password: " + password)

    ftp = FTP_TLS()
    ftp.connect(host, port)
    ftp.login(username, password)
    ftp.prot_p()
    ftp.cwd(remote_folder_path)

    logging.info("Creating directory: " + os.path.basename(local_folder_path))
    try:
        ftp.mkd(os.path.basename(local_folder_path))
    except Exception:
        # TODO: Add a check if the folder already exists
        logging.error("Failed to make directory, it probably already exists")

    destination_path = remote_folder_path + '/' + os.path.basename(local_folder_path)

    for root, dirs, files in os.walk(local_folder_path):
        # Create corresponding directories in the destination path
        relative_path = os.path.relpath(root, local_folder_path)
        if relative_path != '.':
            destination_dir = destination_path + '/' + relative_path
            logging.info("Creating sub directory: " + destination_dir)
            ftp.mkd(destination_dir)  # Create directory on FTP server
        else:
            destination_dir = destination_path
            print(destination_dir)

        # Copy files to their corresponding locations
        for file in files:
            source_file = os.path.join(root, file)
            destination_file = destination_dir + '/' + file
            logging.info("Uploading: " + source_file)
            with open(source_file, 'rb') as f:
                ftp.storbinary('STOR ' + destination_file, f)  # Upload file to FTP server
            logging.info("Uploaded to: " + destination_file)


def ftp_copy_folder_original(local_folder_path, host, port, username, password):
    remote_folder_path = '/downloads/qbittorrent'  # Destination folder on the remote host

    logging.info("Local path: " + local_folder_path)
    logging.info("Host: " + host)
    logging.info("Port: " + str(port))
    logging.info("Username: " + username)
    logging.info("Password: " + password)

    # Connect to the FTP server
    ftp = FTP_TLS()
    ftp.connect(host, port)
    ftp.login(username, password)
    ftp.prot_p()
    ftp.retrlines('LIST')
    logging.info(ftp.pwd())
    # Create the remote folder if it doesn't exist
    remote_dir = os.path.join(remote_folder_path)
    ftp.cwd(remote_dir)
    logging.info("Creating directory: " + os.path.basename(local_folder_path))
    try:
        ftp.mkd(os.path.basename(local_folder_path))
    except Exception:
        # TODO: Add a check if the folder already exists
        logging.error("Failed to make directory, it probably already exists")
    remote_dir = remote_folder_path + '/' + os.path.basename(local_folder_path)

    # for os.path.

    for root, dirs, files in os.walk(local_folder_path):
        relative_path = os.path.relpath(root, local_folder_path)
        remote_dir = os.path.join(remote_folder_path, relative_path)

        # Create remote directories if they don't exist
        try:
            ftp.mkd(remote_dir)
        except:
            pass

        # Change remote working directory
        ftp.cwd(remote_dir)

        # Upload files
        for file in files:
            local_file_path = os.path.join(root, file)
            with open(local_file_path, 'rb') as local_file:
                ftp.storbinary(f'STOR {file}', local_file)
                print("\n")
                logging.info(f"Uploaded file: {file}")

    # Disconnect from the FTP server
    ftp.quit()
    logging.info("Folder copied successfully!")


def upload_file(ftp, local_file_path, remote_file_name):
    with open(local_file_path, 'rb') as local_file:
        ftp.storbinary(f'STOR {remote_file_name}', local_file)


if __name__ == "__main__":
    main()
