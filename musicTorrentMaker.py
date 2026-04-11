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
from urllib.parse import unquote, urlparse
from ftplib import FTP_TLS
from tqdm import tqdm
from concurrent import futures

from torrent_utils.helpers import (
    has_folders, cb, uploadToPTPIMG, copy_folder_structure,
    getUserInput, qbitInject, similarity, get_path_list, ensure_flac_cli,
    play_alert
)
from torrent_utils.config_loader import load_settings, validate_settings
from torrent_utils.music_upload import (
    MusicUploadMetadata,
    build_ops_payload,
    build_red_payload,
    format_tracker_tags,
    render_preflight_table,
    scan_album,
    with_metadata_overrides,
)

__VERSION = "1.4.2"
LOG_FORMAT = "%(asctime)s.%(msecs)03d %(levelname)-8s P%(process)06d.%(module)-12s %(funcName)-16sL%(lineno)04d %(message)s"
LOG_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

BULK_DOWNLOAD_FILE = os.path.join(os.getcwd(), "bulkProcess.txt")


def main():
    parser = argparse.ArgumentParser(
        description="Script to automate creation of torrent files for music albums."
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
        help="RED group ID of existing album. Deprecated alias for --red-groupid.",
        default=None
    )
    parser.add_argument(
        "--red-groupid",
        action="store",
        type=int,
        help="RED group ID of existing album",
        default=None
    )
    parser.add_argument(
        "--ops-groupid",
        action="store",
        type=int,
        help="OPS group ID of existing album",
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
        "-u", "--upload",
        action="store_true",
        default=False,
        help="Enable to automatically upload to REDacted"
    )
    parser.add_argument(
        "--ops",
        action="store_true",
        default=False,
        help="Enable to automatically upload to Orpheus (OPS)"
    )
    parser.add_argument(
        "--preflight",
        action="store_true",
        default=False,
        help="Validate music folders and print an upload readiness table without creating torrents or uploading"
    )
    parser.add_argument(
        "--tags",
        action="store",
        type=str,
        default=None,
        help="Comma-separated tracker tags to use when files do not have genre tags"
    )
    parser.add_argument(
        "--skip-red-dryrun",
        action="store_true",
        default=False,
        help="Skip the RED dry-run request before a real RED upload"
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
        "--skip-flac-check",
        action="store_true",
        default=False,
        help="Skip the check for the FLAC command-line tool."
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
    
    # Silence the verbose logger from the musicbrainzngs library
    logging.getLogger("musicbrainzngs.mbxml").setLevel(logging.WARNING)

    logging.info(f"Version {__VERSION} starting...")
    
    # Check for FLAC dependency if needed (only if explicitly asked)
    if arg.fixMD5 and not arg.skip_flac_check:
        ensure_flac_cli()

    # --- Load and Validate Settings ---
    settings = load_settings()
    
    required_settings = []
    if arg.upload:
        required_settings.extend(['RED_API', 'RED_ANNOUNCE_URL', 'PTPIMG_API'])
    if arg.ops:
        required_settings.extend(['OPS_API', 'OPS_ANNOUNCE_URL', 'PTPIMG_API'])
    if arg.inject:
        required_settings.extend(['QBIT_HOST', 'QBIT_USERNAME', 'QBIT_PASSWORD'])
    if arg.sbcopy:
        required_settings.extend([
            'SEEDBOX_HOST', 'SEEDBOX_PORT', 'SEEDBOX_FTP_USER', 'SEEDBOX_FTP_PASSWORD',
            'SEEDBOX_QBIT_HOST', 'SEEDBOX_QBIT_USER', 'SEEDBOX_QBIT_PASSWORD'
        ])
    if not arg.preflight:
        required_settings.append('SEEDING_DIR')

    validate_settings(settings, required_settings)
    
    # Assign settings to variables
    qbit_username = settings.get('QBIT_USERNAME')
    qbit_password = settings.get('QBIT_PASSWORD')
    qbit_host = settings.get('QBIT_HOST')
    ptpimg_api = settings.get('PTPIMG_API')
    red_announce_url = settings.get('RED_ANNOUNCE_URL')
    red_api = settings.get('RED_API')
    ops_announce_url = settings.get('OPS_ANNOUNCE_URL')
    ops_api = settings.get('OPS_API')
    seedbox_host = settings.get('SEEDBOX_HOST')
    seedbox_port = settings.getint('SEEDBOX_PORT') if settings.get('SEEDBOX_PORT') else 0
    seedbox_qbit_host = settings.get('SEEDBOX_QBIT_HOST')
    seedbox_qbit_user = settings.get('SEEDBOX_QBIT_USER')
    seedbox_qbit_password = settings.get('SEEDBOX_QBIT_PASSWORD')
    seedbox_ftp_user = settings.get('SEEDBOX_FTP_USER')
    seedbox_ftp_password = settings.get('SEEDBOX_FTP_PASSWORD')
    seedbox_remote_path = settings.get('SEEDBOX_REMOTE_PATH') or '/downloads/qbittorrent'
    seeding_dir = settings.get('SEEDING_DIR')

    if ptpimg_api == '':
        ptpimg_api = None
    # --- END Settings Section ---

    pathList = get_path_list(arg.path, BULK_DOWNLOAD_FILE)
    pathList = expand_music_paths(pathList)
    logging.info(f"Expanded to {len(pathList)} music folder(s) to process.")

    # Initialise musicbrainz agent
    mb.set_useragent("My Music App", "1.0", "https://www.example.com")

    if arg.preflight:
        scans = []
        mb_cache = {}
        for path in pathList:
            scan = scan_album(path, media=arg.source, tags_override=arg.tags, cover_path=arg.cover, original_year=arg.ogyear)
            cache_key = (scan.metadata.artist, scan.metadata.title)
            if scan.metadata.artist and scan.metadata.title:
                if cache_key not in mb_cache:
                    mb_cache[cache_key] = find_album_match(scan.metadata.artist, scan.metadata.title)
                    sleep(1.1)
                match = mb_cache[cache_key]
                if match:
                    rg = match.get('release-group', {})
                    match_title = rg.get('title', '')
                    match_id = rg.get('id', '')
                    score = similarity(match_title, scan.metadata.title) if match_title else 0
                    scan.group_match_status = f"MB {score:.0f}% {match_id[:8]}"
                else:
                    scan.group_match_status = "no MB match"
            scans.append(scan)

        print(render_preflight_table(scans))
        if any(not scan.ok for scan in scans):
            sys.exit(1)
        return

    lastGroupID = None
    lastOpsGroupID = None
    lastAlbumTitle = None
    red_group_ids_by_identity = {}
    ops_group_ids_by_identity = {}

    for path in pathList:
        scan = scan_album(path, media=arg.source, tags_override=arg.tags, cover_path=arg.cover, original_year=arg.ogyear)
        for warning in scan.warnings:
            logging.warning(f"{os.path.basename(path)}: {warning}")
        if (arg.upload or arg.ops) and scan.blockers:
            logging.error(f"Preflight blockers for {path}: {pformat(scan.blockers)}")
            logging.error("Skipping this album. Use --preflight for the full readiness table.")
            continue

        artist = scan.metadata.artist
        album = scan.metadata.title
        logging.info("Gotten artist: " + str(artist))
        logging.info("Gotten album: " + str(album))

        # Determine if album has multiple discs
        discsArr = []
        if os.path.exists(os.path.join(path, 'Disc 1')):
            discsArr = find_disc_folders(path)

        # Match album with MusicBrainz to get release group info
        releaseForm = None
        releaseGroupID = None
        if lastAlbumTitle != album or not arg.skipPrompts:
            logging.info("Finding artist info...")
            musicBrainzAlbumInfo = find_album_match(artist, album)
            input_response = False
            if musicBrainzAlbumInfo:
                similarityPercent = similarity(musicBrainzAlbumInfo['release-group']['title'], album)
                logging.info("Similarity between album names: " + str(similarityPercent))
                if similarityPercent < 90 and not arg.skipPrompts:
                    input_response = getUserInput(f"The two found albums aren't similar enough. Are these equal?\n'{musicBrainzAlbumInfo['release-group']['title']}', '{album}'")
                accept_match = input_response or similarityPercent >= 90 or musicBrainzAlbumInfo['release-group']['title'] == album
                if accept_match:
                    release_group = musicBrainzAlbumInfo['release-group']
                    releaseGroupID = release_group['id']
                    releaseForm = release_group.get('type') or release_group.get('primary-type')
                    if releaseForm == 'Other' and release_group.get('secondary-type-list'):
                        releaseForm = release_group['secondary-type-list'][0]
                else:
                    releaseGroupID = None
            else:
                releaseGroupID = None
        
        # Create a unique directory for this run's output files
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

        # Optional: Format filenames with track numbers
        if arg.format:
            logging.info("Formatting mode enabled...")
            if len(discsArr) > 0:
                for discPath in discsArr:
                    add_track_position(discPath)
            else:
                add_track_position(path)

        # Pre-upload checks
        logging.info("Checking for missing tracks...")
        missingTracksList = check_missing_tracks(path)
        if len(missingTracksList) > 0:
            logging.warning(f"Missing tracks found :{pformat(missingTracksList)} not allowed on RED")
            continue
        logging.info("No missing tracks found.")
        
        # --- Proactive MD5 Check ---
        if not arg.fixMD5: 
            logging.info("Scanning for missing MD5 signatures...")
            if check_md5_signatures(path):
                prompt = "Missing MD5 signatures were found in one or more FLAC files. This is not allowed on many trackers. Would you like to fix them now?"
                if getUserInput(prompt):
                    if not arg.skip_flac_check:
                        ensure_flac_cli()
                    
                    logging.info("Fixing unset MD5 signatures as requested...")
                    if len(discsArr) > 0:
                        for discPath in discsArr:
                            oldCwd = os.getcwd()
                            fixMD5(discPath)
                            os.chdir(oldCwd)
                    else:
                        oldCwd = os.getcwd()
                        fixMD5(path)
                        os.chdir(oldCwd)
                    logging.info("All flac files fixed.")
                else:
                    logging.warning("Skipping album due to missing MD5 signatures.")
                    continue
            else:
                logging.info("No missing MD5 signatures found.")

        # Optional: Fix FLAC MD5 signatures (if explicitly requested)
        if arg.fixMD5:
            logging.info("Fixing any unset MD5 signatures...")
            if len(discsArr) > 0:
                for discPath in discsArr:
                    oldCwd = os.getcwd()
                    fixMD5(discPath)
                    os.chdir(oldCwd)
            else:
                oldCwd = os.getcwd()
                fixMD5(path)
                os.chdir(oldCwd)
            logging.info("All flac files fixed.")

        # Generate tracklist for description
        logging.info("Generating track list...")
        if len(discsArr) > 0:
            create_track_list(discsArr, runDir + "trackData.txt")
        else:
            create_track_list(path, runDir + "trackData.txt")

        # Upload cover art
        coverImgURL = ""
        if ptpimg_api:
            cover = None
            if scan.cover_path:
                cover = scan.cover_path
            elif arg.cover:
                cover = arg.cover
            else:
                logging.info("No cover file found. Attempting to extract one from file metadata...")
                if len(discsArr) > 0:
                    cover = extract_album_art(discsArr[0])
                else:
                    cover = extract_album_art(path)
            
            if not cover:
                logging.error("Could not find or extract a cover image for this album.")
                if getUserInput("A cover image is required for uploads. Do you want to provide a path to the cover image now?"):
                    play_alert("input")
                    cover = input("Please enter the full path to the cover image:\n").strip().replace("\"", "")
                    if not os.path.exists(cover):
                        logging.error("The provided path does not exist. Exiting.")
                        sys.exit(1)
                else:
                    logging.error("Exiting because no cover image is available.")
                    sys.exit(1)
            
            while True:
                logging.info(f"Uploading cover image: {cover}")
                coverImgURL = uploadToPTPIMG(cover, ptpimg_api)
                if coverImgURL:
                    with open(os.path.join(runDir, "coverImgURL.txt"), 'w') as file:
                        file.write(coverImgURL)
                    logging.info(f"Cover image uploaded successfully. URL: {coverImgURL}")
                    break
                else:
                    logging.error("Failed to upload cover image.")
                    if not getUserInput("Do you want to retry the cover image upload? (Answering 'no' will exit the script)"):
                        logging.error("Exiting because cover image upload failed and is required.")
                        sys.exit(1)

        # Create the .torrent file
        logging.info("Creating torrent file")
        torrent = torf.Torrent()
        torrent.private = True
        
        # Add trackers based on user flags
        if arg.upload:
            torrent.trackers.append(red_announce_url)
        if arg.ops:
            torrent.trackers.append(ops_announce_url)

        torrent.path = path
        torrentFileName = os.path.basename(path).strip() + ".torrent"
        head, tail = os.path.split(path)
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

        if arg.inject:
            qbitInject(qbit_host, qbit_username, qbit_password, "music", runDir, torrentFileName, False, postName)

        if arg.sbcopy:
            ftp_copy_folder(path, seedbox_host, seedbox_port, seedbox_ftp_user, seedbox_ftp_password, seedbox_remote_path)
            qbitInject(seedbox_qbit_host, seedbox_qbit_user, seedbox_qbit_password, "music", runDir, torrentFileName, False, postName)

        # --- Prepare common metadata for uploads ---
        if arg.upload or arg.ops:
            upload_metadata = with_metadata_overrides(
                scan.metadata,
                image=coverImgURL,
                release_type=releaseForm or scan.metadata.release_type,
                release_group_id=releaseGroupID,
            )
            red_upload_succeeded = not arg.upload
            
            # --- Upload to REDacted ---
            if arg.upload:
                logging.info("Attempting to upload to REDacted...")
                redGroupId_to_use = arg.red_groupid or arg.groupid
                if not redGroupId_to_use and upload_metadata.identity_key in red_group_ids_by_identity:
                    logging.info("Album identity matches a previous REDacted upload. Using the same REDacted group ID...")
                    redGroupId_to_use = red_group_ids_by_identity[upload_metadata.identity_key]

                warn_tracker_duplicates("red", red_api, upload_metadata)

                response_red = upload_to_red(runDir=runDir,
                                             torrent_file=os.path.join(runDir, torrentFileName),
                                             artists=upload_metadata.artist, title=upload_metadata.title, year=upload_metadata.year,
                                             ogyear=None, releasetype=upload_metadata.release_type,
                                             audioFormat=upload_metadata.audio_format, bitrate=upload_metadata.bitrate, media=upload_metadata.media,
                                             tags=upload_metadata.tags, recordLabel=upload_metadata.record_label, image=upload_metadata.image,
                                             api=red_api, releaseGroup=releaseGroupID,
                                             redGroupId=redGroupId_to_use, noDesc=arg.nodesc,
                                             skipPrompts=arg.skipPrompts,
                                             dry_run=not arg.skip_red_dryrun,
                                             edition_year=upload_metadata.edition_year)
                if response_red:
                    try:
                        response_json = response_red.json()
                        if response_red.status_code == 200 and response_json.get('status') == 'success':
                            lastGroupID = response_json['response']['groupid']
                            red_group_ids_by_identity[upload_metadata.identity_key] = lastGroupID
                            red_upload_succeeded = True
                            logging.info(f"Saved new REDacted Group ID: {lastGroupID}")
                        else:
                            logging.error(f"REDacted API returned an error: {response_json.get('error', 'Unknown error')}")
                    except json.JSONDecodeError:
                        logging.error("Failed to decode JSON from REDacted response. The site may be down or returned an error page.")
                        logging.error(f"Response Text: {response_red.text}")
                
            # --- Upload to Orpheus ---
            if arg.ops:
                if arg.upload and not red_upload_succeeded:
                    logging.error("Skipping Orpheus upload because REDacted did not complete successfully.")
                    continue
                logging.info("Attempting to upload to Orpheus...")
                opsGroupId_to_use = arg.ops_groupid
                if not opsGroupId_to_use and upload_metadata.identity_key in ops_group_ids_by_identity:
                    logging.info("Album identity matches a previous Orpheus upload. Using the same Orpheus group ID...")
                    opsGroupId_to_use = ops_group_ids_by_identity[upload_metadata.identity_key]

                warn_tracker_duplicates("ops", ops_api, upload_metadata)

                response_ops = upload_to_orpheus(runDir=runDir,
                                   torrent_file=os.path.join(runDir, torrentFileName),
                                   artists=upload_metadata.artist, title=upload_metadata.title, year=upload_metadata.year,
                                   releasetype=upload_metadata.release_type, audioFormat=upload_metadata.audio_format,
                                   bitrate=upload_metadata.bitrate, media=upload_metadata.media, tags=upload_metadata.tags,
                                   image=upload_metadata.image, api=ops_api,
                                   recordLabel=upload_metadata.record_label,
                                   remaster_year=upload_metadata.edition_year,
                                   opsGroupId=opsGroupId_to_use,
                                   skipPrompts=arg.skipPrompts)
                if response_ops:
                    try:
                        response_json = response_ops.json()
                        if response_ops.status_code == 200 and response_json.get('status') == 'success':
                            lastOpsGroupID = response_json['response']['groupId']
                            ops_group_ids_by_identity[upload_metadata.identity_key] = lastOpsGroupID
                            logging.info(f"Saved new Orpheus Group ID: {lastOpsGroupID}")
                        else:
                            logging.error(f"Orpheus API returned an error: {response_json.get('error', 'Unknown error')}")
                    except json.JSONDecodeError:
                        logging.error("Failed to decode JSON from Orpheus response. The site may be down or returned an error page.")
                        logging.error(f"Response Text: {response_ops.text}")

        lastAlbumTitle = album

def _tracker_headers(tracker: str, api: str):
    if tracker == "ops":
        return {"Authorization": f"token {api}"}
    return {
        "Authorization": api,
        "User-Agent": "TorrentMaker/1.4.2"
    }


def search_tracker_duplicates(tracker: str, api: str, metadata: MusicUploadMetadata):
    """Return likely duplicate browse results, or an empty list if lookup fails."""
    if not api:
        return []
    if tracker == "ops":
        url = "https://orpheus.network/ajax.php?action=browse"
    else:
        url = "https://redacted.ch/ajax.php?action=browse"
    params = {
        "artistname": metadata.artist,
        "groupname": metadata.title,
        "year": metadata.year,
        "format": metadata.audio_format,
        "encoding": metadata.bitrate,
        "media": metadata.media,
    }
    try:
        response = requests.get(url, headers=_tracker_headers(tracker, api), params=params, timeout=20)
        response.raise_for_status()
        body = response.json()
    except (requests.exceptions.RequestException, json.JSONDecodeError) as exc:
        logging.warning(f"{tracker.upper()} duplicate lookup failed: {exc}")
        return []
    if body.get("status") != "success":
        logging.warning(f"{tracker.upper()} duplicate lookup returned API failure: {body.get('error', 'Unknown error')}")
        return []
    response_obj = body.get("response", {})
    if isinstance(response_obj, list):
        return response_obj
    results = response_obj.get("results", []) if isinstance(response_obj, dict) else []
    if isinstance(results, list):
        return results
    return []


def warn_tracker_duplicates(tracker: str, api: str, metadata: MusicUploadMetadata):
    duplicates = search_tracker_duplicates(tracker, api, metadata)
    if duplicates:
        logging.warning(
            f"{tracker.upper()} browse found {len(duplicates)} likely duplicate result(s) for "
            f"{metadata.artist} - {metadata.title} ({metadata.year}) {metadata.audio_format} {metadata.bitrate} {metadata.media}."
        )


def _has_audio_files(path: str, recursive: bool = False) -> bool:
    walker = os.walk(path) if recursive else [(path, [], os.listdir(path) if os.path.isdir(path) else [])]
    for _, _, files in walker:
        for file_name in files:
            if file_name.lower().endswith((".mp3", ".flac")):
                return True
    return False


def expand_music_paths(paths):
    """Expand collection folders into immediate album folders, preserving multi-disc album roots."""
    expanded = []
    for path in paths:
        if not os.path.isdir(path) or _has_audio_files(path, recursive=False):
            expanded.append(path)
            continue

        child_dirs = [
            os.path.join(path, name)
            for name in sorted(os.listdir(path))
            if os.path.isdir(os.path.join(path, name))
        ]
        if any(os.path.basename(child).lower().startswith("disc") for child in child_dirs):
            expanded.append(path)
            continue

        album_dirs = [child for child in child_dirs if _has_audio_files(child, recursive=True)]
        expanded.extend(album_dirs or [path])
    return expanded


def check_md5_signatures(directory):
    """
    Scans all FLAC files in a directory to see if any are missing an MD5 signature.

    Args:
        directory (str): The path to the directory containing the music files.

    Returns:
        bool: True if any FLAC files are missing an MD5 signature, False otherwise.
    """
    flac_files = []
    # Find all FLAC files recursively
    for root, _, files in os.walk(directory):
        for file in files:
            if file.lower().endswith('.flac'):
                flac_files.append(os.path.join(root, file))

    if not flac_files:
        return False # No FLAC files to check

    missing_md5 = False
    for file_path in flac_files:
        try:
            audio = FLAC(file_path)
            if not audio.info.md5_signature:
                logging.warning(f"Missing MD5 signature in: {os.path.basename(file_path)}")
                missing_md5 = True
        except Exception as e:
            logging.error(f"Could not read metadata from {os.path.basename(file_path)}: {e}")
    
    return missing_md5

def upload_to_red(runDir, releaseGroup, torrent_file, artists: str, title: str, year, releasetype, audioFormat, bitrate, media, tags, image, api, recordLabel=None, redGroupId=None, ogyear=None, noDesc=False, skipPrompts=False, dry_run=True, edition_year=None):
    """Constructs and sends the upload request to the REDacted API."""
    url = "https://redacted.ch/ajax.php?action=upload"

    with open(os.path.join(runDir, "trackData.txt"), 'r', encoding='UTF-8') as _td:
        albumDesc = _td.read()
    albumDesc = albumDesc.replace('\u2008', ' ')
    if releaseGroup:
        musicBrainzURL = "https://musicbrainz.org/release-group/" + releaseGroup
        albumDesc = albumDesc + "\n\n\n" + f"[url={musicBrainzURL}]MusicBrainz Release Group[/url]"

    if 'remix' in title.lower():
        releasetype = 'Remix'

    initial_year = year
    if ogyear:
        initial_year = ogyear
        edition_year = year

    metadata = MusicUploadMetadata(
        artist=artists,
        title=title,
        year=initial_year,
        release_type=releasetype,
        audio_format=audioFormat,
        bitrate=bitrate,
        media=media,
        tags=format_tracker_tags(tags),
        image=image,
        record_label=recordLabel,
        edition_year=edition_year,
        release_group_id=releaseGroup,
    )

    headers = {
        "Authorization": api,
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/107.0.0.0 Safari/537.36"
    }

    if recordLabel:
        if len(recordLabel) < 2 or len(recordLabel) > 80:
            play_alert("input")
            recordLabel = input("Gotten record label too long or too short for RED\nGotten label: " + recordLabel + "\nPlease input a record label:\n")
        first_artist = artists.split(',')[0].strip()
        if 'records dk' in recordLabel.lower() or first_artist.lower() == recordLabel.lower():
            recordLabel = 'Self-Released'
        metadata.record_label = recordLabel

    try:
        data = build_red_payload(metadata, albumDesc, group_id=redGroupId, no_desc=noDesc)
        dryrun_data = build_red_payload(metadata, albumDesc, group_id=redGroupId, dryrun=True, no_desc=noDesc)
    except ValueError as exc:
        logging.error(f"REDacted upload payload is incomplete: {exc}")
        return None

    pprint(data)
    if skipPrompts or getUserInput("Do you want to upload this to REDacted?"):
        try:
            if dry_run:
                logging.info("Sending REDacted dry-run upload request...")
                with open(torrent_file, 'rb') as torrent_f:
                    dryrun_response = requests.post(headers=headers, url=url, data=dryrun_data, files={'file_input': torrent_f}, timeout=30)
                dryrun_response.raise_for_status()
                try:
                    dryrun_json = dryrun_response.json()
                except json.JSONDecodeError:
                    logging.error(f"REDacted dry-run did not return JSON: {dryrun_response.text}")
                    return None
                if dryrun_json.get('status') != 'success':
                    logging.error(f"REDacted dry-run failed: {dryrun_json.get('error', 'Unknown error')}")
                    logging.error(f"Response content: {dryrun_response.text}")
                    return None
                logging.info("REDacted dry-run succeeded.")

            with open(torrent_file, 'rb') as torrent_f:
                torrent_payload = {'file_input': torrent_f}
                response = requests.post(headers=headers, url=url, data=data, files=torrent_payload, timeout=30)
            response.raise_for_status()
            return response
        except requests.exceptions.RequestException as e:
            logging.error(f"Failed to upload to REDacted: {e}")
            if 'response' in locals() and response:
                logging.error(f"Response content: {response.text}")
            return None
    else:
        return None

def upload_to_orpheus(runDir, torrent_file, artists: str, title: str, year, releasetype, audioFormat, bitrate, media, tags, image, api, recordLabel=None, remaster_year=None, opsGroupId=None, skipPrompts=False):
    """Constructs and sends the upload request to the Orpheus API."""
    
    upload_url = "https://orpheus.network/ajax.php?action=upload"
    headers = { "Authorization": f"token {api}" }

    with open(os.path.join(runDir, "trackData.txt"), 'r', encoding='UTF-8') as _td:
        albumDesc = _td.read()

    metadata = MusicUploadMetadata(
        artist=artists,
        title=title,
        year=year,
        release_type=releasetype,
        audio_format=audioFormat,
        bitrate=bitrate,
        media=media,
        tags=format_tracker_tags(tags),
        image=image,
        record_label=recordLabel,
        edition_year=remaster_year,
    )
    try:
        data = build_ops_payload(metadata, albumDesc, group_id=opsGroupId)
    except ValueError as exc:
        logging.error(f"Orpheus upload payload is incomplete: {exc}")
        return None

    if opsGroupId:
        logging.info(f"Using existing Orpheus Group ID: {opsGroupId}")

    pprint(data)
    if skipPrompts or getUserInput("Do you want to upload this to Orpheus?"):
        try:
            with open(torrent_file, 'rb') as torrent_f:
                files = {'file_input': torrent_f}
                response = requests.post(url=upload_url, headers=headers, data=data, files=files, timeout=30)
            response.raise_for_status()
            logging.info("Successfully uploaded to Orpheus.")
            pprint(response.json())
            return response
        except requests.exceptions.RequestException as e:
            logging.error(f"Failed to upload to Orpheus: {e}")
            if 'response' in locals() and response:
                logging.error(f"Response content: {response.text}")
            return None
    else:
        return None

def extract_album_art(folder_path):
    for root, dirs, files in os.walk(folder_path):
        for file in files:
            if file.lower().endswith(('.mp3', '.flac', '.ogg', '.m4a', '.wav')):
                audio_file_path = os.path.join(root, file)
                audio = File(audio_file_path)
                if 'APIC:' in audio:
                    cover = audio.tags['APIC:'].data
                elif 'covr' in audio:
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
    os.chdir(folder_path)
    command = ['flac', '-f8', '*.flac']
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, universal_newlines=True, shell=True)
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
    if copyright_string:
        label = process_string(copyright_string)
    if label is not None:
        parts = label.lower().split('under exclusive')
        if len(parts) > 0:
            label = parts[0].strip()
    return label

def process_string(input_string):
    output_string = re.sub(r'\b\d{4}\b', '', input_string)
    words = output_string.split()
    unique_words = []
    for word in words:
        if word not in unique_words:
            unique_words.append(word)
    output_string = ' '.join(unique_words)
    output_string = re.sub(r'[™©®℗]', '', output_string)
    output_string = output_string.split(', ')[0].strip()
    return output_string

def download_torrent(runDir, torrent_id, api_key):
    url = 'https://redacted.ch/ajax.php?action=download'
    headers = {'Authorization': api_key}
    params = {'id': torrent_id}
    response = requests.get(url, params=params, headers=headers)
    if response.status_code == 200:
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
    for filename in sorted(os.listdir(path)):
        file_path = os.path.join(path, filename)
        if filename.lower().endswith(".mp3"):
            audio = EasyID3(file_path)
            if 'date' in audio:
                release_year = int(audio.get('date')[0][:4])
                return release_year
        elif filename.lower().endswith(".flac"):
            audio = FLAC(file_path)
            if 'year' in audio:
                release_year = int(audio['year'][0])
                return release_year
            elif 'date' in audio:
                release_year = int(audio['date'][0][:4])
                return release_year

    if release_year is None:
        logging.error("No release year found in any file. Please check the metadata.")
        print_all_metadata_path(path) # Print metadata for debugging
        play_alert("input")
        release_year = int(input("Please enter the 4-digit release year manually:\n"))
    return release_year

def get_genre(path):
    for filename in os.listdir(path):
        if filename.endswith(".mp3"):
            audio = EasyID3(os.path.join(path, filename))
            break
        elif filename.endswith(".flac"):
            audio = FLAC(os.path.join(path, filename))
            break
    try:
        genre = audio['genre'][0]
        genre = genre.replace('Alternatif et Indé', 'Alternative, Indie')
        genre = genre.replace('Bandes originales de films', 'Stage and Screen')
    except (KeyError, NameError):
        logging.error("No genre found, please give genres comma separated")
        play_alert("input")
        genre = input()
    return genre.lower()

def detect_audio_format(path):
    for filename in os.listdir(path):
        filepath = os.path.join(path, filename)
        if os.path.isfile(filepath):
            ext = os.path.splitext(filename)[1].lower()
            if ext in {'.mp3', '.mp2', '.mpga'}: return "MP3"
            if ext in {'.flac'}: return "FLAC"
    return None

def get_album_type(folder_path):
    audio_files = []
    if isinstance(folder_path, list):
        for path in folder_path:
            audio_files.extend([os.path.join(path, f) for f in os.listdir(path) if f.endswith(('.mp3', '.flac'))])
    else:
        audio_files.extend([os.path.join(folder_path, f) for f in os.listdir(folder_path) if f.endswith(('.mp3', '.flac'))])

    if not audio_files: raise ValueError(f"No audio files found in {folder_path}")

    track_numbers = set()
    for audio_file in audio_files:
        try:
            audio = mutagen.File(audio_file)
            track_numbers.add(audio.get("tracknumber", [""])[0].split('/')[0])
        except Exception:
            pass
    
    if not track_numbers: raise ValueError("No track numbers found in audio files")
    
    track_numbers = {int(t) for t in track_numbers if t.isdigit()}
    if len(track_numbers) < 3: return "Single"
    if len(track_numbers) <= 5: return "EP"
    return "Album"

def get_audio_files(path):
    audio_files = []
    for root, dirs, files in os.walk(path):
        for file in files:
            if file.endswith((".mp3", ".flac")):
                audio_files.append(os.path.join(root, file))
    return audio_files

def get_bitrate_or_lossless(path):
    audio_files = get_audio_files(path)
    if not audio_files: return None
    for file_path in audio_files:
        audio = mutagen.File(file_path)
        if audio:
            if audio.mime[0] == "audio/mp3":
                bitrate = audio.info.bitrate // 1000
                if bitrate in {320, 256, 192}: return str(bitrate)
            elif audio.mime[0] == "audio/flac":
                bit_depth = audio.info.bits_per_sample
                if bit_depth == 16: return "Lossless"
                if bit_depth == 24: return "24bit Lossless"
    return None

def check_file_path_length(folder_path):
    for root, dirs, files in os.walk(folder_path):
        for file_name in files:
            if len(os.path.basename(root)) + len(file_name) > 180:
                return False
    return True

def format_genres(genre_str):
    # Replace common separators with commas first
    processed_str = genre_str.replace('/', ',').replace('&', ',')
    genres = processed_str.split(',')
    # Format each genre tag: strip whitespace, replace spaces with dots, convert to lowercase
    formatted_genres = [g.strip().replace(' ', '.').lower() for g in genres if g.strip()]
    # Join the cleaned tags back into a single string
    return ', '.join(formatted_genres)

def convert_roles_to_int(roles_list):
    roles_dict = { "Main": 1, "Guest": 2, "Composer": 4, "Conductor": 5, "DJ / Compiler": 6, "Remixer": 3, "Producer": 7 }
    return [roles_dict.get(role, 1) for role in roles_list]

def get_first_song_album(folder_path):
    for file_name in sorted(os.listdir(folder_path)):
        if file_name.endswith((".mp3", ".flac")):
            audio = mutagen.File(os.path.join(folder_path, file_name))
            if audio and 'album' in audio:
                return audio['album'][0]
    return None

def print_all_metadata_path(path):
    for file in sorted(os.listdir(path)):
        if file.endswith(('.mp3', '.m4a', '.flac')):
            print_all_metadata(os.path.join(path, file))

def print_all_metadata(file_path):
    audio = mutagen.File(file_path)
    pprint(audio)

def get_first_song_artist(folder_path):
    for file_name in sorted(os.listdir(folder_path)):
        if file_name.endswith((".mp3", ".flac")):
            audio = mutagen.File(os.path.join(folder_path, file_name))
            if audio:
                if 'albumartist' in audio: return audio['albumartist'][0]
                if 'artist' in audio: return audio['artist'][0]
    logging.error("No suitable artist found.")
    return None

def find_album_match(artist_name, album_name):
    try:
        artist_results = mb.search_artists(artist_name)
        if not artist_results["artist-list"]: return None
        
        best_artist = None
        for result in artist_results["artist-list"]:
            if similarity(result['name'], artist_name) > 95:
                best_artist = result
                break
        if not best_artist: return None

        album_results = mb.search_releases(artist=best_artist['name'], release=album_name)
        if not album_results["release-list"]: return None

        for result in album_results['release-list']:
            if best_artist['name'] in [a['name'] for a in result['artist-credit']]:
                return mb.get_release_group_by_id(result["release-group"]["id"])
    except Exception as e:
        logging.error(f"MusicBrainz search failed: {e}")
    return None

def check_missing_tracks(directory):
    music_files = [f for f in os.listdir(directory) if f.endswith(('.mp3', '.m4a', '.flac'))]
    track_numbers = []
    for file in music_files:
        try:
            tags = mutagen.File(os.path.join(directory, file))
            track_number = tags['tracknumber'][0].split('/')[0]
            if track_number.isdigit():
                track_numbers.append(int(track_number))
        except Exception:
            pass
    missing_tracks = []
    if track_numbers:
        for i in range(1, max(track_numbers) + 1):
            if i not in track_numbers:
                missing_tracks.append(i)
    return missing_tracks

def add_track_position(folder_path):
    music_files = sorted([f for f in os.listdir(folder_path) if f.endswith(('.mp3', '.wav', '.flac'))])
    for i, file_name in enumerate(music_files):
        if not file_name[:2].isdigit():
            track_position = str(i + 1).zfill(2)
            new_file_name = f"{track_position} - {file_name}"
            os.rename(os.path.join(folder_path, file_name), os.path.join(folder_path, new_file_name))
            logging.info(f"Renamed to: {new_file_name}")
    logging.info("Track positions added successfully!")

def create_track_list(folder_path, output_file):
    track_list = []
    
    def process_folder(path, disc_prefix=""):
        music_files = sorted([f for f in os.listdir(path) if f.endswith(('.mp3', '.wav', '.flac'))])
        for i, file_name in enumerate(music_files):
            audio = mutagen.File(os.path.join(path, file_name))
            track_length = int(audio.info.length)
            minutes, seconds = divmod(track_length, 60)
            track_length_str = f"{int(minutes):02d}:{int(seconds):02d}"
            title = audio.get('title', [os.path.splitext(file_name)[0]])[0]
            track_position = str(i + 1).zfill(2)
            track_list.append(f"{disc_prefix}{track_position}. {title} ({track_length_str})")

    if isinstance(folder_path, list):
        for path in folder_path:
            disc_number = os.path.basename(path).split(" ")[-1]
            track_list.append(f"\nDisk {disc_number}:")
            process_folder(path)
    else:
        process_folder(folder_path)

    with open(output_file, 'w', encoding='UTF-8') as f:
        f.write('\n'.join(track_list))
    logging.info(f"Track list written to {output_file} successfully!")

def ftp_copy_folder(local_folder_path, host, port, username, password, remote_path='/downloads/qbittorrent'):
    remote_folder_path = remote_path
    try:
        with FTP_TLS() as ftp:
            ftp.connect(host, port)
            ftp.login(username, password)
            ftp.prot_p()
            ftp.cwd(remote_folder_path)
            
            remote_target_dir = os.path.join(remote_folder_path, os.path.basename(local_folder_path))
            try:
                ftp.mkd(os.path.basename(local_folder_path))
            except Exception:
                logging.warning(f"Directory {os.path.basename(local_folder_path)} likely already exists.")

            for root, dirs, files in os.walk(local_folder_path):
                relative_path = os.path.relpath(root, local_folder_path)
                remote_dir = os.path.join(remote_target_dir, relative_path) if relative_path != '.' else remote_target_dir
                
                for d in dirs:
                    try:
                        ftp.mkd(os.path.join(remote_dir, d))
                    except Exception:
                        pass # Ignore if exists

                for file in files:
                    local_file = os.path.join(root, file)
                    remote_file = os.path.join(remote_dir, file)
                    with open(local_file, 'rb') as f:
                        ftp.storbinary(f'STOR {remote_file}', f)
                    logging.info(f"Uploaded {file} to {remote_file}")
        logging.info("Folder copied successfully!")
    except Exception as e:
        logging.error(f"FTP copy failed: {e}")

if __name__ == "__main__":
    main()
