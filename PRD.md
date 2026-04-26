# Product Requirements Document — Job Gap Analyzer

## 1. Problem Statement

Job hunting in India's data/tech market has two pain points:

1. **Volume without signal.** Portals like LinkedIn and Naukri surface hundreds of listings, most from IT services firms (TCS, Infosys, Wipro) doing body-shopping. Candidates spend hours filtering manually and still apply to poor-fit roles.

2. **No feedback loop.** A candidate pastes their resume into a portal and hears nothing. They have no idea why they aren't shortlisted and can't improve their application for a specific JD.

**Goal:** Automate both — surface only product/fintech company roles matching your profile, and for each job, immediately show where you fall short and exactly what to fix.

---

## 2. Features

| Feature | Description |
|---------|-------------|
| Job Search Mode | Enter any job title or paste a raw JD; AI extracts keywords, fetches 20 real listings across 4 cities, scores each against your resume |
| ATS Resume Scanner | Upload PDF or paste text; backend extracts text layer for analysis |
| Job Link Analyzer | Paste any LinkedIn job URL; app fetches and parses the JD, returns full gap analysis with a 5-step action plan to reach 100% match |
| Match Score | AI rates current fit 0–100 per job |
| Skill Gap Breakdown | 3 specific skills the JD needs that the resume lacks |
| Resume Bullet Suggestions | 3 rewritten resume lines tailored to that specific JD |
| Cover Letter Opener | One-sentence hook for each application |
| Action Plan | 5 ordered, concrete steps to close all gaps for a specific role |
| Daily Email Alerts | 7 AM IST daily digest of new matches for your keyword — no manual searching needed |
| Live Progress Stream | Jobs appear on screen as each finishes analysis, no waiting for all 20 |
| Company Filtering | IT services / staffing firms excluded automatically |

---

## 3. Architecture Overview

```
User Browser (React / Vite)
        |
        | HTTPS
        v
  Vercel CDN (frontend)
        |
        | API calls
        v
  Render.com (FastAPI / uvicorn)
        |
   +----+--------+----------+
   |             |          |
Adzuna API  LinkedIn    OpenRouter
(job data)  guest API   (LLM analysis)
            (job URLs)
        |
     Resend API
     (email delivery)
```

---

## 4. Technology Decisions

### 4.1 Backend — FastAPI

**Need:** An HTTP server that can handle concurrent LLM calls (one per job card), stream results to the browser as they complete, and run a background scheduler for email alerts — all within a single Python process.

**Why FastAPI:**
- Native async support — each job's LLM call runs in a thread pool (`asyncio.to_thread`) while others run in parallel
- Server-Sent Events (SSE) via `StreamingResponse` lets results appear on screen card-by-card instead of making the user wait 60+ seconds for all 20
- Background scheduler (`APScheduler`) can run inside the same process using `lifespan` events
- Auto-generates `/docs` (OpenAPI) with zero extra code
- Pydantic models validate request bodies and give useful errors

**Why not Flask:** Flask is synchronous by default. Streaming concurrent LLM responses would require either gevent/eventlet (fragile) or a thread-per-request model that can't sustain 20 concurrent calls cleanly.

**Why not Django:** Massive overhead for a single-file API. Django's ORM, admin, migrations are all irrelevant here; no database is needed.

**Why not Express (Node.js):** The analysis pipeline is CPU/IO-bound Python. Node would require a separate Python subprocess for every LLM call, adding spawn overhead and complicating error handling.

---

### 4.2 Frontend — React + Vite

**Need:** A UI that updates in real time as jobs stream in (not a full page reload after all results arrive), with drag-and-drop file upload, mode tabs, and simple state management.

**Why React + Vite:**
- React's state model (`useState`, `useEffect`) maps directly to the streaming model: `setJobs(prev => [...prev, newJob])` appends each card as the SSE event arrives
- Vite dev server's proxy config routes `/analyze`, `/parse-resume`, etc. to localhost:8000 without CORS issues locally
- Vite builds to static files — deployable to any CDN (Vercel, Netlify, GitHub Pages) with no server required
- No TypeScript overhead needed for a project this size

**Why not Next.js:** Next.js SSR/RSC adds complexity (server components, hydration) with no benefit — this app is 100% client-side with dynamic data; there's no SEO need and nothing to pre-render.

**Why not vanilla JS:** Managing 20 streaming job cards, PDF upload state, mode switching, and error states without a component model would require manual DOM manipulation that's error-prone and hard to maintain.

**Why not Vue / Svelte:** React was chosen for familiarity; Svelte would also work cleanly, but there's no technical reason to switch mid-project.

---

### 4.3 Job Data — Adzuna API

**Need:** A free, programmatic source of real job listings in India that returns structured data (title, company, location, description, posted date) via a REST API.

**Why Adzuna:**
- Free tier: 250 API calls/month — sufficient for 1 search/day × 8 calls/search (2 keywords × 4 cities)
- Returns full job descriptions, not just titles — essential for LLM gap analysis
- India endpoint (`/api/jobs/in/`) with city-level `where` filtering
- Structured JSON: `title`, `company.display_name`, `description`, `redirect_url`, `created`
- No scraping, no authentication UI, no OAuth flow — just an API key

**Why not LinkedIn Jobs API:** LinkedIn's official Jobs API requires a company developer account with a listed product, commercial agreement, and approval process. Not available to individuals.

**Why not Indeed API:** Indeed deprecated their public job search API in 2023. No public programmatic access exists.

**Why not Naukri API:** No public API. Naukri is scraping-only, which violates ToS and is fragile.

**Why not Glassdoor API:** Glassdoor shut down their public API in 2024.

**Adzuna quota math:** With `MAX_KEYWORDS = 2` and `SCHED_CITIES = 4` (Bangalore, Hyderabad, Pune, Chennai):
- Scheduled run: 2 × 4 = 8 calls/day
- 30-day month: 240 calls (leaves 10 calls buffer)
- Manual searches during the month: each costs 8 calls

---

### 4.4 LLM — OpenRouter + GPT-OSS 120B

**Need:** An LLM that returns structured JSON (match score, gaps, suggestions, action plan) reliably, with a free tier that doesn't require a credit card or have strict rate limits for personal use.

**Why OpenRouter:**
- Single API key, access to dozens of models including free ones
- Free tier includes `openai/gpt-oss-120b:free` — a 120B parameter model that follows JSON output instructions reliably
- Falls back cleanly: if one model is down, swap the `MODEL` constant

**Why GPT-OSS 120B (free):**
- 120B parameters: large enough to follow complex multi-key JSON prompts consistently
- Free on OpenRouter: no cost per call
- Better instruction-following than smaller free models (e.g. Gemma 7B), which occasionally produce markdown-wrapped JSON or miss required keys

**Why not OpenAI GPT-4 / GPT-4o:** Paid. At 20 LLM calls per search, cost would add up quickly.

**Why not Google Gemini:** Gemini's free tier has very aggressive rate limits (15 RPM) — 20 concurrent calls would hit them immediately.

**Why not local LLM (Ollama, LM Studio):** Requires the user's machine to run a 7B+ model (needs ~8 GB VRAM). Incompatible with cloud deployment on free Render instances (512 MB RAM).

**Retry logic:** The code retries each LLM call up to 3 times with exponential back-off (5s, 10s, 15s) on 429 or parse errors, so transient rate limits don't surface as visible errors.

---

### 4.5 LinkedIn Job URLs — LinkedIn Guest API

**Need:** Adzuna's `redirect_url` for Indian jobs often points to Adzuna's own redirect page, not the original LinkedIn job page. Users need a direct `linkedin.com/jobs/view/{id}` link to apply in one click.

**Why LinkedIn guest API:**
- `linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search` returns HTML containing `jobPosting:{id}` — no login required
- `linkedin.com/jobs-guest/jobs/api/jobPosting/{id}` returns the full job card HTML — also no login
- Both endpoints are publicly accessible with a browser User-Agent header
- Free, no API key, no rate limit agreement needed

**Why not LinkedIn official API:** Requires company developer account (see §4.3).

**Why not scraping the main linkedin.com/jobs page:** The main search page is heavily JavaScript-rendered; it requires a headless browser (Playwright, Selenium) which adds 200+ MB of dependencies and 2–5s cold start per search. The guest API returns HTML directly.

**Company name normalization:** Adzuna company names often include legal suffixes ("WELLS FARGO BANK"), regional codes ("ASSPL - Telangana - D82"), or PVT/LTD suffixes. The `_clean_company()` function strips these before searching LinkedIn, dramatically improving URL match rates.

---

### 4.6 PDF Parsing — pypdf

**Need:** Extract text from a user's resume PDF so they can upload instead of copy-pasting.

**Why pypdf:**
- Pure Python, no external binaries (no Poppler, no Ghostscript)
- Works on Render's free tier without system package installation
- Handles multi-page PDFs, returns text per page
- 5 MB cap enforced before parsing to prevent memory spikes

**Limitation:** Works only for text-layer PDFs (digitally created). Scanned / image-only PDFs return no text. This is communicated to the user with a clear error message.

**Why not pdfminer.six:** More accurate text extraction but significantly more complex API and larger install. For a resume (clean, structured text), pypdf is sufficient.

**Why not Apache Tika (tika-python):** Requires a running Java server. Not viable on Render free tier.

**Why not pdf2image + OCR (Tesseract):** Adds ~300 MB of system dependencies. Overcomplicated for standard digitally-created resumes. If the PDF has a text layer (which all modern resume builders produce), pypdf is enough.

---

### 4.7 Email Delivery — Resend

**Need:** Send formatted HTML emails with job cards when the daily alert fires.

**Why Resend:**
- Free tier: 3,000 emails/month, 100/day — sufficient for 1 email/day
- No domain verification required when using `onboarding@resend.dev` as sender
- Simple REST API: single POST call with `from`, `to`, `subject`, `html`
- Deliverability is high (SPF/DKIM handled on their end)

**Why not SendGrid:** SendGrid's free tier was reduced to 100 emails/day and requires domain verification. API is also more complex.

**Why not Mailgun:** Free tier requires a registered domain; `mailgun.org` sandbox domains only work with verified recipient addresses.

**Why not SMTP directly (Gmail, Outlook):** Gmail's SMTP requires "less secure app access" (deprecated) or OAuth2 setup. Both are fragile for automated sending and violate Google's ToS for programmatic use.

**Why not nodemailer:** Python backend — no Node.js available.

---

### 4.8 Scheduling — cron-job.org + APScheduler

**Need:** Fire the email digest at 7:00 AM IST every day reliably, even when the Render free-tier service is sleeping.

**Architecture (two-layer):**

1. **cron-job.org (primary trigger):** A free external cron service calls `POST /run-scheduled` at `30 1 * * *` (01:30 UTC = 07:00 IST) daily. This wakes the Render service if sleeping and triggers the analysis pipeline. A second cron-job.org job pings `GET /health` every 5 minutes to keep the service warm so the 7 AM trigger hits instantly.

2. **APScheduler (backup trigger):** `BackgroundScheduler` with `CronTrigger(hour=7, minute=0, timezone=Asia/Kolkata)` runs inside the FastAPI process. `misfire_grace_time=6*3600` means if the process was paused and wakes up within 6 hours of 7 AM, it still fires. This catches cases where cron-job.org misses a run.

**`/run-scheduled` endpoint:** Accepts GET or POST with no required body. Fires `run_scheduled_analysis()` as a background task and returns `{"status": "triggered"}` immediately. Optionally protected by `CRON_SECRET` env var header check.

**Why APScheduler alone was not enough:** Render free tier pauses the process after 15 min inactivity. APScheduler's default `misfire_grace_time` is 1 second — if the process is paused at 7 AM and wakes at 10 AM, the job is silently skipped. Fixed by setting `misfire_grace_time=6*3600`.

**Why not Celery + Redis:** Massive over-engineering. Celery requires a message broker (Redis), a separate worker process, and additional cloud services — all for one daily job.

**Why not Render Cron Jobs:** Render's `type: cron` in `render.yaml` only takes effect when the project is set up via Render Blueprints. Services created manually via the dashboard don't auto-create new services from yaml changes.

---

### 4.9 Streaming — Server-Sent Events (SSE)

**Need:** Show job cards on screen as each one finishes LLM analysis, not after all 20 complete. Without streaming, a user waits 60+ seconds for a blank screen.

**Why SSE over WebSockets:**
- SSE is one-directional (server → client) which matches this use case exactly — the client sends one POST, then listens for events
- SSE works over standard HTTP; no protocol upgrade needed
- FastAPI's `StreamingResponse` with `text/event-stream` content type implements SSE natively
- Browser's `ReadableStream` API reads SSE without any library

**Why not polling:** Polling (client repeatedly asking "are there new results?") adds latency between each job and unnecessary API calls.

**Why not WebSockets:** WebSockets add handshake complexity and require a persistent connection manager. For a request-response pattern with server push, SSE is simpler and sufficient.

**Why Render and not Vercel for the backend:** Vercel serverless functions have a hard 10-second timeout on the free tier. One LLM call alone takes 10–30 seconds. Also, Vercel kills the process after the function returns — APScheduler (persistent background thread) would be destroyed on every request. Render runs a persistent Docker-like container where threads and schedulers live for the container's lifetime.

---

### 4.10 Backend Hosting — Render

**Need:** Free 24/7 hosting for a Python server with persistent in-process state (APScheduler thread) and no execution time limits.

**Why Render:**
- Free web service tier: 512 MB RAM, 0.1 CPU, auto-deploy from GitHub
- No timeout limit on running processes (unlike Vercel's 10s)
- Singapore region option (lower latency to India)
- `render.yaml` in the repo root configures everything declaratively — no dashboard clicking for teammates
- Supports environment variables natively
- Auto-deploys on every `git push main`

**Limitation:** Free tier sleeps after 15 minutes of inactivity. Solved with cron-job.org pinging `/health` every 10 minutes.

**Why not Vercel for backend:** 10s function timeout, no persistent processes, no APScheduler (see §4.9).

**Why not Railway:** Railway's free tier was reduced to $5 credit/month in 2023, then free tier removed in 2024. Not free anymore.

**Why not Fly.io:** Free tier requires a credit card on file. Render does not.

**Why not Heroku:** Heroku removed its free tier in November 2022.

**Why not Google Cloud Run / AWS Lambda:** Both have free tiers but cold start latency (2–5s) on the free plans makes the first request after inactivity noticeably slow. Also, Lambda's 15-minute timeout would interrupt long streaming responses.

---

### 4.11 Frontend Hosting — Vercel

**Need:** Free, fast CDN hosting for static React files with automatic HTTPS and preview deployments.

**Why Vercel:**
- Free tier: unlimited static deploys, global CDN, automatic HTTPS
- Zero config for Vite/React — detects the framework automatically
- `vercel.json` in `frontend/` configures SPA routing (`"rewrites": [{"source": "/(.*)", "destination": "/index.html"}]`)
- Instant deploys on every `git push`
- `VITE_API_URL` environment variable points the frontend at the Render backend URL

**Why not Netlify:** Netlify is equally valid. Vercel's Vite integration is marginally simpler.

**Why not GitHub Pages:** GitHub Pages doesn't support environment variables at build time, so `VITE_API_URL` would need to be hardcoded.

---

### 4.12 HTTP Client — httpx

**Need:** Make HTTP calls to Adzuna, OpenRouter, LinkedIn guest API, and Resend from inside an async FastAPI app.

**Why httpx:**
- Supports both sync and async call modes — sync calls work inside `asyncio.to_thread()` without blocking the event loop
- Identical API to `requests` (drop-in familiar)
- Built-in timeout parameter per request
- `follow_redirects=True` for generic job URL fetching

**Why not requests:** `requests` is synchronous only and would block the event loop if called directly in an async context without `to_thread`. httpx is the async-native evolution of requests.

**Why not aiohttp:** aiohttp has a more complex API (requires explicit session management, context managers). httpx is simpler for this pattern.

---

### 4.13 HTML Parsing — stdlib `html.parser`

**Need:** Strip HTML tags from LinkedIn job descriptions and generic job pages to get clean plain text for LLM input.

**Why stdlib HTMLParser:**
- Zero dependencies — no `beautifulsoup4` install needed
- Sufficient for the use case: skip `<script>`, `<style>`, `<nav>`, collect text from `<p>`, `<li>`, `<div>`
- Reduces `requirements.txt` complexity

**Why not BeautifulSoup4:** BS4 is powerful but adds a dependency (and `lxml` or `html5lib` parser). For this use case, a 30-line custom HTMLParser subclass does the job.

---

### 4.14 Company / Role Filtering

**Need:** Adzuna results for "data engineer" in Bangalore include a lot of IT services roles (TCS, Infosys, Wipro) which are not the target. These firms have a different hiring culture, tech stack, and growth trajectory than product companies.

**Implementation:**
- `SERVICE_PATTERNS`: 40+ company name substrings covering all major Indian IT services firms, staffing agencies, and Big 4 consulting
- `ROLE_PATTERNS`: job title must contain one of 15 data/analytics/ML role phrases
- `TITLE_EXCLUDE`: title must not contain infrastructure, GIS, marketing analyst, SAP, or supply chain terms that Adzuna sometimes returns for "data" keyword searches

**Why client-side filtering (not Adzuna params):** Adzuna's `company` filter is an exact match field; partial name filtering isn't supported. The `what` keyword field doesn't support exclusions. The filtering must happen post-fetch.

---

## 5. Data Flow — Search Mode

```
1. User enters keyword + resume → POST /analyze (SSE)
2. resolve_keywords(): LLM converts input to 2 Adzuna search terms
   → SSE: { type: "keyword", keyword_used: "..." }
3. fetch_jobs_multi_city(): 2 keywords × 4 cities = 8 Adzuna API calls
   Filter: remove service companies, irrelevant titles
   → Top 20 by recency
   → SSE: { type: "total", count: 20 }
4. For each job (concurrency = 3):
   a. _find_linkedin_url(): LinkedIn guest search → extract jobPosting:{id} → jobs/view/{id}
   b. analyze_job(): LLM prompt with JD + resume → JSON { match_score, gaps, bullet_suggestions, cover_opener }
   → SSE: { type: "job", job: { ... } }
5. → SSE: { type: "done" }
6. If alerts enabled: save schedule_config.json with resume + keyword + email
```

## 6. Data Flow — URL Analysis Mode

```
1. User pastes LinkedIn URL + resume → POST /analyze-url
2. fetch_job_from_url():
   - Extract jobPosting ID from URL
   - _fetch_linkedin_job(): GET linkedin.com/jobs-guest/jobs/api/jobPosting/{id}
   - Parse title, company, description from HTML
3. analyze_job_detailed(): LLM prompt → JSON {
     match_score, gaps, bullet_suggestions, cover_opener, action_plan (5 steps)
   }
4. Return single job object with full analysis
```

## 7. Data Flow — Daily Email Alert

```
cron-job.org fires at 01:30 UTC (07:00 IST) daily
  → POST https://job-gap-analyzer-api.onrender.com/run-scheduled
  → Render wakes service if sleeping (cold start ~30s)
  → /run-scheduled fires run_scheduled_analysis() as background task
  → Returns {"status": "triggered"} immediately

run_scheduled_analysis():
  → Read /tmp/schedule_config.json (enabled, keyword, resume, email)
  → If not enabled or file missing: return (no-op)
  → resolve_keywords(keyword)[:2]  -- max 2 keywords
  → fetch_jobs_multi_city(keywords, hours_back=24, cities=SCHED_CITIES)  -- only last 24h
  → If no new jobs: skip email, log info
  → Else: _format_result() for each job (analyze_job + _find_linkedin_url)
  → build_email_html(): styled HTML with job cards
  → Resend API: POST /emails
  → Write last_sent timestamp to schedule_config.json

APScheduler (backup): also fires run_scheduled_analysis() at 07:00 IST
  with misfire_grace_time=6h in case cron-job.org misses a run
```

---

## 8. API Quota Budget (Adzuna — 250 calls/month)

| Event | Calls per event | Max safe events/month |
|-------|----------------|----------------------|
| Scheduled daily run (2 keywords × 4 cities) | 8 | 31 (daily) = 248 |
| Manual search from UI | 8 | Can do 2–3 extra on top of 31 days |

With daily scheduling, 31 days uses 248 of 250 calls. Manual searches should be limited to 1–2/month if scheduling is active every day.

---

## 9. Security Considerations

- **API keys** stored in `.env` (local) and Render/Vercel environment variables (production) — never committed to git (`.gitignore` covers `.env`)
- **CORS** restricted to specific Vercel app domain in production via `ALLOWED_ORIGINS` env var; `allow_origin_regex` covers all `*.vercel.app` preview URLs
- **File upload** limited to `.pdf` extension check + 5 MB size cap server-side
- **No database** — no SQL injection surface; schedule config stored as a local JSON file in `/tmp/`
- **LLM prompt** does not include the user's email or any PII beyond resume text + job description
- **LinkedIn scraping** uses public guest API endpoints that require no login — no credential risk

---

## 10. Known Limitations

| Limitation | Impact | Mitigation |
|------------|--------|------------|
| Render free tier sleeps after 15 min inactivity | 7 AM cron hits sleeping service | cron-job.org pings `/health` every 5 min to keep service warm; APScheduler `misfire_grace_time=6h` fires if woken within 6h |
| schedule_config.json lost on Render redeploy | Email alerts stop until re-enabled | `/tmp/` persists across sleep/wake cycles but is wiped on redeploy; re-enable alerts from the frontend after any redeploy |
| Scanned PDF resumes return no text | Upload fails with error | Clear error message; fallback to paste mode |
| LinkedIn guest API may return 429 on heavy use | Job URL not found, falls back to Adzuna redirect | URL lookup wrapped in try/except; Adzuna URL used as fallback |
| Adzuna free tier: 250 calls/month | Can't run hourly scans | Capped at 1×/day, 2 keywords, 4 cities |
| LLM response not always valid JSON | Card shows "Analysis unavailable" | 3 retries with back-off; `strip_code_fences()` handles markdown wrapping |
