import argparse
import torf
import logging
import os
import sys

from torrent_utils.helpers import get_path_list # Import the new helper function

__VERSION = "1.1.0" # Incremented version
LOG_FORMAT = "%(asctime)s.%(msecs)03d %(levelname)-8s P%(process)06d.%(module)-12s %(funcName)-16sL%(lineno)04d %(message)s"
LOG_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

BULK_EDIT_FILE = "bulkEdit.txt"

def main():
    # Parse command line arguments
    parser = argparse.ArgumentParser(description='Edit a torrent file')
    parser.add_argument('file', nargs='?', default=None, help='path to the torrent file')
    parser.add_argument('-s', '--source', help='new value for the source field')
    arg = parser.parse_args()

    logging.basicConfig(datefmt=LOG_DATE_FORMAT, format=LOG_FORMAT, level=logging.INFO)
    logging.info(f"Version {__VERSION} starting...")

    # --- Use the new helper function to get the list of paths ---
    # Note: 'file' is the argument name in this script
    pathList = get_path_list(arg.file, BULK_EDIT_FILE)

    for path in pathList:
        try:
            # Load the torrent file
            with open(path, 'rb') as f:
                torrent = torf.Torrent.read_from_file(path)

            # Update the source flag if argument provided
            if arg.source is not None:
                logging.info(f"Updating source for '{os.path.basename(path)}' to '{arg.source}'")
                torrent.source = arg.source

            # Save the modified torrent file
            torrent.write(path)
            logging.info(f"Successfully updated '{os.path.basename(path)}'")

        except FileNotFoundError:
            logging.error(f"File not found: {path}. Skipping.")
        except Exception as e:
            logging.error(f"An error occurred while processing {path}: {e}")

if __name__ == "__main__":
    main()
