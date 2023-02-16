import logging
import os
import json

from pymediainfo import MediaInfo
from pprint import pformat

from torrentmaker.torrentmaker import DUMPFILE


def downloadMediaInfo():
    if not os.path.isdir("Mediainfo"):
        os.mkdir("Mediainfo")
    # Iterate through all the files in the root folder and its subfolders
    mediainfoExists = False
    for root, dirs, files in os.walk("Mediainfo"):
        for file in files:
            if file.lower == "mediainfo.exe":
                mediainfoExists = True
                logging.info("Mediainfo CLI found!")
                break
        if mediainfoExists:
            break
    if not mediainfoExists:
        logging.info("Mediainfo CLI not found. Downloading...")


def generateMIDump():
    global dataFile
    dataFile: dict
    if dataFile['isFolder'] == 1:
        file = os.path.basename(dataFile['path'])
        dataFile['mediaInfoText'] = getInfoDump(dataFile['path'], dataFile['runDir'])
        dataFile['videoFile'] = dataFile['path']
    elif dataFile['isFolder'] == 2:
        # List all files in the folder
        data = os.listdir(dataFile['path'])
        # Sort the files alphabetically
        data.sort()

        # Look for the first video file
        for file in data:
            # Check the file extension
            name, ext = os.path.splitext(file)
            if ext in ['.mp4', '.avi', '.mkv']:
                # Found a video file
                dataFile['videoFile'] = dataFile['path'] + os.sep + file
                dataFile['mediaInfoText'] = getInfoDump(dataFile['path'] + os.sep + file, dataFile['runDir'])
                logging.debug(pformat(json.loads(dataFile['mediaInfoText'])))
                break
    dataFile['mediaInfoText'] = dataFile['mediaInfoText'].strip()
    dataFile['mediaInfoText'] = json.loads(dataFile['mediaInfoText'])


def getInfoDump(filePath: str, runDir: str):
    output = MediaInfo.parse(filename=filePath, output="", full=False)
    logging.debug(output)
    # don't ask, the output looks fine in the terminal, but writing it
    # to a file adds empty lines every second line. This deletes them
    logging.info("Creating mediainfo dump at " + runDir + DUMPFILE)
    with open(runDir + DUMPFILE, "w") as f:
        f.write(output)
    with open(runDir + DUMPFILE, "r") as fi:
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
    with open(runDir + DUMPFILE, 'w') as fo:
        # Write the modified lines to the file
        for line in new_lines:
            fo.write(line)
    # Create a new mediainfo dump in JSON for parsing later
    output = MediaInfo.parse(filename=filePath, output="JSON", full=False)
    return output
