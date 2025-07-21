# Infolio (beta)

Infolio uses AI to generate high-quality reading lists on specific topics from a large collection of documents. It achieves this by tagging articles according to each tag's description, then constructing reading lists which are defined by specifying a set of tags.


## Features

- **Reading Lists**: Automatically generate reading lists based on tags and their natural language descriptions.
- **Automatic Summarization**: Generate AI-powered summaries of articles using OpenRouter API.
- **Smart Tagging**: Automatically tag articles based on their content to improve organization and searchability.
- **Browser Integration**: Import and process articles directly from your browser bookmarks and Downloads folder.
- **Powerful Search**: Search articles by content, tags, or custom Boolean queries.
- **Article Management**: Store and organize articles in various formats (PDF, HTML, MHTML, EPUB, etc.).

### Python Dependencies
- Python 3.13+
- `uv` package manager

### Command-Line Tool Dependencies
- **Pandoc**: Used for converting markdown to EPUB format
- **pdftotext** (from poppler-utils): Used for extracting text from PDF files
- **html2text**: Used for converting HTML to plain text
- **epub2txt**: Used for extracting text from EPUB files
- **ebook-convert** (from Calibre): Used for converting various e-book formats
- **pdftitle**: Used for extracting titles from PDF files
- **xclip**: Used for clipboard operations (Linux only)

### API Dependencies
- **Mineru API**: Used for PDF processing and conversion
- **OpenRouter API**: Used for article summarization and tagging

## Setup

1. **Clone the repository**:
   ```bash
   git clone https://github.com/yourusername/infolio.git
   cd infolio
   ```

2. **Install dependencies**:

   This project uses a `pyproject.toml` for dependency management. Use the following commands to install and manage dependencies with the `uv` tool:
   
   ```bash
   # Install uv if you don't have it
   curl -LsSf https://astral.sh/uv/install.sh | sh
   
   # Install dependencies from pyproject.toml
   uv sync
   ```

   This will read the `pyproject.toml` and set up the virtual environment and dependencies accordingly.

3. **Environment Configuration**:

   - Create a `.env` file in the project root to store sensitive information like API keys. Example:
     ```env
     OPENROUTER_API_KEY=your_openrouter_api_key
     MINERU_API=your_mineru_api_key
     ```

   - Update `config.json` with non-sensitive configuration parameters including file paths, bookmarks location, and processing preferences.
   
   Note: Following best practices, sensitive information like API keys is stored in the `.env` file, while regular configuration parameters are kept in `config.json`.

## Usage

### Main Workflow

Run the main module to process bookmarks, download new articles, extract text for summarization, tag articles, and update your article lists:

```bash
uv run -m src.main
```

The main workflow performs these steps in order:
1. Clean database and remove nonexistent files
2. Calculate and download new articles from bookmarks
3. Retitle PDFs for better file names
4. Move documents to target folder
5. Add new files to database
6. Generate AI summaries for articles
7. Tag articles using AI based on content
8. Update per-tag URL files
9. Handle article deletion/hiding requests
10. Remove duplicate files
11. Update reading lists

The automatically generated reading lists allow you to easily import article paths into [@Voice](https://play.google.com/store/apps/details?id=com.hyperionics.avar&hl=en_US) or other reader apps.

### Tag-Based Management

Utilize tag-based filtering to search and organize articles. Example usage in Python:

```python
from src.db import searchArticlesByTags

# Search for articles with specific criteria
articles = searchArticlesByTags(
    all_tags=["tag1", "tag2"],   # Must have ALL these tags
    any_tags=["tag3", "tag4"],   # Can have ANY of these tags
    not_any_tags=["tag5"],       # Must NOT have these tags
    readState="unread",          # Filter by read state
    formats=["pdf", "epub"]      # Filter by file formats
)
```

### Search Tool

Use the search script to find articles with Boolean queries:

```bash
uv run scripts/search.py "your search query" [subject] [options]
```

Available options:
- `-p`: Return article paths
- `-b`: Return blog URLs
- `-g`: Show article URLs in Gedit
- `-c`: Copy article URLs to clipboard
- `-a`: Send URL file to @Voice
- `-o`: Overwrite articles in @Voice list

## Reading Lists

One of the core functions of this project is the automatic generation of reading lists. These lists comprise paths to articles that match a set of specified tags and can be imported into various reading tools, including but not limited to [@Voice](https://play.google.com/store/apps/details?id=com.hyperionics.avar&hl=en_US) on Android, allowing you to organize your reading based on topics of interest and seamlessly integrate with your preferred reading applications.

Each tag in the configuration is not only a label but comes with a natural language description (configured in `config.json` under the `article_tags` section). This description is used by the language model (LLM) to determine whether a given article should be associated with a particular tag, making tag assignment both dynamic and context-aware.

### Example Tag Configuration

Here's an example of how tags are configured in `config.json`:

```json
"article_tags": {
    "infofi": {
        "description": "about any of the following:\nprediction markets\ninformation markets\nidea markets\nfutarchy\nintelligence marketplaces\ninformation elicitation incentive mechanisms to improve human cognition, improve decision making or improve information quality\napplications of ai agents to crypto\nnovell crypto capital allocation mechanisms\ngovernance incentives",
        "use_summary": true
    }
}
```

### Reading List Generation

The system generates reading lists based on tag configurations defined in `config.json`. This functionality is implemented in `src/generateLists.py` through the main function:

1. `appendToLists()` - Creates lists of articles matching specific tag criteria and converts PDF paths to EPUB paths where applicable
2. `modifyListFiles()` - (Currently disabled in main workflow) Processes the articles in each list, converting PDFs to EPUBs when possible and prefixing HTML/MHTML files with summaries if configured

## Workflow Examples

### Adding New Articles from Bookmarks

1. Save articles as bookmarks in your browser's bookmark folder (configured in `config.json`)
2. Run the main workflow:
   ```bash
   uv run -m src.main
   ```
3. The system will:
   - Download articles from bookmarks
   - Extract text and generate summaries
   - Tag articles based on content
   - Update reading lists

## Project Structure

- `src/`: Source code directory
  - `main.py`: Main entry point integrating all workflow steps including database cleanup, downloading, summarization, tagging, and list generation.
  - `db.py`: Database operations for storing and querying article metadata, summaries, and tags.
  - `articleSummary.py`: Functions for text extraction and AI-powered summarization of articles.
  - `articleTagging.py`: Implements automatic tagging based on article content using OpenRouter API.
  - `textExtraction.py`: Handles text extraction from various file formats.
  - `generateLists.py`: Generates lists of articles based on tags and other criteria, with PDF to EPUB conversion capabilities.
  - `downloadNewArticles.py`: Handles downloading new articles from bookmarks.
  - `manageDocs.py`: Document management including PDF retitling, file moving, and duplicate removal.
  - `manageLists.py`: Utilities for managing article lists and @Voice integration.
  - `utils.py`: Utility functions for file operations, URL formatting, and configuration management.

- `scripts/`: Utility scripts
  - `search.py`: Implements a CLI tool for searching articles using Boolean queries.
  - `convertGitbooks.py`: Script for converting GitBook content.
  - `deleteArticlesBasedOnUrl.py`: Utility for deleting articles by URL.
  - `getAllBlogs.py`: Script for extracting blog information.

- `storage/`: SQLite database and other persistent storage files.
- `output/`: Generated output files such as search results.
- `logs/`: Application logs including summaries and error logs.

## Configuration Details

- **Sensitive Information**: Stored in the `.env` file (e.g., API keys).
- **Non-Sensitive Configuration**: Stored in `config.json` (e.g., file paths and procedural settings).
- `article_tags`: Defines the available tags along with their natural language descriptions. These descriptions inform the LLM during article tagging.
- `listToTagMappings`: Specifies how articles should be grouped into reading lists based on tag criteria. This determines which articles appear on which reading lists.
- Other settings include directories for storing articles, bookmarks paths, backup locations, document formats to process, and exclusion rules, ensuring that the system is exactly tailored to your workflow.

## Advanced Configuration

### Custom Tag Rules

You can create complex tag rules using the `listToTagMappings` configuration:

```json
"listToTagMappings": {
    "infofi": {
        "all_tags": [],
        "formats": ["epub", "mobi", "html", "mhtml"],
        "any_tags": ["infofi"]
    }
}
```

This creates a reading list called "infofi" that includes any article with the "infofi" tag in the specified formats.

### Multiple Tag Criteria

You can use multiple tag criteria to create more specific reading lists:

```json
"advanced_topic": {
    "all_tags": ["technical", "research"],
    "any_tags": ["ai", "blockchain"],
    "not_any_tags": ["beginner"],
    "formats": ["epub", "mobi", "html", "mhtml"]
}
```

This creates a list of technical research articles about AI or blockchain that are not tagged as beginner-level.

## Development

- This project leverages the `uv` tool for running and adding dependencies.
- Use `uv run` to execute the application or run modules.
- Follow best practices in code efficiency, modularity, and security (as demonstrated in the project structure).

## Contributing

Contributions are welcome! Please adhere to the guidelines outlined in [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md).

## License

See the [LICENSE](LICENSE) file for details.
