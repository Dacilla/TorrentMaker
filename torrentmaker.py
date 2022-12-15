import argparse
import os
import logging
import sys
import requests
import cv2
import torf

from base64 import b64encode
from pymediainfo import MediaInfo

__VERSION = "1.0.0"
LOG_FORMAT = "%(asctime)s.%(msecs)03d %(levelname)-8s P%(process)06d.%(module)-12s %(funcName)-16sL%(lineno)04d %(message)s"
LOG_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

DUMPFILE = "mediainfo.txt"
APIKEYFILE = "tmdbApi.txt"


def main():
    parser = argparse.ArgumentParser(
        description="Script to automate creation of torrent files, as well as grabbing mediainfo dump, screenshots, and tmdb description"
    )
    parser.add_argument(
        "path", action="store",
        help="Path for file or folder to create .torrent file for",
        type=str
    )
    parser.add_argument(
        "-t", "--tmdb",
        action="store",
        type=int,
        help="TMDB ID for media",
        default=None
    )
    parser.add_argument(
        "-u",
        "--upload",
        action="store_true",
        default=False,
        help="Enable to upload generated screenshots to imgbb automatically"
    )
    parser.add_argument(
        "-D", "--debug", action="store_true", help="debug mode", default=False
    )
    parser.add_argument(
        "-V", "--version", action="version", version="%(prog)s {version}".format(version=__VERSION),
    )

    arg = parser.parse_args()
    level = logging.INFO
    if arg.debug:
        level = logging.DEBUG

    logging.basicConfig(datefmt=LOG_DATE_FORMAT, format=LOG_FORMAT, level=level)
    logging.info(f"Version {__VERSION} starting...")

    path = arg.path
    result = FileOrFolder(path)
    if result not in [1, 2]:
        logging.error("Input not a file or directory")
        sys.exit()
    logging.info(f"Creating mediainfo dump in {DUMPFILE}...")
    if result == 1:
        videoFile = path
        info = getInfoDump(path)
    elif result == 2:
        # List all files in the folder
        files = os.listdir(path)

        # Sort the files alphabetically
        files.sort()

        # Look for the first video file
        for file in files:
            # Check the file extension
            name, ext = os.path.splitext(file)
            if ext in ['.mp4', '.avi', '.mkv']:
                # Found a video file
                videoFile = path + os.sep + file
                info = getInfoDump(path + os.sep + file)
                break
    logging.info("Mediainfo dump created")

    if arg.tmdb is not None:
        if not os.path.isfile(os.getcwd() + os.sep + APIKEYFILE):
            logging.error(f"{APIKEYFILE} does not exist")
            sys.exit()
        # Get TMDB info
        logging.info("Getting TMDB description")
        # Replace YOUR_API_KEY with your TMDb API key
        with open(APIKEYFILE) as fa:
            api_key = fa.read()

        # Replace TV_SHOW_ID with the ID of the TV show you want to get the description for
        tv_show_id = arg.tmdb

        # Build the URL for the API request
        url = f'https://api.themoviedb.org/3/tv/{tv_show_id}?api_key={api_key}'

        # Make the GET request to the TMDb API
        response = requests.get(url)

        # Get the JSON data from the response
        data = response.json()

        # Print the description of the TV show
        logging.debug("description gotten: " + data['overview'])
        with open("showDesc.txt", "w") as fb:
            fb.write(data['overview'] + "\n\n")
        logging.info("TMDB Description dumped to showDesc.txt")

    logging.info("Making screenshots...")
    if not os.path.isdir("screenshots"):
        os.mkdir("screenshots")
    else:
        files = os.listdir("screenshots")
        for i in files:
            os.remove("screenshots" + os.sep + i)

    video = cv2.VideoCapture(videoFile)
    # Get the total duration of the video in seconds
    total_duration = int(video.get(cv2.CAP_PROP_FRAME_COUNT)) / int(video.get(cv2.CAP_PROP_FPS))

    # Define the timestamps for the screenshots
    timestamps = [i * total_duration / 10 for i in range(10)]
    # remove the first and last items from the list so we don't get totally black screenshots and/or screenshots of the first and last frames
    timestamps.pop(0)
    timestamps.pop(-1)

    # Iterate over the timestamps and create a screenshot at each timestamp
    for timestamp in timestamps:
        # Set the video position to the timestamp
        video.set(cv2.CAP_PROP_POS_MSEC, timestamp * 1000)
        # Read the frame at the current position
        success, image = video.read()
        if success:
            # Save the image to a file
            cv2.imwrite(f"screenshots{os.sep}" + "screenshot_{}.png".format(timestamp), image)
            logging.info(f"Screenshot made at screenshots{os.sep}" + "screenshot_{}.png".format(timestamp))

    if arg.upload:
        logging.info("Uploading screenshots to imgbb")
        if not os.path.isfile("imgbbApi.txt"):
            logging.error("No imgbbApi.txt file found")
            sys.exit()
        with open("imgbbApi.txt", "r") as bb:
            imgbbAPI = bb.read()
        api_endpoint = "https://api.imgbb.com/1/upload"
        images = os.listdir("screenshots")
        logging.info("Screenshots loaded...")
        UrlList = []
        for image in images:
            logging.info(f"Uploading {image}")
            # Open the file and read the data
            filePath = "screenshots" + os.sep + image
            with open(filePath, "rb") as file:
                file_data = file.read()
            # Set the payload for the POST request
            payload = {
                "key": imgbbAPI,
                "image": b64encode(file_data),
            }
            # with tqdm(total=file_size, unit="B", unit_scale=True, unit_divisor=1024) as t:
            #     wrapped_file = CallbackIOWrapper(t.update, payload)
            #     requests.put(api_endpoint, data=wrapped_file)
            response = requests.post(api_endpoint, payload)
            # Get the image URL from the response
            image_url = response.json()
            logging.debug(image_url)
            try:
                image_url = response.json()["data"]["url"]
                image_url_viewer = response.json()["data"]["url_viewer"]
                # Print the image URL
                # Template: [url=https://ibb.co/0fbvMqH][img]https://i.ibb.co/0fbvMqH/screenshot-785-895652173913.png[/img][/url]
                bbcode = f"[url={image_url_viewer}][img]{image_url}[/img][/url]"
                with open("showDesc.txt", "a") as fileAdd:
                    fileAdd.write(bbcode + "\n")
                logging.info(f"bbcode for image URL {image_url} added to showDesc.txt")
            except Exception as e:
                logging.critical("Unexpected Exception: " + e)
                continue
    
    logging.info("Creating torrent file")
    torrent = torf.Torrent()
    torrent.private = True
    # using the same result variable from way earlier to tell if path is a file or folder


def FileOrFolder(path: str):
    # returns 1 if file, 2 if folder, 0 if neither
    if os.path.isfile(path):
        return 1
    elif os.path.isdir(path):
        return 2
    else:
        return 0


def getInfoDump(filePath: str):
    output = MediaInfo.parse(filename=filePath, output="", full=False)
    logging.debug(output)
    # don't ask, the output looks fine in the terminal, but writing it
    # to a file adds empty lines every second line. This deletes them
    with open(DUMPFILE, "w") as f:
        f.write(output)
    with open(DUMPFILE, "r") as fi:
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
    with open(DUMPFILE, 'w') as fo:
        # Write the modified lines to the file
        for line in new_lines:
            fo.write(line)

if __name__ == "__main__":
    main()
