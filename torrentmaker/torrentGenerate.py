import logging
import torf
import re
import sys
import os

from datetime import datetime
from babel import Locale

from HUNOInfo import bannedEncoders, encoderGroups
from torrentmaker.torrentmaker import SEEDING_DIR


def generateTorrent():
    global dataFile
    dataFile: dict
    logging.info("Creating torrent file")
    torrent = torf.Torrent()
    torrent.private = True
    torrent.source = "HUNO"
    torrent.path = dataFile['path']
    torrent.trackers = dataFile["hunoURL"]
    torrentFileName = "generatedTorrent.torrent"

    if dataFile["tmdbApi"]:
        # Create torrent file name from TMDB and Mediainfo
        # Template:
        # TV: ShowName (Year) S00 (1080p BluRay x265 SDR DD 5.1 Language - Group) [REPACK]
        # MOVIE: ShowName (Year) EDITION (1080p BluRay x265 SDR DD 5.1 Language - Group) [REPACK]
        # pprint(mediaInfoText)
        if dataFile['isMovie']:
            showName: str = dataFile['tmdbData']['original_title']
        else:
            showName: str = dataFile['tmdbData']['name']
        showName = showName.replace(":", " -")
        logging.info("Name: " + str(showName))
        if dataFile['isMovie']:
            dateString = dataFile['tmdbData']['release_date']
        else:
            dateString = dataFile['tmdbData']['first_air_date']
        date = datetime.strptime(dateString, "%Y-%m-%d")
        year = str(date.year)
        logging.info("Year: " + year)
        if not dataFile['isMovie']:
            # if isFolder == 2:
            #     episodeNum = check_folder_for_episode(file)
            # else:
            #     filename = os.path.basename(file)
            #     episodeNum = re.compile(r'S\d{2}E\d{2}').search(filename)
            #     if match:
            #         season = episodeNum.g
            season = get_season(dataFile['videoFile'])
            logging.info("Season: " + season)
        if dataFile['isEpisode']:
            episode = "E" + get_episode(dataFile['videoFile'])
            logging.info("Episode: " + episode)
        # Detect resolution
        acceptedResolutions = "2160p|1080p|720p"
        match = re.search(acceptedResolutions, dataFile['videoFile'])
        if match:
            resolution = match.group()
        else:
            width = dataFile['mediaInfoText']['media']['track'][1]['Width']
            height = dataFile['mediaInfoText']['media']['track'][1]['Height']
            resolution = getResolution(width=width, height=height)
        if "Interlaced" in str(dataFile['mediaInfoText']):
            resolution = resolution.replace("p", "i")
        logging.info("Resolution: " + resolution)
        # Detect if file is HDR
        colourSpace = get_colour_space(dataFile['mediaInfoText'])
        logging.info("Colour Space: " + colourSpace)
        # Detect video codec
        if 'HEVC' in dataFile['mediaInfoText']['media']['track'][1]['Format']:
            if 'remux' in dataFile['videoFile'].lower():
                videoCodec = 'HEVC'
            if 'h265' in dataFile['videoFile'].lower():
                videoCodec = 'H265'
            else:
                videoCodec = "x265"
        elif "VC-1" in dataFile['mediaInfoText']['media']['track'][1]['Format']:
            videoCodec = "VC-1"
        elif 'remux' in dataFile['videoFile'].lower():
            videoCodec = "AVC"
        else:
            videoCodec = "H264"
        logging.info("Video Codec: " + videoCodec)
        # Detect audio codec
        audio = get_audio_info(dataFile['mediaInfoText'])
        logging.info("Audio: " + audio)
        # Get language
        if 'Language' in dataFile['mediaInfoText']['media']['track'][2]:
            language = get_language_name(dataFile['mediaInfoText']['media']['track'][2]['Language'])
        else:
            language = input("No language found in audio data. Please input language:\n")
        logging.info("Language: " + language)
        # Get source
        if dataFile['source']:
            source = dataFile['source']
        else:
            source = ""
        logging.info("Source: " + source)
        # Get group
        if dataFile['group']:
            group = dataFile['group']

            # Check for banned group
            if 'WEB' in videoCodec:
                if group in bannedEncoders['WEB']:
                    logging.info(f"Group '{group}' in banned on HUNO. Cannot upload there")
                    if dataFile['huno']:
                        sys.exit()
            if 'REMUX' in videoCodec:
                if group in bannedEncoders['REMUX']:
                    logging.info(f"Group '{group}' in banned on HUNO. Cannot upload there")
                    if dataFile['huno']:
                        sys.exit()
            if group in bannedEncoders['ENCODE']:
                logging.info(f"Group '{group}' in banned on HUNO. Cannot upload there")
                if dataFile['huno']:
                    sys.exit()

            # Get group tag
            for encodeGroup, members in encoderGroups.items():
                if group in members:
                    group = group + ' ' + encodeGroup
                    logging.info("Group found: " + encodeGroup)
                    break
        else:
            group = "NOGRP"
        logging.info("Group: " + group)
        # Get Edition
        if dataFile['edition']:
            edition = " " + dataFile['edition']
        else:
            edition = ""
        # Get if repack
        if "REPACK" in dataFile['videoFile']:
            repack = " [REPACK]"
        else:
            repack = ""
        # Construct torrent name
        if dataFile['isMovie']:
            torrentFileName = f"{showName} ({year}){edition} ({resolution} {source} {videoCodec} {colourSpace} {audio} {language} - {group}){repack}.torrent"
        elif dataFile['isEpisode']:
            torrentFileName = f"{showName} ({year}) {season}{episode}{edition} ({resolution} {source} {videoCodec} {colourSpace} {audio} {language} - {group}){repack}.torrent"
        else:
            torrentFileName = f"{showName} ({year}) {season}{edition} ({resolution} {source} {videoCodec} {colourSpace} {audio} {language} - {group}){repack}.torrent"
        logging.info("Final name: " + torrentFileName)

        if dataFile['huno'] and dataFile['inject']:
            head, tail = os.path.split(dataFile['path'])
            headBasename = os.path.basename(head)
            postName = torrentFileName.replace(".torrent", "")
            if head != SEEDING_DIR:
                logging.info("Attempting to create hardlinks for easy seeding...")
                destination = os.path.join(SEEDING_DIR, postName)
                copy_folder_structure(dataFile['path'], destination)
                logging.info("Hardlinks created at " + destination)
                torrent.path = destination

    logging.info("Generating torrent file hash. This will take a long while...")
    success = torrent.generate(callback=cb, interval=0.25)
    logging.info("Writing torrent file to disk...")
    torrent.write(dataFile['runDir'] + torrentFileName)
    logging.info("Torrent file wrote to " + torrentFileName)


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
            os.link(src_item_path, dst_item_path)
        # If the item is a folder, recursively copy its contents
        elif os.path.isdir(src_item_path):
            copy_folder_structure(src_item_path, dst_item_path)


def get_language_name(language_code):
    try:
        # Create a Locale instance with the given language code
        locale = Locale(language_code)
        # Return the language name in english
        return locale.get_display_name('en')
    except Exception:
        # If the language code is invalid or the name cannot be determined, return an empty string
        return ''


def get_audio_info(mediaInfo):
    # Codec
    codecsDict = {
        "E-AC-3": "EAC3",
        "MLP FBA": "TrueHD",
        "DTS": "DTS",
        "AAC": "AAC",
        "PCM": "PCM",
        "AC-3": "DD",
        "FLAC": "FLAC",
        "Opus": "OPUS"
    }
    audioFormat = None
    if 'Format_Commercial_IfAny' in str(mediaInfo['media']['track'][2]):
        if mediaInfo['media']['track'][2]['Format_Commercial_IfAny']:
            commercialFormat = mediaInfo['media']['track'][2]['Format_Commercial_IfAny']
            if "Dolby Digital" in commercialFormat:
                if "Plus" in commercialFormat:
                    audioFormat = "DDP"
                else:
                    audioFormat = "DD"
            elif "TrueHD" in commercialFormat:
                audioFormat = "TrueHD"
            elif "DTS" in commercialFormat:
                if "HD High Resolution" in commercialFormat:
                    audioFormat = "DTS-HD HR"
                elif "Master Audio" in commercialFormat:
                    audioFormat = "DTS-HD MA"

    if audioFormat is None:
        if mediaInfo['media']['track'][2]['Format'] in codecsDict:
            audioFormat = codecsDict[mediaInfo['media']['track'][2]['Format']]

    if audioFormat is None:
        logging.error("Audio format was not found")
    # Channels
    channelsNum = mediaInfo['media']['track'][2]['Channels']
    channelsLayout = mediaInfo['media']['track'][2]['ChannelLayout']
    if "LFE" in channelsLayout:
        channelsNum = str(int(channelsNum) - 1)
        channelsNum2 = ".1"
    else:
        channelsNum2 = ".0"
    channelsNum = channelsNum + channelsNum2
    audioInfo = audioFormat + " " + channelsNum
    return audioInfo


def get_colour_space(mediaInfo):
    if "HDR" not in mediaInfo:
        return "SDR"
    if "Dolby Vision" in mediaInfo['media']['track'][1]['HDR_Format']:
        if "HDR10" in mediaInfo['media']['track'][1]['HDR_Format_Compatibility']:
            return "DV HDR"
        else:
            return "DV"
    return "HDR"


def getResolution(width, height):
    width_to_height_dict = {"720": "576", "960": "540", "1280": "720", "1920": "1080", "4096": "2160", "3840": "2160", "692": "480", "1024": "576"}
    acceptedHeights = ['576', '480', '360', '240', '720', '1080', '1440', '2160']
    if width in width_to_height_dict:
        height = width_to_height_dict[width]
        return f"{str(height)}p"

    if height is not None and height in acceptedHeights:
        return f"{str(height)}p"

    return input("Resolution could not be found. Please input the resolution manually (e.g. 1080p, 2160p, 720p)\n")


def get_episode(filename: str):
    import re
    match = re.search(r'S\d{2}E\d{2}', filename.upper())
    if match:
        return match.group().split('E')[1]
    return input("Episode number can't be found. Please enter episode number in format 'E00'\n")


def get_season(filename: str):
    # Use a regex to match the season string
    match = re.search(r'S\d\d', filename.upper())
    if match:
        # If a match is found, return the season string
        return match.group(0)
    else:
        # If no match is found, return an empty string
        return input('Season number was not found. Please input in the format S00')
    
def cb(torrent, filepath, pieces_done, pieces_total):
    print(f'{pieces_done/pieces_total*100:3.0f} % done', end="\r")