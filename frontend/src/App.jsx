import { useState, useEffect } from "react";
import JobCard from "./components/JobCard";

const API_BASE = import.meta.env.VITE_API_URL || "";

export default function App() {
  const [mode, setMode]                 = useState("search");  // "search" | "url"
  const [resumeMode, setResumeMode]     = useState("paste");   // "paste" | "upload"
  const [resume, setResume]             = useState("");
  const [pdfMeta, setPdfMeta]           = useState(null);      // { name, pages, words }
  const [pdfParsing, setPdfParsing]     = useState(false);
  const [keyword, setKeyword]           = useState("");
  const [jobUrl, setJobUrl]             = useState("");
  const [email, setEmail]               = useState("");
  const [enableAlerts, setEnableAlerts] = useState(false);

  const [jobs, setJobs]               = useState(null);   // null = not yet searched
  const [urlResult, setUrlResult]     = useState(null);   // single job from URL analysis
  const [keywordUsed, setKeywordUsed] = useState("");
  const [totalJobs, setTotalJobs]     = useState(0);
  const [analyzed, setAnalyzed]       = useState(0);
  const [loading, setLoading]         = useState(false);
  const [phase, setPhase]             = useState("");     // "resolving" | "fetching" | "analyzing"
  const [error, setError]             = useState("");
  const [sortByScore, setSortByScore] = useState(false);
  const [alertStatus, setAlertStatus] = useState(null);

  useEffect(() => {
    fetch(`${API_BASE}/schedule`)
      .then((r) => r.json())
      .then((d) => { if (d.enabled) setAlertStatus(d); })
      .catch(() => {});
  }, []);

  const handleAnalyze = async () => {
    if (!resume.trim()) {
      setError(resumeMode === "upload"
        ? "Please upload your PDF resume first."
        : "Please paste your resume text.");
      return;
    }
    if (!keyword.trim()) {
      setError("Please enter a job title or description.");
      return;
    }
    if (enableAlerts && !email.trim()) {
      setError("Please enter your email to enable alerts.");
      return;
    }

    setError("");
    setJobs([]);
    setKeywordUsed("");
    setTotalJobs(0);
    setAnalyzed(0);
    setSortByScore(false);
    setLoading(true);
    setPhase("resolving");

    try {
      const res = await fetch(`${API_BASE}/analyze`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          resume,
          keyword,
          email: enableAlerts ? email : "",
          enable_alerts: enableAlerts,
        }),
      });

      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        throw new Error(data.detail || `Server error ${res.status}`);
      }

      const reader  = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer    = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n");
        buffer = lines.pop() ?? "";

        for (const line of lines) {
          if (!line.startsWith("data: ")) continue;
          try {
            const msg = JSON.parse(line.slice(6));
            if (msg.type === "keyword") {
              setKeywordUsed(msg.keyword_used);
              setPhase("fetching");
            } else if (msg.type === "total") {
              setTotalJobs(msg.count);
              setPhase("analyzing");
            } else if (msg.type === "job") {
              setJobs((prev) => [...(prev ?? []), msg.job]);
              setAnalyzed((n) => n + 1);
            } else if (msg.type === "done") {
              setLoading(false);
              setPhase("");
              if (enableAlerts && email) setAlertStatus({ enabled: true, email, last_sent: null });
            } else if (msg.type === "error") {
              setError(msg.message);
              setLoading(false);
              setPhase("");
            }
          } catch { /* ignore partial lines */ }
        }
      }
    } catch (err) {
      setError(err.message || "Something went wrong. Please try again.");
    } finally {
      setLoading(false);
      setPhase("");
    }
  };

  const handlePdfUpload = async (file) => {
    if (!file) return;
    if (!file.name.toLowerCase().endsWith(".pdf")) {
      setError("Please upload a PDF file.");
      return;
    }
    setError("");
    setPdfParsing(true);
    setPdfMeta(null);
    const form = new FormData();
    form.append("file", file);
    try {
      const res = await fetch(`${API_BASE}/parse-resume`, { method: "POST", body: form });
      let data;
      try { data = await res.json(); } catch { throw new Error(`Server returned an unexpected response (${res.status}). Is the backend running?`); }
      if (!res.ok) throw new Error(data.detail || `Error ${res.status}`);
      setResume(data.text);
      setPdfMeta({ name: file.name, pages: data.pages, words: data.words });
    } catch (err) {
      setError(err.message || "PDF parsing failed.");
    } finally {
      setPdfParsing(false);
    }
  };

  const handleAnalyzeUrl = async () => {
    if (!resume.trim()) {
      setError(resumeMode === "upload"
        ? "Please upload your PDF resume first."
        : "Please paste your resume text.");
      return;
    }
    if (!jobUrl.trim()) {
      setError("Please paste a job posting URL.");
      return;
    }
    setError("");
    setUrlResult(null);
    setLoading(true);
    setPhase("analyzing");
    try {
      const res = await fetch(`${API_BASE}/analyze-url`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ resume, url: jobUrl }),
      });
      let data;
      try { data = await res.json(); } catch { throw new Error(`Server returned an unexpected response (${res.status}). Is the backend running?`); }
      if (!res.ok) throw new Error(data.detail || `Error ${res.status}`);
      setUrlResult(data);
    } catch (err) {
      setError(err.message || "Could not analyze that URL. Make sure it is a public LinkedIn job page.");
    } finally {
      setLoading(false);
      setPhase("");
    }
  };

  const handleDisableAlerts = async () => {
    await fetch(`${API_BASE}/schedule`, { method: "DELETE" });
    setAlertStatus(null);
    setEnableAlerts(false);
  };

  const displayJobs = sortByScore && jobs
    ? [...jobs].sort((a, b) => (b.analysis.match_score ?? -1) - (a.analysis.match_score ?? -1))
    : jobs;

  const phaseLabel = {
    resolving: "Extracting job title…",
    fetching:  "Fetching jobs across 5 cities…",
    analyzing: `Analyzing ${analyzed} / ${totalJobs} jobs…`,
  }[phase] ?? "";

  return (
    <div style={s.page}>
      <header style={s.header}>
        <div style={s.headerInner}>
          <span style={s.logoIcon}>⚡</span>
          <div>
            <h1 style={s.title}>Job Gap Analyzer</h1>
            <p style={s.subtitle}>
              Bangalore · Hyderabad · Pune · Chennai — top 20 matches, AI gap analysis
            </p>
          </div>
        </div>
      </header>

      <main style={s.main}>
        {/* Active alert banner */}
        {alertStatus?.enabled && (
          <div style={s.alertBanner}>
            <span>
              <span style={s.dot} />
              Alerts active — <strong>{alertStatus.email}</strong> once daily
              {alertStatus.last_sent && (
                <span style={s.muted}> · Last: {new Date(alertStatus.last_sent).toLocaleString()}</span>
              )}
            </span>
            <button style={s.disableBtn} onClick={handleDisableAlerts}>Disable</button>
          </div>
        )}

        {/* Input card */}
        <div style={s.card}>
          {/* Mode tabs */}
          <div style={s.tabs}>
            <button
              style={{ ...s.tab, ...(mode === "search" ? s.tabActive : {}) }}
              onClick={() => { setMode("search"); setError(""); setUrlResult(null); }}
              disabled={loading}
            >
              🔍 Search Jobs
            </button>
            <button
              style={{ ...s.tab, ...(mode === "url" ? s.tabActive : {}) }}
              onClick={() => { setMode("url"); setError(""); setJobs(null); }}
              disabled={loading}
            >
              🔗 Analyze a Job Link
            </button>
          </div>

          {mode === "search" ? (
            <div style={s.field}>
              <label style={s.label}>Job Title, Designation, or Paste a Job Description</label>
              <input
                style={s.input}
                type="text"
                placeholder='"Analytics Engineer" — or paste a full JD and AI extracts the role'
                value={keyword}
                onChange={(e) => setKeyword(e.target.value)}
                disabled={loading}
              />
            </div>
          ) : (
            <div style={s.field}>
              <label style={s.label}>Job Posting URL</label>
              <input
                style={s.input}
                type="url"
                placeholder="Paste a LinkedIn job URL — e.g. linkedin.com/jobs/view/1234567890"
                value={jobUrl}
                onChange={(e) => setJobUrl(e.target.value)}
                disabled={loading}
              />
            </div>
          )}

          {/* Resume input — toggle between upload and paste */}
          <div style={s.field}>
            <div style={s.resumeHeader}>
              <label style={s.label}>Your Resume</label>
              <div style={s.resumeTabs}>
                <button
                  style={{ ...s.resumeTab, ...(resumeMode === "upload" ? s.resumeTabActive : {}) }}
                  onClick={() => setResumeMode("upload")}
                  disabled={loading}
                  type="button"
                >
                  📄 Upload PDF
                </button>
                <button
                  style={{ ...s.resumeTab, ...(resumeMode === "paste" ? s.resumeTabActive : {}) }}
                  onClick={() => setResumeMode("paste")}
                  disabled={loading}
                  type="button"
                >
                  ✏️ Paste Text
                </button>
              </div>
            </div>

            {resumeMode === "upload" ? (
              <div
                style={s.dropzone}
                onDragOver={(e) => e.preventDefault()}
                onDrop={(e) => { e.preventDefault(); handlePdfUpload(e.dataTransfer.files[0]); }}
              >
                {pdfParsing ? (
                  <><Spinner /> <span style={{ color: "var(--text-muted)" }}>Parsing PDF…</span></>
                ) : pdfMeta ? (
                  <div style={s.pdfSuccess}>
                    <span style={s.pdfIcon}>✓</span>
                    <div>
                      <div style={s.pdfName}>{pdfMeta.name}</div>
                      <div style={s.pdfStats}>{pdfMeta.pages} page{pdfMeta.pages !== 1 ? "s" : ""} · {pdfMeta.words.toLocaleString()} words extracted</div>
                    </div>
                    <button
                      style={s.pdfChange}
                      onClick={() => { setPdfMeta(null); setResume(""); }}
                      type="button"
                    >
                      Change
                    </button>
                  </div>
                ) : (
                  <>
                    <span style={s.dropIcon}>📄</span>
                    <span style={s.dropText}>Drag & drop your PDF here, or</span>
                    <label style={s.browseBtn}>
                      Browse
                      <input
                        type="file"
                        accept=".pdf"
                        style={{ display: "none" }}
                        onChange={(e) => handlePdfUpload(e.target.files[0])}
                        disabled={loading}
                      />
                    </label>
                    <span style={s.dropHint}>Text-based PDFs only · max 5 MB</span>
                  </>
                )}
              </div>
            ) : (
              <textarea
                style={s.textarea}
                placeholder="Paste your resume here — plain text works best."
                value={resume}
                onChange={(e) => setResume(e.target.value)}
                disabled={loading}
                rows={11}
              />
            )}
          </div>

          {/* Alerts toggle — only in search mode */}
          {mode === "search" && (
            <div style={s.alertBox}>
              <label style={s.toggleRow}>
                <input
                  type="checkbox"
                  checked={enableAlerts}
                  onChange={(e) => setEnableAlerts(e.target.checked)}
                  disabled={loading}
                  style={{ accentColor: "var(--accent)", width: 16, height: 16 }}
                />
                <span>Email me new job matches daily</span>
                <span style={s.badge4x}>1×/day</span>
              </label>
              {enableAlerts && (
                <input
                  style={{ ...s.input, marginTop: "0.6rem" }}
                  type="email"
                  placeholder="your@email.com"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  disabled={loading}
                />
              )}
            </div>
          )}

          {error && <div style={s.errorBox}>{error}</div>}

          <button
            style={{ ...s.btn, ...(loading ? s.btnOff : {}) }}
            onClick={mode === "search" ? handleAnalyze : handleAnalyzeUrl}
            disabled={loading}
          >
            {loading
              ? <><Spinner /> {phaseLabel || "Analyzing…"}</>
              : mode === "search" ? "Analyze My Resume →" : "Match This Job →"}
          </button>
        </div>

        {/* Live progress bar while streaming */}
        {loading && totalJobs > 0 && (
          <div style={s.progress}>
            <div style={{ ...s.progressBar, width: `${Math.round((analyzed / totalJobs) * 100)}%` }} />
            <span style={s.progressLabel}>{analyzed} / {totalJobs} analyzed</span>
          </div>
        )}

        {/* URL analysis result */}
        {urlResult && !loading && (
          <section>
            <div style={s.resultsHeader}>
              <div>
                <h2 style={s.resultsTitle}>Match Analysis</h2>
                <p style={s.resultsMeta}>
                  Showing how well your resume fits this specific role — including a step-by-step action plan.
                </p>
              </div>
            </div>
            <div style={s.grid}>
              <JobCard job={urlResult} index={0} />
            </div>
          </section>
        )}

        {/* Search results */}
        {jobs !== null && jobs.length > 0 && (
          <section>
            <div style={s.resultsHeader}>
              <div>
                <h2 style={s.resultsTitle}>
                  {loading ? `${analyzed} of ${totalJobs}` : jobs.length} Jobs{" "}
                  {loading ? "Streaming…" : "Analyzed"}
                </h2>
                <p style={s.resultsMeta}>
                  Searching: <strong style={{ color: "var(--accent-light)" }}>{keywordUsed}</strong>
                  {keywordUsed !== keyword && <em style={s.muted}> (extracted from your input)</em>}
                  {" "}· Bangalore, Hyderabad, Pune, Chennai
                </p>
              </div>
              {!loading && jobs.length > 1 && (
                <button
                  style={{ ...s.sortBtn, ...(sortByScore ? s.sortBtnActive : {}) }}
                  onClick={() => setSortByScore((v) => !v)}
                >
                  {sortByScore ? "⬇ Sorted by match" : "Sort by match score"}
                </button>
              )}
            </div>
            <div style={s.grid}>
              {displayJobs.map((job, i) => <JobCard key={i} job={job} index={i} />)}
            </div>
          </section>
        )}

        {jobs !== null && jobs.length === 0 && !loading && (
          <div style={s.empty}>
            <p style={{ fontSize: "2rem" }}>🔍</p>
            <p style={{ fontWeight: 600 }}>No jobs found</p>
            <p style={s.muted}>Try a broader keyword or check back later.</p>
          </div>
        )}
      </main>

      <footer style={s.footer}>
        Powered by Adzuna · OpenRouter · GPT-OSS 120B (free)
      </footer>
    </div>
  );
}

function Spinner() {
  return (
    <svg style={{ width: 15, height: 15, animation: "spin .8s linear infinite", flexShrink: 0 }} viewBox="0 0 24 24" fill="none">
      <style>{`@keyframes spin{to{transform:rotate(360deg)}}`}</style>
      <circle cx="12" cy="12" r="10" stroke="#3730a3" strokeWidth="3" />
      <path d="M12 2a10 10 0 0 1 10 10" stroke="#6c63ff" strokeWidth="3" strokeLinecap="round" />
    </svg>
  );
}

const s = {
  page:        { display: "flex", flexDirection: "column", minHeight: "100vh", background: "var(--bg)" },
  header:      { borderBottom: "1px solid var(--border)", background: "var(--surface)" },
  headerInner: { maxWidth: 920, margin: "0 auto", padding: "1.4rem 1.5rem", display: "flex", gap: "1rem", alignItems: "center" },
  logoIcon:    { fontSize: "2rem", lineHeight: 1, flexShrink: 0 },
  title:       { fontSize: "1.45rem", fontWeight: 700, color: "var(--text)", margin: 0 },
  subtitle:    { fontSize: "0.8rem", color: "var(--text-muted)", marginTop: "0.15rem" },

  main: { flex: 1, maxWidth: 920, width: "100%", margin: "0 auto", padding: "1.75rem 1.5rem", display: "flex", flexDirection: "column", gap: "1.4rem" },

  alertBanner: { background: "#052e16", border: "1px solid #16a34a", borderRadius: "var(--radius-sm)", padding: "0.7rem 1rem", display: "flex", justifyContent: "space-between", alignItems: "center", gap: "1rem", fontSize: "0.85rem", color: "#86efac" },
  dot:         { display: "inline-block", width: 8, height: 8, borderRadius: "50%", background: "#22c55e", marginRight: "0.5rem" },
  muted:       { opacity: 0.6, fontStyle: "italic" },
  disableBtn:  { background: "transparent", border: "1px solid #16a34a", borderRadius: "4px", color: "#86efac", fontSize: "0.75rem", padding: "0.2rem 0.55rem", cursor: "pointer", flexShrink: 0 },

  tabs:       { display: "flex", gap: "0.5rem", borderBottom: "1px solid var(--border)", paddingBottom: "1rem", marginBottom: "0.15rem" },
  tab:        { background: "transparent", border: "1px solid var(--border)", borderRadius: "var(--radius-sm)", color: "var(--text-muted)", fontSize: "0.83rem", fontWeight: 500, padding: "0.45rem 1rem", cursor: "pointer" },
  tabActive:  { background: "var(--accent)", borderColor: "var(--accent)", color: "#fff", fontWeight: 600 },

  card:    { background: "var(--surface)", border: "1px solid var(--border)", borderRadius: "var(--radius)", padding: "1.6rem", display: "flex", flexDirection: "column", gap: "1.15rem" },
  field:   { display: "flex", flexDirection: "column", gap: "0.35rem" },
  label:   { fontSize: "0.78rem", fontWeight: 600, color: "var(--text-muted)", textTransform: "uppercase", letterSpacing: "0.05em" },
  input:   { background: "var(--surface-2)", border: "1px solid var(--border)", borderRadius: "var(--radius-sm)", color: "var(--text)", fontSize: "0.92rem", padding: "0.65rem 0.9rem", outline: "none", width: "100%" },
  textarea: { background: "var(--surface-2)", border: "1px solid var(--border)", borderRadius: "var(--radius-sm)", color: "var(--text)", fontSize: "0.85rem", padding: "0.7rem 0.9rem", outline: "none", resize: "vertical", fontFamily: "inherit", lineHeight: 1.6, width: "100%" },

  resumeHeader:   { display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "0.35rem" },
  resumeTabs:     { display: "flex", gap: "0.3rem" },
  resumeTab:      { background: "transparent", border: "1px solid var(--border)", borderRadius: "var(--radius-sm)", color: "var(--text-muted)", fontSize: "0.75rem", fontWeight: 500, padding: "0.25rem 0.65rem", cursor: "pointer" },
  resumeTabActive:{ background: "var(--surface-2)", borderColor: "var(--accent)", color: "var(--accent-light)", fontWeight: 600 },

  dropzone: { border: "2px dashed var(--border)", borderRadius: "var(--radius-sm)", background: "var(--surface-2)", padding: "2rem 1rem", display: "flex", flexDirection: "column", alignItems: "center", gap: "0.5rem", textAlign: "center", cursor: "default" },
  dropIcon: { fontSize: "2rem" },
  dropText: { fontSize: "0.85rem", color: "var(--text-muted)" },
  dropHint: { fontSize: "0.72rem", color: "var(--text-muted)", opacity: 0.6 },
  browseBtn:{ background: "var(--accent)", color: "#fff", border: "none", borderRadius: "var(--radius-sm)", padding: "0.3rem 0.85rem", fontSize: "0.8rem", fontWeight: 600, cursor: "pointer" },
  pdfSuccess: { display: "flex", alignItems: "center", gap: "0.75rem", width: "100%", padding: "0.25rem 0" },
  pdfIcon:    { fontSize: "1.4rem", color: "#22c55e", flexShrink: 0 },
  pdfName:    { fontSize: "0.85rem", fontWeight: 600, color: "var(--text)" },
  pdfStats:   { fontSize: "0.75rem", color: "var(--text-muted)", marginTop: "0.1rem" },
  pdfChange:  { marginLeft: "auto", background: "transparent", border: "1px solid var(--border)", borderRadius: "4px", color: "var(--text-muted)", fontSize: "0.75rem", padding: "0.2rem 0.5rem", cursor: "pointer", flexShrink: 0 },

  alertBox:  { background: "var(--surface-2)", border: "1px solid var(--border)", borderRadius: "var(--radius-sm)", padding: "0.8rem 1rem" },
  toggleRow: { display: "flex", alignItems: "center", gap: "0.5rem", fontSize: "0.87rem", color: "var(--text)", cursor: "pointer" },
  badge4x:   { fontSize: "0.63rem", fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.05em", background: "#1e1b4b", color: "var(--accent-light)", border: "1px solid #3730a3", borderRadius: "4px", padding: "1px 5px" },

  errorBox: { background: "#450a0a", border: "1px solid #7f1d1d", borderRadius: "var(--radius-sm)", color: "#fca5a5", fontSize: "0.87rem", padding: "0.7rem 0.9rem" },

  btn:    { background: "var(--accent)", color: "#fff", border: "none", borderRadius: "var(--radius-sm)", padding: "0.75rem 1.75rem", fontSize: "0.92rem", fontWeight: 600, cursor: "pointer", alignSelf: "flex-end", display: "flex", alignItems: "center", gap: "0.5rem" },
  btnOff: { opacity: 0.6, cursor: "not-allowed" },

  progress:      { background: "var(--surface)", border: "1px solid var(--border)", borderRadius: "var(--radius-sm)", padding: "0.9rem 1.1rem", position: "relative", overflow: "hidden" },
  progressBar:   { position: "absolute", inset: 0, background: "#1e1b4b", transition: "width 0.4s ease", zIndex: 0 },
  progressLabel: { position: "relative", zIndex: 1, fontSize: "0.82rem", color: "var(--text-muted)", fontWeight: 500 },

  resultsHeader: { display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: "1rem", gap: "1rem", flexWrap: "wrap" },
  resultsTitle:  { fontSize: "1.15rem", fontWeight: 700, color: "var(--text)", margin: 0 },
  resultsMeta:   { fontSize: "0.8rem", color: "var(--text-muted)", marginTop: "0.2rem" },
  sortBtn:       { background: "var(--surface-2)", border: "1px solid var(--border)", borderRadius: "var(--radius-sm)", color: "var(--text-muted)", fontSize: "0.78rem", padding: "0.4rem 0.8rem", cursor: "pointer", flexShrink: 0, fontWeight: 500 },
  sortBtnActive: { border: "1px solid var(--accent)", color: "var(--accent-light)" },

  grid:  { display: "flex", flexDirection: "column", gap: "1.1rem" },
  empty: { background: "var(--surface)", border: "1px solid var(--border)", borderRadius: "var(--radius)", padding: "3rem", textAlign: "center", display: "flex", flexDirection: "column", alignItems: "center", gap: "0.5rem" },
  footer: { borderTop: "1px solid var(--border)", textAlign: "center", padding: "1rem", fontSize: "0.72rem", color: "var(--text-muted)" },
};
