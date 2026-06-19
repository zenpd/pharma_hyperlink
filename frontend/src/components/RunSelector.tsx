/**
 * RunSelector
 *
 * A slim bar shown above the Reports + Analysis screens that lets the user
 * choose which data source those screens read from: the latest pipeline runs
 * or the seeded demo dossier. Backed by the ActiveRun context.
 */

import { useActiveRun } from "../contexts/ActiveRun";

export function RunSelector() {
  const { runs, activeRunId, setActiveRunId, refresh, loading } = useActiveRun();
  const live = !!activeRunId;

  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        gap: 10,
        padding: "8px 16px",
        margin: "0 0 12px",
        background: "var(--surface, #fff)",
        border: "1px solid var(--border-color, #e5e7eb)",
        borderRadius: 8,
        fontSize: 12,
        flexWrap: "wrap",
      }}
    >
      <span style={{ fontWeight: 700, color: "var(--text-muted)", textTransform: "uppercase", letterSpacing: "0.05em" }}>
        Data source
      </span>

      <select
        value={activeRunId}
        onChange={(e) => setActiveRunId(e.target.value)}
        style={{
          padding: "5px 10px",
          borderRadius: 6,
          border: "1px solid var(--border-color, #e5e7eb)",
          background: "var(--card-bg, #fff)",
          color: "var(--text, #111)",
          fontSize: 12,
          minWidth: 280,
          maxWidth: 460,
        }}
      >
        <option value="">📦 Demo data (seed dossier)</option>
        {runs.length > 0 && (
          <optgroup label="Live pipeline runs (newest first)">
            {runs.map((r) => (
              <option key={r.run_id} value={r.run_id}>
                {/* 🔒 marks classified runs — non-cleared users never receive
                    them from the API, so this badge is admin-facing info. */}
                {`${r.classification === "classified" ? "🔒 " : ""}▶ ${r.run_id} · ${r.dossier_id || "dossier"} · ${r.total_links} links`}
                {r.score != null ? ` · ${r.score.toFixed(0)} (${r.grade ?? "?"})` : ""}
              </option>
            ))}
          </optgroup>
        )}
      </select>

      <span
        style={{
          padding: "2px 8px",
          borderRadius: 10,
          fontSize: 10,
          fontWeight: 700,
          color: live ? "#1b5e20" : "#6B7280",
          background: live ? "#e8f5e9" : "rgba(0,0,0,0.05)",
        }}
        title={live ? "Showing a live pipeline run" : "Showing the seeded demo dossier"}
      >
        {live ? "● LIVE RUN" : "● DEMO SEED"}
      </span>

      <button
        className="btn-ghost btn-sm"
        onClick={refresh}
        style={{ marginLeft: "auto" }}
        title="Refresh the list of completed runs"
      >
        {loading ? "…" : "↺ Refresh runs"}
      </button>
    </div>
  );
}
