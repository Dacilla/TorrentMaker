import logging
import os
import cv2
import requests

from base64 import b64encode


def generateScreenshots():
    global dataFile
    dataFile: dict
    logging.info("Making screenshots...")
    if not os.path.isdir(dataFile['runDir'] + "screenshots"):
        os.mkdir(dataFile['runDir'] + "screenshots")
    else:
        data = os.listdir(dataFile['runDir'] + "screenshots")
        for i in data:
            os.remove(dataFile['runDir'] + "screenshots" + os.sep + i)

    video = cv2.VideoCapture(dataFile['videoFile'])
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
            cv2.imwrite(dataFile['runDir'] + f"screenshots{os.sep}" + "screenshot_{}.png".format(timestamp), image)
            logging.info(f"Screenshot made at {dataFile['runDir']}screenshots{os.sep}" + "screenshot_{}.png".format(timestamp))
    video.release()


def uploadScreenshots():
    global dataFile
    dataFile: dict

    logging.info("Uploading screenshots to imgbb")
    api_endpoint = "https://api.imgbb.com/1/upload"
    images = os.listdir(f"{dataFile['runDir']}screenshots{os.sep}")
    logging.info("Screenshots loaded...")
    for image in images:
        ptpupload = False
        logging.info(f"Uploading {image}")
        # Open the file and read the data
        filePath = dataFile['runDir'] + "screenshots" + os.sep + image
        with open(filePath, "rb") as imagefile:
            file_data = imagefile.read()
        # Set the payload for the POST request
        payload = {
            "key": dataFile["imgbbApi"],
            "image": b64encode(file_data),
        }
        # with tqdm(total=file_size, unit="B", unit_scale=True, unit_divisor=1024) as t:
        #     wrapped_file = CallbackIOWrapper(t.update, payload)
        #     requests.put(api_endpoint, data=wrapped_file)
        try:
            response = requests.post(api_endpoint, payload)
            # Get the image URL from the response
            image_url = response.json()
        except Exception:
            logging.error("Failed to upload to imgbb. It's probably down.")
            if dataFile["ptpimgApi"]:
                logging.info("PTPImg API exists. Attempting to upload there...")
                image_url = uploadToPTPIMG(filePath, dataFile["ptpimgApi"])
                ptpupload = True
        logging.debug(image_url)
        try:
            if ptpupload:
                bbcode = f"[url={image_url}][img]{image_url}[/img][/url]"
            else:
                image_url = response.json()["data"]["url"]
                image_url_viewer = response.json()["data"]["url_viewer"]
                # Print the image URL
                # Template: [url=https://ibb.co/0fbvMqH][img]https://i.ibb.co/0fbvMqH/screenshot-785-895652173913.png[/img][/url]
                bbcode = f"[url={image_url_viewer}][img]{image_url}[/img][/url]"
            with open(dataFile['runDir'] + "showDesc.txt", "a") as fileAdd:
                fileAdd.write(bbcode + "\n")
            logging.info(f"bbcode for image URL {image_url} added to showDesc.txt")
        except Exception as e:
            logging.critical("Unexpected Exception: " + str(e))
            continue


def uploadToPTPIMG(imageFile: str, api_key):
    # Stole this code from https://github.com/DeadNews/images-upload-cli
    response = requests.post(
        url="https://ptpimg.me/upload.php",
        data={"api_key": api_key},
        files={"file-upload[0]": open(imageFile, 'rb').read()},
    )
    if not response.ok:
        raise Exception(response.json())

    logging.debug(response.json())

    return f"https://ptpimg.me/{response.json()[0]['code']}.{response.json()[0]['ext']}"
