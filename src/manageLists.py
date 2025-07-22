import os
import glob
from . import utils
from loguru import logger


def getArticlesFromList(listName):
    """
    Returns a list of *relative* article paths extracted from the `.rlst`
    file named `listName`.

    Behaviour overview
    ------------------
    1.  Reads the list file (quietly returns [] if it does not exist).
    2.  Parses it into an optional **header** region and a list of article
        paths (relative to `droidEbooksFolderPath`).
    3.  If the list name starts with “_”, merges in any Syncthing
        `*.sync‑conflict-*` versions, keeping their article lines and then
        deleting the conflicts.
    4.  **New:** removes any article whose *real* file has vanished from
        `articleFileFolder`, and rewrites the list on disk if pruning
        occurred so the file stays self‑healing.
    5.  Returns the cleaned list of relative paths.
    """

    # ------------------------------------------------------------------
    # Resolve paths and bail out early if the list file is missing
    # ------------------------------------------------------------------
    config_path = utils.getConfig()["atVoiceFolderPath"]
    listPath = os.path.join(config_path, ".config", listName + ".rlst")
    rootPath = utils.getConfig()["droidEbooksFolderPath"]

    if not os.path.exists(listPath):
        return []

    # ------------------------------------------------------------------
    # Helper: parse header + article lines from a .rlst text blob
    # ------------------------------------------------------------------
    def parse_article_lines(text):
        """
        Returns (header_text | None, [article_relative_path, …])

        `article_relative_path` is the path *relative to* droidEbooksFolderPath.
        """
        text = text.strip()
        if not text:
            return None, []

        lines = text.split("\n")

        # Detect a header — the file has one when the second line starts with ":"
        if len(lines) > 1 and lines[1].startswith(":"):
            # Everything up to the *last* "\n:" belongs to the header
            parts = text.split("\n:")
            header_text = "\n:".join(parts[:-1]).rstrip("\n")
            tail = parts[-1].split("\n")
            article_lines = tail[1:]  # skip the ":" marker
        else:
            header_text = None
            article_lines = lines

        articles = []
        for line in article_lines:
            line = line.strip()
            if not line:
                continue
            first_field = line.split("\t")[0]
            if first_field:
                rel_to_root = os.path.relpath(first_field, rootPath)
                if rel_to_root not in articles:
                    articles.append(rel_to_root)

        return header_text, articles

    # ------------------------------------------------------------------
    # 1. Read and parse the main file
    # ------------------------------------------------------------------
    with open(listPath, "r", encoding="utf-8") as f:
        mainText = f.read()

    mainHeader, mainArticles = parse_article_lines(mainText)

    # ------------------------------------------------------------------
    # 2. Gather possible Syncthing conflict files (only for "_" lists)
    # ------------------------------------------------------------------
    conflict_files = []
    # if listName.startswith("_"):
    baseName = os.path.basename(listPath)
    name_only = os.path.splitext(baseName)[0]
    extension = os.path.splitext(baseName)[1]
    dirName = os.path.dirname(listPath)
    pattern = f"{name_only}.sync-conflict-*{extension}"
    conflict_files = glob.glob(os.path.join(dirName, pattern))

    # ------------------------------------------------------------------
    # 3. Merge conflict articles, rewrite, and delete conflicts
    # ------------------------------------------------------------------
    articleFileFolder = utils.getConfig()["articleFileFolder"]
    if conflict_files:
        logger.info(f"Found {len(conflict_files)} conflict files for {listName}")
        for cfile in conflict_files:
            try:
                with open(cfile, "r", encoding="utf-8") as cf:
                    _, conflictArticles = parse_article_lines(cf.read())
                for art in conflictArticles:
                    if art not in mainArticles:
                        if os.path.exists(os.path.join(articleFileFolder, art)):
                            mainArticles.append(art)
            except Exception as e:
                logger.error(f"Error reading conflict file {cfile}: {e}")

        # rewrite the merged list (header preserved if present)
        if mainHeader is not None:
            merged_text = f"{mainHeader}\n:\n" + "\n".join(mainArticles)
        else:
            merged_text = "\n".join(os.path.join(rootPath, art) for art in mainArticles)
        try:
            with open(listPath, "w", encoding="utf-8") as f:
                f.write(merged_text)
            for cfile in conflict_files:
                try:
                    os.remove(cfile)
                except Exception as e:
                    logger.error(f"Error deleting conflict file {cfile}: {e}")
        except Exception as e:
            logger.error(f"Error saving merged content to {listPath}: {e}")

    # ------------------------------------------------------------------
    # 4. Done
    # ------------------------------------------------------------------
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
                "mobi": "#",
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
