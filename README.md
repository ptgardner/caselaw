# NCAT Appeal Panel Decision Scraper

Scrapes and classifies NCAT Appeal Panel decisions from [NSW Caselaw](https://www.caselaw.nsw.gov.au).

## Features

- Scrapes all NCAT Appeal Panel decisions (~3,500)
- Classifies decisions as final or interlocutory
- Extracts grounds of appeal
- Determines appeal outcome (allowed/dismissed)
- Identifies successful grounds for allowed appeals
- Outputs structured JSON

## Installation

```bash
# Clone repository
git clone <repo-url>
cd caselaw

# Create virtual environment
python -m venv venv
source venv/bin/activate  # or `venv\Scripts\activate` on Windows

# Install dependencies
pip install -e .
```

## Usage

```bash
# Full scrape (will take many hours due to rate limiting)
ncat-scraper

# Limited scrape for testing
ncat-scraper --limit 10

# Resume interrupted scrape
ncat-scraper --resume ncat_decisions.json

# Verbose output
ncat-scraper --verbose
```

## Output Format

```json
{
  "decisions": [
    {
      "url": "https://www.caselaw.nsw.gov.au/decision/...",
      "medium_neutral_citation": "Smith v Jones [2024] NSWCATAP 123",
      "year": 2024,
      "decision_makers": ["A Smith", "B Jones"],
      "decision_type": "final",
      "grounds_of_appeal": ["error_of_law", "denial_of_procedural_fairness"],
      "outcome": "allowed",
      "successful_grounds": ["error_of_law"]
    }
  ]
}
```

## Classification Categories

### Decision Types
- `final`: Appeal allowed or dismissed on merits
- `interlocutory`: Costs, stays, extensions, procedural matters

### Grounds of Appeal
Based on s.80(2) Civil and Administrative Tribunal Act 2013 (NSW):
- `error_of_law`
- `denial_of_procedural_fairness`
- `jurisdictional_error`
- `evidence_and_findings`
- `failure_to_give_reasons`
- `irrelevant_considerations`
- `apprehended_bias`
- `fresh_evidence`

## Configuration

Edit `src/ncat_scraper/config.py` to change:
- `REQUEST_DELAY_SECONDS`: Delay between requests (default: 10)
- `OUTPUT_FILE`: Default output filename

## License

MIT
