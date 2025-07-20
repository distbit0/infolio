import os
import re
import time
import subprocess
import tempfile
import zipfile
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Dict, Tuple, Optional, Any, Set

import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from loguru import logger

# Assuming local imports work as before
from . import utils, db
from . import manageLists

# --- Configuration & Constants --- (Same as before)
load_dotenv()
API_TOKEN = os.getenv("MINERU_API")
if not API_TOKEN:
    raise ValueError("MINERU_API token not found in .env")

MINERU_API_BASE = "https://mineru.net/api/v4"
MINERU_HEADERS = {
    "Content-Type": "application/json",
    "Authorization": f"Bearer {API_TOKEN}",
}
POLL_RETRIES = 25
POLL_INTERVAL = 12
REQ_TIMEOUT_S = 30
REQ_TIMEOUT_L = 300
EPUB_SUBDIR = "epubArticles"
PREFIXED_SUBDIR = "prefixedArticles"
HTML_EXT = {".html", ".mhtml"}
PDF_EXT = ".pdf"
EPUB_EXT = ".epub"
PANDOC_CMD = [
    "pandoc",
    "{input_md}",
    "-o",
    "{output_epub}",
    "--webtex=https://latex.codecogs.com/svg.latex?",
    "-f",
    "markdown_github+tex_math_single_backslash+tex_math_dollars",
    "--embed-resources",
    "--standalone",
    "--resource-path",
    "{resource_path}",
    "--split-level=1",
    "--epub-title-page=false",
]
MAX_CONVERSION_WORKERS = 6  # Default, can be overridden by config


# --- Helper: Mineru API Request --- (Same as before)
def _mineru_request(
    method: str, endpoint_or_url: str, is_full_url=False, **kwargs
) -> requests.Response:
    """Wrapper for Mineru API requests with error handling."""
    url = endpoint_or_url if is_full_url else f"{MINERU_API_BASE}{endpoint_or_url}"
    # Ensure standard Mineru headers are used unless explicitly overridden
    headers = kwargs.pop("headers", MINERU_HEADERS)
    try:
        kwargs.setdefault("timeout", REQ_TIMEOUT_S)
        response = requests.request(method, url, headers=headers, **kwargs)
        response.raise_for_status()
        # Check for Mineru specific API errors in JSON response (if applicable)
        # Only check if it looks like a JSON response and NOT a file download (e.g. GET zip)
        # And also not for the PUT upload which doesn't return JSON
        if method.upper() not in [
            "PUT",
            "GET",
        ] or "application/json" in response.headers.get("Content-Type", ""):
            # Check more carefully if response likely contains JSON
            try:
                result = response.json()
                if isinstance(result, dict) and result.get("code") not in [
                    0,
                    200,
                    None,
                ]:
                    # Handle Mineru API specific error codes if present
                    raise requests.exceptions.HTTPError(
                        f"Mineru API Error (code {result.get('code')}): {result.get('message', result)}",
                        response=response,
                    )
            except requests.exceptions.JSONDecodeError:
                # Ignore if response is not JSON (e.g., could be the raw file from PUT)
                pass  # Or log a debug message if needed

        return response
    except requests.exceptions.RequestException as e:
        err_msg = f"Mineru API request failed ({method} {url}): {e}"
        if e.response is not None:
            err_msg += (
                f" - Status: {e.response.status_code}, Body: {e.response.text[:200]}"
            )
        logger.error(err_msg)
        raise


# --- PDF to EPUB Conversion Sub-Functions --- (Same as before)
def _mineru_get_upload_info(pdf_path: Path) -> Tuple[str, str]:
    """Gets batch ID and upload URL from Mineru."""
    filename = pdf_path.name
    payload = {
        "files": [{"name": filename, "is_ocr": False, "data_id": filename}],
        "enable_formula": True,
        "enable_table": True,
        "language": "en",
    }
    logger.debug(f"Requesting upload info for {filename}")
    resp = _mineru_request(
        "POST", "/file-urls/batch", json=payload, timeout=REQ_TIMEOUT_S
    )
    data = resp.json().get("data", {})
    batch_id = data.get("batch_id")
    upload_url = data.get("file_urls", [None])[0]
    if not batch_id or not upload_url:
        raise ValueError(
            f"Missing batch_id or upload_url in Mineru response for {filename}"
        )
    logger.debug(f"Obtained batch_id: {batch_id} for {filename}")
    return batch_id, upload_url


def _mineru_upload_file(upload_url: str, pdf_path: Path):
    """Uploads the PDF file to the given Mineru pre-signed URL."""
    logger.debug(f"Uploading {pdf_path.name} to Mineru pre-signed URL...")
    try:
        with pdf_path.open("rb") as f:
            # Use requests.put directly WITHOUT the standard Mineru headers.
            # Pre-signed S3/OSS URLs require specific (or lack of) headers.
            # The documentation explicitly says not to set Content-Type.
            # Requests library will typically set an appropriate Content-Type like
            # 'application/octet-stream' or the server might not require it at all.
            # CRUCIALLY, we omit the 'Authorization' header provided by MINERU_HEADERS.
            response = requests.put(
                upload_url,
                data=f,
                # NO 'headers' argument here! This avoids sending MINERU_HEADERS.
                timeout=REQ_TIMEOUT_L,
            )
            response.raise_for_status()  # Check for HTTP errors (like the 403)
        logger.debug(f"Successfully uploaded {pdf_path.name} via pre-signed URL")
    except requests.exceptions.RequestException as e:
        # Provide specific error context for upload failures
        err_msg = f"Mineru file upload failed (PUT {upload_url}): {e}"
        if e.response is not None:
            # Log the specific error from the upload server (OSS/S3)
            err_msg += f" - Status: {e.response.status_code}, Body: {e.response.text[:500]}"  # Log more body for upload errors
        logger.error(err_msg)
        raise  # Re-raise the exception to be caught by the main conversion orchestrator


def _mineru_poll_for_zip_url(batch_id: str, filename: str) -> str:
    """Polls Mineru until the processing is done and returns the zip URL."""
    result_url = f"/extract-results/batch/{batch_id}"
    logger.debug(f"Polling Mineru task status for batch {batch_id} ({filename})")
    for attempt in range(POLL_RETRIES):
        try:
            res = _mineru_request("GET", result_url, timeout=REQ_TIMEOUT_S)
            result_data = res.json().get("data", {})
            extract_result = result_data.get("extract_result", [{}])[0]
            state = extract_result.get("state")
            logger.debug(
                f"Polling batch {batch_id} (attempt {attempt+1}/{POLL_RETRIES}): state={state}"
            )
            if state == "done":
                full_zip_url = extract_result.get("full_zip_url")
                if not full_zip_url:
                    raise ValueError(
                        f"Missing full_zip_url in 'done' state for batch {batch_id}"
                    )
                logger.info(
                    f"Mineru processing finished for batch ({filename}) {full_zip_url}"
                )
                return full_zip_url
            elif state == "failed":
                err_msg = extract_result.get("err_msg", "Unknown failure")
                raise RuntimeError(
                    f"Mineru processing failed for batch {batch_id}: {err_msg}"
                )
            time.sleep(POLL_INTERVAL)
        except requests.exceptions.HTTPError as e:
            if not (500 <= e.response.status_code < 600):
                raise
            logger.warning(
                f"Server error during polling ({e.response.status_code}), retrying..."
            )
            time.sleep(POLL_INTERVAL)
    raise TimeoutError(
        f"Polling timed out for batch {batch_id} ({filename}) after {POLL_RETRIES} attempts."
    )


def _run_pandoc_conversion(extracted_dir: Path, epub_path: Path):
    """Finds the markdown, demotes headers, and runs Pandoc."""
    md_path = extracted_dir / "full.md"
    if not md_path.is_file():
        raise FileNotFoundError(f"full.md not found in {extracted_dir}")
    logger.debug(f"Preparing Pandoc conversion for {epub_path.name}")
    md_content = re.sub(
        r"^# (?!#)", "## ", md_path.read_text(encoding="utf-8"), flags=re.MULTILINE
    )
    tmp_md_path = extracted_dir.parent / "temp_full.md"
    tmp_md_path.write_text(md_content, encoding="utf-8")
    try:
        pandoc_cmd_formatted = [
            item.format(
                input_md=str(tmp_md_path),
                output_epub=str(epub_path),
                resource_path=str(extracted_dir),
            )
            for item in PANDOC_CMD
        ]
        logger.debug(f"Running Pandoc: {' '.join(pandoc_cmd_formatted)}")
        result = subprocess.run(
            pandoc_cmd_formatted, capture_output=True, text=True, check=False
        )
        if result.returncode != 0:
            err_log = f"Pandoc failed for {epub_path.name} (code {result.returncode}). Stderr: {result.stderr.strip()}"
            logger.error(err_log)
            raise ChildProcessError(err_log)
        if result.stderr:
            logger.debug(
                f"Pandoc stderr (warnings) for {epub_path.name}: {result.stderr.strip()}"
            )
        logger.debug(f"Pandoc conversion successful for {epub_path.name}")
    finally:
        tmp_md_path.unlink(missing_ok=True)


def _download_extract_and_convert(zip_url: str, epub_path: Path, pdf_stem: str) -> bool:
    """Downloads zip, extracts, and triggers Pandoc conversion within a temp directory."""
    with tempfile.TemporaryDirectory(prefix=f"mineru_{pdf_stem}_") as tmpdir:
        tmp_path = Path(tmpdir)
        zip_path = tmp_path / "result.zip"
        extract_dir = tmp_path / "extracted"
        extract_dir.mkdir()
        logger.debug(f"Downloading result zip from {zip_url}")
        with _mineru_request(
            "GET", zip_url, is_full_url=True, stream=True, timeout=REQ_TIMEOUT_L
        ) as r:
            with zip_path.open("wb") as f:
                for chunk in r.iter_content(8192):
                    f.write(chunk)
        logger.debug(f"Extracting zip {zip_path.name} to {extract_dir}")
        try:
            with zipfile.ZipFile(zip_path, "r") as zip_ref:
                zip_ref.extractall(extract_dir)
        except zipfile.BadZipFile as e:
            logger.error(f"Invalid zip file downloaded from {zip_url}: {e}")
            return False
        _run_pandoc_conversion(extract_dir, epub_path)  # Raises on pandoc failure
    return True


# --- PDF to EPUB Conversion Orchestrator --- (Same as before)
def _run_pdf_to_epub_conversion(pdf_path: Path, epub_path: Path) -> bool:
    """Orchestrates the PDF -> Mineru -> EPUB conversion using helper functions."""
    logger.info(f"Starting conversion: {pdf_path.name} -> {epub_path.name}")
    try:
        batch_id, upload_url = _mineru_get_upload_info(pdf_path)
        _mineru_upload_file(upload_url, pdf_path)
        full_zip_url = _mineru_poll_for_zip_url(batch_id, pdf_path.name)
        success = _download_extract_and_convert(full_zip_url, epub_path, pdf_path.stem)
        if success:
            logger.info(f"Successfully converted {pdf_path.name} -> {epub_path.name}")
            return True
        else:
            logger.error(
                f"Conversion process failed for {pdf_path.name} after polling."
            )
            return False
    except Exception as e:
        logger.exception(f"Conversion failed for {pdf_path.name}")
        return False


# --- HTML Prefixing Logic --- (Same as before)
def _run_html_prefixing(html_path: Path, prefixed_path: Path, summary: str) -> bool:
    """Adds summary prefix to an HTML/MHTML file."""
    if not summary:
        return False
    try:
        content = html_path.read_text(encoding="utf-8", errors="ignore")
        summary_html = f"<p>{summary}</p><hr/>"
        try:
            soup = BeautifulSoup(content, "html5lib")
        except:
            soup = BeautifulSoup(content, "html.parser")
        body = soup.find("body")
        prefix_soup = BeautifulSoup(summary_html, "html.parser")
        if body:
            body.insert(0, prefix_soup)
        else:
            soup.insert(0, prefix_soup)
        prefixed_path.write_text(str(soup), encoding="utf-8")
        logger.info(f"Successfully prefixed {html_path.name} -> {prefixed_path.name}")
        return True
    except Exception as e:
        logger.exception(f"Failed prefixing {html_path.name}")
        return False


# --- Main List Processing Functions ---


# Correction: appendToLists now adds FULL PATHS (as strings) to the list
def appendToLists():
    """Searches DB and adds FULL article paths (strings) to lists based on config."""
    config = utils.getConfig()
    listToTagMappings = config.get("listToTagMappings", {})
    article_dir = Path(config.get("articleFileFolder", "."))
    if not article_dir.is_dir():
        logger.error(f"Article directory not found: {article_dir}")
        return  # Cannot proceed without article directory

    for listName, listInfo in listToTagMappings.items():
        if listInfo.get("disabled", False):
            manageLists.deleteListIfExists(listName)
            continue

        logger.debug(f"Checking articles for list '{listName}'")
        try:
            # Assuming searchArticlesByTags returns a map of FILENAME -> sort_key
            article_files_map = db.searchArticlesByTags(
                all_tags=listInfo.get("all_tags", []),
                any_tags=listInfo.get("any_tags", []),
                not_any_tags=listInfo.get("not_any_tags", []),
                readState=listInfo.get("readState", "unread"),
                formats=listInfo.get("formats", config.get("docFormatsToMove", [])),
            )
            # Convert filenames to full paths and sort
            sorted_full_paths = [
                str(article_dir / item[0])  # Create full path string
                for item in sorted(article_files_map.items(), key=lambda x: x[1])
                if (
                    article_dir / item[0]
                ).is_file()  # Ensure the source file actually exists
            ]

            # Log if any files returned by DB search don't exist on disk
            if len(sorted_full_paths) != len(article_files_map):
                logger.warning(
                    f"List '{listName}': Found {len(article_files_map) - len(sorted_full_paths)} missing files during DB scan."
                )
            # convert pdf paths to epub paths
            convertedPaths = []
            article_dir = Path(config.get("articleFileFolder", "."))
            epub_dir = os.path.join(article_dir, EPUB_SUBDIR)
            for path in sorted_full_paths:
                base_name = os.path.basename(str(path))
                extension = os.path.splitext(base_name)[1]
                if extension == ".pdf":
                    fileName_stem = os.path.splitext(base_name)[0]
                    fileName = fileName_stem + ".epub"
                    filePath = os.path.join(epub_dir, fileName)
                    convertedPaths.append(filePath)
                else:
                    convertedPaths.append(path)

            # Add the list of full path strings
            manageLists.addArticlesToList(listName, convertedPaths)
            logger.info(
                f"List '{listName}': Populated with {len(convertedPaths)} article paths"  # {convertedPaths}"
            )

        except Exception:
            logger.exception(
                f"Failed processing criteria or updating list '{listName}'",
            )


# --- `modifyListFiles` Helper Functions ---


# Correction: Takes List[Path] objects now
def _schedule_tasks_and_update_existing(
    current_paths: List[Path],  # List of Path objects
    epub_dir: Path,
    prefixed_dir: Path,
    prefixSummary: bool,
    listName: str,
    executor: ThreadPoolExecutor,
    article_dir: Path,
) -> Tuple[List[Optional[Path]], Dict[Any, Tuple[int, Path, Path]]]:
    """
    Iterates current paths, handles existing targets, schedules PDF conversions.
    Returns the initial final_paths list (as Paths) and the pdf_futures dictionary.
    """
    final_paths: List[Optional[Path]] = list(
        current_paths
    )  # Start with current Path objects
    pdf_futures = {}  # future -> (original_index, source_path, target_path)

    for i, source_path in enumerate(current_paths):  # Now iterating over Path objects
        # No need to check is_file() here, assuming appendToLists filtered correctly
        # If not, add: if not source_path.is_file(): final_paths[i] = None; continue

        file_ext = source_path.suffix.lower()

        # Handle PDF: Check existing EPUB or schedule conversion
        if file_ext == EPUB_EXT and epub_dir == source_path.parent:
            fileName = source_path.name
            target_epub_path = epub_dir / fileName
            src_pdf_path = article_dir / fileName.replace(EPUB_EXT, PDF_EXT)
            if target_epub_path.exists():
                logger.debug(
                    f"Using existing EPUB for {source_path.name}: {target_epub_path.name}"
                )
                final_paths[i] = target_epub_path  # Update with Path object
            else:
                logger.debug(f"Scheduling PDF->EPUB conversion for {source_path.name}")
                future = executor.submit(
                    _run_pdf_to_epub_conversion, src_pdf_path, target_epub_path
                )
                pdf_futures[future] = (i, source_path, target_epub_path)
                # Keep original Path in final_paths until future completes

        # Handle HTML: Check existing prefixed file
        elif file_ext in HTML_EXT and prefixSummary:
            # Construct potential target path using the *original filename*
            target_prefixed_path = prefixed_dir / source_path.name
            if target_prefixed_path.exists():
                logger.debug(
                    f"Using existing prefixed HTML for {source_path.name}: {target_prefixed_path.name}"
                )
                final_paths[i] = target_prefixed_path  # Update with Path object
            # Actual prefixing happens later if needed

    return final_paths, pdf_futures


# Correction: Accepts and updates list of Optional[Path]
def _process_pdf_futures(pdf_futures: dict, final_paths: List[Optional[Path]]):
    """Waits for PDF conversion futures and updates final_paths (list of Path) based on results."""
    if not pdf_futures:
        return

    logger.info(f"Waiting for {len(pdf_futures)} PDF conversion tasks...")
    for future in as_completed(pdf_futures):
        original_index, source_path, target_path = pdf_futures[future]
        try:
            success = future.result()  # Result is True/False
            if success:
                final_paths[original_index] = (
                    target_path  # Update path (Path object) on success
                )
            else:
                logger.warning(
                    f"Conversion failed for {source_path.name}, keeping original path in list."
                )
                # Original Path object remains in final_paths[original_index]
        except Exception as exc:
            logger.exception(
                f"PDF conversion future raised an unexpected exception for {source_path.name}",
            )
            # Keep original Path object on unexpected error


# Correction: Accepts List[Optional[Path]] and List[Path]
def _process_html_prefixing(
    final_paths: List[Optional[Path]],  # Current state (Paths or None)
    original_paths: List[Path],  # Original paths (Paths)
    prefixSummary: bool,
    prefixed_dir: Path,
):
    """Performs sequential HTML prefixing for paths that need it."""
    if not prefixSummary:
        return

    logger.info("Processing HTML prefixing...")
    for i, current_final_path in enumerate(final_paths):
        if current_final_path is None:
            continue  # Skip removed items

        original_source_path = original_paths[i]  # Get the original Path for this index

        # Check if the *original* path was HTML and if the *current* path in final_paths
        # is still that original path (meaning it wasn't updated to an EPUB or existing prefixed file yet).
        if (
            original_source_path.suffix.lower() in HTML_EXT
            and current_final_path == original_source_path
        ):
            # Use the original filename to create the target prefixed path name
            target_prefixed_path = prefixed_dir / original_source_path.name
            # Check DB for summary using original filename
            article_data = db.get_article_by_file_name(original_source_path.name)
            summary = article_data.get("summary") if article_data else None
            if summary:
                logger.debug(f"Attempting to prefix {original_source_path.name}")
                # Run prefixing using the current_final_path (which equals original_source_path here)
                success = _run_html_prefixing(
                    current_final_path, target_prefixed_path, summary
                )
                if success:
                    final_paths[i] = (
                        target_prefixed_path  # Update path (Path object) on success
                    )
                else:
                    logger.warning(
                        f"Prefixing failed for {original_source_path.name}, keeping original path."
                    )
            else:
                logger.debug(
                    f"No summary found for {original_source_path.name}, skipping prefixing."
                )


# --- Main `modifyListFiles` Orchestrator ---


def modifyListFiles():
    """Processes files (referenced by full paths) in lists: PDF->EPUB conversion, HTML prefixing."""
    config = utils.getConfig()
    listToTagMappings = config.get("listToTagMappings", {})
    article_dir = Path(config.get("articleFileFolder", "."))
    epub_dir = article_dir / EPUB_SUBDIR
    prefixed_dir = article_dir / PREFIXED_SUBDIR
    epub_dir.mkdir(parents=True, exist_ok=True)
    prefixed_dir.mkdir(parents=True, exist_ok=True)
    max_workers = config.get("maxConversionWorkers", MAX_CONVERSION_WORKERS)

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        for listName, listInfo in listToTagMappings.items():
            if listInfo.get("disabled", False):
                continue

            prefixSummary = listInfo.get("prefixSummary", False)
            try:
                # Get list of FULL PATHS (strings) from the utility function now
                current_paths_str = manageLists.getArticlesFromList(listName)
                if not current_paths_str:
                    logger.debug(f"List '{listName}' is empty, skipping modification.")
                    continue

                # Convert string paths to Path objects for internal processing
                current_paths: List[Path] = []
                valid_current_paths_str: List[str] = (
                    []
                )  # Keep track of original strings for comparison later
                for p_str in current_paths_str:
                    p_str = os.path.join(str(article_dir), p_str)
                    p = Path(p_str)
                    current_paths.append(p)
                    valid_current_paths_str.append(p_str)

                if not current_paths:
                    logger.debug(
                        f"List '{listName}' contains no existing files after validation, skipping modification."
                    )
                    # Optionally, clear the list here if it contained only invalid paths
                    # manageLists.addArticlesToList(listName, [], overwrite=True)
                    continue

                logger.info(
                    f"Processing modifications for list '{listName}' ({len(current_paths)} valid items)"
                )

                # Stage 1: Schedule parallel PDF tasks & handle existing targets (uses Path objects)
                final_paths, pdf_futures = _schedule_tasks_and_update_existing(
                    current_paths,
                    epub_dir,
                    prefixed_dir,
                    prefixSummary,
                    listName,
                    executor,
                    article_dir,
                )  # Receives/Returns List[Optional[Path]]

                # Stage 2: Wait for parallel PDF tasks (updates final_paths with Path objects)
                _process_pdf_futures(pdf_futures, final_paths)

                # Stage 3: Perform sequential HTML prefixing (uses/updates final_paths with Path objects)
                _process_html_prefixing(
                    final_paths, current_paths, prefixSummary, prefixed_dir
                )

                # Stage 4: Update the list in the utility
                # Convert final Path objects back to strings, filtering Nones
                updated_paths_str = [str(p) for p in final_paths if p is not None]

                # # Compare sets of strings to see if changes occurred
                # original_paths_set = set(
                #     valid_current_paths_str
                # )  # Use only the valid original paths for comparison
                # updated_paths_set = set(updated_paths_str)

                # if updated_paths_set != original_paths_set:
                #     logger.info(
                #         f"Updating list '{listName}' with {len(updated_paths_str)} processed paths."
                #     )
                #     logger.info(f"Updated paths: {updated_paths_str}")
                #     manageLists.addArticlesToList(listName, updated_paths_str, overwrite=True)
                # else:
                #     logger.info(
                #         f"No effective changes required for list '{listName}' after processing."
                #     )

            except Exception:
                logger.exception(
                    f"Failed processing modifications for list '{listName}'",
                )


# --- Main Execution Guard --- (Same as before)
if __name__ == "__main__":
    appendToLists()
    modifyListFiles()
