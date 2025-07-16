import re
import json
from . import utils
from .utils import getConfig, calculate_normal_hash, calculate_ipfs_hash
import os
from collections import defaultdict
from . import reTitlePDFs
from .generateLists import modifyListFiles, appendToLists
from .downloadNewArticles import downloadNewArticles
import sys
import cProfile
import pstats
import shutil
from typing import Iterable
from . import db
from .articleSummary import (
    summarize_articles,
    add_files_to_database,
    remove_nonexistent_files_from_database,
    remove_orphaned_tags_from_database,
)
from .articleTagging import main as tag_articles
from loguru import logger

# Configure loguru logger
logger.remove()
logger.add(sys.stdout, level="INFO")

sys.path.append(getConfig()["convertLinksDir"])
from convertLinks import main as convertLinks


def getBookmarks():
    bookmarksFilePath = getConfig()["bookmarksFilePath"]
    with open(bookmarksFilePath) as f:
        bookmarks = json.load(f)
        return bookmarks


def addFileHashesToAlreadyAdded():
    nonHtmlFormats = getConfig()["docFormatsToMove"]
    nonHtmlFormats = [fmt for fmt in nonHtmlFormats if fmt not in ["html", "mhtml"]]
    listFile = utils.getAbsPath("../storage/alreadyAddedArticles.txt")
    matchingArticles = utils.getArticlePathsForQuery("*", formats=nonHtmlFormats)
    alreadyAddedFileNames = str(utils.getUrlsFromFile(listFile)).lower()
    fileNames = [
        os.path.basename(filePath)
        for filePath in matchingArticles
        if os.path.basename(filePath) not in alreadyAddedFileNames
    ]
    fileHashes = [
        calculate_normal_hash(filePath)
        for filePath in matchingArticles
        if os.path.basename(filePath) not in alreadyAddedFileNames
    ]
    itemsToAdd = list(set(fileNames + fileHashes))
    utils.addUrlToUrlFile(itemsToAdd, listFile)


def addReadFilesHashesToMarkedAsRead():
    nonHtmlFormats = [
        fmt for fmt in getConfig()["docFormatsToMove"] if fmt not in ["html", "mhtml"]
    ]
    listFile = utils.getAbsPath("../storage/alreadyAddedArticles.txt")
    matchingArticles = utils.getArticlePathsForQuery(
        "*", formats=nonHtmlFormats, readState="read"
    )
    alreadyMarkedAsReadFileNames = utils.getUrlsFromFile(listFile)
    fileNames = [
        os.path.basename(filePath)
        for filePath in matchingArticles
        if os.path.basename(filePath) not in alreadyMarkedAsReadFileNames
    ]
    fileHashes = [
        calculate_normal_hash(filePath)
        for filePath in matchingArticles
        if os.path.basename(filePath) not in alreadyMarkedAsReadFileNames
    ]
    itemsToAdd = list(set(fileNames + fileHashes))
    utils.addUrlToUrlFile(itemsToAdd, listFile)

    fileHashes = [calculate_normal_hash(filePath) for filePath in matchingArticles]
    utils.addUrlToUrlFile(fileHashes, listFile)


def calcUrlsToAdd(onlyRead=False):
    bookmarks = getBookmarks()
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


def markReadBookmarksAsRead():
    readUrls = calcUrlsToAdd(onlyRead=True)["AlreadyRead"]
    utils.markArticlesWithUrlsAsRead(readUrls, getConfig()["articleFileFolder"])


def deleteFilesMarkedToDelete():
    markedAsDeletedFiles = utils.getArticlesFromList("_DELETE")
    articleFileFolder = getConfig()["articleFileFolder"]
    for fileName in markedAsDeletedFiles:
        utils.delete_file_with_name(fileName, articleFileFolder)
    utils.deleteAllArticlesInList("_DELETE")


def hideArticlesMarkedAsRead():
    markedAsReadFiles = utils.getArticlesFromList("_READ")
    articleFileFolder = getConfig()["articleFileFolder"]
    for fileName in markedAsReadFiles:
        newPath = utils.hide_file_with_name(fileName, articleFileFolder)
        if newPath:
            try:
                utils.addUrlToUrlFile(
                    utils.getUrlOfArticle(newPath),
                    utils.getAbsPath("../storage/markedAsReadArticles.txt"),
                )
            except FileNotFoundError:
                logger.error(f"Failed to mark {fileName} as read")
    utils.deleteAllArticlesInList("_READ")


def updatePerTagFiles(root_folder):
    """Generate file lists per tag for both URLs and file names/hashes.

    This function queries the database for all tags, then for each tag:
    1. Creates a file containing the URLs and titles of HTML/MHTML articles with that tag
    2. Creates a file containing names and hashes of all articles with that tag

    All files are stored in a single "tag_files" subdirectory.

    Args:
        root_folder: Path to the root folder where articles are stored
    """

    # Ensure database is set up
    db.setup_database()

    # Get the tag files directory from config
    tag_files_dir = getConfig()["backupFolderPath"]
    os.makedirs(tag_files_dir, exist_ok=True)

    # Load existing hash data from all JSON files to avoid recalculating hashes
    existing_hash_data = {}
    for file_name in os.listdir(tag_files_dir):
        if file_name.endswith("_files_and_hashes.json"):
            file_path = os.path.join(tag_files_dir, file_name)
            try:
                with open(file_path, "r") as f:
                    tag_hash_data = json.load(f)
                    # Add to our master dictionary of file paths and their hashes
                    existing_hash_data.update(tag_hash_data)
            except (json.JSONDecodeError, IOError):
                # If file is corrupted, skip it
                pass

    # Get all tags with article counts
    tags = db.get_all_tags_with_article_count()

    # Total number of tags processed
    total_tags = len(tags)
    tags_processed = 0
    skipped_tags = 0

    # Process each tag
    for tag_id, tag_name, article_count in tags:
        # Skip tags with 0 articles
        if article_count == 0:
            skipped_tags += 1
            continue

        tags_processed += 1
        logger.debug(
            f"Processing tag {tags_processed}/{total_tags}: {tag_name} ({article_count} articles)"
        )

        # Get all articles with this tag
        tagged_articles = db.get_articles_for_tag(tag_id)

        # Lists to store URLs and file data
        urls_with_titles = []
        file_data = {}

        # Process each article
        for article_id, file_name in tagged_articles:
            try:
                # Find the full path of the article
                article_path = os.path.join(root_folder, file_name)

                # Check if we already have hash for this file
                if article_path in existing_hash_data and os.path.exists(article_path):
                    # Use existing hash if file exists
                    file_hash = existing_hash_data[article_path]
                else:
                    # Calculate hash only for new or modified files
                    file_hash = calculate_ipfs_hash(article_path)

                file_data[article_path] = file_hash

                # Add URL and title if available (only for HTML/MHTML files)
                if article_path.lower().endswith((".html", ".mhtml")):
                    article_url = utils.getUrlOfArticle(article_path)
                    if article_url:
                        # Try to extract a title from the file if possible
                        title_display = os.path.splitext(
                            os.path.basename(article_path)
                        )[0]
                        urls_with_titles.append((article_url, title_display))
            except Exception as e:
                logger.info(f"Error processing {file_name}: {e}")

        # Sanitize tag name for file system
        safe_tag_name = re.sub(r"[^\w\-_\.]", "_", tag_name)

        # Write URL file if we found any URLs
        if urls_with_titles:
            tag_url_file_path = os.path.join(tag_files_dir, f"{safe_tag_name}_urls.txt")
            with open(tag_url_file_path, "w") as f:
                for url, title in urls_with_titles:
                    f.write(f"# {title}\n{url}\n\n")

            logger.debug(
                f"  - Created URL file with {len(urls_with_titles)} URLs: {os.path.basename(tag_url_file_path)}"
            )

        # Write file data if we found any files
        if file_data:
            tag_file_path = os.path.join(
                tag_files_dir, f"{safe_tag_name}_files_and_hashes.json"
            )

            with open(tag_file_path, "w") as f:
                json.dump(file_data, f, indent=2)

            logger.debug(
                f"  - Created file hash data with {len(file_data)} files: {os.path.basename(tag_file_path)}"
            )

    # Clean up the database by removing orphaned items
    orphaned_tags, orphaned_hashes = db.clean_orphaned_database_items()
    if orphaned_tags > 0:
        logger.info(f"Removed {orphaned_tags} tags with no associated articles")
    if orphaned_hashes > 0:
        logger.info(f"Removed {orphaned_hashes} orphaned tag hash entries")

    logger.info(
        f"Finished processing {tags_processed} tags ({skipped_tags} tags with 0 articles skipped)"
    )
    logger.info(f"All tag files have been generated in: {tag_files_dir}")


def updatePerTagUrlListFiles(root_folder):
    """This function is deprecated. Use updatePerTagFiles() instead."""
    logger.info(
        "WARNING: updatePerTagUrlListFiles is deprecated. Using updatePerTagFiles instead."
    )
    updatePerTagFiles(root_folder)


def updatePerTagFileNamesAndHashes(root_folder):
    """This function is deprecated. Use updatePerTagFiles() instead."""
    logger.info(
        "WARNING: updatePerTagFileNamesAndHashes is deprecated. Using updatePerTagFiles instead."
    )
    updatePerTagFiles(root_folder)


def deleteDuplicateArticleFiles(urls_to_filenames):
    # Dictionary to store seen URLs in each directory
    dir_seen_urls = {}

    for fileName in urls_to_filenames:
        url = urls_to_filenames[fileName]
        if not url:
            continue
        url = utils.formatUrl(url)

        # Get directory of the file
        directory = os.path.dirname(fileName)

        if directory not in dir_seen_urls:
            # If directory is not in the dictionary, add it with the current url
            dir_seen_urls[directory] = {url}
        elif url in dir_seen_urls[directory] and url:
            # If url has been seen in this directory, delete the file
            logger.info(f"deleting because duplicate: {fileName} {url}")
            homeDir = os.path.expanduser("~")
            dest = os.path.join(
                homeDir, ".local/share/Trash/files/", "DUP_" + fileName.split("/")[-1]
            )
            shutil.move(fileName, dest)
        else:
            # If url has not been seen in this directory, add it to the set
            dir_seen_urls[directory].add(url)


def moveDocsToTargetFolder():
    docPaths = []
    PDFFolders = getConfig()["pdfSourceFolders"]
    targetFolder = getConfig()["articleFileFolder"]

    for folderPath in PDFFolders:
        docPaths += utils.getArticlePathsForQuery("*", folderPath=folderPath)

    logger.info(f"Number of docPaths: {len(docPaths)}")

    alreadyAddedHashes = str(
        utils.getUrlsFromFile(utils.getAbsPath("../storage/alreadyAddedArticles.txt"))
    )
    markedAsReadHashes = str(
        utils.getUrlsFromFile(utils.getAbsPath("../storage/markedAsReadArticles.txt"))
    )

    for docPath in docPaths:
        docHash = calculate_normal_hash(docPath)
        if docHash in alreadyAddedHashes:
            logger.info(f"Skipping importing duplicate file: {docPath}")
            docFileName = docPath.split("/")[-1]
            homeDir = os.path.expanduser("~")
            erroDocPath = os.path.join(
                homeDir, ".local/share/Trash/files/", "DUPLICATE_" + docFileName
            )
            shutil.move(docPath, erroDocPath)
            continue

        docName = docPath.split("/")[-1]

        # Create a unique filename if needed
        baseName, extension = os.path.splitext(docName)
        uniqueName = docName
        counter = 1
        while os.path.exists(os.path.join(targetFolder, uniqueName)):
            uniqueName = f"{baseName}_{counter}{extension}"
            counter += 1

        targetPath = os.path.join(targetFolder, uniqueName)

        if docHash in markedAsReadHashes:
            targetPath = os.path.join(targetFolder, "." + uniqueName)
            logger.info(f"Marking as read: {docName}")

        logger.info(f"Moving {docName} to {targetPath} derived from {docPath}")
        shutil.move(docPath, targetPath)

        utils.addUrlToUrlFile(
            [docHash, os.path.basename(targetPath)],
            utils.getAbsPath("../storage/alreadyAddedArticles.txt"),
        )


def deleteDuplicateFiles(directory_path):
    duplicate_size_files = defaultdict(list)

    for root, _, filenames in os.walk(directory_path):
        if any(part.startswith(".") for part in root.split(os.sep)):
            continue  ###why is this here... mightn't it result in duplicate hidden articles remaining?

        for filename in filenames:
            full_path = os.path.join(root, filename)
            file_size = os.path.getsize(full_path)
            file_hash = calculate_normal_hash(full_path)
            unique_key = f"{file_size}_{file_hash}_{root}"

            duplicate_size_files[unique_key].append(full_path)

    for unique_key, file_paths in duplicate_size_files.items():
        if len(file_paths) > 1:
            filesMarkedAsRead = [
                path for path in file_paths if path.split("/")[-1][0] == "."
            ]
            if len(filesMarkedAsRead) < len(file_paths):
                for path in filesMarkedAsRead:
                    file_paths.remove(path)

            root_files = [
                path
                for path in file_paths
                if os.path.dirname(path).strip("/") == directory_path.strip("/")
            ]
            non_root_files = [
                path
                for path in file_paths
                if os.path.dirname(path).strip("/") != directory_path.strip("/")
            ]

            if root_files:
                files_to_remove = (
                    root_files[:-1] if len(non_root_files) == 0 else root_files
                )
            else:
                files_to_remove = non_root_files[:-1]
            logger.info(
                "files_to_remove",
                files_to_remove,
                "root files",
                root_files,
                "non_root_files",
                non_root_files,
            )
            for file_path in files_to_remove:
                logger.info(f"removed: {file_path}")
                homeDir = os.path.expanduser("~")
                dest = os.path.join(
                    homeDir, ".local/share/Trash/files/", file_path.split("/")[-1]
                )
                shutil.move(file_path, dest)


def main():
    logger.info("remove nonexistent files from database")
    db.remove_duplicate_file_entries()
    remove_nonexistent_files_from_database()
    logger.info("remove orphaned tags from database")
    remove_orphaned_tags_from_database()
    logger.info("calc new urls to add")
    urlsToAdd = calcUrlsToAdd()
    urlsToAdd = urlsToAdd["AlreadyRead"] + urlsToAdd["UnRead"]
    logger.info("download new articles")
    downloadNewArticles(urlsToAdd)
    logger.info("give files readable filenames")
    reTitlePDFs.retitleAllPDFs()
    logger.info("add files to database")
    add_files_to_database()
    logger.info("summarize articles")
    summarize_articles()
    logger.info("tag articles")
    tag_articles()
    logger.info("move docs to target folder")
    moveDocsToTargetFolder()
    logger.info("update urlList files")
    updatePerTagFiles(getConfig()["articleFileFolder"])
    logger.info("act on requests to delete/hide articles from atVoice app\n\n")
    logger.info("delete files marked to delete")
    deleteFilesMarkedToDelete()
    logger.info("hide articles marked as read")
    hideArticlesMarkedAsRead()
    logger.info("mark read bookmarks as read")
    markReadBookmarksAsRead()
    logger.info("add file hashes to already added files")
    addFileHashesToAlreadyAdded()
    logger.info("add read file hashes to marked as read files")
    addReadFilesHashesToMarkedAsRead()
    logger.info("delete duplicate files")
    articles = utils.searchArticlesForQuery(
        "*", [], readState="", formats=["html", "mhtml"]
    )
    articleUrls = [url for url in articles.values() if url]
    deleteDuplicateArticleFiles(articles)
    deleteDuplicateFiles(getConfig()["articleFileFolder"])
    logger.info("update alreadyAddedArticles.txt")
    utils.addUrlToUrlFile(
        articleUrls,
        utils.getAbsPath("../storage/alreadyAddedArticles.txt"),
    )
    logger.info("update @voice lists")
    appendToLists()
    # modifyListFiles()


if __name__ == "__main__":
    # profiler = cProfile.Profile()
    # profiler.enable()

    main()
    # moveDocsToTargetFolder()
    # remove_nonexistent_files_from_database()
    # summarize_articles()
    # deleteFilesMarkedToDelete()
    # hideArticlesMarkedAsRead()
    # tag_articles()
    # appendToLists()
    # modifyListFiles()

    # profiler.disable()
    # stats = pstats.Stats(profiler)
    # stats.sort_stats(pstats.SortKey.CUMULATIVE)
    # stats.print_stats("src")
