import os
import sys
import requests
import shutil
from bs4 import BeautifulSoup
from . import utils
import pysnooper
from loguru import logger


sys.path.append(utils.getConfig()["convertLinksDir"])
from convertLinks import main as convertLinks


urlSubstring = "ifirhfuhfruihriuhfriuehfouehoui"


def process_articles_in_directory(directory):
    for root, dirs, files in os.walk(directory):
        for file in files:
            if file.endswith(".html") or file.endswith(".mhtml"):
                file_path = os.path.join(root, file)
                url = utils.getUrlOfArticle(file_path)
                if url and urlSubstring.lower() in url.lower():
                    ## move file to linux trash directory
                    trashDir = "/home/pimania/.local/share/Trash/files/"
                    logger.info(f"moving to trash: {file_path}")
                    # shutil.move(file_path, trashDir)


directory = utils.getConfig()["articleFileFolder"]
process_articles_in_directory(directory)
