"""Global configuration constants for SEC schema tracking."""

import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CACHE_DIR = PROJECT_ROOT / "cache"
SCHEMA_DIR = PROJECT_ROOT / "schema_versions"
CIK = "0001144879"
USER_AGENT = os.environ.get("SEC_USER_AGENT", "").strip() or "Mide-project adegboyeayomide822@gmail.com"
