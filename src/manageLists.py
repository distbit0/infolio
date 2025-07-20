import os
import glob
from . import utils
from loguru import logger


def getArticlesFromList(listName):
    """
    Returns a list of article filenames from the .rlst file named `listName`.
    If listName starts with '_', then any Syncthing conflict files are merged in
    (only their article lines) and subsequently removed.
    """

    config_path = utils.getConfig()["atVoiceFolderPath"]
    listPath = os.path.join(config_path, ".config", listName + ".rlst")
    rootPath = os.path.join(utils.getConfig()["droidEbooksFolderPath"])

    if not os.path.exists(listPath):
        return []

    def parse_article_lines(text):
        """
        Given the full text of a .rlst file, return (header_text, article_list).

        - header_text is the lines up to the last occurrence of a "\n:" marker
          (i.e., the "header" region). If no header is detected, returns None.
        - article_list is the list of extracted article filenames.
        """
        text = text.strip()
        if not text:
            return None, []

        lines = text.split("\n")

        # Detect a header if there's a second line that starts with ":"
        if len(lines) > 1 and lines[1].startswith(":"):
            # Everything up to the last "\n:" is considered the header
            parts = text.split("\n:")
            # All parts except the last are the header
            header_text = "\n:".join(parts[:-1]).rstrip("\n")
            # The last part is what comes after the final header marker
            tail = parts[-1].split("\n")
            # tail[0] is the ":" line, so skip it
            article_lines = tail[1:]
        else:
            # No header found
            header_text = None
            article_lines = lines

        # Extract article filenames from article_lines
        articles = []
        for line in article_lines:
            line = line.strip()
            if not line:
                continue
            # The first token (split by tab) holds the path
            parts = line.split("\t")
            if parts:
                if parts[0]:
                    filePathRelativeToRoot = os.path.relpath(parts[0], rootPath)
                    if filePathRelativeToRoot not in articles:
                        articles.append(filePathRelativeToRoot)

        return header_text, articles

    # -------------------------------------------------------
    # 1. Read and parse main file
    # -------------------------------------------------------
    with open(listPath, "r", encoding="utf-8") as f:
        mainText = f.read()

    mainHeader, mainArticles = parse_article_lines(mainText)

    # -------------------------------------------------------
    # 2. Check for conflict files only if listName starts with '_'
    # -------------------------------------------------------
    conflict_files = []
    if listName.startswith("_"):
        logger.info("looking for sync conflict files")
        baseName = os.path.basename(listPath)
        extension = os.path.splitext(baseName)[1]
        fileName = os.path.splitext(baseName)[0]
        dirName = os.path.dirname(listPath)
        pattern = fileName + ".sync-conflict-*" + extension
        conflict_path = os.path.join(dirName, pattern)
        logger.info(f"Checking for conflict files in: {conflict_path}")
        conflict_files = glob.glob(conflict_path)

    # -------------------------------------------------------
    # 3. Merge conflict articles (excluding their headers)
    # -------------------------------------------------------
    if conflict_files:
        logger.info(f"Found {len(conflict_files)} conflict files for {listName}")
        for cfile in conflict_files:
            try:
                with open(cfile, "r", encoding="utf-8") as cf:
                    ctext = cf.read()
                # We only take the articles, ignoring conflict headers
                _, conflictArticles = parse_article_lines(ctext)
                for article in conflictArticles:
                    if article not in mainArticles:
                        mainArticles.append(article)
            except Exception as e:
                logger.error(f"Error reading conflict file {cfile}: {e}")

        # -------------------------------------------------------
        # 4. Rewrite the main file with the merged articles
        # -------------------------------------------------------
        if mainHeader is not None:
            newText = f"{mainHeader}\n:\n" + "\n".join(mainArticles)
        else:
            articlesWithRoot = [
                os.path.join(rootPath, article) for article in mainArticles
            ]
            newText = "\n".join(articlesWithRoot)

        try:
            with open(listPath, "w", encoding="utf-8") as f:
                f.write(newText)

            # Delete the conflicts
            for cfile in conflict_files:
                try:
                    os.remove(cfile)
                except Exception as e:
                    logger.error(f"Error deleting conflict file {cfile}: {e}")
        except Exception as e:
            logger.error(f"Error saving merged content to {listPath}: {e}")

    # -------------------------------------------------------
    # 5. Return final article list
    # -------------------------------------------------------
    return mainArticles


def createListIfNotExists(listPath):
    exists = os.path.exists(listPath)
    if not exists:
        open(listPath, "a").close()
    return True


def deleteListIfExists(listName):
    listPath = os.path.join(
        utils.getConfig()["atVoiceFolderPath"], ".config", listName + ".rlst"
    )
    if os.path.exists(listPath):
        logger.info(f"deleting disabled list: {listName}")
        os.remove(listPath)


def addArticlesToList(listName, articlePathsForList):
    listPath = os.path.join(
        utils.getConfig()["atVoiceFolderPath"], ".config", listName + ".rlst"
    )
    createListIfNotExists(listPath)
    articleNamesInList = [
        os.path.basename(line) for line in getArticlesFromList(listName)
    ]
    droidEbooksFolderPath = utils.getConfig()["droidEbooksFolderPath"]
    articleFileFolder = utils.getConfig()["articleFileFolder"]
    linesToAppend = []
    for articlePath in articlePathsForList:
        articleName = os.path.basename(articlePath)
        relativeArticlePath = os.path.relpath(articlePath, articleFileFolder)
        droidArticlePath = os.path.join(droidEbooksFolderPath, relativeArticlePath)
        if articleName not in articleNamesInList:
            extension = os.path.splitext(articleName)[1].lstrip(
                "."
            )  # Remove leading dot using lstrip
            extIndicator = {
                "pdf": "!",
                "epub": "#",
                "mhtml": "*",
                "html": "*",
            }.get(extension, "")
            displayName = os.path.splitext(articleName)[0]
            linesToAppend.append(
                droidArticlePath + "\t" + extIndicator + " " + displayName
            )
    newListText = "\n".join(linesToAppend) + "\n" if linesToAppend else ""

    # Read the current list content safely
    currentListText = ""
    if os.path.exists(listPath):
        with open(listPath, "r") as f:
            currentListText = f.read().strip()

    headers, existingArticleListText = "", ""

    # Handle list format safely, checking for sufficient lines and format
    if currentListText:
        lines = currentListText.split("\n")
        # Check if we have at least 2 lines and the second line starts with ":"
        if len(lines) > 1 and lines[1].startswith(":"):
            existingArticleListText = "\n".join(
                currentListText.split("\n:")[-1].split("\n")[1:]
            )
            headers = (
                currentListText.replace(existingArticleListText, "").strip() + "\n"
            )
        else:
            # Simple format with no headers
            existingArticleListText = currentListText

    articleList = newListText + existingArticleListText
    # remove duplicates from existingArticleListText, deleting articles at the top of the list first and while preserving the order
    deDupedArticleListText = []
    seen = set()
    for line in articleList.split("\n"):
        fileName = os.path.basename(line.split("\t")[0]).lower()
        if fileName not in seen:
            seen.add(fileName)
            deDupedArticleListText.append(line)
    articleList = "\n".join(deDupedArticleListText)

    combinedListText = headers + articleList
    if len(linesToAppend) > 0:
        logger.info(f"Adding the following articles to list: {listName}\n{newListText}")

    if len(linesToAppend) > 0:
        with open(listPath, "w") as f:
            f.write(combinedListText)


def deleteAllArticlesInList(listName):
    listPath = os.path.join(
        utils.getConfig()["atVoiceFolderPath"], ".config", listName + ".rlst"
    )
    createListIfNotExists(listPath)
    currentListText = open(listPath).read().strip()

    textWithArticlesRemoved = ""
    if "\n:m" not in currentListText:
        # print(f":m not found in list {listName}")
        textWithArticlesRemoved = ""
    else:
        textWithArticlesRemoved = (
            "\n:m".join(currentListText.split("\n:m")[:-1])
            + "\n:m"
            + currentListText.split("\n:m")[-1].split("\n")[0]
            + "\n"
        )  # i.e. currentListText.split("\n:m")[-1].split("\n")[0] refers to the last line in the doc which starts with :m

    with open(listPath, "w") as f:
        f.write(textWithArticlesRemoved)
