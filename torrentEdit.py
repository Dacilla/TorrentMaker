import argparse
import torf
import logging
import os
import sys

__VERSION = "1.0.0"
LOG_FORMAT = "%(asctime)s.%(msecs)03d %(levelname)-8s P%(process)06d.%(module)-12s %(funcName)-16sL%(lineno)04d %(message)s"
LOG_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

BULK_EDIT_FILE = "bulkEdit.txt"

# Parse command line arguments
parser = argparse.ArgumentParser(description='Edit a torrent file')
parser.add_argument('file', help='path to the torrent file')
parser.add_argument('-s', '--source', help='new value for the source field')
arg = parser.parse_args()

logging.basicConfig(datefmt=LOG_DATE_FORMAT, format=LOG_FORMAT, level=logging.INFO)
logging.info(f"Version {__VERSION} starting...")

pathList = []
if not arg.path:
    logging.info(f"No explicit path given, reading {BULK_EDIT_FILE}")
    if not os.path.exists(BULK_EDIT_FILE):
        logging.warning(f"No {BULK_EDIT_FILE} file found. Creating...")
        with open(BULK_EDIT_FILE, 'w') as f:
            f.write("")
    with open(BULK_EDIT_FILE, 'r') as dlFile:
        file_contents = dlFile.read()
        if len(file_contents) == 0:
            logging.error(f"No path given in either arg.path or {BULK_EDIT_FILE}. Exiting...")
            sys.exit(-1)
        print(f"File contents: {file_contents}")
        for line in file_contents.split('\n'):
            pathList.append(line.strip().replace("\"", ""))
            print(f"Added {line.strip()} to pathList")
    logging.info("Loaded " + str(len(pathList)) + " paths...")
else:
    pathList.append(arg.path)

for path in pathList:
    # Load the torrent file
    with open(path, 'rb') as f:
        torrent_data = f.read()

    torrent = torf.Torrent(torrent_data)

    # Update the source flag if argument provided
    if arg.source is not None:
        torrent.source = arg.source

    # Save the modified torrent file
    
