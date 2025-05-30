import os
import ssl
import time
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.by import By
import requests
from selenium import webdriver
from urllib.parse import urlparse
from .utils import getConfig, addUrlToUrlFile, getAbsPath, formatUrl
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import markdown


requests.packages.urllib3.disable_warnings()


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
    saveDirectory = getConfig()["pdfSourceFolders"][0]
    print(urlsToAdd)
    for url in urlsToAdd:
        urlCopy = str(url)
        if url.endswith(".pdf"):
            continue
        print(f"trying to download: {url}")
        try:
            save_mobile_article_as_mhtml(url, saveDirectory)
        except Exception as e:
            print(f"Error downloading article: {url} {e}")
        else:
            addUrlToUrlFile(
                [formatUrl(urlCopy)], getAbsPath("../storage/alreadyAddedArticles.txt")
            )

    # Add downloaded URLs to alreadyAddedArticles.txt


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

    # try:
    start_time = time.time()
    driver.get(url)
    wait = WebDriverWait(driver, timeout)
    wait.until(EC.presence_of_element_located((By.TAG_NAME, "body")))
    body_load_time = time.time() - start_time
    remaining_time = max(0, min_load_time - body_load_time)
    time.sleep(remaining_time)

    title = driver.title
    title = "".join(c for c in title if c.isalnum() or c.isspace()).rstrip()

    driver.execute_cdp_cmd("Page.captureSnapshot", {"format": "mhtml"})
    mhtml_data = driver.execute_cdp_cmd(
        "Page.captureSnapshot", {"format": "mhtml"}
    )["data"]

    # finally:
    #     driver.quit()

    return mhtml_data, title


def save_mobile_article_as_mhtml(url, saveDirectory, timeout=10, min_load_time=5):
    originalUrl = url
    try:
        response = requests.get(url, verify=False, timeout=timeout)
    except requests.exceptions.SSLError:
        url = url.replace("https", "http")
        response = requests.get(url, verify=False, timeout=timeout)
    if response.status_code != 200:
        raise Exception(f"Failed to download {url}, status code {response.status_code}")

    content_type = response.headers.get("Content-Type")
    content_disposition = response.headers.get("Content-Disposition")
    downloadAsHtml = content_type == "text/plain" or (
        content_disposition and "attachment" in content_disposition
    )
    if downloadAsHtml:
        fileExt = ".html"
        print(f"saving url: {url} as text")
        htmlText, title = save_text_as_html(url)
    else:
        fileExt = ".mhtml"
        print(f"saving url: {url} as webpage")
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
