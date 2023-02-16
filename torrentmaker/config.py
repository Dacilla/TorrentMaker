import logging
import configparser
import os
import sys


def SetupConfig():
    global dataFile
    dataFile: dict
    if not os.path.exists('settings.ini'):
        logging.info("No settings.ini file found. Generating...")
        config = configparser.ConfigParser()

        config['DEFAULT'] = {
            'HUNO_API': '',
            'TMDB_API': '',
            'IMGBB_API': '',
            'QBIT_USERNAME': '',
            'QBIT_PASSWORD': '',
            'HUNO_URL': '',
            'PTPIMG_API': ''
        }

        with open('settings.ini', 'w') as configfile:
            config.write(configfile)

        sys.exit("settings.ini file generated. Please fill out before running again")

    # Load the INI file
    config = configparser.ConfigParser()
    config.read('settings.ini')
    dataFile["hunoApi"] = config['DEFAULT']['HUNO_API']
    dataFile["tmdbApi"] = config['DEFAULT']['TMDB_API']
    dataFile["imgbbApi"] = config['DEFAULT']['IMGBB_API']
    dataFile["qbitUser"] = config['DEFAULT']['QBIT_USERNAME']
    dataFile["qbitPass"] = config['DEFAULT']['QBIT_PASSWORD']
    dataFile["hunoURL"] = config['DEFAULT']['HUNO_URL']
    dataFile["ptpimgApi"] = config['DEFAULT']['PTPIMG_API']
    if dataFile["ptpimgApi"] == '':
        dataFile["ptpimgApi"] = None


def SetupRunFolder():
    global dataFile
    dataFile: dict
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
        # if not delete_if_no_torrent(os.getcwd() + os.sep + "runs" + os.sep + str(maxValue).zfill(3)):
        #     maxValue = maxValue + 1
        #     logging.info("Found directory does not have finished .torrent file. Directory Deleted.")
        maxValue = maxValue + 1
        maxValue = str(maxValue).zfill(3)
        os.mkdir("runs" + os.sep + maxValue)
        runDir = os.getcwd() + os.sep + "runs" + os.sep + maxValue + os.sep

    dataFile['runDir'] = runDir


def has_folders(path_to_parent):
    folders = list(folders_in(path_to_parent))
    return len(folders) != 0


def folders_in(path_to_parent):
    for fname in os.listdir(path_to_parent):
        if os.path.isdir(os.path.join(path_to_parent, fname)):
            yield os.path.join(path_to_parent, fname)
