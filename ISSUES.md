3. SQL Query Construction Bug in db.py

if all_tags:
    sql = sql.replace(
        "FROM article_summaries as1",
        f"FROM article_summaries as1 {tag_join}",
    )
# Later...
if any_tags:
    sql = sql.replace(
        "FROM article_summaries as1",
        f"FROM article_summaries as1 {any_tag_join}",
    )
The second replace won't work correctly because the FROM clause was already modified by the first replace.


