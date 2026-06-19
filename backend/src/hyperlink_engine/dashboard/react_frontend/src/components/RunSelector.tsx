/**
 * RunSelector — the data-source bar shown above every screen.
 *
 * Lets the user choose which run the dashboard reads from: the seeded demo
 * dossier (default) or any completed live pipeline run. Styled with the
 * design-token primitives so it matches the rest of the enterprise shell.
 */

import React from "react";
import { useActiveRun } from "../contexts/ActiveRun";
import { Icon } from "./shared";

export const RunSelector: React.FC = () => {
  const { runs, activeRunId, setActiveRunId, refresh, loading } = useActiveRun();
  const live = !!activeRunId;

  return (
    <div
      style={{
        height: 40,
        flexShrink: 0,
        display: "flex",
        alignItems: "center",
        gap: 10,
        padding: "0 16px",
        borderBottom: "1px solid var(--border)",
        background: "var(--surface-raised)",
        fontSize: 12,
      }}
    >
      <span
        style={{
          display: "inline-flex",
          alignItems: "center",
          gap: 6,
          fontSize: 10,
          color: "var(--text-3)",
          textTransform: "uppercase",
          letterSpacing: "0.06em",
        }}
      >
        <Icon name="database" size={12} color="var(--text-3)" />
        Data source
      </span>

      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 6,
          height: 28,
          padding: "0 8px 0 10px",
          border: "1px solid var(--border)",
          borderRadius: "var(--r-4)",
          background: "var(--surface)",
        }}
      >
        <select
          value={activeRunId}
          onChange={(e) => setActiveRunId(e.target.value)}
          aria-label="Select data source"
          style={{
            border: "none",
            background: "transparent",
            color: "var(--text-1)",
            fontSize: 12,
            fontFamily: "inherit",
            outline: "none",
            cursor: "pointer",
            minWidth: 240,
            maxWidth: 460,
          }}
        >
          <option value="">📦 Demo data (seed dossier)</option>
          {runs.length > 0 && (
            <optgroup label="Live pipeline runs (newest first)">
              {runs.map((r) => (
                <option key={r.run_id} value={r.run_id}>
                  {`▶ ${r.run_id} · ${r.dossier_id || "dossier"} · ${r.total_links} links`}
                  {r.score != null ? ` · ${r.score.toFixed(0)} (${r.grade ?? "?"})` : ""}
                </option>
              ))}
            </optgroup>
          )}
        </select>
        <Icon name="chevron-down" size={12} color="var(--text-3)" />
      </div>

      <span
        className={`chip chip-sm ${live ? "success" : "outline"}`}
        title={live ? "Showing a live pipeline run" : "Showing the seeded demo dossier"}
      >
        <span
          className="dot dot-sm"
          style={{ background: live ? "var(--success)" : "var(--text-3)" }}
        />
        {live ? "LIVE RUN" : "DEMO SEED"}
      </span>

      <span className="mono" style={{ color: "var(--text-3)", fontSize: 11 }}>
        {runs.length} completed run{runs.length === 1 ? "" : "s"}
      </span>

      <button
        className="btn btn-sm btn-secondary"
        onClick={refresh}
        style={{ marginLeft: "auto" }}
        title="Refresh the list of completed runs"
      >
        <Icon name="refresh" size={12} color="var(--text-2)" />
        {loading ? "Refreshing…" : "Refresh runs"}
      </button>
    </div>
  );
};
