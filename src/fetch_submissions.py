#fetch_submissions.py fetches APLD's submission history from SEC EDGAR and caches it locally.
import json
import logging
import os
import sys
from pathlib import Path

import requests


#  Logging Setup
# contains logging it has levels, timestamps, and can
# be redirected to files or monitoring systems without code changes.
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


# Configuration 
# Read from environment with a fallback. This lets CI/CD inject values
# without touching source code.
CIK = "0001144879"
SUBMISSIONS_URL = f"https://data.sec.gov/submissions/CIK{CIK}.json"

# CRITICAL: The SEC requires User-Agent. Fail fast if missing.
USER_AGENT = os.environ.get("SEC_USER_AGENT", "").strip()
if not USER_AGENT:
    # Fallback for local development only — not for CI.
    USER_AGENT = "Mide-project  adegboyeayomide822@gmail.com"
    logger.warning("SEC_USER_AGENT not set in environment, using fallback.")

CACHE_DIR = Path("cache") / CIK
CACHE_FILE = CACHE_DIR / "submissions.json"

# Network resilience: timeout prevents infinite hangs.
REQUEST_TIMEOUT = 30  # seconds


#  Core Functions

def fetch_submissions(use_user_agent: bool = True) -> dict:
    """
    Fetch APLD's submission history from SEC EDGAR.
    
    Args:
        use_user_agent: If False, omits User-Agent to demonstrate SEC rejection.
    
    Raises:
        requests.HTTPError: On 4xx/5xx responses.
        requests.Timeout: If the request exceeds REQUEST_TIMEOUT.
    """
    headers = {}
    if use_user_agent:
        headers["User-Agent"] = USER_AGENT
        logger.info("Fetching submissions for CIK %s with UA: %s", CIK, USER_AGENT.split()[0])
    else:
        logger.warning("Sending request WITHOUT User-Agent (expected 403)")
    
    try:
        response = requests.get(
            SUBMISSIONS_URL,
            headers=headers,
            timeout=REQUEST_TIMEOUT,
        )
        response.raise_for_status()
    except requests.Timeout:
        logger.error("Request timed out after %ds", REQUEST_TIMEOUT)
        raise
    
    return response.json()


def save_to_cache(data: dict, path: Path) -> None:
    """Atomically save JSON to cache to avoid corruption on interrupt."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(".tmp")
    
    with open(temp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    
    # Atomic rename prevents half-written files if script is killed mid-write.
    temp_path.replace(path)
    logger.info("Cached to: %s", path)


def load_from_cache(path: Path) -> dict | None:
    """Load JSON from cache if present and valid."""
    if not path.exists():
        return None
    
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        logger.info("Loaded from cache: %s", path)
        return data
    except json.JSONDecodeError:
        logger.warning("Cache file corrupted, will re-fetch: %s", path)
        return None


def parse_filings(data: dict) -> list[dict]:
    """Extract 10-K and 10-Q filings from submissions data."""
    recent = data.get("filings", {}).get("recent", {})
    forms = recent.get("form", [])
    dates = recent.get("filingDate", [])
    accession_numbers = recent.get("accessionNumber", [])
    
    filings = []
    for form, date, acc in zip(forms, dates, accession_numbers):
        if form in ("10-K", "10-Q"):
            filings.append({
                "form": form,
                "filingDate": date,
                "accessionNumber": acc,
            })
    
    return filings


# Main 

def main() -> int:
    force_refresh = "--refresh" in sys.argv
    
    data = None if force_refresh else load_from_cache(CACHE_FILE)
    
    if data is None:
        try:
            data = fetch_submissions(use_user_agent=True)
            save_to_cache(data, CACHE_FILE)
        except requests.HTTPError as e:
            logger.error("HTTP error: %s", e)
            return 1
        except requests.RequestException as e:
            logger.error("Network error: %s", e)
            return 1
    
    # Output
    print(f"\nCompany: {data.get('name', 'N/A')}")
    print(f"CIK:     {data.get('cik', 'N/A')}")
    
    filings = parse_filings(data)
    print(f"\n10-K / 10-Q filings: {len(filings)}")
    print(f"{'Form':<8} {'Date':<12} {'Accession Number'}")
    print("-" * 50)
    for f in filings:
        print(f"{f['form']:<8} {f['filingDate']:<12} {f['accessionNumber']}")
    
    return 0


if __name__ == "__main__":
    sys.exit(main())