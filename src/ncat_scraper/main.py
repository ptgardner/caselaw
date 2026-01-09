"""Main entry point for NCAT Appeal Panel scraper."""

import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path

import httpx

from .config import OUTPUT_FILE, REQUEST_DELAY_SECONDS
from .models import Decision, decisions_to_json
from .scraper import (
    ScraperError,
    get_total_results,
    scrape_all_decision_urls,
    scrape_decision,
)
from .classifier import classify_decision

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


async def main(
    output_path: str = OUTPUT_FILE,
    limit: int | None = None,
    resume_from: str | None = None,
) -> None:
    """Run the scraper and classifier.

    Args:
        output_path: Path for output JSON file
        limit: Optional limit on number of decisions to scrape
        resume_from: Optional path to existing JSON to resume from
    """
    decisions: list[Decision] = []
    scraped_urls: set[str] = set()

    # Load existing progress if resuming
    if resume_from and Path(resume_from).exists():
        logger.info(f"Resuming from {resume_from}")
        with open(resume_from, "r", encoding="utf-8") as f:
            existing = json.load(f)
            for d in existing.get("decisions", []):
                decisions.append(Decision(**d))
                scraped_urls.add(d["url"])
        logger.info(f"Loaded {len(decisions)} existing decisions")

    async with httpx.AsyncClient(timeout=30.0) as client:
        # Get total count
        try:
            total = await get_total_results(client)
            logger.info(f"Total decisions available: {total}")
        except ScraperError as e:
            logger.error(f"Failed to get results count: {e}")
            return

        # Get all decision URLs
        logger.info("Collecting decision URLs from search results...")
        try:
            all_urls = await scrape_all_decision_urls(client)
        except ScraperError as e:
            logger.error(f"Failed to scrape search results: {e}")
            return

        # Filter out already scraped URLs
        urls_to_scrape = [u for u in all_urls if u not in scraped_urls]
        logger.info(f"URLs to scrape: {len(urls_to_scrape)} (skipping {len(scraped_urls)} already done)")

        # Apply limit if specified
        if limit:
            urls_to_scrape = urls_to_scrape[:limit]
            logger.info(f"Limited to {limit} decisions")

        # Scrape and classify each decision
        for i, url in enumerate(urls_to_scrape, 1):
            logger.info(f"Processing {i}/{len(urls_to_scrape)}: {url}")

            try:
                scraped_data = await scrape_decision(client, url)
                decision = classify_decision(scraped_data)
                decisions.append(decision)

                # Save progress periodically
                if i % 10 == 0:
                    _save_decisions(decisions, output_path)
                    logger.info(f"Progress saved: {len(decisions)} decisions")

            except ScraperError as e:
                logger.error(f"Failed to scrape {url}: {e}")
                continue
            except Exception as e:
                logger.error(f"Error processing {url}: {e}")
                continue

            # Rate limiting
            if i < len(urls_to_scrape):
                await asyncio.sleep(REQUEST_DELAY_SECONDS)

    # Final save
    _save_decisions(decisions, output_path)
    logger.info(f"Complete! Saved {len(decisions)} decisions to {output_path}")

    # Print summary
    _print_summary(decisions)


def _save_decisions(decisions: list[Decision], output_path: str) -> None:
    """Save decisions to JSON file."""
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(decisions_to_json(decisions))


def _print_summary(decisions: list[Decision]) -> None:
    """Print summary statistics."""
    total = len(decisions)
    final = sum(1 for d in decisions if d.decision_type == "final")
    interlocutory = total - final
    allowed = sum(1 for d in decisions if d.outcome == "allowed")
    dismissed = sum(1 for d in decisions if d.outcome == "dismissed")

    print("\n" + "=" * 50)
    print("SUMMARY")
    print("=" * 50)
    print(f"Total decisions:    {total}")
    print(f"Final:              {final}")
    print(f"Interlocutory:      {interlocutory}")
    print(f"Appeals allowed:    {allowed}")
    print(f"Appeals dismissed:  {dismissed}")
    print("=" * 50)


def run() -> None:
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Scrape and classify NCAT Appeal Panel decisions"
    )
    parser.add_argument(
        "-o", "--output",
        default=OUTPUT_FILE,
        help=f"Output JSON file path (default: {OUTPUT_FILE})"
    )
    parser.add_argument(
        "-l", "--limit",
        type=int,
        default=None,
        help="Limit number of decisions to scrape"
    )
    parser.add_argument(
        "-r", "--resume",
        default=None,
        help="Resume from existing JSON file"
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Enable debug logging"
    )

    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    try:
        asyncio.run(main(
            output_path=args.output,
            limit=args.limit,
            resume_from=args.resume,
        ))
    except KeyboardInterrupt:
        logger.info("Interrupted by user")
        sys.exit(1)


if __name__ == "__main__":
    run()
