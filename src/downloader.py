"""SECDownloader: fetches XBRL filings from SEC EDGAR with rate limiting."""

import logging
import random
import time
from pathlib import Path
from typing import Optional

import requests

from rate_limiter import RateLimiter

logger = logging.getLogger(__name__)

SEC_ARCHIVE_URL = "https://www.sec.gov/Archives/edgar/data/{cik}/{accession_clean}/{filename}"
_RETRYABLE_STATUS_CODES = {429, 502, 503, 504}
_MAX_RETRIES = 3
_REQUEST_TIMEOUT = 30


class SECDownloader:
    def __init__(
        self,
        cik: str,
        cache_dir: Path,
        user_agent: str,
        rate_limiter: Optional[RateLimiter] = None,
    ):
        self.cik = cik
        self.cik_stripped = cik.lstrip("0") or "0"
        self.cache_dir = Path(cache_dir)
        self.rate_limiter = rate_limiter or RateLimiter()
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": user_agent})

    def _request(self, url: str, context: str = "") -> requests.Response:
        for attempt in range(_MAX_RETRIES + 1):
            self.rate_limiter.acquire(context=context)
            try:
                response = self.session.get(url, timeout=_REQUEST_TIMEOUT)
                if response.status_code == 200:
                    logger.info("GET %s", url)
                    return response
                if response.status_code in _RETRYABLE_STATUS_CODES and attempt < _MAX_RETRIES:
                    sleep_time = (2 ** attempt) + random.uniform(0, 1)
                    logger.warning("HTTP %d on %s, retrying in %.1fs...", response.status_code, url, sleep_time)
                    time.sleep(sleep_time)
                    continue
                response.raise_for_status()
            except requests.Timeout:
                if attempt < _MAX_RETRIES:
                    sleep_time = (2 ** attempt) + random.uniform(0, 1)
                    logger.warning("Timeout on %s, retrying in %.1fs...", url, sleep_time)
                    time.sleep(sleep_time)
                    continue
                raise

        raise requests.HTTPError(f"Max retries exceeded for {url}")

    def get_filing_index(self, accession: str) -> list[dict]:
        accession_clean = accession.replace("-", "")
        url = SEC_ARCHIVE_URL.format(
            cik=self.cik_stripped,
            accession_clean=accession_clean,
            filename="index.json",
        )

        data = self._request(url, context=f"index:{accession}").json()

        items: list = []
        if isinstance(data, dict):
            directory = data.get("directory", {})
            if isinstance(directory, dict):
                items = directory.get("item", [])
            elif isinstance(directory, list):
                items = directory
        elif isinstance(data, list):
            items = data

        normalized = []
        for item in items:
            if isinstance(item, dict):
                raw_size = item.get("size")
                size = raw_size if raw_size and str(raw_size).strip() else None
                normalized.append({
                    "name": item.get("name", ""),
                    "size": size,
                    "last_modified": item.get("last-modified"),
                })
            elif isinstance(item, str):
                normalized.append({"name": item, "size": None, "last_modified": None})

        return normalized

    @staticmethod
    def classify_xbrl_file(filename: str) -> Optional[str]:
        lower = filename.lower()
        if lower.endswith(".xsd"):
            return "schema"
        if lower.endswith("_cal.xml"):
            return "calculation"
        if lower.endswith("_pre.xml"):
            return "presentation"
        if lower.endswith("_def.xml"):
            return "definition"
        if lower.endswith("_lab.xml"):
            return "label"
        if lower.endswith(".xml"):
            return "instance"
        return None

    def download_file(
        self,
        accession: str,
        filename: str,
        expected_size: Optional[int] = None,
    ) -> Optional[Path]:
        accession_clean = accession.replace("-", "")
        url = SEC_ARCHIVE_URL.format(
            cik=self.cik_stripped,
            accession_clean=accession_clean,
            filename=filename,
        )

        filing_dir = self.cache_dir / self.cik / accession
        filing_dir.mkdir(parents=True, exist_ok=True)
        local_path = filing_dir / filename

        if local_path.exists():
            if expected_size is None:
                logger.debug("Cache hit (no size check): %s", local_path)
                return local_path
            actual_size = local_path.stat().st_size
            if actual_size == expected_size:
                logger.debug("Cache hit (size %d): %s", actual_size, local_path)
                return local_path
            logger.warning(
                "Cache size mismatch for %s (expected %d, got %d), re-downloading",
                filename, expected_size, actual_size
            )

        try:
            response = self._request(url, context=f"file:{accession}/{filename}")
        except requests.RequestException:
            logger.exception("Failed to download %s", url)
            raise

        temp_path = local_path.with_suffix(".tmp")
        try:
            temp_path.write_bytes(response.content)
            temp_path.replace(local_path)
        except OSError:
            if temp_path.exists():
                temp_path.unlink()
            raise

        logger.info("Downloaded: %s (%d bytes)", local_path, len(response.content))
        return local_path

    def download_filing_xbrl(self, accession: str) -> dict[str, Path]:
        items = self.get_filing_index(accession)
        downloaded: dict[str, Path] = {}

        for item in items:
            name = item["name"]
            size_str = item["size"]
            size = int(size_str) if size_str else None

            file_type = self.classify_xbrl_file(name)
            if file_type is None:
                continue

            try:
                path = self.download_file(accession, name, expected_size=size)
                if path:
                    downloaded[file_type] = path
            except requests.RequestException:
                logger.error("Skipping %s/%s due to download failure", accession, name)

        if not downloaded:
            logger.warning(
                "No XBRL files found for filing %s (possibly pre-XBRL era)",
                accession
            )

        return downloaded