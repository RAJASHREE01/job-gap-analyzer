const scoreColor = (score) => {
  if (score === null || score === undefined) return { color: "#8b90a8", bg: "#1e2235", label: "N/A" };
  if (score >= 70) return { color: "#22c55e", bg: "#052e16", label: `${score}%` };
  if (score >= 40) return { color: "#eab308", bg: "#422006", label: `${score}%` };
  return { color: "#ef4444", bg: "#450a0a", label: `${score}%` };
};

export default function JobCard({ job, index }) {
  const { title, company, location, url, analysis } = job;
  const { match_score, gaps, bullet_suggestions, cover_opener, error } = analysis;
  const badge = scoreColor(match_score);

  return (
    <article style={styles.card}>
      <header style={styles.header}>
        <div style={styles.headerLeft}>
          <span style={styles.index}>#{index + 1}</span>
          <div>
            <h2 style={styles.title}>{title}</h2>
            <p style={styles.meta}>
              {company}
              <span style={styles.separator}>·</span>
              {location}
            </p>
          </div>
        </div>
        <div style={styles.headerRight}>
          <div
            style={{
              ...styles.badge,
              color: badge.color,
              background: badge.bg,
              border: `1px solid ${badge.color}33`,
            }}
          >
            {match_score !== null ? (
              <>
                <span style={styles.badgeLabel}>Match</span>
                <span style={styles.badgeScore}>{badge.label}</span>
              </>
            ) : (
              <span style={styles.badgeLabel}>N/A</span>
            )}
          </div>
          {url && (
            <a href={url} target="_blank" rel="noopener noreferrer" style={styles.link}>
              Apply Now ↗
            </a>
          )}
        </div>
      </header>

      {error ? (
        <p style={styles.errorNote}>Analysis unavailable for this listing.</p>
      ) : (
        <div style={styles.body}>
          <Section title="Skill Gaps" icon="⚡">
            {gaps.length > 0 ? (
              <ul style={styles.list}>
                {gaps.map((g, i) => (
                  <li key={i} style={styles.listItem}>
                    <span style={styles.bullet}>▸</span>
                    {g}
                  </li>
                ))}
              </ul>
            ) : (
              <p style={styles.empty}>No gaps identified.</p>
            )}
          </Section>

          <Section title="Resume Bullet Suggestions" icon="✏️">
            {bullet_suggestions.length > 0 ? (
              <ul style={styles.list}>
                {bullet_suggestions.map((b, i) => (
                  <li key={i} style={{ ...styles.listItem, ...styles.bulletSuggestion }}>
                    <span style={styles.bullet}>▸</span>
                    {b}
                  </li>
                ))}
              </ul>
            ) : (
              <p style={styles.empty}>No suggestions available.</p>
            )}
          </Section>

          <Section title="Cover Letter Opener" icon="💌">
            <blockquote style={styles.quote}>"{cover_opener}"</blockquote>
          </Section>

          {analysis.action_plan?.length > 0 && (
            <Section title="Action Plan — Path to 100% Match" icon="🎯">
              <ol style={styles.actionList}>
                {analysis.action_plan.map((step, i) => (
                  <li key={i} style={styles.actionItem}>
                    <span style={styles.actionNum}>{i + 1}</span>
                    <span>{step}</span>
                  </li>
                ))}
              </ol>
            </Section>
          )}
        </div>
      )}
    </article>
  );
}

function Section({ title, icon, children }) {
  return (
    <div style={styles.section}>
      <h3 style={styles.sectionTitle}>
        <span>{icon}</span> {title}
      </h3>
      {children}
    </div>
  );
}

const styles = {
  card: {
    background: "var(--surface)",
    border: "1px solid var(--border)",
    borderRadius: "var(--radius)",
    overflow: "hidden",
    transition: "border-color 0.2s",
  },
  header: {
    display: "flex",
    justifyContent: "space-between",
    alignItems: "flex-start",
    gap: "1rem",
    padding: "1.25rem 1.5rem",
    background: "var(--surface-2)",
    borderBottom: "1px solid var(--border)",
    flexWrap: "wrap",
  },
  headerLeft: {
    display: "flex",
    gap: "0.75rem",
    alignItems: "flex-start",
    flex: 1,
    minWidth: 0,
  },
  headerRight: {
    display: "flex",
    flexDirection: "column",
    alignItems: "flex-end",
    gap: "0.5rem",
    flexShrink: 0,
  },
  index: {
    fontSize: "0.75rem",
    fontWeight: 700,
    color: "var(--accent-light)",
    background: "#1e1b4b",
    border: "1px solid #3730a3",
    borderRadius: "var(--radius-sm)",
    padding: "0.15rem 0.4rem",
    marginTop: "0.2rem",
    flexShrink: 0,
  },
  title: {
    fontSize: "1.05rem",
    fontWeight: 600,
    color: "var(--text)",
    lineHeight: 1.3,
    marginBottom: "0.25rem",
  },
  meta: {
    fontSize: "0.825rem",
    color: "var(--text-muted)",
    display: "flex",
    gap: "0.4rem",
    alignItems: "center",
    flexWrap: "wrap",
  },
  separator: {
    color: "var(--border)",
  },
  badge: {
    display: "flex",
    flexDirection: "column",
    alignItems: "center",
    borderRadius: "var(--radius-sm)",
    padding: "0.35rem 0.75rem",
    minWidth: "64px",
  },
  badgeLabel: {
    fontSize: "0.65rem",
    fontWeight: 600,
    textTransform: "uppercase",
    letterSpacing: "0.05em",
    opacity: 0.75,
  },
  badgeScore: {
    fontSize: "1.15rem",
    fontWeight: 700,
    lineHeight: 1.2,
  },
  link: {
    fontSize: "0.8rem",
    color: "var(--accent-light)",
    textDecoration: "none",
    fontWeight: 500,
    whiteSpace: "nowrap",
  },
  body: {
    display: "flex",
    flexDirection: "column",
    gap: 0,
  },
  section: {
    padding: "1.1rem 1.5rem",
    borderBottom: "1px solid var(--border)",
  },
  sectionTitle: {
    fontSize: "0.75rem",
    fontWeight: 700,
    textTransform: "uppercase",
    letterSpacing: "0.08em",
    color: "var(--text-muted)",
    marginBottom: "0.6rem",
    display: "flex",
    gap: "0.4rem",
    alignItems: "center",
  },
  list: {
    listStyle: "none",
    display: "flex",
    flexDirection: "column",
    gap: "0.4rem",
  },
  listItem: {
    fontSize: "0.875rem",
    color: "var(--text)",
    display: "flex",
    gap: "0.5rem",
    alignItems: "flex-start",
    lineHeight: 1.5,
  },
  bulletSuggestion: {
    color: "#a5b4fc",
    fontStyle: "italic",
  },
  bullet: {
    color: "var(--accent-light)",
    flexShrink: 0,
    marginTop: "0.1rem",
  },
  quote: {
    fontSize: "0.9rem",
    color: "#c4b5fd",
    fontStyle: "italic",
    borderLeft: "3px solid var(--accent)",
    paddingLeft: "0.75rem",
    lineHeight: 1.6,
  },
  empty: {
    fontSize: "0.825rem",
    color: "var(--text-muted)",
  },
  actionList: {
    listStyle: "none",
    display: "flex",
    flexDirection: "column",
    gap: "0.55rem",
    paddingLeft: 0,
  },
  actionItem: {
    fontSize: "0.875rem",
    color: "var(--text)",
    display: "flex",
    gap: "0.65rem",
    alignItems: "flex-start",
    lineHeight: 1.5,
  },
  actionNum: {
    flexShrink: 0,
    width: "1.35rem",
    height: "1.35rem",
    borderRadius: "50%",
    background: "var(--accent)",
    color: "#fff",
    fontSize: "0.7rem",
    fontWeight: 700,
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    marginTop: "0.1rem",
  },
  errorNote: {
    padding: "1rem 1.5rem",
    fontSize: "0.875rem",
    color: "var(--text-muted)",
    fontStyle: "italic",
  },
};
