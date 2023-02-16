import logging
import sys
import requests

from pprint import pformat


def getDesc():
    global dataFile
    dataFile: dict
    if dataFile["tmdbApi"] == "":
        logging.error("TMDB_API field not filled in settings.ini")
        sys.exit()

    # Replace TV_SHOW_ID with the ID of the TV show you want to get the description for
    tv_show_id = dataFile['tmdbId']

    # Build the URL for the API request
    if dataFile['isMovie']:
        url = f'https://api.themoviedb.org/3/movie/{tv_show_id}?api_key={dataFile["tmdbApi"]}'
    else:
        url = f'https://api.themoviedb.org/3/tv/{tv_show_id}?api_key={dataFile["tmdbApi"]}'

    # Make the GET request to the TMDb API
    response = requests.get(url)

    # Get the JSON data from the response
    tmdbData = response.json()
    logging.debug(pformat(tmdbData))
    dataFile['tmdbData'] = tmdbData
    # Print the description of the TV show
    logging.debug("description gotten: " + dataFile['tmdbData']['overview'])
    with open(dataFile['runDir'] + "showDesc.txt", "w") as fb:
        fb.write(dataFile['tmdbData']['overview'] + "\n\n")
    logging.info("TMDB Description dumped to showDesc.txt")
