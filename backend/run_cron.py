"""Render cron job entry point — calls /run-scheduled on the web service."""
import sys
import httpx

API_URL = "https://job-gap-analyzer-api.onrender.com/run-scheduled"

try:
    r = httpx.post(API_URL, timeout=300)
    print(r.status_code, r.text)
    sys.exit(0 if r.is_success else 1)
except Exception as e:
    print("Error:", e)
    sys.exit(1)
