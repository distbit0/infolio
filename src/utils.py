import re
import hashlib
from io import BytesIO
from ipfs_cid import cid_sha256_hash_chunked
from typing import Iterable
import glob
import urlexpander
import json
import os
from pathlib import Path
from urllib.parse import urlparse
from loguru import logger
import requests

# import snscrape.modules.twitter as sntwitter
# import snscrape


def checkArticleSubject(articlePath, subjects):
    if not subjects:
        return True
    # articlePath = "/".join(articlePath.split("/")[:-1]) commented out because sometimes I want to filter by the filename e.g. to find yt videos
    for subject in subjects:
        if subject.lower() in articlePath.lower():
            return True
    return False


def handle_cache(file_name, key, value=None):
    # Load existing cache or initialize an empty cache if the file does not exist
    cache = {}
    if os.path.exists(file_name):
        with open(file_name, "r") as f:
            cache = json.load(f)

    if value is None:
        # Get the value from cache
        return cache.get(key)
    else:
        # Write value to cache
        cache[key] = value
        with open(file_name, "w") as f:
            json.dump(cache, f)


def formatUrl(url):
    if "http" not in url:
        return url
    if "t.co/" in url:
        url = urlexpander.expand(url)
    url = url.replace("medium.com", "scribe.rip").strip()
    url = url.replace("en.m.wikipedia.org", "en.wikipedia.org").strip()
    if "gist.github.com" in url:
        usernameIsInUrl = len(url.split("/")) > 4
        if usernameIsInUrl:
            url = "https://gist.github.com/" + url.split("/")[-1]

    url = re.sub(r"\?gi=.*", r"", url)
    url = re.sub(r"\&gi=.*", r"", url)
    if "discord.com" in url:
        url = url.replace("#update", "")
    # remove heading tags which cause false negative duplicate detection
    url = url.replace("###", "##")  # so that it isn't force refreshed in convertLinks
    safeHeadings = []
    hashtag = "#".join(url.split("#")[1:])
    isAlNum = hashtag.replace("-", "").isalnum()
    notSafe = hashtag not in safeHeadings
    if "#" in url and isAlNum and notSafe:
        url = url.split("#")[0]
    return url


def getUrlOfArticle(articleFilePath):
    extractedUrl = ""
    articleExtension = os.path.splitext(articleFilePath)[1][
        1:
    ].lower()  # Remove leading dot

    if articleExtension not in ["txt", "html", "mhtml"]:
        return ""

    with open(articleFilePath, errors="ignore") as _file:
        fileText = _file.read()
        urlPatterns = getConfig()["urlPatterns"]
        for urlPattern in urlPatterns:
            match = re.search(urlPattern, fileText)
            if match:
                extractedUrl = formatUrl(match.group(1).strip())
                break

    return extractedUrl


def getUrlsFromFile(urlFile):
    allUrls = []
    with open(urlFile, "r") as allUrlsFile:
        fileText = allUrlsFile.read().strip()
        for url in fileText.strip().split("\n"):
            url = formatUrl(url)
            allUrls.append(url)
    return allUrls


def removeDupesPreserveOrder(seq):
    seen = set()
    seen_add = seen.add
    return [x for x in seq if not (x in seen or seen_add(x))]


def addUrlsToUrlFile(urlOrUrls, urlFile, overwrite=False):
    mode = "w" if overwrite else "a"
    with open(urlFile, mode) as allUrlsFile:
        if type(urlOrUrls) == type([]):
            for url in urlOrUrls:
                url = formatUrl(url)
                allUrlsFile.write(url + "\n")
        else:
            urlOrUrls = formatUrl(urlOrUrls)
            allUrlsFile.write(urlOrUrls + "\n")

    urls = getUrlsFromFile(urlFile)
    uniqueUrls = removeDupesPreserveOrder(urls)
    with open(urlFile, "w") as allUrlsFile:
        for url in uniqueUrls:
            allUrlsFile.write(url + "\n")


def getTwitterAccountFromTweet(tweet_id):
    return None


#     # Create a TwitterTweetScraper object for the given tweet_id
#     username = handle_cache(getAbsPath("./../storage/twitter_handles.json"), tweet_id)
#     if username != None:
#         return username
#
#     scraper = sntwitter.TwitterTweetScraper(tweet_id)
#
#     # Use the get_items method to get the tweet
#     try:
#         for i, tweet in enumerate(scraper.get_items()):
#             if i == 1:
#                 break
#     except snscrape.base.ScraperException:
#         handle_cache(
#             getAbsPath("./../storage/twitter_handles.json"), tweet_id, ""
#         )
#         return ""
#
#     # Access the 'user' attribute of the tweet, which is a User object,
#     # and then access the 'username' attribute of the User object
#     handle_cache(
#         getAbsPath("./../storage/twitter_handles.json"), tweet_id, tweet.user.username
#     )
#     return tweet.user.username


def getBlogFromUrl(url):
    url = url.replace("nitter.net", "twitter.com")
    if "https://scribe.rip" in url and url.count("/") < 4:
        pass
    if "gist.github.com" in url:
        matches = re.search(r"(https:\/\/gist.github.com\/.*)\/", url)
    elif "https://scribe.rip" in url:
        matches = re.search(r"(https:\/\/scribe.rip\/[^\/]*)\/", url)
    elif "https://medium.com" in url:
        matches = re.search(r"(https:\/\/medium.com\/[^\/]*)\/", url)
    elif ".scribe.rip" in url:
        matches = re.search(r"(https:\/\/.*\.scribe.rip\/)", url)
    elif ".medium.com" in url:
        matches = re.search(r"(https:\/\/.*\.medium.com\/)", url)
    elif "https://mirror.xyz" in url:
        matches = re.search(r"(https:\/\/mirror.xyz\/.*?)\/", url)
    elif "https://write.as" in url:
        matches = re.search(r"(https:\/\/write.as\/.*?)\/", url)
    elif "twitter.com" in url and "/status/" in url:
        url = url.strip("/")
        matches = re.search(r"(https:\/\/twitter.com\/.*?)\/status\/.*", url)
    elif "twitter.com" in url and "/status/" not in url:
        url = url.strip("/")
        matches = re.search(r"(https:\/\/twitter.com\/.*)", url)
    elif "https://threadreaderapp" in url:
        matches = re.search(r"(.*)", "")
        url = url.strip("/").replace(".html", "")
        tweetId = re.search(r"https:\/\/threadreaderapp.com\/thread\/(.*)", url)
        if tweetId.group(1):
            twitterAccount = getTwitterAccountFromTweet(tweetId.group(1))
            if twitterAccount:
                twitterAccountUrl = "https://twitter.com/" + twitterAccount
                matches = re.search(r"(.*)", twitterAccountUrl)
    else:
        matches = re.search(r"^(http[s]*:\/\/[^\/]+)", url)

    if matches:
        blog = matches.group(1).strip()
    else:
        blog = url
    blog = blog.rstrip("/")

    return blog


def getBlogsFromUrls(urls):
    blogUrls = []
    for url in urls:
        if isValidBlog(url):
            blogUrl = getBlogFromUrl(url)
            if blogUrl:
                blogUrls.append(blogUrl)

    return blogUrls


def getInvalidBlogSubstrings():
    invalidBlogSubstrings = getConfig()["invalidBlogSubstrings"]
    return invalidBlogSubstrings


def isValidBlog(url):
    validBlog = True
    invalidBlogSubstrings = getInvalidBlogSubstrings()
    for substring in invalidBlogSubstrings:
        if substring.lower() in url.lower():
            validBlog = False

    if not url.startswith("http"):
        validBlog = False

    return validBlog


def getAbsPath(relPath):
    basepath = os.path.dirname(__file__)
    fullPath = os.path.abspath(os.path.join(basepath, relPath))

    return fullPath


def getConfig():
    configFileName = getAbsPath("../config.json")
    with open(configFileName) as config:
        config = json.loads(config.read())

    return config


def doesPathContainDotFolders(input_path):
    path_obj = Path(input_path)
    # Check all parent directories (excluding the file itself)
    for part in path_obj.parent.parts:
        if part and part.startswith("."):
            return True
    return False


def getArticlePaths(
    formats=[],
    folderPath="",
    fileName=None,
    recursive=False,
    readState=None,
    subjects=[],
):
    """
    Get article paths matching the formats, and optional fileName.

    Args:
        formats: List of file formats to include
        folderPath: Path to search in (default: from config)
        fileName: Optional specific filename to search for

    Returns:
        List of article paths matching the criteria
    """
    globWildcard = "**" if recursive else "*"
    folderPath = folderPath if folderPath else getConfig()["articleFileFolder"]
    folderPath = (folderPath + "/").replace("//", "/")
    formats = getConfig()["docFormatsToMove"] if not formats else formats
    fileNamesToSkip = getConfig()["fileNamesToSkip"]

    # Treat fileName as a format if provided, otherwise use provided formats
    search_targets = [glob.escape(fileName)] if fileName else formats
    # Create glob patterns for both root and recursive searches

    # Create the glob patterns
    glob_patterns = [
        *(
            (
                os.path.join(folderPath, globWildcard, f"{target}")
                if recursive
                else os.path.join(folderPath, f"{globWildcard}{target}")
            )
            for target in search_targets
        ),  # Recursively
    ]
    final_patterns = []
    for pattern in glob_patterns:
        lastSegment = os.path.split(pattern)[-1]
        if readState == "read":
            lastSegment = f".{lastSegment}"
        firstSegments = os.path.split(pattern)[:-1]
        pattern = os.path.join(*firstSegments, lastSegment)
        final_patterns.append(pattern)

    glob_patterns = final_patterns
    include_hidden = False if readState == "unread" else True
    allArticlesPaths = []
    for pattern in glob_patterns:
        try:
            matching_paths = glob.glob(
                pattern, recursive=recursive, include_hidden=include_hidden
            )
            matching_paths = [
                path for path in matching_paths if not doesPathContainDotFolders(path)
            ]
            allArticlesPaths.extend(matching_paths)
        except Exception as e:
            logger.error(f"Error in glob pattern {pattern}: {e}")

    allArticlesPaths = [
        path
        for path in allArticlesPaths
        if not any(skip in path for skip in fileNamesToSkip)
    ]
    if subjects:
        allArticlesPaths = [
            path for path in allArticlesPaths if checkArticleSubject(path, subjects)
        ]
    allArticlesPaths = list(set(allArticlesPaths))
    return allArticlesPaths


def getArticleUrls(subjects=[], readState=""):
    matchingArticles = {}
    allArticlesPaths = getArticlePaths(
        ["html", "mhtml"], "", readState=readState, subjects=subjects
    )
    for articlePath in allArticlesPaths:
        articleUrl = getUrlOfArticle(articlePath)
        if articleUrl:
            matchingArticles[articlePath] = articleUrl

    return matchingArticles


def getSrcUrlOfGitbook(articlePath):
    htmlText = open(articlePath, errors="ignore").read()
    if '" rel="nofollow">Original</a></p>' in htmlText:
        srcUrl = htmlText.split('" rel="nofollow">Link to original</a></p>')[0]
        srcUrl = srcUrl.split('><a href="')[-1]
        return srcUrl
    return None


def calculate_ipfs_hash(file_path):
    """Calculate IPFS hash for a file."""

    def as_chunks(stream: BytesIO, chunk_size: int) -> Iterable[bytes]:
        while len((chunk := stream.read(chunk_size))) > 0:
            yield chunk

    with open(file_path, "rb") as f:
        # Use a larger chunk size for better performance (64KB instead of 4 bytes)
        result = cid_sha256_hash_chunked(as_chunks(f, 65536))
        return result


def calculate_normal_hash(file_path):
    hasher = hashlib.sha256()
    file_size = os.path.getsize(file_path)

    if file_size < 4096:
        with open(file_path, "rb") as f:
            hasher.update(f.read())
    else:
        offset = (file_size - 4096) // 2
        with open(file_path, "rb") as f:
            f.seek(offset)
            hasher.update(f.read(4096))

    return hasher.hexdigest()


def get_directory_snapshot(directory_path):
    """Get a snapshot of all files in a directory with their modification times."""
    snapshot = {}
    try:
        # Since all files are in root directory, use os.listdir instead of os.walk
        for filename in os.listdir(directory_path):
            file_path = os.path.join(directory_path, filename)

            # Skip if not a file
            if not os.path.isfile(file_path):
                continue

            try:
                stat = os.stat(file_path)
                snapshot[file_path] = {
                    "size": stat.st_size,
                    "mtime": stat.st_mtime,
                }
            except (OSError, FileNotFoundError):
                # File might have been deleted between listdir and stat
                continue
    except FileNotFoundError:
        logger.warning(f"Directory not found: {directory_path}")
    return snapshot


def log_directory_diff(before_snapshot, after_snapshot, directory_name):
    """Log the differences between two directory snapshots."""
    added_files = set(after_snapshot.keys()) - set(before_snapshot.keys())
    removed_files = set(before_snapshot.keys()) - set(after_snapshot.keys())
    modified_files = []

    for file_path in set(before_snapshot.keys()) & set(after_snapshot.keys()):
        if (
            before_snapshot[file_path]["size"] != after_snapshot[file_path]["size"]
            or before_snapshot[file_path]["mtime"] != after_snapshot[file_path]["mtime"]
        ):
            modified_files.append(file_path)

    if added_files or removed_files or modified_files:
        logger.info(f"=== {directory_name} Directory Changes ===")

        if added_files:
            logger.info(f"Added files ({len(added_files)}):")
            for file_path in sorted(added_files):
                logger.info(f"  + {file_path}")

        if removed_files:
            logger.info(f"Removed files ({len(removed_files)}):")
            for file_path in sorted(removed_files):
                logger.info(f"  - {file_path}")

        if modified_files:
            logger.info(f"Modified files ({len(modified_files)}):")
            for file_path in sorted(modified_files):
                logger.info(f"  ~ {file_path}")

        logger.info(f"=== End {directory_name} Changes ===")
    else:
        logger.info(f"No changes detected in {directory_name}")


def removeIllegalChars(pdfTitle):
    illegalChars = getConfig()["illegalFileNameChars"]
    for char in illegalChars:
        pdfTitle = pdfTitle.replace(char, "")

    return pdfTitle


def getArxivTitle(arxiv_id):
    # Make a request to the arXiv API to get the metadata for the paper
    logger.info(f"Getting arXiv title for: {arxiv_id}")
    res = requests.get(f"http://export.arxiv.org/api/query?id_list={arxiv_id}")

    # Check if the request was successful
    if res.status_code != 200:
        return "Error: Could not retrieve paper information"

    # Extract the title from the response
    data = res.text.replace("\n", "").replace("\t", "")
    # print(data)
    start = data.index("</published>    <title>") + len("</published>    <title>")
    end = data.index("</title>    <summary>")
    # print(start, end)
    title = data[start:end]
    return title


def getDOITitle(doi):
    # Make a request to the CrossRef API to get the metadata for the paper
    headers = {"Accept": "application/json"}
    res = requests.get(f"https://api.crossref.org/v1/works/{doi}", headers=headers)

    # Check if the request was successful
    if res.status_code != 200:
        return "Error: Could not retrieve paper information"

    # Extract the title from the response
    data = res.json()
    title = data["message"]["title"][0]
    return title


def get_id_type(paper_id):
    # Check if the given string is a valid arXiv ID
    if re.match(r"^\d+\.\d+$", paper_id):
        return "arxiv"

    # Check if the given string is a valid DOI
    if paper_id.startswith("10."):
        return "doi"

    # If the string is neither an arXiv ID nor a DOI, return False
    return False
