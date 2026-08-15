import sys
sys.path.insert(0, "src")
from fetch_submissions import fetch_submissions

try:
    fetch_submissions(use_user_agent=False)
    print("UNEXPECTED: request succeeded without User-Agent")
except Exception as e:
    print(f"EXPECTED FAILURE: {type(e).__name__}: {e}")