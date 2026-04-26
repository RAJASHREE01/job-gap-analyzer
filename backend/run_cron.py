"""Render cron job entry point — calls /run-scheduled on the web service."""
import sys
import time
import httpx

API_URL = "https://job-gap-analyzer-api.onrender.com/run-scheduled"
RETRIES = 5
RETRY_DELAY = 40  # seconds — enough for Render free tier cold start

for attempt in range(1, RETRIES + 1):
    try:
        r = httpx.post(API_URL, timeout=60)
        print(f"Attempt {attempt}: {r.status_code} {r.text}")
        if r.is_success:
            sys.exit(0)
        print(f"Non-2xx response, retrying in {RETRY_DELAY}s...")
    except Exception as e:
        print(f"Attempt {attempt} error: {e}, retrying in {RETRY_DELAY}s...")
    if attempt < RETRIES:
        time.sleep(RETRY_DELAY)

print("All attempts failed.")
sys.exit(1)
