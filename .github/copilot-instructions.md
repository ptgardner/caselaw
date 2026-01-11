# NCAT Appeal Panel Scraper - AI Instructions

## Project Overview

Scrapes and classifies NCAT (NSW Civil and Administrative Tribunal) Appeal Panel decisions from NSW Caselaw.

## Architecture

```
src/ncat_scraper/
├── __init__.py      # Package init
├── config.py        # Constants: URLs, headers, delays
├── models.py        # Dataclasses: Decision, ScrapedDecisionData
├── scraper.py       # HTTP fetching, HTML parsing, concurrent scraping
├── classifier.py    # Decision classification with confidence scoring
├── storage.py       # Storage backends: JSON, JSONL, SQLite
└── main.py          # CLI entry point
```

## Key Features

### Performance Optimizations
- **Pre-compiled regex**: All patterns compiled at module load
- **Concurrent scraping**: Configurable parallel requests with semaphore
- **Connection pooling**: HTTP keep-alive with configurable limits
- **Batch processing**: Async batch processing with rate limiting

### Classification Features
- **Confidence scoring**: Each ground match includes confidence (0.0-1.0)
- **Negation detection**: Filters false positives like "no denial of..."
- **Context-aware**: Boosts confidence for matches in relevant sections
- **33 granular grounds** across 10 categories

### Storage Backends
- **JSON**: Single file, all decisions
- **JSONL**: Streaming, one per line, resumable
- **SQLite**: Queryable database with statistics

## Ground Taxonomy

Categories: `procedural_fairness`, `jurisdictional_error`, `statutory_construction`, `application_of_facts_to_law`, `evidentiary`, `relevant_considerations`, `reasons`, `unreasonableness`, `procedural_non_compliance`, `other`

Ground codes follow format: `{category_prefix}_{specific}` (e.g., `pf_no_hearing`, `ev_no_evidence`)

### Key Legal Distinctions
- "Relevant" = mandatory per statute (Peko-Wallsend)
- "Irrelevant" = prohibited by statute's purpose
- Wrongly applying correct principles ≠ applying wrong principles (Bimson)

## CLI Usage

```bash
# Basic usage
ncat-scraper

# With options
ncat-scraper -f jsonl -o decisions.jsonl --resume --concurrent 3

# Options:
#   -o, --output     Output file path
#   -f, --format     json|jsonl|sqlite
#   -l, --limit      Limit decisions to scrape
#   -r, --resume     Resume from existing file
#   -c, --concurrent Concurrent requests (default: 1)
#   -d, --delay      Delay in seconds (default: 10)
#   -v, --verbose    Debug logging
```

## Modifying Grounds

Edit `GROUNDS` list in `classifier.py`:

```python
GroundDefinition(
    code="category_specific_name",
    category="category_name",
    description="Description",
    patterns=[r"regex1", r"regex2"],
    authority="Case citation",
    weight=0.9,  # Confidence weight 0.0-1.0
),
```

## Testing

```bash
pip install -e ".[dev]"
python -m ncat_scraper.main --limit 5 --verbose
pytest
```

## SQLite Queries

```sql
-- Decisions by ground
SELECT d.* FROM decisions d
JOIN grounds g ON d.id = g.decision_id
WHERE g.ground = 'ev_no_evidence';

-- Success rate by ground
SELECT g.ground,
       COUNT(*) as total,
       SUM(CASE WHEN d.outcome = 'allowed' THEN 1 ELSE 0 END) as allowed
FROM grounds g
JOIN decisions d ON g.decision_id = d.id
GROUP BY g.ground;
```

## Dependencies

- httpx: Async HTTP with connection pooling
- beautifulsoup4 + lxml: HTML parsing
- Python 3.10+
