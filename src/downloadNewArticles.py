import os
import webbrowser
import ssl
import time
import json
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.by import By
import requests
from urllib.parse import urlparse
import markdown
from loguru import logger
from . import utils
import sys
import pysnooper

requests.packages.urllib3.disable_warnings()

sys.path.append(utils.getConfig()["convertLinksDir"])
from convertLinks import main as convertLinks


def calcUrlsToAdd(onlyRead=False):
    bookmarksFilePath = utils.getConfig()["bookmarksFilePath"]
    with open(bookmarksFilePath) as f:
        bookmarks = json.load(f)

    urlsToAdd = {}

    if onlyRead:
        markedAsReadUrls = utils.getUrlsFromFile(
            utils.getAbsPath("../storage/markedAsReadArticles.txt")
        )

    allAddedUrls = utils.getUrlsFromFile(
        utils.getAbsPath("../storage/alreadyAddedArticles.txt")
    )
    bmBar = bookmarks["roots"]["bookmark_bar"]["children"]
    for folder in bmBar:
        if folder["type"] == "folder" and folder["name"] == "@Voice":
            for folder in folder["children"]:
                subject = folder["name"]
                if onlyRead and subject.lower() == "unread":
                    continue
                urlsToAdd[subject] = []
                for link in folder["children"]:
                    url = link["url"]
                    url = utils.formatUrl(url)
                    if onlyRead:
                        if (
                            url.lower() not in "\n".join(markedAsReadUrls).lower()
                            and url.lower() in "\n".join(allAddedUrls).lower()
                        ):
                            url = convertLinks(url, False, True)
                            if url and url[0]:
                                url = url[0]
                                if (
                                    url.lower()
                                    not in "\n".join(markedAsReadUrls).lower()
                                    and url.lower() in "\n".join(allAddedUrls).lower()
                                ):
                                    urlsToAdd[subject].append(url)
                                    logger.info(f"added url: {url}")
                    else:
                        if url.lower() not in "\n".join(allAddedUrls).lower():
                            url = convertLinks(url, False, True)
                            if url and url[0]:
                                url = url[0]
                                if url.lower() not in "\n".join(allAddedUrls).lower():
                                    urlsToAdd[subject].append(url)
                                    logger.info(f"added url: {url}")

    return urlsToAdd


def save_text_as_html(url):
    response = requests.get(url, verify=ssl.CERT_NONE, timeout=10)
    text_content = response.text

    # Convert text to HTML using markdown
    html_content = markdown.markdown(text_content)

    parsed_url = urlparse(url)
    title = os.path.basename(parsed_url.path)
    title = "".join(c for c in title if c.isalnum() or c.isspace()).rstrip()

    return html_content, title


def downloadNewArticles(urlsToAdd):
    saveDirectory = utils.getConfig()["pdfSourceFolders"][0]
    logger.info(f"URLs to add: {urlsToAdd}")
    for url in urlsToAdd:
        urlCopy = str(url)
        if url.endswith(".pdf"):
            continue
        logger.info(f"trying to download: {url}")
        try:
            save_mobile_article_as_mhtml(url, saveDirectory)
        except Exception as e:
            logger.error(f"Error downloading article: {url} {e}")


def save_webpage_as_mhtml(url, timeout=10, min_load_time=5):
    try:
        resp = requests.get(url, verify=False, timeout=timeout)
    except requests.exceptions.RequestException as e:
        raise Exception(f"Failed to fetch {url}: {e}")
    if resp.status_code != 200:
        raise Exception(f"Failed to download {url}, status code {resp.status_code}")

    chrome_options = Options()
    user_agent = "Mozilla/5.0 (iPhone; CPU iPhone OS 14_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/14.0 Mobile/15E148 Safari/604.1"
    chrome_options.add_argument(f"user-agent={user_agent}")
    chrome_options.add_argument("--ignore-certificate-errors")
    chrome_options.add_argument("--headless")
    driver = webdriver.Chrome(options=chrome_options)

    try:
        start_time = time.time()
        driver.get(url)
        wait = WebDriverWait(driver, timeout)
        wait.until(EC.presence_of_element_located((By.TAG_NAME, "body")))
        body_load_time = time.time() - start_time
        remaining_time = max(0, min_load_time - body_load_time)
        time.sleep(remaining_time)

        title = driver.title
        title = "".join(c for c in title if c.isalnum() or c.isspace()).rstrip()

        mhtml_data = driver.execute_cdp_cmd(
            "Page.captureSnapshot", {"format": "mhtml"}
        )["data"]

    finally:
        driver.quit()

    return mhtml_data, title


def save_mobile_article_as_mhtml(url, saveDirectory, timeout=10, min_load_time=5):
    originalUrl = url
    try:
        response = requests.get(url, verify=False, timeout=timeout)
    except requests.exceptions.SSLError:
        url = url.replace("https", "http")
        response = requests.get(url, verify=False, timeout=timeout)
    if response.status_code != 200:

        webbrowser.open(url)
        raise Exception(f"Failed to download {url}, status code {response.status_code}")

    content_type = response.headers.get("Content-Type")
    content_disposition = response.headers.get("Content-Disposition")
    downloadAsHtml = content_type == "text/plain" or (
        content_disposition and "attachment" in content_disposition
    )
    if downloadAsHtml:
        fileExt = ".html"
        logger.debug(f"saving url: {url} as text")
        htmlText, title = save_text_as_html(url)
    else:
        fileExt = ".mhtml"
        logger.debug(f"saving url: {url} as webpage")
        htmlText, title = save_webpage_as_mhtml(url, timeout, min_load_time)

    file_path = os.path.join(saveDirectory, f"{title}{fileExt}")
    if os.path.exists(file_path):
        currentTime = int(time.time())
        file_path = file_path.replace(fileExt, f"_{currentTime}{fileExt}")

    if downloadAsHtml:
        htmlText = f"<!-- Hyperionics-OriginHtml {originalUrl}-->\n{htmlText}"
        with open(file_path, "w") as file:
            file.write(htmlText)
    else:
        with open(file_path, "wb") as file:
            file.write(htmlText.encode("utf-8"))


if __name__ == "__main__":
    articles = """https://embeddedsw.net/doc/physical_coercion.txt
    https://github.com"""
    downloadNewArticles(articles.split("\n"))
