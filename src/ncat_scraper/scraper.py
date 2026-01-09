"""Web scraper for NSW Caselaw NCAT Appeal Panel decisions."""

import asyncio
import logging
import re
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup

from .config import (
    BASE_URL,
    SEARCH_URL,
    RESULTS_PER_PAGE,
    REQUEST_DELAY_SECONDS,
    DEFAULT_HEADERS,
)
from .models import ScrapedDecisionData

logger = logging.getLogger(__name__)


class ScraperError(Exception):
    """Raised when scraping fails."""
    pass


async def fetch_page(client: httpx.AsyncClient, url: str) -> str:
    """Fetch a page and return its HTML content.

    Args:
        client: Async HTTP client instance
        url: URL to fetch

    Returns:
        HTML content as string

    Raises:
        ScraperError: If request fails or returns non-200 status
    """
    logger.debug(f"Fetching: {url}")
    try:
        response = await client.get(url, headers=DEFAULT_HEADERS, follow_redirects=True)
        response.raise_for_status()
        return response.text
    except httpx.HTTPStatusError as e:
        raise ScraperError(f"HTTP {e.response.status_code} for {url}") from e
    except httpx.RequestError as e:
        raise ScraperError(f"Request failed for {url}: {e}") from e


def parse_total_results(html: str) -> int:
    """Extract total number of results from search page.

    Looks for text like "Displaying 1 - 20 of 3500"

    Args:
        html: HTML content of search results page

    Returns:
        Total number of results

    Raises:
        ScraperError: If count cannot be extracted
    """
    soup = BeautifulSoup(html, "lxml")
    h1 = soup.find("h1")
    if not h1:
        raise ScraperError("Could not find results header")

    match = re.search(r"Displaying \d+ - \d+ of ([\d,]+)", h1.get_text())
    if not match:
        raise ScraperError(f"Could not parse results count from: {h1.get_text()}")

    return int(match.group(1).replace(",", ""))


def parse_search_results(html: str) -> list[str]:
    """Extract decision URLs from search results page.

    Args:
        html: HTML content of search results page

    Returns:
        List of decision URLs (absolute)
    """
    soup = BeautifulSoup(html, "lxml")
    urls = []

    for result_div in soup.select("div.row.result"):
        link = result_div.select_one("h4 > a")
        if link and link.get("href"):
            href = link["href"]
            if href.startswith("/decision/"):
                urls.append(urljoin(BASE_URL, href))

    return urls


def parse_decision_page(html: str, url: str) -> ScrapedDecisionData:
    """Parse a decision page and extract structured data.

    Handles both modern (definition list) and legacy (table) layouts.

    Args:
        html: HTML content of decision page
        url: URL of the page (for reference)

    Returns:
        ScrapedDecisionData with extracted fields

    Raises:
        ScraperError: If required fields cannot be extracted
    """
    soup = BeautifulSoup(html, "lxml")

    # Check which layout type we have
    dts = soup.find_all("dt")
    if dts:
        return _parse_modern_layout(soup, url)
    else:
        return _parse_legacy_layout(soup, url)


def _parse_modern_layout(soup: BeautifulSoup, url: str) -> ScrapedDecisionData:
    """Parse modern layout using dt/dd pairs."""

    def get_dd_text(label: str) -> str:
        """Find dt with label and return text of following dd."""
        for dt in soup.find_all("dt"):
            if dt.get_text(strip=True).lower() == label.lower():
                dd = dt.find_next_sibling("dd")
                if dd:
                    return dd.get_text(strip=True)
        return ""

    # Extract medium neutral citation
    mnc = get_dd_text("Medium Neutral Citation")
    if not mnc:
        raise ScraperError(f"Could not find Medium Neutral Citation for {url}")

    # Extract year from citation [YYYY]
    year_match = re.search(r"\[(\d{4})\]", mnc)
    if not year_match:
        raise ScraperError(f"Could not extract year from citation: {mnc}")
    year = int(year_match.group(1))

    # Extract decision makers (from "Before" field)
    before_text = get_dd_text("Before")
    decision_makers = _parse_decision_makers(before_text)

    # Extract catchwords
    catchwords = get_dd_text("Catchwords")

    # Extract body text
    body_div = soup.select_one("div.body")
    body_text = ""
    if body_div:
        # Get all text content, preserving some structure
        body_text = body_div.get_text(separator="\n", strip=True)

    return ScrapedDecisionData(
        url=url,
        medium_neutral_citation=mnc,
        year=year,
        decision_makers=decision_makers,
        body_text=body_text,
        catchwords=catchwords,
    )


def _parse_legacy_layout(soup: BeautifulSoup, url: str) -> ScrapedDecisionData:
    """Parse legacy table-based layout."""

    def get_table_value(label: str) -> str:
        """Find table row with label and return value from third cell."""
        for tr in soup.find_all("tr"):
            cells = tr.find_all("td")
            if len(cells) >= 3:
                header = cells[1].get_text(strip=True).upper()
                if label.upper() in header:
                    return cells[2].get_text(strip=True)
        return ""

    # Extract citation
    mnc = get_table_value("CITATION")
    if not mnc:
        raise ScraperError(f"Could not find CITATION for {url}")

    # Extract year from citation
    year_match = re.search(r"\[(\d{4})\]", mnc)
    if not year_match:
        raise ScraperError(f"Could not extract year from citation: {mnc}")
    year = int(year_match.group(1))

    # Extract decision makers
    before_text = get_table_value("JUDGMENT OF")
    decision_makers = _parse_decision_makers(before_text)

    # Extract catchwords
    catchwords = get_table_value("CATCHWORDS")

    # Extract body text (from JUDGMENT row)
    body_text = get_table_value("JUDGMENT")

    return ScrapedDecisionData(
        url=url,
        medium_neutral_citation=mnc,
        year=year,
        decision_makers=decision_makers,
        body_text=body_text,
        catchwords=catchwords,
    )


def _parse_decision_makers(text: str) -> list[str]:
    """Parse decision maker names from 'Before' field.

    Handles formats like:
    - "A Smith, Senior Member"
    - "J Doe, Principal Member; A Smith, Senior Member"
    - "J Doe PM; A Smith SM"
    """
    if not text:
        return []

    # Split on semicolons or newlines
    parts = re.split(r"[;\n]", text)
    names = []

    for part in parts:
        part = part.strip()
        if not part:
            continue
        # Remove role suffixes like ", Senior Member" or "SM"
        # Keep just the name part
        name = re.sub(r",?\s*(Senior|Principal|General|Deputy)?\s*Member.*$", "", part, flags=re.IGNORECASE)
        name = re.sub(r"\s+(SM|PM|GM|DPM)$", "", name)
        name = name.strip()
        if name:
            names.append(name)

    return names


async def get_total_results(client: httpx.AsyncClient) -> int:
    """Get total number of NCAT Appeal Panel decisions.

    Args:
        client: Async HTTP client

    Returns:
        Total count of decisions
    """
    html = await fetch_page(client, SEARCH_URL)
    return parse_total_results(html)


async def scrape_search_page(client: httpx.AsyncClient, page: int) -> list[str]:
    """Scrape a single search results page.

    Args:
        client: Async HTTP client
        page: Page number (1-indexed)

    Returns:
        List of decision URLs from this page
    """
    # Build URL with page parameter
    url = SEARCH_URL.replace("page=&", f"page={page}&")
    html = await fetch_page(client, url)
    return parse_search_results(html)


async def scrape_decision(client: httpx.AsyncClient, url: str) -> ScrapedDecisionData:
    """Scrape a single decision page.

    Args:
        client: Async HTTP client
        url: URL of the decision page

    Returns:
        Scraped decision data
    """
    html = await fetch_page(client, url)
    return parse_decision_page(html, url)


async def scrape_all_decision_urls(client: httpx.AsyncClient) -> list[str]:
    """Scrape all decision URLs from search results.

    Paginates through all search results pages.

    Args:
        client: Async HTTP client

    Returns:
        List of all decision URLs
    """
    total = await get_total_results(client)
    total_pages = (total - 1) // RESULTS_PER_PAGE + 1

    logger.info(f"Found {total} decisions across {total_pages} pages")

    all_urls = []
    for page in range(1, total_pages + 1):
        logger.info(f"Scraping search page {page}/{total_pages}")
        urls = await scrape_search_page(client, page)
        all_urls.extend(urls)

        if page < total_pages:
            await asyncio.sleep(REQUEST_DELAY_SECONDS)

    logger.info(f"Collected {len(all_urls)} decision URLs")
    return all_urls
