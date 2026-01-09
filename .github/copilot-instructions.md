# NCAT Appeal Panel Scraper - AI Instructions

## Project Overview

This project scrapes and classifies NCAT (NSW Civil and Administrative Tribunal) Appeal Panel decisions from the NSW Caselaw website.

## Architecture

```
src/ncat_scraper/
├── __init__.py      # Package init
├── config.py        # Constants: URLs, headers, delays
├── models.py        # Dataclasses: Decision, ScrapedDecisionData
├── scraper.py       # HTTP fetching and HTML parsing
├── classifier.py    # Decision classification logic
└── main.py          # CLI entry point
```

## Data Flow

1. `main.py` orchestrates the pipeline
2. `scraper.py` fetches search results, paginates, extracts decision URLs
3. `scraper.py` fetches individual decision pages, extracts raw data
4. `classifier.py` classifies each decision (type, grounds, outcome)
5. `models.py` structures output as JSON

## Classification Logic

Decisions are classified as:
- **Interlocutory**: Costs, stays, extensions, procedural matters
- **Final**: Appeal allowed or dismissed

For final decisions:
- **Grounds of appeal**: Extracted from s.80(2) CATA 2013 categories (error of law, procedural fairness, etc.)
- **Outcome**: allowed/dismissed based on orders section
- **Successful grounds**: Which grounds succeeded (for allowed appeals)

## Key Technical Notes

### HTML Parsing
- Two layouts exist: modern (dt/dd) and legacy (tables)
- Check for `<dt>` tags to determine layout
- Medium Neutral Citation in "Medium Neutral Citation" dt or "CITATION" table cell

### Rate Limiting
- 10-second delay between requests (configurable in config.py)
- Required to avoid 403 errors

### Anti-Scraping
- Requires browser-like User-Agent headers
- See `DEFAULT_HEADERS` in config.py

### Resume Capability
- Progress saves every 10 decisions
- Use `--resume` flag to continue interrupted runs

## Common Modifications

### Add New Ground of Appeal
Edit `GROUND_PATTERNS` in `classifier.py`:
```python
"new_ground_name": [
    r"pattern1",
    r"pattern2",
]
```

### Change Rate Limiting
Edit `REQUEST_DELAY_SECONDS` in `config.py`

### Add New Output Fields
1. Add field to `Decision` dataclass in `models.py`
2. Extract in `scraper.py` (if from HTML)
3. Set in `classifier.py` (if derived)

## Testing

```bash
# Install dev dependencies
pip install -e ".[dev]"

# Run limited scrape for testing
python -m ncat_scraper.main --limit 5 --verbose

# Run tests
pytest
```

## Known Limitations

- Classifier relies on pattern matching; edge cases may misclassify
- "Successful grounds" extraction is best-effort; may return all grounds if specific ones can't be identified
- Legacy HTML layout (older decisions) has different structure

## Dependencies

- httpx: Async HTTP client
- beautifulsoup4 + lxml: HTML parsing
- Python 3.10+: Required for type syntax
