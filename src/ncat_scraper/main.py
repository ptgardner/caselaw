"""Main entry point for NCAT Appeal Panel scraper.

Supports:
- Concurrent or sequential scraping
- Multiple output formats (JSON, JSONL, SQLite)
- Resume capability
- Progress reporting
"""

import argparse
import asyncio
import logging
import sys
from pathlib import Path

from .config import OUTPUT_FILE, REQUEST_DELAY_SECONDS
from .models import Decision
from .scraper import (
    ScraperError,
    create_client,
    get_total_results,
    scrape_all_decision_urls,
    scrape_decisions_concurrent,
    scrape_decisions_sequential,
)
from .classifier import classify_decision
from .storage import JSONStorage, JSONLStorage, SQLiteStorage

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


async def main(
    output_path: str = OUTPUT_FILE,
    output_format: str = "json",
    limit: int | None = None,
    resume: bool = False,
    concurrent: int = 1,
    delay: float = REQUEST_DELAY_SECONDS,
) -> None:
    """Run the scraper and classifier.

    Args:
        output_path: Path for output file
        output_format: Output format (json, jsonl, sqlite)
        limit: Optional limit on number of decisions to scrape
        resume: Resume from existing output file
        concurrent: Number of concurrent requests (1 = sequential)
        delay: Delay between requests/batches in seconds
    """
    # Initialize storage backend
    if output_format == "jsonl":
        storage = JSONLStorage(output_path)
    elif output_format == "sqlite":
        storage = SQLiteStorage(output_path)
        storage.connect()
    else:
        storage = JSONStorage(output_path)

    # Get already scraped URLs if resuming
    scraped_urls: set[str] = set()
    if resume:
        if output_format == "sqlite":
            scraped_urls = storage.get_scraped_urls()
        elif output_format == "jsonl":
            scraped_urls = storage.get_scraped_urls()
        elif Path(output_path).exists():
            existing = storage.load()
            scraped_urls = {d.url for d in existing}

        if scraped_urls:
            logger.info(f"Resuming: found {len(scraped_urls)} already scraped")

    async with create_client() as client:
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

        if not urls_to_scrape:
            logger.info("No new decisions to scrape")
            _print_summary_from_storage(storage, output_format)
            return

        # Progress callback
        def on_progress(completed: int, total: int, url: str, result):
            status = "✓" if not isinstance(result, Exception) else "✗"
            logger.info(f"[{completed}/{total}] {status} {url}")

        # Scrape decisions
        if concurrent > 1:
            logger.info(f"Scraping with {concurrent} concurrent requests...")
            results = await scrape_decisions_concurrent(
                client,
                urls_to_scrape,
                max_concurrent=concurrent,
                delay_between_batches=delay,
                on_progress=on_progress,
            )
        else:
            logger.info("Scraping sequentially...")
            results = await scrape_decisions_sequential(
                client,
                urls_to_scrape,
                delay=delay,
                on_progress=on_progress,
            )

        # Classify and store decisions
        decisions: list[Decision] = []
        for url, result in results:
            if isinstance(result, Exception):
                continue

            try:
                decision = classify_decision(result)
                decisions.append(decision)

                # For JSONL and SQLite, save incrementally
                if output_format == "jsonl":
                    storage.append(decision)
                elif output_format == "sqlite":
                    storage.insert(decision)

            except Exception as e:
                logger.error(f"Error classifying {url}: {e}")

        # For JSON, save all at once
        if output_format == "json":
            # Load existing if resuming
            if resume and Path(output_path).exists():
                existing = storage.load()
                decisions = existing + decisions
            storage.save(decisions)

        logger.info(f"Complete! Saved {len(decisions)} new decisions to {output_path}")

    # Print summary
    _print_summary_from_storage(storage, output_format)

    # Close SQLite connection
    if output_format == "sqlite":
        storage.close()


def _print_summary_from_storage(storage, output_format: str) -> None:
    """Print summary statistics."""
    print("\n" + "=" * 50)
    print("SUMMARY")
    print("=" * 50)

    if output_format == "sqlite":
        stats = storage.get_statistics()
        print(f"Total decisions:    {stats['total']}")
        print(f"Final:              {stats['by_type'].get('final', 0)}")
        print(f"Interlocutory:      {stats['by_type'].get('interlocutory', 0)}")
        print(f"Appeals allowed:    {stats['by_outcome'].get('allowed', 0)}")
        print(f"Appeals dismissed:  {stats['by_outcome'].get('dismissed', 0)}")
        print()
        print("Top grounds:")
        for ground, count in list(stats['top_grounds'].items())[:5]:
            print(f"  {ground}: {count}")
    else:
        if output_format == "jsonl":
            decisions = list(storage.iter_decisions())
        else:
            decisions = storage.load()

        total = len(decisions)
        final = sum(1 for d in decisions if d.decision_type == "final")
        interlocutory = total - final
        allowed = sum(1 for d in decisions if d.outcome == "allowed")
        dismissed = sum(1 for d in decisions if d.outcome == "dismissed")

        print(f"Total decisions:    {total}")
        print(f"Final:              {final}")
        print(f"Interlocutory:      {interlocutory}")
        print(f"Appeals allowed:    {allowed}")
        print(f"Appeals dismissed:  {dismissed}")

    print("=" * 50)


def run() -> None:
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Scrape and classify NCAT Appeal Panel decisions",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Output formats:
  json    Single JSON file with all decisions (default)
  jsonl   One JSON object per line (streaming, resumable)
  sqlite  SQLite database (queryable)

Examples:
  ncat-scraper                           # Full scrape to JSON
  ncat-scraper -f jsonl -o decisions.jsonl --resume
  ncat-scraper -f sqlite -o decisions.db --concurrent 3
  ncat-scraper --limit 10 --verbose      # Test with 10 decisions
        """
    )
    parser.add_argument(
        "-o", "--output",
        default=OUTPUT_FILE,
        help=f"Output file path (default: {OUTPUT_FILE})"
    )
    parser.add_argument(
        "-f", "--format",
        choices=["json", "jsonl", "sqlite"],
        default="json",
        help="Output format (default: json)"
    )
    parser.add_argument(
        "-l", "--limit",
        type=int,
        default=None,
        help="Limit number of decisions to scrape"
    )
    parser.add_argument(
        "-r", "--resume",
        action="store_true",
        help="Resume from existing output file"
    )
    parser.add_argument(
        "-c", "--concurrent",
        type=int,
        default=1,
        help="Number of concurrent requests (default: 1 = sequential)"
    )
    parser.add_argument(
        "-d", "--delay",
        type=float,
        default=REQUEST_DELAY_SECONDS,
        help=f"Delay between requests in seconds (default: {REQUEST_DELAY_SECONDS})"
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Enable debug logging"
    )

    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    # Adjust output filename based on format if using default
    output_path = args.output
    if output_path == OUTPUT_FILE:
        if args.format == "jsonl":
            output_path = output_path.replace(".json", ".jsonl")
        elif args.format == "sqlite":
            output_path = output_path.replace(".json", ".db")

    try:
        asyncio.run(main(
            output_path=output_path,
            output_format=args.format,
            limit=args.limit,
            resume=args.resume,
            concurrent=args.concurrent,
            delay=args.delay,
        ))
    except KeyboardInterrupt:
        logger.info("Interrupted by user")
        sys.exit(1)


if __name__ == "__main__":
    run()
