
"""
download_filings.py

Orchestrator: loads APLD's filing history from cache,
then downloads XBRL taxonomy files for each filing with full
rate-limit compliance and cache reuse.
"""

import json
import logging
import sys
from pathlib import Path

from downloader import SECDownloader
from rate_limiter import RateLimiter

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)

CIK = "0001144879"
USER_AGENT = "Mide-project adegboyeayomide822@gmail.com"
CACHE_DIR = Path("cache")
SUBMISSIONS_FILE = CACHE_DIR / CIK / "submissions.json"


def load_filings() -> list[dict]:
    """Load 10-K/10-Q filings from the local cache."""
    if not SUBMISSIONS_FILE.exists():
        logging.error("Submissions cache not found. Run fetch_submissions.py first.")
        sys.exit(1)

    with open(SUBMISSIONS_FILE, encoding="utf-8") as f:
        data = json.load(f)

    recent = data.get("filings", {}).get("recent", {})
    forms = recent.get("form", [])
    dates = recent.get("filingDate", [])
    accession_numbers = recent.get("accessionNumber", [])

    filings = []
    for form, date, acc in zip(forms, dates, accession_numbers):
        if form in ("10-K", "10-Q"):
            filings.append({
                "form": form,
                "date": date,
                "accession": acc,
            })

    return filings


def main() -> int:
    filings = load_filings()
    logging.info("Found %d 10-K/10-Q filings in history", len(filings))

    limiter = RateLimiter(max_requests=10, window_seconds=1.0)
    downloader = SECDownloader(CIK, CACHE_DIR, USER_AGENT, limiter)

    
    target_filings = filings[:4]
    success_count = 0

    for filing in target_filings:
        accession = filing["accession"]
        print(f"\n{'='*60}")
        print(f"Filing: {accession} | {filing['form']} | {filing['date']}")
        print(f"{'='*60}")

        try:
            files = downloader.download_filing_xbrl(accession)
            if files:
                success_count += 1
                print(f"Downloaded {len(files)} XBRL files:")
                for file_type, path in sorted(files.items()):
                    size = path.stat().st_size
                    print(f"  {file_type:<12} {path.name:<40} {size:>10,} bytes")
            else:
                print("  (No XBRL files — possibly pre-XBRL filing)")
        except Exception:
            logging.exception("Failed to process filing %s", accession)
            print("  ERROR: See log for details")

    print(f"\n{'='*60}")
    print(f"SUMMARY: {success_count}/{len(target_filings)} filings processed")
    print(f"Cache location: {CACHE_DIR / CIK}")
    print(f"Rate limiter: {limiter.get_current_count()} requests in current window")
    print(f"{'='*60}")
    return 0


if __name__ == "__main__":
    sys.exit(main())