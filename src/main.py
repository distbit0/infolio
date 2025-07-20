import sys
import cProfile
import pstats
import datetime
from pathlib import Path
from loguru import logger
from . import (
    generateLists,
    downloadNewArticles,
    articleSummary,
    articleTagging,
    db,
    utils,
    manageDocs,
)

# Configure loguru logger
logger.remove()
logger.add(sys.stdout, level="INFO")

# Add file logging to logs/main.log with rotation
log_file = Path("logs/main.log")
logger.add(
    log_file,
    level="INFO",
    rotation="10 MB",
    retention="30 days",
    format="{time:YYYY-MM-DD HH:mm:ss} | {level} | {message}",
)


def main():
    ebooks_folder = utils.getConfig()["articleFileFolder"]

    logger.info(f"Starting main.py execution at {datetime.datetime.now()}")
    logger.info(f"Monitoring directory: {ebooks_folder}")

    # Capture initial directory state
    initial_snapshot = utils.get_directory_snapshot(ebooks_folder)

    logger.info("remove nonexistent files from database")
    db.remove_duplicate_file_entries()
    db.remove_nonexistent_files_from_database()
    logger.info("remove orphaned tags from database")
    db.remove_orphaned_tags_from_database()
    logger.info("calc new urls to add")
    urlsToAdd = downloadNewArticles.calcUrlsToAdd()
    allUrls = urlsToAdd["AlreadyRead"] + urlsToAdd["UnRead"]
    logger.info("download new articles")
    downloadNewArticles.downloadNewArticles(allUrls)
    logger.info("give files readable filenames")
    manageDocs.retitleAllPDFs()
    logger.info("add files to database")
    db.add_files_to_database()
    logger.info("summarize articles")
    articleSummary.summarize_articles()
    logger.info("tag articles")
    articleTagging.tagArticles()
    logger.info("move docs to target folder")
    manageDocs.moveDocsToTargetFolder()
    logger.info("update urlList files")
    articleTagging.updatePerTagFiles(utils.getConfig()["articleFileFolder"])
    logger.info("act on requests to delete/hide articles from atVoice app\n\n")
    logger.info("delete files marked to delete")
    manageDocs.deleteFilesMarkedToDelete()
    logger.info("hide articles marked as read")
    manageDocs.hideArticlesMarkedAsRead()
    logger.info("mark read bookmarks as read")
    manageDocs.markArticlesWithUrlsAsRead(
        downloadNewArticles.calcUrlsToAdd(onlyRead=True)["AlreadyRead"],
    )
    logger.info("add file hashes to already added files")
    manageDocs.addFileHashesToAlreadyAdded()
    logger.info("add read file hashes to marked as read files")
    manageDocs.addReadFilesHashesToMarkedAsRead()
    logger.info("delete duplicate files")
    manageDocs.deleteDuplicateArticleFiles()
    manageDocs.deleteDuplicateFiles()
    logger.info("update alreadyAddedArticles.txt")
    articleUrls = [url for url in utils.getArticleUrls().values()]
    utils.addUrlsToUrlFile(
        articleUrls,
        utils.getAbsPath("../storage/alreadyAddedArticles.txt"),
    )
    logger.info("update @voice lists")
    generateLists.appendToLists()
    # generateLists.modifyListFiles()

    # Capture final directory state and log differences
    final_snapshot = utils.get_directory_snapshot(ebooks_folder)
    utils.log_directory_diff(initial_snapshot, final_snapshot, "Ebooks Folder")

    logger.info(f"Completed main.py execution at {datetime.datetime.now()}")


if __name__ == "__main__":
    # profiler = cProfile.Profile()
    # profiler.enable()

    main()

    # profiler.disable()
    # stats = pstats.Stats(profiler)
    # stats.sort_stats(pstats.SortKey.CUMULATIVE)
    # stats.print_stats("src")
