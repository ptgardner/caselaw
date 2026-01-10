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
├── classifier.py    # Decision classification logic with ground taxonomy
└── main.py          # CLI entry point
```

## Data Flow

1. `main.py` orchestrates the pipeline
2. `scraper.py` fetches search results, paginates, extracts decision URLs
3. `scraper.py` fetches individual decision pages, extracts raw data
4. `classifier.py` classifies each decision (type, grounds, outcome)
5. `models.py` structures output as JSON

## Ground Taxonomy

The classifier uses a granular taxonomy based on legal authorities. Ground codes follow the format `{category}_{specific}`.

### Categories and Grounds

**procedural_fairness** (Fair hearing rule, Bias rule)
- `pf_no_hearing` - Denial of opportunity to be heard
- `pf_no_notice` - No notice of case to answer
- `pf_new_issue` - Decision based on issue not raised with parties
- `pf_no_cross_examination` - Denied opportunity to test evidence
- `pf_failure_to_address_submissions` - Failed to respond to substantial arguments (Dranichnikov; Alexandria Landfill)
- `pf_bias_actual` - Actual bias
- `pf_bias_apprehended` - Reasonable apprehension of bias

**jurisdictional_error** (Hossain [2018] HCA 34)
- `je_no_jurisdiction` - Lacked jurisdiction
- `je_exceeded_jurisdiction` - Exceeded statutory limits
- `je_constructive_failure` - Failed to decide a claim (Dranichnikov)
- `je_wrong_question` - Asked wrong question (Prendergast [13])
- `je_statutory_precondition` - Failed to comply with statutory precondition

**statutory_construction** (Bianco Walling; Pozzolanic)
- `sc_misconstruction` - Misconstrued statute
- `sc_wrong_legal_test` - Applied wrong legal test (Bimson; Roads & Maritime)
- `sc_technical_term` - Erred on meaning of technical term
- `sc_effect_of_term` - Erred on effect of term
- `sc_contract_construction` - Misconstrued contract

**application_of_facts_to_law** (Hope v Bathurst; Pozzolanic prop 5)
- `afl_facts_necessarily_satisfy` - Facts necessarily satisfied/didn't satisfy statute

**evidentiary** (Al-Miahi; Prendergast)
- `ev_no_evidence` - No evidence to support finding
- `ev_inference_not_available` - Inference not available from facts (Al-Miahi [34])
- `ev_probative_evidence_ignored` - Failed to consider probative evidence
- `ev_finding_not_open` - Finding not open on the evidence
- `ev_fresh_evidence` - Fresh evidence available (leave ground)

**relevant_considerations** (Peko-Wallsend pp 39-40)
- `ric_mandatory_ignored` - Failed to consider mandatory consideration
- `ric_prohibited_considered` - Considered prohibited consideration

**reasons** (Prendergast [13])
- `r_failure_to_give_reasons` - Failed to provide reasons
- `r_inadequate_reasons` - Inadequate reasons
- `r_failure_to_make_findings` - Failed to make findings on material facts

**unreasonableness** (Prendergast [13])
- `u_wednesbury` - Wednesbury unreasonable
- `u_illogical_irrational` - Illogical or irrational

**procedural_non_compliance**
- `pnc_statutory_procedure` - Statutory procedure not observed
- `pnc_tribunal_rules` - Tribunal rules not followed

**other** (catch-all)
- `other_error_of_law` - Error of law not otherwise categorised

### Important Legal Distinctions

Per the authorities:
- "Relevant" considerations = mandatory per statute
- "Irrelevant" considerations = prohibited by subject-matter, scope and purpose
- Wrongly applying correct principles ≠ applying wrong principles (Bimson)
- Categories are not closed

## Key Technical Notes

### HTML Parsing
- Two layouts exist: modern (dt/dd) and legacy (tables)
- Check for `<dt>` tags to determine layout
- Medium Neutral Citation in "Medium Neutral Citation" dt or "CITATION" table cell

### Rate Limiting
- 10-second delay between requests (configurable in config.py)
- Required to avoid 403 errors

### Resume Capability
- Progress saves every 10 decisions
- Use `--resume` flag to continue interrupted runs

## Common Modifications

### Add New Ground of Appeal
Edit `GROUNDS` list in `classifier.py`:
```python
GroundDefinition(
    code="category_specific_name",
    category="category_name",
    description="Description of ground",
    patterns=[r"regex_pattern1", r"regex_pattern2"],
    authority="Case citation",
),
```

### Change Rate Limiting
Edit `REQUEST_DELAY_SECONDS` in `config.py`

## Testing

```bash
pip install -e ".[dev]"
python -m ncat_scraper.main --limit 5 --verbose
pytest
```

## Dependencies

- httpx: Async HTTP client
- beautifulsoup4 + lxml: HTML parsing
- Python 3.10+: Required for type syntax
