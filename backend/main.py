import asyncio
import io
import json
import logging
import os
import re
import time
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from pathlib import Path

import httpx
import pytz
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from dotenv import load_dotenv
from fastapi import FastAPI, File, Header, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

load_dotenv()
logger = logging.getLogger("uvicorn.error")

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
MODEL = "openai/gpt-oss-120b:free"
CITIES      = ["Bangalore", "Hyderabad", "Pune", "Chennai", "Mumbai"]
SCHED_CITIES = ["Bangalore", "Hyderabad", "Pune", "Chennai"]   # 4 cities for scheduled runs
MAX_KEYWORDS = 2   # cap keeps Adzuna calls at 2×4=8 per run → 250 calls lasts >30 days
SCHEDULE_FILE = Path(os.environ.get("SCHEDULE_FILE_PATH", str(Path(__file__).parent / "schedule_config.json")))

# Companies/patterns to exclude (IT services / staffing / non-product)
SERVICE_PATTERNS = [
    "tcs", "tata consultancy", "infosys", "wipro", "hcl tech", "hcltech",
    "cognizant", "capgemini", "accenture", "tech mahindra", "techmahindra",
    "mphasis", "hexaware", "mindtree", "ltimindtree", "l&t infotech",
    "persistent systems", "kpit", "cyient", "zensar", "birlasoft", "coforge",
    "stefanini", "aditi tech", "cerebra it", "dxc technology", "ntt data",
    "ntt ltd", "ntt america", "virtusa", "syntel", "mastech", "niit tech",
    "happiest minds", "igate", "patni", "wpp", "haworth", "metro global solution",
    "scout incorporation", "staffing", "manpower", "recruitment", "outsourcing",
    "it services", "consulting pvt", "solutions pvt", "bechtel", "wsp usa",
    "burns & mcdonnell", "mondelez",
    "pricewaterhousecoopers", "pwc", "deloitte", "ernst & young", "kpmg",
    "subramaniam", "hemamalini",
]

# Title must match at least one of these exact role phrases
ROLE_PATTERNS = [
    "data engineer",
    "analytics engineer",
    "data analyst",
    "data products",
    "product data",
    "bi engineer",
    "bi analyst",
    "business intelligence engineer",
    "business intelligence analyst",
    "data platform engineer",
    "data platform",
    "etl engineer",
    "data scientist",
    "ml engineer",
    "machine learning engineer",
]

# Title must NOT contain any of these regardless of above
TITLE_EXCLUDE = [
    "data center", "datacenter", "dcim",
    "electrical", "mechanical", "civil", "plumbing", "fire protection",
    "gis ", "network engineer", "field engineer",
    "security engineer", "configuration engineer",
    "infrastructure engineer", "l2 ", "l3 ",
    "marketing analyst", "ad monetization",
    "met scientist", "sap ", "product manager", "product owner",
    "supply chain", "procurement",
]

scheduler = BackgroundScheduler(daemon=True)


@asynccontextmanager
async def lifespan(app: FastAPI):
    ist = pytz.timezone("Asia/Kolkata")
    scheduler.add_job(
        run_scheduled_analysis,
        CronTrigger(hour=7, minute=0, timezone=ist),
        id="email_alerts",
        replace_existing=True,
        misfire_grace_time=6 * 3600,  # fire if woken up within 6h of scheduled time
    )
    scheduler.start()
    logger.info("Scheduler started -- email alerts fire at 07:00 IST daily")
    yield
    scheduler.shutdown(wait=False)


app = FastAPI(title="Job Gap Analyzer", lifespan=lifespan)

_ALLOWED_ORIGINS = [o.strip() for o in os.environ.get("ALLOWED_ORIGINS", "*").split(",")]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_ALLOWED_ORIGINS,
    allow_origin_regex=r"https://.*\.vercel\.app",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class AnalyzeRequest(BaseModel):
    resume: str
    keyword: str       # job title, designation, or full JD paste
    email: str = ""
    enable_alerts: bool = False


class AnalyzeUrlRequest(BaseModel):
    resume: str
    url: str


# ── LLM ──────────────────────────────────────────────────────────────────────

def _llm(prompt: str, temperature: float = 0.3, timeout: int = 60) -> str | None:
    try:
        r = httpx.post(
            OPENROUTER_URL,
            headers={
                "Authorization": f"Bearer {os.environ.get('OPENROUTER_API_KEY')}",
                "Content-Type": "application/json",
            },
            json={"model": MODEL, "messages": [{"role": "user", "content": prompt}], "temperature": temperature},
            timeout=timeout,
        )
        body = r.json()
        if r.status_code != 200 or "error" in body:
            logger.error("LLM error: %s", body.get("error", r.status_code))
            return None
        return body["choices"][0]["message"]["content"] or ""
    except Exception as exc:
        logger.error("LLM call failed: %s", exc)
        return None


def resolve_keywords(text: str) -> list[str]:
    """
    Turn any user input — short role name, comma list, or long description —
    into 2-3 concrete Adzuna search terms focused on product/fintech data roles.
    """
    prompt = (
        "The user is searching for data/analytics/engineering jobs at product-based "
        "or fintech companies in India. Based on their input below, return 2-3 short "
        "job search keywords suitable for Adzuna (each 2-4 words). "
        "Focus on roles like: data engineer, analytics engineer, data analyst, "
        "data products, product data analyst, data platform engineer. "
        "Return ONLY a JSON array of 3-4 strings, no explanation.\n"
        f'Input: "{text[:600]}"\n'
        'Example: ["data engineer", "analytics engineer", "data products", "data analyst"]'
    )
    result = _llm(prompt, temperature=0.1, timeout=30)
    if result:
        try:
            parsed = json.loads(strip_code_fences(result))
            if isinstance(parsed, list) and parsed:
                return [str(k).strip()[:60] for k in parsed[:4]]
        except Exception:
            pass
    # Fallback: use first 4 words as single keyword
    return [" ".join(text.split()[:4])]


def _is_service_company(job: dict) -> bool:
    name = job.get("company", {}).get("display_name", "").lower()
    return any(p in name for p in SERVICE_PATTERNS)


def _is_relevant_role(job: dict) -> bool:
    title = job.get("title", "").lower()
    if any(excl in title for excl in TITLE_EXCLUDE):
        return False
    return any(role in title for role in ROLE_PATTERNS)


def strip_code_fences(text: str) -> str:
    text = re.sub(r"^```json\s*", "", text.strip())
    text = re.sub(r"^```\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    return text.strip()


# ── Adzuna ───────────────────────────────────────────────────────────────────

def fetch_jobs_multi_city(keywords: list[str] | str, hours_back: int | None = None, _cities: list[str] | None = None) -> list[dict]:
    """
    Search each keyword across cities, deduplicate, filter out service/staffing
    companies, sort by recency, return top 20 product-company results.
    _cities overrides the default CITIES list (used by scheduler to cap API calls).
    """
    if isinstance(keywords, str):
        keywords = [keywords]

    app_id = os.environ.get("ADZUNA_APP_ID")
    app_key = os.environ.get("ADZUNA_APP_KEY")
    if not app_id or not app_key:
        raise ValueError("ADZUNA_APP_ID and ADZUNA_APP_KEY must be set in .env")

    seen: set[str] = set()
    merged: list[dict] = []

    cities = _cities if _cities else CITIES
    for keyword in keywords:
        for city in cities:
            try:
                r = httpx.get(
                    "https://api.adzuna.com/v1/api/jobs/in/search/1",
                    params={
                        "app_id": app_id,
                        "app_key": app_key,
                        "results_per_page": 8,
                        "what": keyword,
                        "where": city,
                        "sort_by": "date",
                        "max_days_old": 7,
                    },
                    headers={"Content-Type": "application/json"},
                    timeout=15,
                )
                if r.status_code == 200:
                    for job in r.json().get("results", []):
                        jid = job.get("id", "")
                        if jid and jid not in seen and not _is_service_company(job) and _is_relevant_role(job):
                            seen.add(jid)
                            merged.append(job)
            except Exception as exc:
                logger.warning("Adzuna '%s'/'%s' failed: %s", keyword, city, exc)

    merged.sort(key=lambda j: j.get("created", ""), reverse=True)

    if hours_back is not None:
        cutoff = datetime.now(timezone.utc) - timedelta(hours=hours_back)
        recent = [j for j in merged if _posted_after(j, cutoff)]
        return recent[:20] if recent else merged[:5]

    return merged[:20]


# ── Job URL scraping ─────────────────────────────────────────────────────────

class _TextExtractor(HTMLParser):
    """Strip HTML tags; skip script/style/nav blocks."""
    def __init__(self):
        super().__init__()
        self._parts: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "nav", "footer", "header"):
            self._skip += 1
        if tag in ("p", "li", "br", "h1", "h2", "h3", "h4", "h5", "tr", "div"):
            self._parts.append("\n")

    def handle_endtag(self, tag):
        if tag in ("script", "style", "nav", "footer", "header"):
            self._skip = max(0, self._skip - 1)

    def handle_data(self, data):
        if not self._skip:
            self._parts.append(data)

    def get_text(self) -> str:
        text = "".join(self._parts)
        return re.sub(r"\n{3,}", "\n\n", text).strip()


def _html_to_text(html: str) -> str:
    p = _TextExtractor()
    p.feed(html)
    return p.get_text()


def _extract_linkedin_job_id(url: str) -> str | None:
    m = re.search(r"/jobs/view/[^/?#]*?(\d{8,})", url)
    return m.group(1) if m else None


def _fetch_linkedin_job(job_id: str) -> dict:
    r = httpx.get(
        f"https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/{job_id}",
        headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0 Safari/537.36"},
        timeout=15,
    )
    if r.status_code != 200:
        return {}
    html = r.text
    title_m   = re.search(r'class="top-card-layout__title[^"]*"[^>]*>\s*([^<]+)<', html)
    company_m = re.search(r'class="topcard__org-name-link[^"]*"[^>]*>\s*([^<]+)<', html)
    desc_m    = re.search(r'description__text[^>]*>(.*?)(?=</section>)', html, re.DOTALL)
    return {
        "title":       (title_m.group(1).strip()   if title_m   else "Job Listing"),
        "company":     {"display_name": company_m.group(1).strip() if company_m else "Company"},
        "description": (_html_to_text(desc_m.group(1))[:5000]    if desc_m    else ""),
        "url":         f"https://www.linkedin.com/jobs/view/{job_id}",
    }


def _fetch_generic_job(url: str) -> dict:
    r = httpx.get(
        url,
        headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0 Safari/537.36"},
        timeout=15,
        follow_redirects=True,
    )
    if r.status_code != 200:
        return {}
    text = _html_to_text(r.text)
    # Truncate to keep prompt manageable
    return {
        "title":       "Job Listing",
        "company":     {"display_name": "Company"},
        "description": text[:5000],
        "url":         str(r.url),
    }


def fetch_job_from_url(url: str) -> dict:
    job_id = _extract_linkedin_job_id(url)
    if job_id:
        return _fetch_linkedin_job(job_id)
    return _fetch_generic_job(url)


def analyze_job_detailed(resume: str, job: dict) -> dict:
    """Enhanced analysis with action_plan for how to reach 100% match."""
    title       = job.get("title", "Unknown Role")
    company     = job.get("company", {}).get("display_name", "Unknown Company")
    description = job.get("description", "")

    prompt = (
        "You are a career coach helping a candidate maximize their match with a specific job.\n\n"
        f"Job Title: {title}\n"
        f"Company: {company}\n"
        f"Job Description:\n{description}\n\n"
        f"Candidate Resume:\n{resume}\n\n"
        "Analyze deeply and return ONLY valid JSON with exactly these keys:\n"
        '  "match_score": integer 0-100 (honest current fit)\n'
        '  "gaps": array of exactly 3 strings (specific skills/tools the JD needs that the resume lacks)\n'
        '  "bullet_suggestions": array of exactly 3 strings (specific rewritten resume bullets tailored to this JD)\n'
        '  "cover_opener": single string (compelling one-sentence cover letter opener for this role)\n'
        '  "action_plan": array of exactly 5 strings (specific, ordered steps to push the match score to 100%; '
        'each step must be concrete and actionable, e.g. "Add a project showcasing X" or '
        '"Rewrite your Y section to highlight Z metric from the JD")\n\n'
        'Example: {"match_score": 65, "gaps": ["a","b","c"], "bullet_suggestions": ["x","y","z"], '
        '"cover_opener": "...", "action_plan": ["step1","step2","step3","step4","step5"]}'
    )

    for attempt in range(3):
        try:
            r = httpx.post(
                OPENROUTER_URL,
                headers={
                    "Authorization": f"Bearer {os.environ.get('OPENROUTER_API_KEY')}",
                    "Content-Type": "application/json",
                },
                json={"model": MODEL, "messages": [{"role": "user", "content": prompt}], "temperature": 0.3},
                timeout=90,
            )
            body = r.json()
            if r.status_code == 429 or "error" in body:
                time.sleep(5 * (attempt + 1))
                continue
            r.raise_for_status()
            raw  = body["choices"][0]["message"]["content"] or ""
            data = json.loads(strip_code_fences(raw))
            return {
                "match_score":        int(data.get("match_score", 0)),
                "gaps":               list(data.get("gaps", []))[:3],
                "bullet_suggestions": list(data.get("bullet_suggestions", []))[:3],
                "cover_opener":       str(data.get("cover_opener", "")),
                "action_plan":        list(data.get("action_plan", []))[:5],
                "error": False,
            }
        except Exception as exc:
            logger.error("analyze_job_detailed attempt %d: %s", attempt + 1, exc)
            if attempt < 2:
                time.sleep(5)

    return {"match_score": None, "gaps": [], "bullet_suggestions": [],
            "cover_opener": "", "action_plan": [], "error": True}


def _clean_company(name: str) -> str:
    """Normalize Adzuna company name for LinkedIn search (strip legal suffixes, location codes)."""
    name = re.split(r"\s*[-–—]\s*", name)[0].strip()
    name = re.sub(
        r"\b(bank|pvt|private|ltd|limited|llc|inc|corp|corporation|holdings|"
        r"technologies|solutions|services|consulting|india|global|international)\b",
        "", name, flags=re.IGNORECASE,
    )
    name = re.sub(r"[,.]", "", name)
    return re.sub(r"\s+", " ", name).strip().title()


def _find_linkedin_url(title: str, company: str, city: str) -> str:
    """Search LinkedIn's free guest API and return an exact jobs/view/{id} URL."""
    try:
        city_short = city.split(",")[0].strip()
        r = httpx.get(
            "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search",
            params={"keywords": f"{title} {_clean_company(company)}", "location": f"{city_short}, India", "start": "0"},
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0 Safari/537.36"},
            timeout=10,
        )
        if r.status_code == 200:
            ids = re.findall(r"jobPosting:(\d+)", r.text)
            if ids:
                return f"https://www.linkedin.com/jobs/view/{ids[0]}"
    except Exception as exc:
        logger.debug("LinkedIn URL lookup failed for '%s': %s", title, exc)
    return ""


def _posted_after(job: dict, cutoff: datetime) -> bool:
    created = job.get("created", "")
    if not created:
        return True
    try:
        return datetime.fromisoformat(created.replace("Z", "+00:00")) >= cutoff
    except Exception:
        return True


# ── Analysis ─────────────────────────────────────────────────────────────────

def analyze_job(resume: str, job: dict) -> dict:
    title = job.get("title", "Unknown Role")
    company = job.get("company", {}).get("display_name", "Unknown Company")
    description = job.get("description", "")

    prompt = (
        "You are a career advisor. Analyze the job description against the resume below.\n\n"
        f"Job Title: {title}\n"
        f"Company: {company}\n"
        f"Job Description:\n{description}\n\n"
        f"Resume:\n{resume}\n\n"
        'Return ONLY valid JSON with exactly these keys:\n'
        '  "match_score": integer 0-100\n'
        '  "gaps": array of exactly 3 strings (skills the JD needs that the resume lacks)\n'
        '  "bullet_suggestions": array of exactly 2 strings (rewritten resume bullets for this JD)\n'
        '  "cover_opener": single string (one-line cover letter opener)\n\n'
        'Example: {"match_score": 72, "gaps": ["a","b","c"], "bullet_suggestions": ["x","y"], "cover_opener": "z"}'
    )

    for attempt in range(3):
        try:
            r = httpx.post(
                OPENROUTER_URL,
                headers={
                    "Authorization": f"Bearer {os.environ.get('OPENROUTER_API_KEY')}",
                    "Content-Type": "application/json",
                },
                json={"model": MODEL, "messages": [{"role": "user", "content": prompt}], "temperature": 0.3},
                timeout=60,
            )
            body = r.json()
            if r.status_code == 429 or "error" in body:
                wait = 5 * (attempt + 1)
                logger.warning("Rate limited for '%s', retrying in %ds", title, wait)
                time.sleep(wait)
                continue
            r.raise_for_status()
            raw = body["choices"][0]["message"]["content"] or ""
            data = json.loads(strip_code_fences(raw))
            return {
                "match_score": int(data.get("match_score", 0)),
                "gaps": list(data.get("gaps", []))[:3],
                "bullet_suggestions": list(data.get("bullet_suggestions", []))[:2],
                "cover_opener": str(data.get("cover_opener", "Analysis unavailable")),
                "error": False,
            }
        except Exception as exc:
            logger.error("analyze_job attempt %d for '%s': %s", attempt + 1, title, exc)
            if attempt < 2:
                time.sleep(5)

    return {"match_score": None, "gaps": [], "bullet_suggestions": [],
            "cover_opener": "Analysis unavailable", "error": True}


def _format_result(resume: str, job: dict) -> dict:
    title    = job.get("title", "Unknown Role")
    company  = job.get("company", {}).get("display_name", "Unknown")
    location = job.get("location", {}).get("display_name", "India")
    url = _find_linkedin_url(title, company, location) or job.get("redirect_url", "")
    return {
        "title":    title,
        "company":  company,
        "location": location,
        "url":      url,
        "posted":   job.get("created", ""),
        "analysis": analyze_job(resume, job),
    }


# ── Email ─────────────────────────────────────────────────────────────────────

def _score_color(score) -> str:
    if score is None: return "#6b7280"
    if score >= 70:   return "#16a34a"
    if score >= 40:   return "#ca8a04"
    return "#dc2626"


def build_email_html(jobs: list, keyword: str) -> str:
    date_str = datetime.now().strftime("%b %d, %Y %H:%M")
    blocks = ""
    for job in jobs:
        a = job["analysis"]
        score = a.get("match_score")
        color = _score_color(score)
        score_label = "N/A" if score is None else f"{score}%"
        gaps_li    = "".join(f"<li style='margin:4px 0'>{g}</li>" for g in a.get("gaps", []))
        bullets_li = "".join(f"<li style='margin:4px 0;color:#4338ca'>{b}</li>" for b in a.get("bullet_suggestions", []))
        view = f'<a href="{job["url"]}" style="color:#4f46e5;font-weight:600;">Apply Now &#8599;</a>' if job.get("url") else ""
        blocks += f"""
        <div style="padding:20px;border-bottom:1px solid #e5e7eb;">
          <table width="100%" cellpadding="0" cellspacing="0"><tr>
            <td>
              <h2 style="margin:0 0 4px;font-size:16px;color:#111827;">{job['title']}</h2>
              <p style="margin:0;color:#6b7280;font-size:12px;">{job['company']} &middot; {job['location']}</p>
            </td>
            <td align="right" valign="top">
              <span style="background:{color};color:#fff;padding:4px 12px;border-radius:20px;font-weight:700;font-size:14px;">{score_label}</span>
            </td>
          </tr></table>
          <p style="margin:12px 0 3px;font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:.06em;color:#9ca3af;">Skill Gaps</p>
          <ul style="margin:0;padding-left:16px;font-size:13px;color:#374151;">{gaps_li}</ul>
          <p style="margin:12px 0 3px;font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:.06em;color:#9ca3af;">Resume Suggestions</p>
          <ul style="margin:0;padding-left:16px;font-size:13px;">{bullets_li}</ul>
          <p style="margin:12px 0 3px;font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:.06em;color:#9ca3af;">Cover Opener</p>
          <p style="margin:0;padding-left:10px;border-left:3px solid #4f46e5;color:#4338ca;font-style:italic;font-size:13px;">{a.get('cover_opener','')}</p>
          <p style="margin:10px 0 0;">{view}</p>
        </div>"""

    return f"""<!DOCTYPE html><html><body style="margin:0;padding:20px;background:#f3f4f6;font-family:Arial,sans-serif;">
<div style="max-width:660px;margin:0 auto;background:#fff;border-radius:10px;overflow:hidden;border:1px solid #e5e7eb;">
  <div style="background:#4f46e5;padding:24px 20px;">
    <h1 style="margin:0;color:#fff;font-size:19px;">Job Gap Analysis</h1>
    <p style="margin:6px 0 0;color:rgba(255,255,255,.8);font-size:12px;">
      <strong>{keyword}</strong> &middot; Bangalore, Hyderabad, Pune, Chennai &middot; {date_str}
    </p>
  </div>
  {blocks}
  <div style="padding:12px;text-align:center;background:#f9fafb;">
    <p style="margin:0;font-size:11px;color:#9ca3af;">Job Gap Analyzer &middot; Sent every 6 hours</p>
  </div>
</div></body></html>"""


def send_email(jobs: list, recipient: str, keyword: str):
    api_key   = os.environ.get("RESEND_API_KEY")
    email_from = os.environ.get("EMAIL_FROM", "onboarding@resend.dev")
    if not api_key:
        logger.error("RESEND_API_KEY not set -- skipping email")
        return
    try:
        r = httpx.post(
            "https://api.resend.com/emails",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={
                "from": email_from,
                "to": [recipient],
                "subject": f"Job Alert: {keyword} | {datetime.now().strftime('%b %d %H:%M')}",
                "html": build_email_html(jobs, keyword),
            },
            timeout=15,
        )
        if r.status_code in (200, 201):
            logger.info("Email sent to %s (keyword: %s)", recipient, keyword)
        else:
            logger.error("Resend error %s: %s", r.status_code, r.text)
    except Exception as exc:
        logger.error("Failed to send email: %s", exc)


# ── Scheduler ────────────────────────────────────────────────────────────────

def run_scheduled_analysis():
    if not SCHEDULE_FILE.exists():
        return
    config = json.loads(SCHEDULE_FILE.read_text())
    if not config.get("enabled"):
        return

    logger.info("Scheduled run -- keyword: %s", config.get("keyword"))
    try:
        keywords = resolve_keywords(config["keyword"])[:MAX_KEYWORDS]
        jobs_raw = fetch_jobs_multi_city(keywords, hours_back=24, _cities=SCHED_CITIES)
        if not jobs_raw:
            logger.info("No new jobs in last 24h for '%s' -- skipping email", config.get("keyword"))
            return
        results = [_format_result(config["resume"], j) for j in jobs_raw]
        send_email(results, config["email"], ", ".join(keywords))
        config["last_sent"] = datetime.now().isoformat()
        SCHEDULE_FILE.write_text(json.dumps(config))
    except Exception as exc:
        logger.error("Scheduled analysis failed: %s", exc)


# ── Endpoints ────────────────────────────────────────────────────────────────

@app.get("/health")
def health():
    return {"status": "ok", "scheduler_running": scheduler.running}


@app.post("/run-scheduled")
async def trigger_scheduled(x_cron_secret: str = Header(default="")):
    expected = os.environ.get("CRON_SECRET", "")
    if expected and x_cron_secret != expected:
        raise HTTPException(status_code=403, detail="Forbidden")
    asyncio.create_task(asyncio.to_thread(run_scheduled_analysis))
    return {"status": "triggered"}


@app.post("/parse-resume")
async def parse_resume(file: UploadFile = File(...)):
    if not (file.filename or "").lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are supported.")
    content = await file.read()
    if len(content) > 5 * 1024 * 1024:  # 5 MB cap
        raise HTTPException(status_code=413, detail="PDF too large. Please upload a file under 5 MB.")
    try:
        import pypdf
        reader = pypdf.PdfReader(io.BytesIO(content))
        pages_text = []
        for page in reader.pages:
            t = page.extract_text()
            if t:
                pages_text.append(t)
        text = "\n".join(pages_text).strip()
        if not text:
            raise HTTPException(
                status_code=422,
                detail="No text could be extracted. Make sure the PDF is text-based, not a scanned image."
            )
        return {"text": text, "pages": len(reader.pages), "words": len(text.split())}
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("PDF parse failed: %s", exc)
        raise HTTPException(status_code=422, detail=f"PDF parsing failed: {exc}")


@app.get("/schedule")
def get_schedule():
    if not SCHEDULE_FILE.exists():
        return {"enabled": False, "email": None, "last_sent": None}
    c = json.loads(SCHEDULE_FILE.read_text())
    return {"enabled": c.get("enabled", False), "email": c.get("email"), "last_sent": c.get("last_sent")}


@app.delete("/schedule")
def disable_schedule():
    if SCHEDULE_FILE.exists():
        c = json.loads(SCHEDULE_FILE.read_text())
        c["enabled"] = False
        SCHEDULE_FILE.write_text(json.dumps(c))
    return {"status": "disabled"}


@app.post("/analyze")
async def analyze(request: AnalyzeRequest):
    if not request.resume.strip():
        raise HTTPException(status_code=400, detail="Resume text cannot be empty.")
    if not request.keyword.strip():
        raise HTTPException(status_code=400, detail="Job title or description cannot be empty.")

    async def generate():
        try:
            # Step 1: resolve to concrete search keywords (capped to stay within Adzuna free quota)
            keywords = (await asyncio.to_thread(resolve_keywords, request.keyword))[:MAX_KEYWORDS]
            keyword_display = ", ".join(keywords)
            yield f"data: {json.dumps({'type': 'keyword', 'keyword_used': keyword_display})}\n\n"

            # Always keep the schedule's resume fresh when user re-analyzes
            if SCHEDULE_FILE.exists():
                try:
                    cfg = json.loads(SCHEDULE_FILE.read_text())
                    if cfg.get("enabled"):
                        cfg["resume"]  = request.resume
                        cfg["keyword"] = request.keyword
                        SCHEDULE_FILE.write_text(json.dumps(cfg))
                except Exception:
                    pass

            # Step 2: fetch from all 5 cities across all resolved keywords
            try:
                jobs_raw = await asyncio.to_thread(fetch_jobs_multi_city, keywords, None, SCHED_CITIES)
            except ValueError as exc:
                yield f"data: {json.dumps({'type': 'error', 'message': str(exc)})}\n\n"
                return
            except httpx.HTTPError as exc:
                yield f"data: {json.dumps({'type': 'error', 'message': f'Adzuna error: {exc}'})}\n\n"
                return

            if not jobs_raw:
                no_jobs_msg = json.dumps({"type": "error", "message": f"No jobs found for '{keyword_display}' across the 5 cities."})
                yield f"data: {no_jobs_msg}\n\n"
                return

            yield f"data: {json.dumps({'type': 'total', 'count': len(jobs_raw)})}\n\n"

            # Persist email schedule if requested
            if request.enable_alerts and request.email:
                SCHEDULE_FILE.write_text(json.dumps({
                    "resume": request.resume,
                    "keyword": request.keyword,
                    "email": request.email,
                    "enabled": True,
                    "last_sent": None,
                }))

            # Step 3: analyze jobs 3 at a time, stream each card as it finishes
            sem = asyncio.Semaphore(3)
            queue: asyncio.Queue = asyncio.Queue()

            async def run_one(job: dict):
                async with sem:
                    try:
                        result = await asyncio.to_thread(_format_result, request.resume, job)
                    except Exception as exc:
                        logger.error("Job analysis failed: %s", exc)
                        result = {
                            "title": job.get("title", "Unknown"),
                            "company": job.get("company", {}).get("display_name", "Unknown"),
                            "location": job.get("location", {}).get("display_name", "India"),
                            "url": job.get("redirect_url", ""),
                            "posted": job.get("created", ""),
                            "analysis": {"match_score": None, "gaps": [], "bullet_suggestions": [],
                                         "cover_opener": "Analysis unavailable", "error": True},
                        }
                    await queue.put(result)

            tasks = [asyncio.create_task(run_one(j)) for j in jobs_raw]

            for _ in range(len(jobs_raw)):
                result = await queue.get()
                yield f"data: {json.dumps({'type': 'job', 'job': result})}\n\n"

            await asyncio.gather(*tasks, return_exceptions=True)   # ensure cleanup
            yield f"data: {json.dumps({'type': 'done'})}\n\n"

        except Exception as exc:
            logger.error("SSE stream error: %s", exc)
            yield f"data: {json.dumps({'type': 'error', 'message': 'Internal server error'})}\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/analyze-url")
async def analyze_url_endpoint(request: AnalyzeUrlRequest):
    if not request.resume.strip():
        raise HTTPException(status_code=400, detail="Resume text cannot be empty.")
    if not request.url.strip():
        raise HTTPException(status_code=400, detail="Job URL cannot be empty.")

    job = await asyncio.to_thread(fetch_job_from_url, request.url)
    if not job or not job.get("description"):
        raise HTTPException(status_code=422, detail="Could not extract job details from that URL. Try pasting the job description directly instead.")

    analysis = await asyncio.to_thread(analyze_job_detailed, request.resume, job)
    return {
        "title":    job.get("title", "Job Listing"),
        "company":  job.get("company", {}).get("display_name", "Company"),
        "location": "",
        "url":      request.url,
        "analysis": analysis,
    }
