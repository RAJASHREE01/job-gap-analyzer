# Job Gap Analyzer

Paste your resume and a job title — the app fetches real listings from Adzuna (India) and uses Gemma 2 27B (via OpenRouter) to score your match, surface skill gaps, suggest resume rewrites, and draft a cover letter opener for each role.

## Prerequisites

- Python 3.11+
- Node.js 18+
- Free accounts at:
  - [Adzuna Developer](https://developer.adzuna.com/) — get `app_id` + `app_key`
  - [OpenRouter](https://openrouter.ai/) — get an API key (Gemma 2 27B is on the free tier)

## Setup

### 1. Backend

```bash
cd backend

# Copy and fill in your API keys
cp .env.example .env
# Edit .env with your ADZUNA_APP_ID, ADZUNA_APP_KEY, OPENROUTER_API_KEY

# Create virtual environment
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate

pip install -r requirements.txt

# Start the server (port 8000)
uvicorn main:app --reload
```

Backend runs at http://localhost:8000  
Health check: http://localhost:8000/health

### 2. Frontend

```bash
cd frontend
npm install
npm run dev
```

Frontend runs at http://localhost:5173

Open http://localhost:5173 in your browser. The Vite dev server proxies `/analyze` and `/health` to the FastAPI backend automatically.

## Usage

1. Paste your resume text into the large text area.
2. Enter a job keyword (e.g. "Data Analyst", "MLOps Engineer").
3. Click **Analyze My Resume** (or Ctrl+Enter).
4. Wait ~20–60 seconds while the backend fetches 5 Adzuna listings and runs LLM analysis on each.
5. Review the cards — each shows:
   - **Match score** (green ≥70, yellow 40–69, red <40)
   - **Skill gaps** — what the JD wants that your resume lacks
   - **Resume bullet suggestions** — rewrites tailored to this role
   - **Cover letter opener** — one-line hook for the application

## Project Structure

```
job-gap-analyzer/
├── backend/
│   ├── main.py          # FastAPI app with /analyze + /health
│   ├── requirements.txt
│   └── .env.example
├── frontend/
│   ├── index.html
│   ├── vite.config.js   # Dev proxy → localhost:8000
│   └── src/
│       ├── main.jsx
│       ├── App.jsx      # Main UI and state
│       ├── index.css
│       └── components/
│           └── JobCard.jsx
└── README.md
```

## Environment Variables

| Variable | Description |
|---|---|
| `ADZUNA_APP_ID` | Your Adzuna application ID |
| `ADZUNA_APP_KEY` | Your Adzuna application key |
| `OPENROUTER_API_KEY` | Your OpenRouter API key |

## Notes

- The free Gemma model on OpenRouter can be slow (~5–15 s per job). With 5 jobs the full analysis takes 30–60 s.
- If a single job's LLM response fails to parse, the card shows "Analysis unavailable" and the rest continue rendering.
- To use a different country change `/in/` in the Adzuna URL in `backend/main.py` (e.g. `/us/`, `/gb/`).
