from calendar import c
from hashlib import file_digest
import html
import os
import sys
from venv import create
from openai import file_from_path
from pyparsing import html_comment
import requests
import shutil
from bs4 import BeautifulSoup
import pysnooper
from . import utils
from loguru import logger


sys.path.append(utils.getConfig()["convertLinksDir"])
from convertLinks import main as convertLinks


def getSrcUrlOfArticle(articlePath):
    htmlText = open(articlePath, errors="ignore").read()
    if '" rel="nofollow">Link to original</a></p>' in htmlText:
        srcUrl = htmlText.split('" rel="nofollow">Link to original</a></p>')[0]
        srcUrl = srcUrl.split('><a href="')[-1]
        return srcUrl
    return None


def process_articles_in_directory(directory):
    filesToConvert = []
    for root, dirs, files in os.walk(directory):
        for file in files:
            if file.endswith(".html") or file.endswith(".mhtml"):
                file_path = os.path.join(root, file)
                url = utils.getUrlOfArticle(file_path)
                if "gist.github.com" in url:
                    srcUrl = getSrcUrlOfArticle(file_path)
                    if srcUrl:
                        filesToConvert.append([file_path, srcUrl, url])

    logger.info(f"files to convert: {len(filesToConvert)}")
    for i, article in enumerate(filesToConvert):
        file_path, url, gitBookUrl = article
        logger.info(f"Processing article {i+1} of {len(filesToConvert)}")
        # print(f"gitbook url: {gitBookUrl}")
        # print(f"converting url: {url}")
        newUrls = main(url, False, True)
        newUrl = newUrls[0] if newUrls else False

        if not newUrl:
            logger.warning(
                f"deleting file because of issue with url: {url} {file_path}"
            )
            # os.remove(file_path)
            continue

        logger.info(f"new url: {newUrl}")
        response = requests.get(newUrl)
        soup = BeautifulSoup(response.text, "html.parser")
        html_content = str(soup)
        html_content = f"<!-- Hyperionics-OriginHtml {newUrl}-->\n" + html_content
        # print(html_content[:100])
        # with open(file_path, "w") as file:
        #     file.write(html_content)


# def createFiles(mapOfFiles):
#     for url in mapOfFiles:
#         filePath = mapOfFiles[url]
#         try:
#             os.remove(filePath)
#             print(f"deleted file: {filePath}")
#         except OSError as e:
#             print(f"Error deleting {filePath}: {e}")
#         filePath = filePath.strip(" ")
#         response = requests.get(url)
#         soup = BeautifulSoup(response.text, "html.parser")
#         html_content = str(soup)
#         html_content = f"<!-- Hyperionics-OriginHtml {url}-->\n" + html_content
#         with open(filePath, "w") as file:
#             print(f"about to write: ", filePath, url)
#             file.write(html_content)
#         open(filePath, "r").read()


directory = utils.getConfig()["articleFileFolder"]
process_articles_in_directory(directory)
# createFiles()
