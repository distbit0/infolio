import argparse
import os
from . import utils
from . import manageLists
from loguru import logger


def getCMDArguments():
    parser = argparse.ArgumentParser(description="Boolean search saved articles")
    parser.add_argument("query", help="Query to search for")
    parser.add_argument(
        "subject", nargs="?", help="Subject folders to include in search", default=""
    )
    parser.add_argument(
        "-p", action="store_true", help="Return article paths", dest="returnPaths"
    )
    parser.add_argument(
        "-b", action="store_true", help="Return blog URLs", dest="returnBlogs"
    )
    parser.add_argument(
        "-g",
        action="store_true",
        help="Show article URLs in Gedit",
        dest="openGedit",
    )
    parser.add_argument(
        "-c",
        action="store_true",
        help="Copy article URLs to clipboard",
        dest="copyUrls",
    )
    parser.add_argument(
        "-a",
        action="store_true",
        help="Send URL file to @Voice",
        dest="atVoice",
    )
    parser.add_argument(
        "-o",
        action="store_true",
        help="Overwrite articles in @voice list",
        dest="overwrite",
    )
    args = parser.parse_args()

    return args


def main():
    args = getCMDArguments()
    subjectList = [args.subject] if args.subject else []

    ## articles = utils.getArticleUrls(
    ##     subjectList, readState="", formats=["html", "pdf", "mhtml"]
    ## )

    articleUrls = [url for url in articles.values() if url]
    articlePaths = list(articles.keys())
    articleUrls = sorted(articleUrls)

    utils.addUrlsToUrlFile(
        articleUrls, utils.getAbsPath("../output/searchResultUrls.txt"), True
    )

    logger.info("Article URLs:")
    for path, url in articles.items():
        if url:
            file_name = os.path.basename(path)
            clean_file_name = "".join(
                c if c.isalnum() else " " for c in file_name
            ).strip()
            logger.info(f"{clean_file_name}:\n{url}\n")

    if args.returnPaths:
        logger.info(f"\n\nArticle paths:\n\n" + "\n".join(articlePaths))

    if args.returnBlogs:
        blogUrls = utils.getBlogsFromUrls(articleUrls)
        logger.info(f"\n\nBlog URLs:\n\n" + "\n".join(blogUrls))

    if args.copyUrls:
        os.system(
            "xclip -sel c < " + utils.getAbsPath("../output/searchResultUrls.txt")
        )
        logger.info("Copied article URLs to clipboard")

    if args.overwrite:
        manageLists.deleteAllArticlesInList("zz+++TEMP+++")

    if args.atVoice:
        manageLists.addArticlesToList("zz+++TEMP+++", articlePaths)
        if not args.overwrite:
            logger.warning(
                "not overwriting existing articles in @voice list!. Use -o to overwrite"
            )


if __name__ == "__main__":
    main()
