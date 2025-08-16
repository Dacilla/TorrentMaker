import argparse
import logging
import sys
import os
import re
import guessit
from pprint import pformat

from torrent_utils.helpers import getUserInput, get_path_list
from torrent_utils.config_loader import load_settings, validate_settings
from torrent_utils.media import Movie, TVShow

__VERSION = "2.0.2" # Incremented version for the fix
LOG_FORMAT = "%(asctime)s.%(msecs)03d %(levelname)-8s P%(process)06d.%(module)-12s %(funcName)-16sL%(lineno)04d %(message)s"
LOG_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

BULK_DOWNLOAD_FILE = os.path.join(os.getcwd(), "bulkProcess.txt")

def main():
    parser = argparse.ArgumentParser(
        description="A script to intelligently rename media files based on metadata."
    )
    # Arguments remain the same as before
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
        help="Source of the media (e.g., BluRay, WEB-DL).",
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

    pathList = get_path_list(arg.path, BULK_DOWNLOAD_FILE)

    for path in pathList:
        # --- Object-Oriented Approach ---
        guessItOutput = guessit.guessit(os.path.basename(path))
        is_movie = guessItOutput.get('type') == 'movie'
        
        media_file = None
        try:
            if is_movie:
                media_file = Movie(path, tmdb_api, arg.tmdb)
            else:
                media_file = TVShow(path, tmdb_api, arg.tmdb)
        except ValueError as e:
            logging.error(e)
            continue

        group = arg.group or media_file.guessit_info.get('release_group', 'NOGRP')
        if isinstance(group, list):
            group = group[0]
        group = re.sub(r"[\[\]\(\)\{\}]", " ", group).split()[0]
        
        source = arg.source or ""
        # --- ADDED: Standardize Blu-ray source naming ---
        if source.lower() == 'blu-ray':
            source = 'BluRay'
            logging.info("Standardized source to 'BluRay'")

        postFileName = media_file.generate_name(source=source, group=group, huno_format=arg.huno_format)

        if not postFileName:
            logging.error(f"Could not generate a new name for {path}. Skipping.")
            continue

        logging.info("Final file name:\n" + postFileName)
        
        if arg.skip_prompts or getUserInput("Is this acceptable?"):
            destination_path = os.path.join(os.path.dirname(path), postFileName)
            
            try:
                if arg.hardlink:
                    logging.info("Creating renamed hardlink...")
                    if os.path.exists(destination_path):
                        logging.warning(f"Destination file already exists: {destination_path}. Skipping.")
                        continue
                    os.link(src=path, dst=destination_path)
                    logging.info(f"Hardlink created at: {destination_path}")
                else:
                    logging.info("Renaming file...")
                    if os.path.exists(destination_path):
                         logging.warning(f"Destination file already exists: {destination_path}. Skipping.")
                         continue
                    os.rename(src=path, dst=destination_path)
                    logging.info(f"File renamed to: {destination_path}")
            except OSError as e:
                logging.error(f"Failed to rename/link file: {e}")

if __name__ == "__main__":
    main()
