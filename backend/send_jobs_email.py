"""Send a real job analysis email right now: python send_jobs_email.py"""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))

from dotenv import load_dotenv
load_dotenv()

from main import resolve_keywords, fetch_jobs_multi_city, analyze_job, send_email, _find_linkedin_url

USER_INPUT = (
    "analytics engineer, data engineer, product data analyst, "
    "product data engineer, data products, fintech"
)

RESUME = (
    "5 years experience in data analytics and engineering. "
    "Proficient in SQL, Python, dbt, Spark, Airflow, and cloud data warehouses "
    "(BigQuery, Snowflake, Redshift). Built end-to-end data pipelines and "
    "dashboards for fintech and e-commerce products. Strong in stakeholder "
    "reporting, A/B testing, product metrics, and data modeling. "
    "Worked closely with product and engineering teams on data platform initiatives."
)

RECIPIENT = "chartacodex@gmail.com"

print(f"Resolving keywords from: '{USER_INPUT}'")
keywords = resolve_keywords(USER_INPUT)
print(f"Searching for: {keywords}")

print(f"\nFetching product-company jobs across Bangalore, Hyderabad, Pune, Chennai, Mumbai...")
jobs_raw = fetch_jobs_multi_city(keywords)
print(f"Found {len(jobs_raw)} product-company jobs after filtering. Analyzing...\n")

results = []
for i, job in enumerate(jobs_raw, 1):
    title   = job.get("title", "?")
    company = job.get("company", {}).get("display_name", "?")
    city    = job.get("location", {}).get("display_name", "?")
    print(f"  [{i}/{len(jobs_raw)}] {title} @ {company} ({city})")
    analysis = analyze_job(RESUME, job)
    score = analysis.get("match_score", "?")
    print(f"           match: {score}%")
    results.append({
        "title": title, "company": company, "location": city,
        "url": _find_linkedin_url(title, company, city) or job.get("redirect_url", ""), "posted": job.get("created", ""),
        "analysis": analysis,
    })

keyword_label = ", ".join(keywords)
print(f"\nSending to {RECIPIENT}...")
send_email(results, RECIPIENT, keyword_label)
print("Done — check your inbox.")
