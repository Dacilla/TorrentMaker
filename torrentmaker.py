import argparse
import os
import sys
import requests
import cv2
import torf
import json
import re
import shutil
import zipfile

from datetime import datetime


__VERSION = "1.0.0"
LOG_FORMAT = "%(asctime)s.%(msecs)03d %(levelname)-8s P%(process)06d.%(module)-12s %(funcName)-16sL%(lineno)04d %(message)s"
LOG_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"



# TODO: Support anime with MAL ID (HUNO API Doesn't support MAL atm)
# TODO: Add detection of bluray extras
# TODO: Download Mediainfo if it's not found
# TODO: Add support for more trackers
# TODO: Add documentation to readme
# TODO: Support BD Raw Discs
# TODO: Add AV1 detection
# TODO: Support music
# TODO: Add function to stop multiple instances from reading off the same drive, slowing it down for both

# https://qbittorrent-api.readthedocs.io/en/latest/apidoc/torrents.html#qbittorrentapi.torrents.TorrentDictionary.rename_file


def main():
    

    

    if arg.huno:
        logging.info("Uploading to HUNO enabled")
        pathresult = FileOrFolder(path)
        if pathresult == 1 or arg.movie or arg.episode:
            season_pack = 0
        else:
            season_pack = 1

        if arg.movie:
            category = 1
        else:
            category = 2

        if videoCodec == "x265":
            type_id = 15
        elif "remux" in source.lower():
            type_id = 2
        else:
            type_id = 3

        match resolution:
            case "2160p":
                resolution_id = 2
            case "1080p":
                resolution_id = 3
            case "1080i":
                resolution_id = 4
            case "720p":
                resolution_id = 5
            case "576p":
                resolution_id = 6
            case "480p":
                resolution_id = 8

        # Get IMDB ID from TVDB API
        if arg.movie:
            IMDB_ID = tmdbData["imdb_id"]
            TVDB_ID = 0
        else:
            url = f'https://api.themoviedb.org/3/tv/{tv_show_id}/external_ids?api_key={tmdb_api}'
            # Make the GET request to the TMDb API
            response = requests.get(url)

            # Get the JSON data from the response
            tmdbtoIMDDdata = response.json()
            IMDB_ID = tmdbtoIMDDdata['imdb_id']
            TVDB_ID = tmdbtoIMDDdata['tvdb_id']
        # Get description
        IMDB_ID = int(re.findall(r'\d+', IMDB_ID)[0])
        with open(runDir + "showDesc.txt", "r") as descFile:
            description = descFile.read()

        # Get MediaInfo Dump
        with open(runDir + "mediainfo.txt", "r") as infoFile:
            mediaInfoDump = infoFile.read()

        # Get post name
        postName = torrentFileName.replace(".torrent", "")
        torrent_file = runDir + torrentFileName
        torrent_file = {'torrent': open(torrent_file, 'rb')}
        data = {
            'season_pack': season_pack,
            'stream': 1,
            'anonymous': 0,
            'internal': 0,
            'category_id': category,
            'type_id': type_id,
            'resolution_id': resolution_id,
            'tmdb': arg.tmdb,
            'imdb': IMDB_ID,
            'tvdb': TVDB_ID,
            'description': f'''{description}''',
            'mediainfo': f'''{mediaInfoDump}''',
            'name': postName,
        }

        # Get the season number
        if not arg.movie:
            seasonNum = int(re.findall(r'\d+', season)[0])
            data["season"] = seasonNum
            if arg.episode:
                seasonNum = int(re.findall(r'\d+', episode)[0])
            else:
                data["episode"] = 0
        # if arg.mal:
        #     data['mal'] = int(arg.mal)
        # pprint(headers)
        print(data)
        print("\n-------------------------\n")
        pprint(data)
        # print(headers)
        if arg.skipPrompt or getUserInput("Do you want to upload this to HUNO?"):
            # Make API requests
            logging.info("HUNO API KEY: " + huno_api)
            url = f"https://hawke.uno/api/torrents/upload?api_token={huno_api}"
            logging.info("API URL: " + url)
            response = requests.post(url=url, data=data, files=torrent_file)
            print(response.status_code)
            print(response.json())

    if arg.inject:
        logging.info("Qbittorrent injection enabled")
        logging.info("Logging in to qbit...")
        qb = qbittorrentapi.Client("http://192.168.1.114:8080", username=qbit_username, password=qbit_password)
        # try:
        #     qb.auth_log_in()
        # except qbittorrentapi.LoginFailed as e:
        #     print(e)
        #     sys.exit()
        # except Exception as e:
        #     print(e)
        #     sys.exit()
        logging.info("Logged in to qbit")
        torrent_file = runDir + torrentFileName
        torrent_file = rf"{torrent_file}"
        logging.info(f"Injecting {torrent_file} to qbit...")
        if arg.huno:
            paused = False
        else:
            paused = True
        try:
            result = qb.torrents_add(is_skip_checking=True, torrent_files=torrent_file, is_paused=paused, category="HUNO", tags="Self-Upload", rename=postName)
        except Exception as e:
            print(e)
        if result == "Ok.":
            logging.info("Torrent successfully injected.")
        else:
            logging.critical(result)







def check_folder_for_episode(folder_path):
    # list all files in folder
    files = os.listdir(folder_path)
    video_files = [f for f in files if f.endswith('.mp4') or f.endswith('.mkv') or f.endswith('.avi')]
    # check if there is only one video file
    if len(video_files) != 1:
        return None
    # check if the video file name has format S00E00
    episode_pattern = re.compile(r'S\d{2}E\d{2}')
    match = episode_pattern.search(video_files[0])
    if match:
        return match.group()
    return None








def downloadMediainfo():
    # Set the URL for the mediainfo download
    url = "https://mediaarea.net/download/binary/mediainfo/22.12/MediaInfo_CLI_22.12_Windows_x64.zip"

    # Set the destination folder
    destination_folder = "Mediainfo"

    # Create the destination folder if it doesn't already exist
    if not os.path.exists(destination_folder):
        os.makedirs(destination_folder)

    # Download the file
    response = requests.get(url)
    open("MediaInfo_CLI_22.12_Windows_x64.zip", "wb").write(response.content)
    logging.info("MediaInfo_CLI_22.12_Windows_x64.zip downloaded. Unpacking in to ./Mediainfo/")
    # Unpack the zip file
    with zipfile.ZipFile("MediaInfo_CLI_22.12_Windows_x64.zip", "r") as zip_ref:
        zip_ref.extractall(destination_folder)

    # Delete the zip file
    os.remove("MediaInfo_CLI_22.12_Windows_x64.zip")







def getUserInput(question: str):
    question = question + " [y, n]"
    Userinput = None
    while Userinput not in ["y", "yes", "n", "no"]:
        Userinput = input(question)
        if Userinput in ["y", "yes"]:
            return True
        if Userinput in ["n", "no"]:
            return False
        logging.warning("Given input is not valid. Must be one of [y,n]\n")


def delete_if_no_torrent(dirpath):
    # Runs through contents of a directory, and deletes directory if there's no .torrent files.
    # Returns true if directory was deleted, false otherwise
    # Use os.listdir() to get the list of files in the directory
    files = os.listdir(dirpath)
    # Check if there are any .torrent files in the list
    if not any(f.endswith('.torrent') for f in files):
        # If no .torrent files are found, delete the directory
        shutil.rmtree(dirpath)
        return True
    return False




















if __name__ == "__main__":
    main()
