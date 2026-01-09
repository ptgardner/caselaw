"""Configuration constants for the NCAT Appeal Panel scraper."""

BASE_URL = "https://www.caselaw.nsw.gov.au"

# Advanced search URL filtered to NCAT Appeal Panel (tribunal ID: 54a634063004de94513d828d)
SEARCH_URL = (
    f"{BASE_URL}/search/advanced?"
    "page=&sort=&body=&title=&before=&catchwords=&party=&mnc=&"
    "startDate=&endDate=&fileNumber=&legislationCited=&casesCited=&"
    "_courts=on&_courts=on&_courts=on&_courts=on&_courts=on&_courts=on&"
    "_courts=on&_courts=on&_courts=on&_courts=on&_courts=on&_courts=on&_courts=on&"
    "_tribunals=on&_tribunals=on&_tribunals=on&"
    "tribunals=54a634063004de94513d828d&"
    "_tribunals=on&_tribunals=on&_tribunals=on&_tribunals=on&_tribunals=on&"
    "_tribunals=on&_tribunals=on&_tribunals=on&_tribunals=on&_tribunals=on&_tribunals=on"
)

RESULTS_PER_PAGE = 20

# Delay between requests in seconds (be respectful to the server)
REQUEST_DELAY_SECONDS = 10

DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
}

# Output file path
OUTPUT_FILE = "ncat_decisions.json"
