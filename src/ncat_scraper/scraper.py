"""Web scraper for NSW Caselaw NCAT Appeal Panel decisions.

Optimizations:
- Concurrent scraping with semaphore rate limiting
- Connection pooling with keep-alive
- Async batch processing
"""

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


# Connection pool limits for optimal performance
HTTP_LIMITS = httpx.Limits(
    max_connections=10,
    max_keepalive_connections=5,
    keepalive_expiry=30.0,
)


def create_client(timeout: float = 30.0) -> httpx.AsyncClient:
    """Create an async HTTP client with optimized settings."""
    return httpx.AsyncClient(
        limits=HTTP_LIMITS,
        timeout=timeout,
        follow_redirects=True,
        headers=DEFAULT_HEADERS,
    )


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
        response = await client.get(url)
        response.raise_for_status()
        return response.text
    except httpx.HTTPStatusError as e:
        raise ScraperError(f"HTTP {e.response.status_code} for {url}") from e
    except httpx.RequestError as e:
        raise ScraperError(f"Request failed for {url}: {e}") from e


# Pre-compiled regex for parsing
RESULTS_COUNT_PATTERN = re.compile(r"Displaying \d+ - \d+ of ([\d,]+)")


def parse_total_results(html: str) -> int:
    """Extract total number of results from search page."""
    soup = BeautifulSoup(html, "lxml")
    h1 = soup.find("h1")
    if not h1:
        raise ScraperError("Could not find results header")

    match = RESULTS_COUNT_PATTERN.search(h1.get_text())
    if not match:
        raise ScraperError(f"Could not parse results count from: {h1.get_text()}")

    return int(match.group(1).replace(",", ""))


def parse_search_results(html: str) -> list[str]:
    """Extract decision URLs from search results page."""
    soup = BeautifulSoup(html, "lxml")
    urls = []

    for result_div in soup.select("div.row.result"):
        link = result_div.select_one("h4 > a")
        if link and link.get("href"):
            href = link["href"]
            if href.startswith("/decision/"):
                urls.append(urljoin(BASE_URL, href))

    return urls


# Pre-compiled regex for decision parsing
YEAR_PATTERN = re.compile(r"\[(\d{4})\]")
MEMBER_SUFFIX_PATTERN = re.compile(r",?\s*(Senior|Principal|General|Deputy)?\s*Member.*$", re.IGNORECASE)
MEMBER_ABBREV_PATTERN = re.compile(r"\s+(SM|PM|GM|DPM)$")


def parse_decision_page(html: str, url: str) -> ScrapedDecisionData:
    """Parse a decision page and extract structured data."""
    soup = BeautifulSoup(html, "lxml")

    dts = soup.find_all("dt")
    if dts:
        return _parse_modern_layout(soup, url)
    else:
        return _parse_legacy_layout(soup, url)


def _parse_modern_layout(soup: BeautifulSoup, url: str) -> ScrapedDecisionData:
    """Parse modern layout using dt/dd pairs."""

    def get_dd_text(label: str) -> str:
        for dt in soup.find_all("dt"):
            if dt.get_text(strip=True).lower() == label.lower():
                dd = dt.find_next_sibling("dd")
                if dd:
                    return dd.get_text(strip=True)
        return ""

    mnc = get_dd_text("Medium Neutral Citation")
    if not mnc:
        raise ScraperError(f"Could not find Medium Neutral Citation for {url}")

    year_match = YEAR_PATTERN.search(mnc)
    if not year_match:
        raise ScraperError(f"Could not extract year from citation: {mnc}")
    year = int(year_match.group(1))

    before_text = get_dd_text("Before")
    decision_makers = _parse_decision_makers(before_text)

    catchwords = get_dd_text("Catchwords")

    body_div = soup.select_one("div.body")
    body_text = ""
    if body_div:
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
        for tr in soup.find_all("tr"):
            cells = tr.find_all("td")
            if len(cells) >= 3:
                header = cells[1].get_text(strip=True).upper()
                if label.upper() in header:
                    return cells[2].get_text(strip=True)
        return ""

    mnc = get_table_value("CITATION")
    if not mnc:
        raise ScraperError(f"Could not find CITATION for {url}")

    year_match = YEAR_PATTERN.search(mnc)
    if not year_match:
        raise ScraperError(f"Could not extract year from citation: {mnc}")
    year = int(year_match.group(1))

    before_text = get_table_value("JUDGMENT OF")
    decision_makers = _parse_decision_makers(before_text)

    catchwords = get_table_value("CATCHWORDS")
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
    """Parse decision maker names from 'Before' field."""
    if not text:
        return []

    parts = re.split(r"[;\n]", text)
    names = []

    for part in parts:
        part = part.strip()
        if not part:
            continue
        name = MEMBER_SUFFIX_PATTERN.sub("", part)
        name = MEMBER_ABBREV_PATTERN.sub("", name)
        name = name.strip()
        if name:
            names.append(name)

    return names


async def get_total_results(client: httpx.AsyncClient) -> int:
    """Get total number of NCAT Appeal Panel decisions."""
    html = await fetch_page(client, SEARCH_URL)
    return parse_total_results(html)


async def scrape_search_page(client: httpx.AsyncClient, page: int) -> list[str]:
    """Scrape a single search results page."""
    url = SEARCH_URL.replace("page=&", f"page={page}&")
    html = await fetch_page(client, url)
    return parse_search_results(html)


async def scrape_decision(client: httpx.AsyncClient, url: str) -> ScrapedDecisionData:
    """Scrape a single decision page."""
    html = await fetch_page(client, url)
    return parse_decision_page(html, url)


async def scrape_all_decision_urls(client: httpx.AsyncClient) -> list[str]:
    """Scrape all decision URLs from search results with rate limiting."""
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


async def scrape_decisions_concurrent(
    client: httpx.AsyncClient,
    urls: list[str],
    max_concurrent: int = 3,
    delay_between_batches: float = REQUEST_DELAY_SECONDS,
    on_progress: callable = None,
) -> list[tuple[str, ScrapedDecisionData | ScraperError]]:
    """Scrape multiple decision pages concurrently with rate limiting.

    Args:
        client: Async HTTP client
        urls: List of decision URLs to scrape
        max_concurrent: Maximum concurrent requests
        delay_between_batches: Delay between batches in seconds
        on_progress: Optional callback(completed, total, url, result)

    Returns:
        List of (url, result) tuples where result is ScrapedDecisionData or ScraperError
    """
    semaphore = asyncio.Semaphore(max_concurrent)
    results: list[tuple[str, ScrapedDecisionData | ScraperError]] = []
    completed = 0

    async def fetch_with_semaphore(url: str) -> tuple[str, ScrapedDecisionData | ScraperError]:
        nonlocal completed
        async with semaphore:
            try:
                data = await scrape_decision(client, url)
                result = (url, data)
            except ScraperError as e:
                logger.error(f"Failed to scrape {url}: {e}")
                result = (url, e)
            except Exception as e:
                logger.error(f"Unexpected error scraping {url}: {e}")
                result = (url, ScraperError(str(e)))

            completed += 1
            if on_progress:
                on_progress(completed, len(urls), url, result[1])

            return result

    # Process in batches to respect rate limits
    batch_size = max_concurrent
    for i in range(0, len(urls), batch_size):
        batch = urls[i:i + batch_size]

        # Run batch concurrently
        batch_results = await asyncio.gather(
            *[fetch_with_semaphore(url) for url in batch]
        )
        results.extend(batch_results)

        # Delay between batches (not after last batch)
        if i + batch_size < len(urls):
            await asyncio.sleep(delay_between_batches)

    return results


async def scrape_decisions_sequential(
    client: httpx.AsyncClient,
    urls: list[str],
    delay: float = REQUEST_DELAY_SECONDS,
    on_progress: callable = None,
) -> list[tuple[str, ScrapedDecisionData | ScraperError]]:
    """Scrape decision pages sequentially with delay.

    Args:
        client: Async HTTP client
        urls: List of decision URLs
        delay: Delay between requests in seconds
        on_progress: Optional callback(completed, total, url, result)

    Returns:
        List of (url, result) tuples
    """
    results = []

    for i, url in enumerate(urls):
        try:
            data = await scrape_decision(client, url)
            results.append((url, data))
            if on_progress:
                on_progress(i + 1, len(urls), url, data)
        except ScraperError as e:
            logger.error(f"Failed to scrape {url}: {e}")
            results.append((url, e))
            if on_progress:
                on_progress(i + 1, len(urls), url, e)

        if i < len(urls) - 1:
            await asyncio.sleep(delay)

    return results
