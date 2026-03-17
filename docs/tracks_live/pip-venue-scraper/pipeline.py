#!/usr/bin/env python3
"""
PIP Venue Discovery Pipeline — Main Orchestrator

Runs the full venue discovery pipeline:
  1. Scrape track directories (Chronokart for FR, curated lists for UK/IT)
  2. Validate and match Apex Timing slugs
  3. Brute-force slug discovery for unresolved venues
  4. Enrich with Google Places data (or free Nominatim geocoding)
  5. Export results

Usage:
  python3 pipeline.py                    # Run full pipeline (no geocoding)
  python3 pipeline.py --geocode          # Run full pipeline + free geocoding
  python3 pipeline.py --geocode-google   # Run full pipeline + Google Places
  python3 pipeline.py --export           # Export to JSON
  python3 pipeline.py --stats            # Show database stats
"""

import asyncio
import argparse
import json
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from utils.database import init_db, get_venues, get_stats, get_connection
from scrapers.sws_scraper import run_sws_scraper
from scrapers.apex_slug_validator import run_apex_discovery
from scrapers.google_enrichment import run_google_enrichment, run_free_geocoding


async def run_full_pipeline(geocode: bool = False, google_geocode: bool = False):
    """Run the complete venue discovery pipeline."""

    print("=" * 60)
    print("  PIP Venue Discovery Pipeline")
    print("=" * 60)

    # Step 1: Initialize database
    init_db()
    print("\n✓ Database initialized")

    # Step 2: Scrape track directories
    print("\n" + "─" * 40)
    print("  PHASE 1: Track Directory Discovery")
    print("─" * 40)
    total = await run_sws_scraper()

    # Step 3: Apex Timing slug discovery
    print("\n" + "─" * 40)
    print("  PHASE 2: Apex Timing Slug Discovery")
    print("─" * 40)
    await run_apex_discovery()

    # Step 4: Geocoding / enrichment
    if google_geocode:
        print("\n" + "─" * 40)
        print("  PHASE 3: Google Places Enrichment")
        print("─" * 40)
        await run_google_enrichment()
    elif geocode:
        print("\n" + "─" * 40)
        print("  PHASE 3: Nominatim Geocoding (free)")
        print("─" * 40)
        await run_free_geocoding()
    else:
        print("\n[Pipeline] Skipping geocoding (use --geocode or --geocode-google)")

    # Final summary
    print("\n" + "=" * 60)
    print("  PIPELINE COMPLETE — Summary")
    print("=" * 60)
    stats = get_stats()
    print(f"\n  Total venues:      {stats['total']}")
    print(f"  Timing verified:   {stats['timing_verified']}")
    print(f"  With Apex slug:    {stats['with_slug']}")
    if stats['total'] > 0:
        print(f"  Resolution rate:   {stats['timing_verified']/stats['total']*100:.1f}%")
    print(f"\n  By country:")
    for country, count in stats["by_country"].items():
        print(f"    {country}: {count}")
    print(f"\n  By source:")
    for source, count in stats["by_source"].items():
        print(f"    {source}: {count}")


def export_venues(output_path: str = None):
    """Export all venues to JSON."""
    if not output_path:
        output_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "data", "venues_export.json"
        )

    venues = get_venues()

    # Clean up for export
    for v in venues:
        if v.get("sws_categories") and isinstance(v["sws_categories"], str):
            try:
                v["sws_categories"] = json.loads(v["sws_categories"])
            except json.JSONDecodeError:
                pass
        # Convert SQLite boolean
        v["timing_verified"] = bool(v.get("timing_verified"))

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(venues, f, indent=2, ensure_ascii=False, default=str)

    print(f"\n✓ Exported {len(venues)} venues to {output_path}")

    # Also export a summary by country
    verified = [v for v in venues if v["timing_verified"]]
    print(f"  Verified venues: {len(verified)}")
    for country in ("FR", "GB", "IT"):
        country_venues = [v for v in venues if v.get("country") == country]
        country_verified = [v for v in country_venues if v["timing_verified"]]
        print(f"  {country}: {len(country_venues)} total, {len(country_verified)} verified")

    return output_path


def show_stats():
    """Print database statistics."""
    init_db()
    stats = get_stats()

    print("\n" + "=" * 50)
    print("  PIP Venue Database Statistics")
    print("=" * 50)
    print(f"\n  Total venues:      {stats['total']}")
    print(f"  Timing verified:   {stats['timing_verified']}")
    print(f"  With Apex slug:    {stats['with_slug']}")

    if stats['total'] > 0:
        print(f"  Resolution rate:   {stats['timing_verified']/stats['total']*100:.1f}%")

    print(f"\n  By country:")
    for country, count in stats["by_country"].items():
        print(f"    {country}: {count}")

    print(f"\n  By source:")
    for source, count in stats["by_source"].items():
        print(f"    {source}: {count}")

    # Show some verified venues
    conn = get_connection()
    verified = conn.execute(
        "SELECT name, country, timing_slug, live_timing_url FROM venues "
        "WHERE timing_verified = 1 ORDER BY country, name LIMIT 20"
    ).fetchall()
    conn.close()

    if verified:
        print(f"\n  Sample verified venues:")
        for v in verified:
            print(f"    [{v['country']}] {v['name']}")
            print(f"         slug: {v['timing_slug']}")
            print(f"         url:  {v['live_timing_url']}")


def main():
    parser = argparse.ArgumentParser(description="PIP Venue Discovery Pipeline")
    parser.add_argument(
        "--geocode", action="store_true",
        help="Enable free geocoding via Nominatim (slow, 1 req/sec)"
    )
    parser.add_argument(
        "--geocode-google", action="store_true",
        help="Enable Google Places enrichment (requires GOOGLE_MAPS_API_KEY)"
    )
    parser.add_argument(
        "--export", action="store_true",
        help="Export venues to JSON after pipeline"
    )
    parser.add_argument(
        "--stats", action="store_true",
        help="Show database statistics (no scraping)"
    )
    parser.add_argument(
        "--export-only", action="store_true",
        help="Only export, don't run pipeline"
    )
    args = parser.parse_args()

    if args.stats:
        show_stats()
        return

    if args.export_only:
        init_db()
        export_venues()
        return

    # Run full pipeline
    asyncio.run(run_full_pipeline(
        geocode=args.geocode,
        google_geocode=args.geocode_google,
    ))

    if args.export:
        export_venues()


if __name__ == "__main__":
    main()
