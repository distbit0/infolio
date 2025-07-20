import random
import re
import traceback
import sys
import os
from pathlib import Path
from typing import Optional, Tuple
import concurrent.futures
from loguru import logger
from dotenv import load_dotenv
from openai import OpenAI

# Handle imports for both package and direct script execution
if __name__ == "__main__":
    # When run directly, add parent directory to path
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    import src.utils as utils
    import src.textExtraction as textExtraction
    import src.db as db
else:
    # When imported as a module
    from . import utils
    from . import textExtraction
    from . import db

# Configure loguru logger
log_file_path = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "logs",
    "summary.log",
)
os.makedirs(os.path.dirname(log_file_path), exist_ok=True)

logger.remove()
logger.add(sys.stdout, level="DEBUG")
logger.add(
    log_file_path,
    rotation="5 MB",
    retention=3,
    level="WARNING",
    format="{time:YYYY-MM-DD HH:mm:ss} | {level} | {name}:{function}:{line} - {message}",
)

# Load environment variables from one of multiple potential .env locations
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
potential_env_paths = [
    os.path.join(project_root, ".env"),
    os.path.join(os.getcwd(), ".env"),
    os.path.abspath(".env"),
]

for env_path in potential_env_paths:
    if os.path.exists(env_path):
        load_dotenv(dotenv_path=env_path)
        logger.debug(f"Loaded environment from: {env_path}")
        break


def summarize_with_openrouter(text: str) -> Tuple[str, bool]:
    """Generate a summary of the text using the OpenRouter API.

    Args:
        text: Text to summarize

    Returns:
        Tuple[str, bool]: Generated summary and flag indicating if the text was sufficient.
    """
    if not text or not text.strip():
        logger.warning("No text to summarize")
        return "No text to summarize", False

    api_key = os.getenv("OPENROUTER_API_KEY")
    if not api_key:
        logger.error("OPENROUTER_API_KEY not found in environment variables")
        raise ValueError("OPENROUTER_API_KEY not found in environment variables")

    config = utils.getConfig()
    model = config.get("ai_model")

    try:
        client = OpenAI(
            base_url="https://openrouter.ai/api/v1",
            api_key=api_key,
        )
        logger.debug(f"Sending summary request to OpenRouter with model: {model}")

        system_prompt = (
            "You are a helpful system that generates concise summaries of academic or educational content. "
            "You must first assess if the provided text contains sufficient content to generate a meaningful summary. "
            "If the text is too short, fragmented, or lacks substantive content, respond with "
            '"<summary>[INSUFFICIENT_TEXT]</summary>" at the beginning of your response. '
            "DO NOT respond with [INSUFFICIENT_TEXT] if there is substantive content but the text merely ends abruptly/not at the end of a sentence. "
            "ALWAYS return your summary enclosed within <summary></summary> tags. "
            "ONLY put the summary itself inside these tags, not any other part of your response."
        )

        user_prompt = (
            f"Please analyze the following text:\n\n{text}\n\n"
            "First, determine if the text provides enough substantial content to write a meaningful summary. "
            "If the text is too short, fragmented, or clearly not the full article (e.g., just metadata, table of contents, or a small snippet), "
            'respond with "<summary>[INSUFFICIENT_TEXT]</summary>" followed by a brief explanation of why the text is insufficient.\n\n'
            "If the text IS sufficient, please summarize it in a concise but informative way that captures the main arguments, principles, "
            'concepts, cruxes, intuitions, explanations and conclusions. Do not say things like "the author argues that..." or '
            '"the text explains how...".\n\n'
            "IMPORTANT: Return ONLY your summary enclosed within <summary></summary> tags. Do not include any other text outside these tags."
        )

        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        )
        full_response = response.choices[0].message.content

        summary_match = re.search(r"<summary>(.*?)</summary>", full_response, re.DOTALL)
        if summary_match:
            summary = summary_match.group(1).strip()
        else:
            error_message = "Summary tags not found in model response"
            logger.error(f"{error_message}. Response: {full_response}")
            return f"Failed to generate summary: {error_message}", False

        if summary.startswith("[INSUFFICIENT_TEXT]"):
            logger.debug(f"Insufficient text detected: {summary}")
            return summary, False

        return summary, True

    except Exception as e:
        error_message = f"Error generating summary: {str(e)}"
        logger.error(f"{error_message}\n{traceback.format_exc()}")
        traceback.print_exc()
        return f"Failed to generate summary: {error_message}", False


def get_article_summary(file_path: str) -> Tuple[str, bool]:
    """Get or create a summary for an article.

    Args:
        file_path: Path to the article file

    Returns:
        Tuple[str, bool]: Article summary and a flag indicating if text was sufficient.
    """
    file_hash = utils.calculate_normal_hash(file_path)
    file_name = os.path.basename(file_path)
    file_format = os.path.splitext(file_path)[1].lower().lstrip(".")

    # Only check existing summary if not forcing a new one
    article = db.get_article_by_hash(file_hash)
    if article and article["summary"] is not None and article["summary"] != "":
        summary = article["summary"]
        if summary == "failed_to_summarise":
            logger.debug(f"Skipping file {file_name} due to previous insufficient text")
            return summary, False
        elif summary == "failed_to_extract":
            logger.debug(f"Skipping file {file_name} due to previous extraction issues")
            return summary, False
        else:
            # Article has a valid summary, return it
            logger.debug(f"Using existing summary for {file_name}")
            # db.update_article_summary(
            #     file_hash,
            #     file_name,
            #     file_format,
            #     summary,
            #     article["extraction_method"],
            #     article["word_count"],
            # )
            return summary, True

    # If we get here, the article needs a summary (either no entry, empty summary, or forcing new)
    logger.debug(f"Generating new summary for: {file_name}")

    try:
        config = utils.getConfig()
        max_words = int(config.get("summary_in_max_words", 3000))
        text, extraction_method, word_count = textExtraction.extract_text_from_file(
            file_path, max_words
        )
        summary, is_sufficient = summarize_with_openrouter(text)
        logger.debug(
            f"Summary generated for {file_name}: is_sufficient={is_sufficient}, length={len(summary)} chars"
        )

        if not is_sufficient and "[INSUFFICIENT_TEXT]" in summary:
            db_summary = "failed_to_summarise"
            logger.warning(
                f"Insufficient text for file: {file_path}, marking as failed_to_summarise: {summary}"
            )
        else:
            db_summary = summary
            logger.debug(f"Successfully created summary for file: {file_path}")

        # Update the database with the new summary
        logger.debug(f"Updating database with summary for {file_name}")
        db.update_article_summary(
            file_hash, file_name, file_format, db_summary, extraction_method, word_count
        )
        return summary, is_sufficient

    except textExtraction.TextExtractionError as te:
        if not getattr(te, "already_logged", False):
            logger.error(f"Error extracting text from article: {str(te)}")
        db.update_article_summary(
            file_hash,
            file_name,
            file_format,
            "failed_to_extract",
            "no method worked",
            0,
        )
        return "failed_to_extract", False

    except Exception as e:
        error_message = f"Error summarizing article: {str(e)}"
        logger.error(error_message)
        if os.environ.get("DEBUG", "false").lower() == "true":
            logger.debug(traceback.format_exc())
        return f"Temporary error: {error_message}", False


def summarize_articles(articles_path: Optional[str] = None, query: str = "*") -> None:
    """Summarize all articles in the given path that don't have summaries yet.

    Uses parallel processing to summarize multiple articles simultaneously.

    Args:
        articles_path: Path to the articles directory.
        query: Query string to filter articles (default: "*" for all articles).
    """
    logger.info("====== Starting article summarization process ======")

    if not articles_path:
        config = utils.getConfig()
        articles_path = config.get("articleFileFolder", "")
        if not articles_path:
            logger.error("No articles directory specified in config or argument")
            return

    if not os.path.isabs(articles_path):
        articles_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))), articles_path
        )

    db.setup_database()
    articles_needing_summary = db.get_articles_needing_summary()
    logger.info(f"Found {len(articles_needing_summary)} articles needing summarization")

    if not articles_needing_summary:
        logger.info("No articles need summarization")
        return

    articles_to_summarize = []
    config = utils.getConfig()
    max_summaries_per_session = int(config.get("maxSummariesPerSession", 150))
    random.shuffle(articles_needing_summary)

    for file_hash, file_name in articles_needing_summary:
        if len(articles_to_summarize) >= max_summaries_per_session:
            logger.info(
                f"Reached limit of {max_summaries_per_session} articles, stopping"
            )
            break
        file_path = os.path.join(articles_path, file_name)
        if os.path.exists(file_path):
            articles_to_summarize.append(file_path)
            logger.debug(f"Added {file_path} to summarization queue")
        else:
            logger.warning(f"Could not find path for {file_name} in {articles_path}")

    logger.info(f"{len(articles_to_summarize)} articles need summarization")
    if not articles_to_summarize:
        logger.info("No articles to summarize")
        return

    max_workers = int(config.get("llm_api_batch_size", 4))
    total_articles = len(articles_to_summarize)
    successful = 0
    failed = 0
    insufficient = 0
    summary_word_counts = []

    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_article = {
            executor.submit(process_single_article, path): path
            for path in articles_to_summarize
        }
        for future in concurrent.futures.as_completed(future_to_article):
            article_path = future_to_article[future]
            try:
                success, message, is_sufficient, summary = future.result()
                if success:
                    if is_sufficient:
                        logger.debug(
                            f"Successfully summarized: {article_path} - {message}"
                        )
                        successful += 1
                        word_count = len(summary.split())
                        if word_count:
                            summary_word_counts.append(word_count)
                    else:
                        insufficient += 1
                else:
                    logger.warning(f"Failed to summarize: {article_path} - {message}")
                    failed += 1
            except Exception as e:
                logger.error(
                    f"Failed to summarize: {article_path} - {str(e)}\n{traceback.format_exc()}"
                )
                failed += 1

    if summary_word_counts:
        avg_word_count = sum(summary_word_counts) / len(summary_word_counts)
        logger.info(
            f"Average word count in generated summaries: {avg_word_count:.2f} words"
        )

    logger.info(
        f"Summary: Processed {total_articles} articles - {successful} successful, {insufficient} insufficient text, {failed} failed"
    )
    logger.info("====== Finished article summarization process ======")


def process_single_article(article_path: str) -> Tuple[bool, str, bool, str]:
    """Process a single article for summarization.

    Args:
        article_path: Path to the article file.

    Returns:
        Tuple[bool, str, bool, str]: Success status, message, sufficiency flag, and summary.
    """
    try:
        summary, is_sufficient = get_article_summary(article_path)
        if summary.startswith("Failed to summarize article:"):
            return False, summary, False, ""
        if not is_sufficient:
            return (
                True,
                f"Insufficient text detected ({len(summary)} chars)",
                False,
                summary,
            )
        return True, f"Summary generated ({len(summary)} chars)", True, summary
    except Exception as e:
        error_message = f"Error processing article: {str(e)}"
        logger.error(f"{error_message}\n{traceback.format_exc()}")
        return False, error_message, False, ""


if __name__ == "__main__":
    db.remove_duplicate_file_entries()
    logger.info("Running article summarization standalone")
    summarize_articles()
