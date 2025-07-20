from . import utils
from loguru import logger

subject = ""


def getBlogs(subject):
    urls = utils.getArticleUrls([subject], readState="read").values()
    urls = list(urls)
    blogs = utils.getBlogsFromUrls(urls)
    return blogs


def getOnlyNewBlogs(blogs):
    newBlogs = []
    alreadyReviewedBlogs = utils.getUrlsFromFile(
        utils.getAbsPath("../storage/reviewedBlogs.txt")
    )
    for blog in blogs:
        if not blog in alreadyReviewedBlogs:
            newBlogs.append(blog)

    return newBlogs


if __name__ == "__main__":
    blogs = getBlogs(subject)
    blogCounts = {}
    for blog in blogs:
        blogUrl = utils.getBlogFromUrl(blog)
        if blogUrl in blogCounts:
            blogCounts[blogUrl] += 1
        else:
            blogCounts[blogUrl] = 1

    sortedBlogCounts = sorted(blogCounts.items(), key=lambda x: x[1], reverse=True)
    newBlogs = [
        f"{blog.replace('scribe.rip', 'medium.com')} ({count})"
        for blog, count in sortedBlogCounts[:5]
    ]
    logger.info("\n".join(newBlogs))
    addBlogs = input(f"Add top {len(newBlogs)} blogs to reviewed? (default=no): ")
    if addBlogs.lower() in ["y", "yes"]:
        utils.addUrlsToUrlFile(
            [blog.split(" ")[0] for blog in newBlogs],
            utils.getAbsPath("../storage/reviewedBlogs.txt"),
        )
