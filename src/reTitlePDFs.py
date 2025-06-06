from . import utils
from .utils import getConfig
import os
import requests
import re


def removeIllegalChars(pdfTitle):
    illegalChars = getConfig()["illegalFileNameChars"]
    for char in illegalChars:
        pdfTitle = pdfTitle.replace(char, "")

    return pdfTitle


def getArxivTitle(arxiv_id):
    # Make a request to the arXiv API to get the metadata for the paper
    print(arxiv_id)
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


def getPDFTitle(pdfPath):
    pdfTitle = ""
    originalFileName = pdfPath.split("/")[-1]
    pdfTitle = os.popen('pdftitle -p "' + pdfPath + '"').read()
    if (not pdfTitle) or len(pdfTitle) < 4:
        pdfTitle = originalFileName[:-4]
        idType = get_id_type(pdfTitle)
        if idType == "arxiv":
            pdfTitle = getArxivTitle(pdfTitle)
        elif idType == "doi":
            pdfTitle = getDOITitle(pdfTitle)
    else:
        pdfTitle = pdfTitle.strip()

    pdfTitle = pdfTitle[:50]

    pdfTitle += ".pdf"

    pdfTitle = removeIllegalChars(pdfTitle)
    return pdfTitle


def reTitlePDF(pdfPath):
    pdfTitle = getPDFTitle(pdfPath)
    newPath = "/".join(pdfPath.split("/")[:-1]) + "/" + pdfTitle
    print(newPath, pdfPath)
    return newPath


def retitlePDFsInFolder(folderPath):
    pdfPaths = utils.getArticlePathsForQuery("*", ["pdf"], folderPath)
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
    PDFFolders = getConfig()["pdfSourceFolders"]
    for folderPath in PDFFolders:
        retitlePDFsInFolder(folderPath)

    return
