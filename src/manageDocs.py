import os
import random
import shutil
from collections import defaultdict
from loguru import logger
from . import utils, manageLists
import pysnooper


def delete_file_with_name(file_name):
    # Find all files with the file name in the folder using our enhanced function
    # Delete all found files
    folder = utils.getConfig()["articleFileFolder"]
    notFound = True
    possibleExts = ["pdf", "epub"]
    currentExt = os.path.splitext(file_name)[1].lstrip(
        "."
    )  # Remove leading dot using lstrip
    possibleExts.append(currentExt)
    file_name = os.path.basename(file_name)
    for ext in possibleExts:
        try:
            fileName = os.path.splitext(file_name)[0] + "." + ext
            matching_file = os.path.join(folder, fileName)
            homeDir = os.path.expanduser("~")
            dest = os.path.join(
                homeDir, ".local/share/Trash/files/", "DEL_FILE_W_NAME" + fileName
            )
            while os.path.exists(dest):
                dest = dest + "_" + str(random.randint(0, 10000))
            if os.path.exists(matching_file):
                shutil.move(matching_file, dest)
                logger.info(f"Deleted {matching_file}")
                notFound = False
        except OSError:
            pass
    if notFound:
        logger.warning(
            f"File {file_name} not found in folder {folder}, with extensions {possibleExts}"
        )


def hide_file_with_name(orgFileName):
    folder = utils.getConfig()["articleFileFolder"]
    possibleExts = ["pdf", "epub"]
    currentExt = os.path.splitext(orgFileName)[1].lstrip(
        "."
    )  # Remove leading dot using lstrip
    orgFileName = os.path.basename(orgFileName)
    possibleExts.append(currentExt)
    notFound = True
    for ext in possibleExts:
        try:
            fileName = os.path.splitext(orgFileName)[0] + "." + ext
            matching_file = os.path.join(folder, fileName)
            if os.path.exists(matching_file):
                hiddenFileName = "." + fileName
                if hiddenFileName == "." or fileName[0] == ".":
                    continue
                hiddenFilePath = os.path.join(folder, hiddenFileName)
                logger.info(f"HIDING {fileName} >> {hiddenFilePath}")
                shutil.move(matching_file, hiddenFilePath)
                notFound = False
                return hiddenFilePath
        except OSError:
            pass
    if notFound:
        logger.warning(
            f"File {orgFileName} not found in folder {folder}, with extensions {possibleExts}"
        )
    return orgFileName


def addFilesToAlreadyAddedList():
    nonHtmlFormats = [
        fmt
        for fmt in utils.getConfig()["docFormatsToMove"]
        if fmt not in ["html", "mhtml"]
    ]
    listFile = utils.getAbsPath("../storage/alreadyAddedArticles.txt")
    matchingArticles = utils.getArticlePaths(formats=nonHtmlFormats)
    alreadyAddedFileNames = str(utils.getUrlsFromFile(listFile)).lower()
    fileNames = [
        os.path.basename(filePath)
        for filePath in matchingArticles
        if os.path.basename(filePath).lower() not in alreadyAddedFileNames
    ]
    fileHashes = [
        utils.calculate_normal_hash(filePath)
        for filePath in matchingArticles
        if os.path.basename(filePath).lower() not in alreadyAddedFileNames
    ]
    itemsToAdd = list(set(fileNames + fileHashes))
    utils.addUrlsToUrlFile(itemsToAdd, listFile)


def addReadFilesToMarkedAsReadList():
    nonHtmlFormats = [
        fmt
        for fmt in utils.getConfig()["docFormatsToMove"]
        if fmt not in ["html", "mhtml"]
    ]
    listFile = utils.getAbsPath("../storage/markedAsReadArticles.txt")
    matchingArticles = utils.getArticlePaths(formats=nonHtmlFormats, readState="read")
    alreadyMarkedAsReadFileNames = str(utils.getUrlsFromFile(listFile)).lower()
    fileNames = [
        os.path.basename(filePath)
        for filePath in matchingArticles
        if os.path.basename(filePath).lower() not in alreadyMarkedAsReadFileNames
    ]
    fileHashes = [
        utils.calculate_normal_hash(filePath)
        for filePath in matchingArticles
        if os.path.basename(filePath).lower() not in alreadyMarkedAsReadFileNames
    ]
    itemsToAdd = list(set(fileNames + fileHashes))
    utils.addUrlsToUrlFile(itemsToAdd, listFile)


def deleteFilesMarkedToDelete():
    markedAsDeletedFiles = manageLists.getArticlesFromList("_DELETE")
    for fileName in markedAsDeletedFiles:
        delete_file_with_name(fileName)
    manageLists.deleteAllArticlesInList("_DELETE")


def hideArticlesMarkedAsRead():
    markedAsReadFiles = manageLists.getArticlesFromList("_READ")
    for fileName in markedAsReadFiles:
        try:
            utils.addUrlsToUrlFile(
                utils.getUrlOfArticle(
                    os.path.join(utils.getConfig()["articleFileFolder"], fileName)
                ),
                utils.getAbsPath("../storage/markedAsReadArticles.txt"),
            )
        except Exception as e:
            logger.error(f"Failed to mark {fileName} as read: {e}")
        try:
            hide_file_with_name(fileName)
        except Exception as e:
            logger.error(f"Failed to hide {fileName}: {e}")
    manageLists.deleteAllArticlesInList("_READ")


def deleteDocsWithSameHash():
    urls_to_filenames = utils.getArticleUrls()
    # Dictionary to store files by URL (since all files are in same directory now)
    url_to_files = {}

    # Group files by their URLs
    for fileName in urls_to_filenames:
        url = urls_to_filenames[fileName]
        if not url:
            continue
        url = utils.formatUrl(url)
        if "http" not in url:
            continue

        if url not in url_to_files:
            url_to_files[url] = []
        url_to_files[url].append(fileName)

    # Process each URL that has duplicates
    for url, file_list in url_to_files.items():
        if len(file_list) > 1:
            # Separate hidden files (marked as read) from non-hidden files
            hidden_files = [
                file_path
                for file_path in file_list
                if os.path.basename(file_path).startswith(".")
            ]
            non_hidden_files = [
                file_path
                for file_path in file_list
                if not os.path.basename(file_path).startswith(".")
            ]

            files_to_remove = []

            # Priority: Keep hidden files over non-hidden files
            if hidden_files:
                # Keep all hidden files, remove all non-hidden files
                files_to_remove = non_hidden_files
                # If multiple hidden files, keep only the last one
                if len(hidden_files) > 1:
                    files_to_remove.extend(hidden_files[:-1])
            else:
                # No hidden files, keep the last non-hidden file
                files_to_remove = non_hidden_files[:-1]

            logger.info(
                f"Duplicate files found for URL {url}:",
                f"hidden_files: {hidden_files}",
                f"non_hidden_files: {non_hidden_files}",
                f"files_to_remove: {files_to_remove}",
            )

            # Remove the duplicate files
            for fileName in files_to_remove:
                logger.warning(
                    f"deleting because duplicate: {fileName} {url} (Duplicate with {url_to_files[url]})"
                )
                homeDir = os.path.expanduser("~")
                dest = os.path.join(
                    homeDir,
                    ".local/share/Trash/files/",
                    "DUP_URL_" + os.path.basename(fileName),
                )
                if os.path.exists(dest):
                    logger.warning(f"File {fileName} already in trash")
                    continue
                shutil.move(fileName, dest)


def moveDocsToTargetFolder():
    docPaths = []
    PDFFolders = utils.getConfig()["pdfSourceFolders"]
    targetFolder = utils.getConfig()["articleFileFolder"]

    for folderPath in PDFFolders:
        docPaths += utils.getArticlePaths(folderPath=folderPath)

    logger.info(f"Number of docPaths: {len(docPaths)}")

    alreadyAddedHashes = str(
        utils.getUrlsFromFile(utils.getAbsPath("../storage/alreadyAddedArticles.txt"))
    ).lower()

    for docPath in docPaths:
        docHash = utils.calculate_normal_hash(docPath)
        docHashIsInAlreadyAdded = docHash.lower() in alreadyAddedHashes
        docUrl = utils.formatUrl(utils.getUrlOfArticle(docPath))
        docUrlIsInAlreadyAdded = docUrl.lower() in alreadyAddedHashes

        if docHashIsInAlreadyAdded or docUrlIsInAlreadyAdded:
            logger.warning(
                f"Skipping importing duplicate file: {docPath}, {docHash}, {docUrl}, {docHashIsInAlreadyAdded}, {docUrlIsInAlreadyAdded}"
            )
            docFileName = os.path.basename(docPath)
            homeDir = os.path.expanduser("~")
            erroDocPath = os.path.join(
                homeDir, ".local/share/Trash/files/", "IMPORT_DUPE_" + docFileName
            )
            if os.path.exists(erroDocPath):
                logger.warning(f"File {docPath} already in trash")
                continue
            shutil.move(docPath, erroDocPath)
            continue

        docName = os.path.basename(docPath)

        # Create a unique filename if needed
        baseName, extension = os.path.splitext(docName)
        uniqueName = docName
        counter = 1
        while os.path.exists(os.path.join(targetFolder, uniqueName)):
            uniqueName = f"{baseName}_{counter}{extension}"
            counter += 1

        targetPath = os.path.join(targetFolder, uniqueName)

        logger.info(f"Moving {docName} to {targetPath} derived from {docPath}")
        shutil.move(docPath, targetPath)

        utils.addUrlsToUrlFile(
            [docHash, docUrl, os.path.basename(targetPath)],
            utils.getAbsPath("../storage/alreadyAddedArticles.txt"),
        )


def deleteDocsWithSameUrl():
    directory_path = utils.getConfig()["articleFileFolder"]
    duplicate_size_files = defaultdict(list)

    for filename in os.listdir(directory_path):
        full_path = os.path.join(directory_path, filename)

        # Skip if not a file
        if not os.path.isfile(full_path):
            continue

        file_size = os.path.getsize(full_path)
        file_hash = utils.calculate_normal_hash(full_path)

        unique_key = f"{file_size}_{file_hash}"

        duplicate_size_files[unique_key].append(full_path)

    for unique_key, file_paths in duplicate_size_files.items():
        if len(file_paths) > 1:
            # Separate hidden files (marked as read) from non-hidden files
            hidden_files = [
                path for path in file_paths if os.path.basename(path)[0] == "."
            ]
            non_hidden_files = [
                path for path in file_paths if os.path.basename(path)[0] != "."
            ]

            files_to_remove = []

            # Priority: Keep hidden files over non-hidden files
            # Delete all non-hidden files if we have hidden files, otherwise keep one non-hidden file
            if hidden_files:
                # Keep all hidden files, remove all non-hidden files
                files_to_remove = non_hidden_files
                # If multiple hidden files, keep only one
                if len(hidden_files) > 1:
                    files_to_remove.extend(hidden_files[:-1])
            else:
                # No hidden files, keep one non-hidden file
                files_to_remove = non_hidden_files[:-1]

            logger.info(
                f"Duplicate files found for key {unique_key}:",
                f"hidden_files: {hidden_files}",
                f"non_hidden_files: {non_hidden_files}",
                f"files_to_remove: {files_to_remove}",
            )

            for file_path in files_to_remove:
                logger.info(f"removed: {file_path}")
                homeDir = os.path.expanduser("~")
                dest = os.path.join(
                    homeDir,
                    ".local/share/Trash/files/",
                    "DUP_HASH_" + os.path.basename(file_path),
                )
                if os.path.exists(dest):
                    logger.warning(f"File {file_path} already in trash")
                    continue
                shutil.move(file_path, dest)


def markArticlesWithUrlsAsRead(readUrls):
    articleUrls = utils.getArticleUrls()
    articleUrls = {v: k for k, v in articleUrls.items()}
    for url in readUrls:
        if url in articleUrls:
            try:
                hide_file_with_name(os.path.basename(articleUrls[url]))
            except OSError:
                logger.error(f"Error hiding {articleUrls[url]}")
        utils.addUrlsToUrlFile(
            url, utils.getAbsPath("../storage/markedAsReadArticles.txt")
        )


def getPDFTitle(pdfPath):
    pdfTitle = ""
    originalFileName = os.path.basename(pdfPath)
    pdfTitle = os.popen('pdftitle -p "' + pdfPath + '"').read()
    if (not pdfTitle) or len(pdfTitle) < 4:
        pdfTitle = originalFileName[:-4]
        idType = utils.get_id_type(pdfTitle)
        if idType == "arxiv":
            pdfTitle = utils.getArxivTitle(pdfTitle)
        elif idType == "doi":
            pdfTitle = utils.getDOITitle(pdfTitle)
    else:
        pdfTitle = pdfTitle.strip()

    pdfTitle = pdfTitle[:50]

    pdfTitle += ".pdf"

    pdfTitle = utils.removeIllegalChars(pdfTitle)
    return pdfTitle


def reTitlePDF(pdfPath):
    pdfTitle = getPDFTitle(pdfPath)
    newPath = os.path.join(os.path.dirname(pdfPath), pdfTitle)
    logger.info(f"Renaming PDF: {pdfPath} -> {newPath}")
    return newPath


def retitlePDFsInFolder(folderPath):
    pdfPaths = utils.getArticlePaths(["pdf"], folderPath)
    newPdfPaths = []
    for pdfPath in pdfPaths:
        newPath = reTitlePDF(pdfPath).lstrip(".")
        suffix = 1
        base, ext = os.path.splitext(newPath)
        while newPath in newPdfPaths or os.path.exists(newPath):
            newPath = f"{base}_{suffix}{ext}"
            suffix += 1
        newPdfPaths.append(newPath)
        os.rename(pdfPath, newPath)


def retitleAllPDFs():
    PDFFolders = utils.getConfig()["pdfSourceFolders"]
    for folderPath in PDFFolders:
        retitlePDFsInFolder(folderPath)
