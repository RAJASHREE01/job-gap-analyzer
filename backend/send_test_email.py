"""Run once to verify Resend is wired up: python send_test_email.py"""
import os, httpx
from dotenv import load_dotenv
from datetime import datetime

load_dotenv()

api_key = os.environ.get("RESEND_API_KEY")
email_from = os.environ.get("EMAIL_FROM", "onboarding@resend.dev")
email_to = input("Send test email to (your address): ").strip()

html = f"""
<!DOCTYPE html><html><body style="font-family:Arial,sans-serif;padding:24px;background:#f3f4f6;">
<div style="max-width:600px;margin:0 auto;background:#fff;border-radius:10px;overflow:hidden;border:1px solid #e5e7eb;">
  <div style="background:#4f46e5;padding:24px;">
    <h1 style="margin:0;color:#fff;font-size:20px;">⚡ Job Gap Analyzer — Test Email</h1>
    <p style="margin:8px 0 0;color:rgba(255,255,255,.8);font-size:13px;">Sent at {datetime.now().strftime('%b %d, %Y %H:%M')}</p>
  </div>
  <div style="padding:24px;">
    <p style="color:#374151;font-size:15px;">
      ✅ Your email alerts are configured correctly.<br><br>
      Every 6 hours the app will fetch the latest jobs from
      <strong>Bangalore, Hyderabad, Pune, Chennai and Mumbai</strong>,
      run AI gap analysis on the top 20 matches, and send results like this to your inbox.
    </p>
    <div style="margin-top:20px;padding:16px;background:#f0fdf4;border:1px solid #86efac;border-radius:8px;">
      <p style="margin:0;font-size:13px;color:#166534;">
        <strong>From:</strong> {email_from}<br>
        <strong>To:</strong> {email_to}<br>
        <strong>API key set:</strong> {"Yes ✓" if api_key else "NO — check .env"}
      </p>
    </div>
  </div>
</div></body></html>
"""

r = httpx.post(
    "https://api.resend.com/emails",
    headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
    json={"from": email_from, "to": [email_to], "subject": "✅ Job Gap Analyzer — test email", "html": html},
    timeout=15,
)

if r.status_code in (200, 201):
    print(f"OK - Email sent! Check {email_to}")
else:
    print(f"FAILED ({r.status_code}): {r.text}")
