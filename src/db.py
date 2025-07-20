import sqlite3
import os
import json
import hashlib
import traceback
from pathlib import Path
from typing import Dict, List, Tuple, Any, Set, Optional
from loguru import logger
from . import utils

PROJECT_ROOT = Path(__file__).resolve().parent.parent
STORAGE_DIR = PROJECT_ROOT / "storage"
DB_FILENAME = "article_summaries.db"
DB_PATH = STORAGE_DIR / DB_FILENAME


def get_db_path() -> str:
    STORAGE_DIR.mkdir(exist_ok=True)
    return str(DB_PATH)


def get_connection() -> sqlite3.Connection:
    return sqlite3.connect(get_db_path())


def setup_database() -> str:
    db_path = get_db_path()
    with get_connection() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS article_summaries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                file_hash TEXT UNIQUE,
                file_name TEXT UNIQUE,
                file_format TEXT,
                summary TEXT,
                extraction_method TEXT,
                word_count INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS tags (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE,
                description TEXT,
                use_summary BOOLEAN,
                any_tags TEXT,
                all_tags TEXT,
                not_any_tags TEXT,
                last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS article_tags (
                article_id INTEGER,
                tag_id INTEGER,
                matches BOOLEAN NOT NULL DEFAULT 1,
                PRIMARY KEY (article_id, tag_id),
                FOREIGN KEY (article_id) REFERENCES article_summaries(id),
                FOREIGN KEY (tag_id) REFERENCES tags(id)
            );
            CREATE TABLE IF NOT EXISTS tag_hashes (
                tag_id INTEGER PRIMARY KEY,
                property_hash TEXT,
                FOREIGN KEY (tag_id) REFERENCES tags(id)
            );
            """
        )
    return db_path


# Article Summary Operations


def get_article_by_hash(file_hash: str) -> Optional[Dict[str, Any]]:
    with get_connection() as conn:
        cursor = conn.execute(
            "SELECT id, file_hash, file_name, file_format, summary, extraction_method, word_count, created_at FROM article_summaries WHERE file_hash = ?",
            (file_hash,),
        )
        row = cursor.fetchone()
    if not row:
        return None
    return {
        "id": row[0],
        "file_hash": row[1],
        "file_name": row[2],
        "file_format": row[3],
        "summary": row[4],
        "extraction_method": row[5],
        "word_count": row[6],
        "created_at": row[7],
    }


def get_article_by_file_name(file_name: str) -> Optional[Dict[str, Any]]:
    with get_connection() as conn:
        cursor = conn.execute(
            "SELECT id, file_hash, file_name, file_format, summary, extraction_method, word_count, created_at FROM article_summaries WHERE file_name = ?",
            (file_name,),
        )
        row = cursor.fetchone()
    if not row:
        return None
    return {
        "id": row[0],
        "file_hash": row[1],
        "file_name": row[2],
        "file_format": row[3],
        "summary": row[4],
        "extraction_method": row[5],
        "word_count": row[6],
        "created_at": row[7],
    }


def update_article_summary(
    file_hash: str,
    file_name: str,
    file_format: str,
    summary: str,
    extraction_method: str,
    word_count: int,
) -> int:
    with get_connection() as conn:
        article = get_article_by_hash(file_hash)
        if article is not None:
            # Article exists, update it
            conn.execute(
                """
                UPDATE article_summaries
                SET file_name = ?, file_format = ?, summary = ?, extraction_method = ?, word_count = ?
                WHERE id = ?
                """,
                (
                    file_name,
                    file_format,
                    summary,
                    extraction_method,
                    word_count,
                    article["id"],
                ),
            )
            article_id = article["id"]
        else:
            # Article doesn't exist, insert it
            cursor = conn.execute(
                """
                INSERT INTO article_summaries (file_hash, file_name, file_format, summary, extraction_method, word_count)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    file_hash,
                    file_name,
                    file_format,
                    summary,
                    extraction_method,
                    word_count,
                ),
            )
            article_id = cursor.lastrowid
        conn.commit()
    return article_id


def add_file_to_database(
    file_hash: str,
    file_name: str,
    file_format: str,
    summary: Optional[str] = None,
    extraction_method: Optional[str] = None,
    word_count: int = 0,
) -> int:
    with get_connection() as conn:
        # Check for article with matching hash or file name
        cursor = conn.execute(
            """
            SELECT id FROM article_summaries 
            WHERE file_hash = ? OR file_name = ?
            """,
            (file_hash, file_name),
        )
        existing_article = cursor.fetchone()

        if existing_article:
            article_id = existing_article[0]
            # Update the existing article with new data
            conn.execute(
                """
                UPDATE article_summaries 
                SET file_hash = ?, file_name = ?, file_format = ?, 
                    summary = ?, extraction_method = ?, word_count = ?
                WHERE id = ?
                """,
                (
                    file_hash,
                    file_name,
                    file_format,
                    summary,
                    extraction_method,
                    word_count,
                    article_id,
                ),
            )
            conn.commit()
            return article_id

        # Insert new article if no match found
        cursor = conn.execute(
            """
            INSERT INTO article_summaries (file_hash, file_name, file_format, summary, extraction_method, word_count)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (file_hash, file_name, file_format, summary, extraction_method, word_count),
        )
        article_id = cursor.lastrowid
        conn.commit()
    return article_id


def get_all_file_hashes() -> List[str]:
    with get_connection() as conn:
        cursor = conn.execute("SELECT file_hash FROM article_summaries")
        return [row[0] for row in cursor.fetchall()]


def get_articles_needing_summary() -> List[Tuple[str, str]]:
    with get_connection() as conn:
        # First, let's check if there are any inconsistencies in the data
        cursor = conn.execute(
            "SELECT COUNT(*) FROM article_summaries WHERE summary IS NOT NULL AND summary != '' AND summary != 'failed_to_summarise' AND summary != 'failed_to_extract'"
        )
        summarized_count = cursor.fetchone()[0]

        cursor = conn.execute("SELECT COUNT(*) FROM article_summaries")
        total_count = cursor.fetchone()[0]

        logger.debug(
            f"Database has {total_count} total articles, {summarized_count} with summaries"
        )

        # Get articles that truly need summarization
        cursor = conn.execute(
            "SELECT file_hash, file_name FROM article_summaries WHERE summary IS NULL OR summary = '' OR (summary != 'failed_to_summarise' AND summary != 'failed_to_extract' AND summary = '')"
        )
        return cursor.fetchall()


def remove_nonexistent_files(existing_files: Set[str]) -> int:
    with get_connection() as conn:
        cursor = conn.execute("SELECT id, file_name FROM article_summaries")
        files_to_remove = [
            file_id
            for file_id, file_name in cursor.fetchall()
            if file_name not in existing_files
        ]
        if files_to_remove:
            for file_id in files_to_remove:
                conn.execute(
                    "DELETE FROM article_tags WHERE article_id = ?", (file_id,)
                )
            placeholders = ",".join("?" for _ in files_to_remove)
            conn.execute(
                f"DELETE FROM article_summaries WHERE id IN ({placeholders})",
                files_to_remove,
            )
            conn.commit()
        return len(files_to_remove)


def remove_duplicate_file_entries() -> int:
    """
    Finds entries in the summaries table with the same file name and deletes duplicates.
    Keeps the most recently created entry for each duplicate file name.

    Returns:
        int: Number of duplicate entries removed
    """
    removed_count = 0
    with get_connection() as conn:
        # Find file names that have multiple entries
        cursor = conn.execute(
            """
            SELECT file_name, COUNT(*) as count
            FROM article_summaries
            GROUP BY file_name
            HAVING count > 1
            """
        )
        duplicate_files = cursor.fetchall()

        for file_name, count in duplicate_files:
            logger.info(f"Found {count} entries for file '{file_name}'")

            # Get all records for this file name, ordered by created_at timestamp (newest first)
            cursor = conn.execute(
                """
                SELECT id, file_hash, created_at
                FROM article_summaries
                WHERE file_name = ?
                ORDER BY created_at DESC
                """,
                (file_name,),
            )
            entries = cursor.fetchall()

            # Keep the first (newest) entry and delete the rest
            keep_id = entries[0][0]
            keep_hash = entries[0][1]

            # Delete all other entries for this file name
            for entry_id, entry_hash, _ in entries[1:]:
                logger.info(
                    f"Removing duplicate entry: id={entry_id}, file_hash={entry_hash}"
                )

                # First delete related records in article_tags table
                conn.execute(
                    "DELETE FROM article_tags WHERE article_id = ?", (entry_id,)
                )

                # Then delete the article summary entry
                conn.execute("DELETE FROM article_summaries WHERE id = ?", (entry_id,))

                removed_count += 1

        conn.commit()

    logger.info(f"Removed {removed_count} duplicate entries from the database")
    return removed_count


# Tag Operations


def get_tag_property_hash(
    description: str,
    use_summary: bool,
    any_tags: List[str] = None,
    all_tags: List[str] = None,
    not_any_tags: List[str] = None,
) -> str:
    any_tags = any_tags or []
    all_tags = all_tags or []
    not_any_tags = not_any_tags or []
    property_string = f"{description}|{use_summary}|{'|'.join(sorted(any_tags))}|{'|'.join(sorted(all_tags))}|{'|'.join(sorted(not_any_tags))}"
    return hashlib.md5(property_string.encode()).hexdigest()


def sync_tags_from_config(config: Dict[str, Any]) -> None:
    tag_config = config.get("article_tags", {})
    if not tag_config:
        logger.error("No 'article_tags' section found in config.json")
        return

    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("PRAGMA table_info(tags)")
        columns = {row[1] for row in cursor.fetchall()}
        for col in ("any_tags", "all_tags", "not_any_tags"):
            if col not in columns:
                cursor.execute(f"ALTER TABLE tags ADD COLUMN {col} TEXT")

        cursor.execute(
            "SELECT id, name, description, use_summary, any_tags, all_tags, not_any_tags FROM tags"
        )
        existing_tags = {
            row[1]: {
                "id": row[0],
                "description": row[2],
                "use_summary": bool(row[3]),
                "any_tags": json.loads(row[4]) if row[4] else [],
                "all_tags": json.loads(row[5]) if row[5] else [],
                "not_any_tags": json.loads(row[6]) if row[6] else [],
            }
            for row in cursor.fetchall()
        }

        cursor.execute("SELECT tag_id, property_hash FROM tag_hashes")
        property_hashes = {row[0]: row[1] for row in cursor.fetchall()}

        config_tag_names = {
            tag_name
            for tag_name, tag_data in tag_config.items()
            if not isinstance(tag_data, list)
        }

        for tag_name, tag_data in tag_config.items():
            if isinstance(tag_data, list):
                continue
            description = tag_data.get("description", "")
            use_summary = tag_data.get("use_summary", True)
            any_tags = tag_data.get("any_tags", [])
            all_tags = tag_data.get("all_tags", [])
            not_any_tags = tag_data.get("not_any_tags", [])
            new_hash = get_tag_property_hash(
                description, use_summary, any_tags, all_tags, not_any_tags
            )
            if tag_name in existing_tags:
                tag_id = existing_tags[tag_name]["id"]
                if property_hashes.get(tag_id) != new_hash:
                    cursor.execute(
                        """
                        UPDATE tags SET description = ?, use_summary = ?, any_tags = ?, all_tags = ?, not_any_tags = ?, last_updated = CURRENT_TIMESTAMP
                        WHERE id = ?
                        """,
                        (
                            description,
                            use_summary,
                            json.dumps(any_tags) if any_tags else None,
                            json.dumps(all_tags) if all_tags else None,
                            json.dumps(not_any_tags) if not_any_tags else None,
                            tag_id,
                        ),
                    )
                    if property_hashes.get(tag_id):
                        cursor.execute(
                            "UPDATE tag_hashes SET property_hash = ? WHERE tag_id = ?",
                            (new_hash, tag_id),
                        )
                    else:
                        cursor.execute(
                            "INSERT INTO tag_hashes (tag_id, property_hash) VALUES (?, ?)",
                            (tag_id, new_hash),
                        )
                    cursor.execute(
                        "DELETE FROM article_tags WHERE tag_id = ?", (tag_id,)
                    )
                    logger.debug(
                        f"Updated tag '{tag_name}' and cleared previous assignments"
                    )
            else:
                cursor.execute(
                    """
                    INSERT INTO tags (name, description, use_summary, any_tags, all_tags, not_any_tags)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        tag_name,
                        description,
                        use_summary,
                        json.dumps(any_tags) if any_tags else None,
                        json.dumps(all_tags) if all_tags else None,
                        json.dumps(not_any_tags) if not_any_tags else None,
                    ),
                )
                tag_id = cursor.lastrowid
                cursor.execute(
                    "INSERT INTO tag_hashes (tag_id, property_hash) VALUES (?, ?)",
                    (tag_id, new_hash),
                )
                logger.debug(f"Added new tag '{tag_name}'")

        for tag_name in set(existing_tags) - config_tag_names:
            tag_id = existing_tags[tag_name]["id"]
            cursor.execute("DELETE FROM article_tags WHERE tag_id = ?", (tag_id,))
            cursor.execute("DELETE FROM tag_hashes WHERE tag_id = ?", (tag_id,))
            cursor.execute("DELETE FROM tags WHERE id = ?", (tag_id,))
            logger.debug(f"Deleted tag '{tag_name}' as it no longer exists in config")

        conn.commit()


def get_tag_id_by_name(tag_name: str) -> Optional[int]:
    with get_connection() as conn:
        cursor = conn.execute("SELECT id FROM tags WHERE name = ?", (tag_name,))
        row = cursor.fetchone()
    return row[0] if row else None


def get_all_tags() -> List[Tuple[int, str]]:
    with get_connection() as conn:
        cursor = conn.execute("SELECT id, name FROM tags")
        return cursor.fetchall()


def get_tags_for_article(article_id: int) -> List[int]:
    with get_connection() as conn:
        cursor = conn.execute(
            "SELECT tag_id FROM article_tags WHERE article_id = ?", (article_id,)
        )
        return [row[0] for row in cursor.fetchall()]


def get_all_article_tags() -> List[Tuple[int, str, int]]:
    """Get all article tags with their associated file names.

    Returns:
        List of tuples containing (article_id, file_name, tag_id)
    """
    with get_connection() as conn:
        cursor = conn.execute(
            """
            SELECT at.article_id, a.file_name, at.tag_id 
            FROM article_tags at
            JOIN article_summaries a ON at.article_id = a.id
            """
        )
        return cursor.fetchall()


def get_all_tag_details() -> Dict[int, Dict[str, Any]]:
    with get_connection() as conn:
        cursor = conn.execute(
            "SELECT id, name, description, use_summary, any_tags, all_tags, not_any_tags FROM tags"
        )
        return {
            row[0]: {
                "id": row[0],
                "name": row[1],
                "description": row[2],
                "use_summary": bool(row[3]),
                "any_tags": json.loads(row[4]) if row[4] else [],
                "all_tags": json.loads(row[5]) if row[5] else [],
                "not_any_tags": json.loads(row[6]) if row[6] else [],
            }
            for row in cursor.fetchall()
        }


def set_article_tag(article_id: int, tag_id: int, matches: bool) -> None:
    with get_connection() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO article_tags (article_id, tag_id, matches) VALUES (?, ?, ?)",
            (article_id, tag_id, 1 if matches else 0),
        )
        conn.commit()


def remove_orphaned_tags() -> int:
    with get_connection() as conn:
        cursor = conn.execute(
            "DELETE FROM tags WHERE id NOT IN (SELECT DISTINCT tag_id FROM article_tags)"
        )
        conn.commit()
    return cursor.rowcount


# Search Operations


def get_articles_by_tag(tag_name: str) -> List[str]:
    tag_id = get_tag_id_by_name(tag_name)
    if not tag_id:
        return []
    with get_connection() as conn:
        cursor = conn.execute(
            "SELECT a.file_name FROM article_summaries a JOIN article_tags at ON a.id = at.article_id WHERE at.tag_id = ? AND at.matches = 1",
            (tag_id,),
        )
        return [row[0] for row in cursor.fetchall()]


def get_articles_not_matching_tag(tag_name: str) -> List[str]:
    tag_id = get_tag_id_by_name(tag_name)
    if not tag_id:
        return []
    with get_connection() as conn:
        cursor = conn.execute(
            "SELECT a.file_name FROM article_summaries a JOIN article_tags at ON a.id = at.article_id WHERE at.tag_id = ? AND at.matches = 0",
            (tag_id,),
        )
        return [row[0] for row in cursor.fetchall()]


def get_articles_needing_tagging(
    max_articles: Optional[int] = None,
) -> List[Tuple[int, str, str, str]]:
    # Get all active tags
    all_tags = get_all_tag_details()

    # If there are no tags, use the original approach
    if not all_tags:
        query = """
            SELECT a.id, a.file_hash, a.file_name, a.summary 
            FROM article_summaries a
            WHERE NOT EXISTS (SELECT 1 FROM article_tags WHERE article_id = a.id)
            AND a.summary IS NOT NULL AND a.summary != ''
            ORDER BY RANDOM()
        """
    else:
        # Count how many tags each article has and compare to the total number of tags
        query = """
            SELECT a.id, a.file_hash, a.file_name, a.summary 
            FROM article_summaries a
            WHERE a.summary IS NOT NULL AND a.summary != ''
            AND (
                (SELECT COUNT(DISTINCT tag_id) FROM article_tags WHERE article_id = a.id) < ?
            )
            ORDER BY RANDOM()
        """

    if max_articles:
        query += f" LIMIT {max_articles}"

    with get_connection() as conn:
        if all_tags:
            cursor = conn.execute(query, (len(all_tags),))
        else:
            cursor = conn.execute(query)
        return cursor.fetchall()


def get_all_tags_with_article_count() -> List[Tuple[int, str, int]]:
    with get_connection() as conn:
        cursor = conn.execute(
            """
            SELECT t.id, t.name, COUNT(at.article_id) 
            FROM tags t LEFT JOIN article_tags at ON t.id = at.tag_id AND at.matches = 1 
            GROUP BY t.id, t.name
            """
        )
        return cursor.fetchall()


def get_articles_for_tag(tag_id: int) -> List[Tuple[int, str]]:
    with get_connection() as conn:
        cursor = conn.execute(
            "SELECT a.id, a.file_name FROM article_summaries a JOIN article_tags at ON a.id = at.article_id WHERE at.tag_id = ? AND at.matches = 1",
            (tag_id,),
        )
        return cursor.fetchall()


def clean_orphaned_database_items() -> Tuple[int, int]:
    orphaned_tags = remove_orphaned_tags()
    with get_connection() as conn:
        cursor = conn.execute(
            "DELETE FROM tag_hashes WHERE tag_id NOT IN (SELECT id FROM tags)"
        )
        conn.commit()
    orphaned_hashes = cursor.rowcount
    return orphaned_tags, orphaned_hashes


def searchArticlesByTags(
    all_tags=[], any_tags=[], not_any_tags=[], readState="", formats=[]
):
    """
    Search for articles that match specified tags.

    Args:
        all_tags: List of tags where all must match (AND logic)
        any_tags: List of tags where any must match (OR logic)
        not_any_tags: List of tags where none should match (NOT ANY logic)
        readState: Filter by read state ('read', 'unread', or '') - empty string means no filtering
        formats: List of file formats to include
        path: Base path to search in

    Returns:
        Dict of article paths with their URLs
    """
    # Early return conditions
    is_format_specific = (
        formats
        and len(formats) > 0
        and formats != utils.getConfig()["docFormatsToMove"]
    )
    if not all_tags and not any_tags and not not_any_tags and not is_format_specific:
        return {}

    # Get database path
    db_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "storage",
        "article_summaries.db",
    )
    if not os.path.exists(db_path):
        logger.error(f"Tag database not found at {db_path}")
        return {}

    # Get all article paths that match the format criteria
    article_paths = utils.getArticlePaths(formats, readState=readState)

    # If no tags specified and only filtering by format, just apply read state filter and return
    if not all_tags and not any_tags and not not_any_tags:
        matchingArticles = {
            articlePath: utils.getUrlOfArticle(articlePath)
            for articlePath in article_paths
        }
        return matchingArticles

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    try:
        # Extract filenames from paths for efficient filtering
        filenames = {os.path.basename(path): path for path in article_paths}

        # Build SQL query for tag filtering
        query_params = []

        # Base SQL query to get article summaries
        sql = """
        SELECT as1.file_name, as1.id 
        FROM article_summaries as1
        WHERE as1.file_name IN ({})
        """.format(
            ",".join(["?"] * len(filenames))
        )

        query_params.extend(filenames.keys())

        # Filter by all_tags (AND logic)
        if all_tags:
            # For each required tag, join to article_tags and check for match
            for i, tag in enumerate(all_tags):
                tag_alias = f"at{i}"
                tag_join = f"""
                JOIN article_tags {tag_alias} ON as1.id = {tag_alias}.article_id
                JOIN tags t{i} ON {tag_alias}.tag_id = t{i}.id AND t{i}.name = ? AND {tag_alias}.matches = 1
                """
                sql = sql.replace(
                    "FROM article_summaries as1",
                    f"FROM article_summaries as1 {tag_join}",
                )
                query_params.append(tag)

        # Filter by any_tags (OR logic)
        if any_tags:
            or_conditions = []
            for tag in any_tags:
                or_conditions.append("(t_any.name = ? AND at_any.matches = 1)")
                query_params.append(tag)

            if or_conditions:
                any_tag_join = """
                JOIN article_tags at_any ON as1.id = at_any.article_id
                JOIN tags t_any ON at_any.tag_id = t_any.id
                """
                any_tag_where = " AND (" + " OR ".join(or_conditions) + ")"

                # Add the join to the FROM clause
                sql = sql.replace(
                    "FROM article_summaries as1",
                    f"FROM article_summaries as1 {any_tag_join}",
                )
                # Add the OR conditions to the WHERE clause
                sql += any_tag_where

        # Filter by not_any_tags (NOT ANY logic)
        if not_any_tags:
            # Create a subquery to exclude articles that have any of the excluded tags
            not_any_subquery = """
            NOT EXISTS (
                SELECT 1 
                FROM article_tags at_not 
                JOIN tags t_not ON at_not.tag_id = t_not.id 
                WHERE as1.id = at_not.article_id 
                AND at_not.matches = 1 
                AND t_not.name IN ({})
            )
            """.format(
                ",".join(["?"] * len(not_any_tags))
            )

            query_params.extend(not_any_tags)
            sql += " AND " + not_any_subquery

        # Execute query
        cursor.execute(sql, query_params)
        matching_files = cursor.fetchall()

        # Build result dictionary
        matchingArticles = {
            filenames[filename]: utils.getUrlOfArticle(filenames[filename])
            for filename, _ in matching_files
            if filename in filenames
        }
        return matchingArticles

    finally:
        if cursor:
            cursor.connection.close()


def remove_nonexistent_files_from_database(articles_path: Optional[str] = None) -> int:
    """Remove database entries for files that no longer exist on the filesystem.

    Args:
        articles_path: Path to the articles directory.

    Returns:
        int: Number of files removed from the database.
    """
    if not articles_path:
        config = utils.getConfig()
        articles_path = config.get("articleFileFolder", "")
        if not articles_path:
            logger.error("Article file folder not found in config")
            return 0

    logger.debug(f"Checking for nonexistent files in database from: {articles_path}")
    existing_files = {os.path.basename(path) for path in utils.getArticlePaths()}
    removed_count = remove_nonexistent_files(existing_files)
    if removed_count > 0:
        logger.info(
            f"Removed {removed_count} entries for nonexistent files from database"
        )
    else:
        logger.info("No nonexistent files found in database")
    return removed_count


def remove_orphaned_tags_from_database() -> int:
    """Remove tags from the database that don't have any associated articles.

    Returns:
        int: Number of orphaned tags removed from the database.
    """
    logger.debug("Checking for orphaned tags in database")
    removed_count = remove_orphaned_tags()
    if removed_count > 0:
        logger.info(f"Removed {removed_count} orphaned tags from database")
    else:
        logger.info("No orphaned tags found in database")
    return removed_count


def add_files_to_database(articles_path: Optional[str] = None) -> int:
    """Add all supported files to the database without summarizing.

    Args:
        articles_path: Path to the articles directory.

    Returns:
        int: Number of new files added to the database.
    """
    if not articles_path:
        config = utils.getConfig()
        articles_path = config.get("articleFileFolder", "")
        if not articles_path:
            logger.error("Article file folder not found in config")
            return 0

    logger.debug(f"Adding files to database from: {articles_path}")
    setup_database()
    config = utils.getConfig()
    file_names_to_skip = config.get("fileNamesToSkip", [])
    existing_hashes = set(get_all_file_hashes())
    added_count = 0
    all_article_paths = utils.getArticlePaths()
    logger.info(f"Found {len(all_article_paths)} files in {articles_path}.")

    for file_path in all_article_paths:
        file_name = os.path.basename(file_path)
        if file_name in file_names_to_skip:
            continue
        try:
            file_hash = utils.calculate_normal_hash(file_path)
            if file_hash in existing_hashes:
                continue
            file_ext = os.path.splitext(file_name)[1].lstrip(".")
            add_file_to_database(file_hash, file_name, file_ext)
            existing_hashes.add(file_hash)
            added_count += 1
            if added_count % 100 == 0:
                logger.debug(f"Added {added_count} new files to database")
        except Exception as e:
            logger.error(f"Error adding file to database: {file_path}: {str(e)}")
            traceback.print_exc()

    logger.info(f"Added a total of {added_count} new files to database")
    return added_count
