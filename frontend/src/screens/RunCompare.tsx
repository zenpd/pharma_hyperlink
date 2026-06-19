/**
 * Screen: Run Compare
 *
 * Before/after comparison for documents processed through the pipeline.
 * Pick a completed run → pick a document → see original vs hyperlinked.
 *
 * Fixes applied:
 *  - Auto-selects the most recent completed run (not just when there is exactly one)
 *  - Clicking a link in the AFTER panel opens the target document via download endpoint
 *  - Deep-link from Pipeline screen (initialRunId + initialDoc) still works
 */

import { Fragment, useEffect, useState } from "react";
import { api } from "../api";
import { BeforeAfter, externalUrl } from "../components/BeforeAfter";
import type { RefTarget } from "./ReferenceView";
import type { DocPreview, Link, RunSummary, RunStage } from "../types";

interface Props {
  onBack: () => void;
  /**
   * True when this screen is the one currently shown. The shell keeps visited
   * screens mounted (display:none) to preserve state, so we re-fetch the run
   * list each time the screen becomes active — otherwise a pipeline run that
   * completes *after* this screen first mounted would never appear here.
   */
  active?: boolean;
  initialRunId?: string;
  initialDoc?: string;
  /**
   * Open the dedicated Reference View page for a clicked hyperlink. Provided by
   * the App shell. When set, clicking a cross-document link navigates to that
   * focused page (which scrolls to the referenced table/section) instead of
   * swapping the document inline.
   */
  onOpenReference?: (runId: string, target: RefTarget) => void;
}

/** Classify what a link points to, using the backend's authoritative fields. */
type LinkKind =
  | { kind: "external"; url: string }
  | { kind: "cross-doc"; target: string }      // a different doc's _linked file
  | { kind: "internal" };                       // bookmark within the current doc

function classifyLink(link: Link, currentDoc: string | null): LinkKind {
  // 1. External website — authoritative via the shared helper (link_kind first,
  //    raw-URL fallback for legacy runs). Centralized so this branch can never
  //    drift from BeforeAfter / ReferenceView.
  const url = externalUrl(link);
  if (url) return { kind: "external", url };

  // 2. Cross-document — backend set target_doc to "<target>_linked.docx"
  //    or "<target>_linked.pdf" (only when resolve_targets matched a
  //    *different* uploaded document).
  const td = link.target_doc || "";
  if (/_linked\.(docx|pdf)$/i.test(td) && td !== currentDoc) {
    return { kind: "cross-doc", target: td };
  }

  // 3. Otherwise it's an internal bookmark within this document.
  return { kind: "internal" };
}

export function RunCompare({ onBack, active = true, initialRunId, initialDoc, onOpenReference }: Props) {
  const [runs, setRuns]                   = useState<RunSummary[]>([]);
  const [loadingRuns, setLoadingRuns]     = useState(true);
  const [runId, setRunId]                 = useState<string | null>(initialRunId ?? null);
  const [doc, setDoc]                     = useState<string | null>(initialDoc ?? null);
  const [preview, setPreview]             = useState<DocPreview | null>(null);
  const [loadingPreview, setLoadingPreview] = useState(false);
  const [error, setError]                 = useState("");
  // Lifecycle stages (per-stage before/after)
  const [stages, setStages]               = useState<RunStage[]>([]);
  const [stage, setStage]                 = useState<string>("linked");
  const [advancing, setAdvancing]         = useState<string | null>(null);

  // Load completed runs whenever the screen becomes active. Because the shell
  // keeps this component mounted, a one-time mount fetch would go stale — a run
  // completed later would never show up. Re-fetching on activation keeps the
  // dropdown current while preserving any selection the user already made.
  useEffect(() => {
    if (!active) return;
    setLoadingRuns(true);
    api.pipeline.listRuns()
      .then((data) => {
        // Sort newest first by run_id (they are timestamp-prefixed) so [0] is always latest
        const done = (data.runs ?? [])
          .filter((r) => r.status === "done")
          .sort((a, b) => b.run_id.localeCompare(a.run_id));
        setRuns(done);
        setLoadingRuns(false);

        // Keep a valid selection: honor an explicit deep-link, keep the current
        // pick if it still exists, otherwise default to the most recent run.
        const ids = done.map((r) => r.run_id);
        if (initialRunId && ids.includes(initialRunId)) {
          setRunId(initialRunId);
        } else if (runId && ids.includes(runId)) {
          // keep current selection
        } else if (done.length > 0) {
          setRunId(done[0].run_id);
        }
      })
      .catch(() => setLoadingRuns(false));
    // Re-run on activation and when a deep-link target changes.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [active, initialRunId]);

  // React to a deep-linked document target (e.g. the "Compare" button on a
  // Pipeline result row) even though the component is already mounted.
  useEffect(() => {
    if (initialDoc) setDoc(initialDoc);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [initialDoc]);

  const activeRun    = runs.find((r) => r.run_id === runId) ?? null;
  const docOptions   = activeRun?.linked_files ?? [];

  // Auto-pick a doc when the selected run changes
  useEffect(() => {
    if (!runId) { setDoc(null); return; }
    if (doc && docOptions.includes(doc)) return;
    if (initialDoc && docOptions.includes(initialDoc)) { setDoc(initialDoc); return; }
    if (docOptions.length > 0) setDoc(docOptions[0]);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [runId, runs]);

  // Load lifecycle stages whenever the run changes.
  function loadStages(rid: string) {
    api.pipeline.stages(rid)
      .then((s) => setStages(s.stages ?? []))
      .catch(() => setStages([]));
  }
  useEffect(() => {
    if (!runId) { setStages([]); return; }
    loadStages(runId);
    setStage("linked");   // reset to the canonical stage on run change
  }, [runId]);

  // Load preview whenever run + doc + stage are selected (stage-aware).
  useEffect(() => {
    if (!runId || !doc) { setPreview(null); return; }
    setLoadingPreview(true);
    setError("");
    setPreview(null);
    api.pipeline.stagePreview(runId, doc, stage)
      .then((p) => { setPreview(p); setLoadingPreview(false); })
      .catch((e: unknown) => {
        setError(e instanceof Error ? e.message : "Failed to load preview");
        setLoadingPreview(false);
      });
  }, [runId, doc, stage]);

  // Advance the lifecycle to the next stage (compliance_approved / fda_ready).
  async function advanceTo(nextStage: string) {
    if (!runId) return;
    setAdvancing(nextStage);
    try {
      await api.pipeline.advanceStage(runId, nextStage);
      loadStages(runId);
      setStage(nextStage);             // jump to the freshly created stage
      showFlash(`Advanced to ${nextStage.replace(/_/g, " ")}`);
    } catch (e) {
      showFlash(e instanceof Error ? e.message : "Could not advance stage");
    } finally {
      setAdvancing(null);
    }
  }

  const [flash, setFlash] = useState<string>("");
  // Pending scroll target — set when a cross-doc link hands off to Reference
  // View; BeforeAfter uses it to auto-scroll after the new preview
  // loads.  Reset when the selected doc changes (useEffect below).
  const [scrollTarget, setScrollTarget] = useState<string | undefined>(undefined);

  function showFlash(msg: string) {
    setFlash(msg);
    window.setTimeout(() => setFlash(""), 3000);
  }

  // Clear the scroll target when the run changes (prevents a stale target
  // from a previous run from firing when the new run's doc loads).
  useEffect(() => { setScrollTarget(undefined); }, [runId]);

  // Click handler — uses the backend's authoritative link classification:
  //   • external website → open the URL in a new tab
  //   • cross-document    → follow it (navigate the compare view, or note if
  //                         the target wasn't part of this run)
  //   • internal bookmark → it jumps within the current document
  //
  // The optional `scrollTargetHeading` arg is an explicit heading to scroll to
  // in the target document; it's currently unused (the snippet popover that
  // supplied it was removed) — Reference View resolves the destination from the
  // link text itself. Kept on the signature for forward compatibility.
  function handleLinkClick(link: Link, scrollTargetHeading?: string) {
    if (!runId) return;
    const c = classifyLink(link, doc);

    if (c.kind === "external") {
      window.open(c.url, "_blank", "noopener,noreferrer");
      showFlash(`Opening external website: ${c.url}`);
      return;
    }

    // Cross-document or internal section/table that lives elsewhere → open the
    // dedicated Reference View page, which resolves the destination document
    // and scrolls to the referenced table / section / paragraph.
    if (onOpenReference) {
      onOpenReference(runId, {
        docHint: c.kind === "cross-doc" ? c.target : (link.target_doc || ""),
        // Anchor used to LOCATE the section/table inside the target document.
        // Prefer the popover-resolved heading; else the human link text — it
        // carries the dotted number ("Table 14.2.1.1") the snippet endpoint
        // searches on. We deliberately do NOT use target_anchor here: for
        // internal refs it's an injected bookmark slug ("table_ref_14_2_1_1",
        // underscores, no dots) that the number regex can't parse, which made
        // the snippet fall back to the first paragraph and scroll to the top.
        anchor: scrollTargetHeading || link.link_text || link.target_anchor,
        // The injected bookmark slug — lets Reference View land a citation on its
        // References ENTRY (ref_helget_2024) instead of the first body mention.
        bookmarkAnchor: link.target_anchor,
        sourceDoc: doc || "",
        linkText: link.link_text,
      });
      return;
    }

    // Fallback (no handler wired): keep the legacy inline doc-swap behavior.
    if (c.kind === "cross-doc") {
      if (docOptions.includes(c.target)) {
        setScrollTarget(scrollTargetHeading);
        setDoc(c.target);
        showFlash(`Followed link → ${c.target}`);
      } else {
        showFlash(`Link points to ${c.target}, which isn't part of this run — upload that document too to follow it.`);
      }
      return;
    }

    showFlash("This link points within the current document (internal bookmark).");
  }

  return (
    <div className="page" style={{ maxWidth: 1400 }}>
      <button className="back-btn" onClick={onBack}>← Back to Pipeline</button>
      <div className="page-title">Run Compare</div>
      <div className="page-subtitle">
        Before &amp; after for documents uploaded and processed through the pipeline.
      </div>

      {/* Run + doc pickers */}
      <div className="card" style={{ padding: "14px 20px", display: "flex", gap: 20, flexWrap: "wrap", alignItems: "flex-end" }}>
        <div style={{ minWidth: 280 }}>
          <label style={{
            fontSize: 11, color: "var(--text-muted)",
            textTransform: "uppercase", letterSpacing: "0.06em",
            display: "block", marginBottom: 4,
          }}>
            Pipeline Run
          </label>
          <select
            value={runId ?? ""}
            onChange={(e) => { setRunId(e.target.value || null); setDoc(null); }}
            disabled={loadingRuns || runs.length === 0}
            style={{
              width: "100%", padding: "7px 10px", borderRadius: 6, fontSize: 13,
              border: "1px solid var(--border)", background: "var(--surface)",
              color: "var(--text)", fontFamily: "monospace",
            }}
          >
            <option value="">
              {loadingRuns ? "Loading…" : runs.length ? "Select a run…" : "No completed runs"}
            </option>
            {runs.map((r) => (
              <option key={r.run_id} value={r.run_id}>
                {r.run_id} · {r.dossier_id} · {r.total_links ?? 0} links
              </option>
            ))}
          </select>
        </div>

        <div style={{ minWidth: 280 }}>
          <label style={{
            fontSize: 11, color: "var(--text-muted)",
            textTransform: "uppercase", letterSpacing: "0.06em",
            display: "block", marginBottom: 4,
          }}>
            Document
          </label>
          <select
            value={doc ?? ""}
            onChange={(e) => { setScrollTarget(undefined); setDoc(e.target.value || null); }}
            disabled={!activeRun || docOptions.length === 0}
            style={{
              width: "100%", padding: "7px 10px", borderRadius: 6, fontSize: 13,
              border: "1px solid var(--border)", background: "var(--surface)",
              color: "var(--text)", fontFamily: "monospace",
            }}
          >
            <option value="">{activeRun ? "Select a document…" : "Pick a run first"}</option>
            {docOptions.map((f) => (
              <option key={f} value={f}>{f}</option>
            ))}
          </select>
        </div>

        {/* Quick stats for the selected run */}
        {activeRun && (
          <div style={{ fontSize: 12, color: "var(--text-muted)", marginLeft: "auto" }}>
            {activeRun.total_links ?? 0} links · {docOptions.length} docs
          </div>
        )}
      </div>

      {/* Submission lifecycle stepper — per-stage before/after */}
      {runId && stages.length > 0 && (
        <div className="card" style={{ padding: "14px 18px", marginTop: 12 }}>
          <div style={{
            fontSize: 11, color: "var(--text-muted)", textTransform: "uppercase",
            letterSpacing: "0.06em", marginBottom: 10,
          }}>
            Submission Lifecycle — Before vs After at each stage
          </div>
          <div style={{ display: "flex", gap: 6, alignItems: "stretch", flexWrap: "wrap" }}>
            {stages.map((s, i) => {
              const isActive = s.stage === stage;
              const canSelect = s.available;
              // A stage is advanceable when its predecessor is available but it
              // isn't, and it's one of the two on-demand stages.
              const advanceable =
                !s.available &&
                (stages[i - 1]?.available ?? false) &&
                (s.stage === "compliance_approved" || s.stage === "fda_ready");
              return (
                <Fragment key={s.stage}>
                  {i > 0 && (
                    <div style={{ alignSelf: "center", color: "var(--text-muted)", fontSize: 16 }}>→</div>
                  )}
                  <div
                    onClick={() => canSelect && setStage(s.stage)}
                    title={s.description}
                    style={{
                      minWidth: 150, padding: "8px 12px", borderRadius: 8,
                      border: `1.5px solid ${isActive ? "var(--primary)" : s.available ? "var(--border)" : "var(--border)"}`,
                      background: isActive ? "var(--primary-bg, rgba(99,102,241,0.10))" : s.available ? "var(--surface)" : "rgba(0,0,0,0.03)",
                      cursor: canSelect ? "pointer" : "default",
                      opacity: s.available ? 1 : 0.6,
                      transition: "all 0.15s",
                    }}
                  >
                    <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                      <span style={{ fontSize: 13 }}>{s.available ? "✅" : "○"}</span>
                      <span style={{ fontSize: 13, fontWeight: 600 }}>{s.label}</span>
                    </div>
                    <div style={{ fontSize: 10, color: "var(--text-muted)", marginTop: 2 }}>
                      {s.available ? `${s.doc_count} doc${s.doc_count === 1 ? "" : "s"}` : "not generated"}
                    </div>
                    {advanceable && (
                      <button
                        className="btn-primary btn-sm"
                        style={{ marginTop: 6, width: "100%", fontSize: 11 }}
                        disabled={advancing === s.stage}
                        onClick={(e) => { e.stopPropagation(); advanceTo(s.stage); }}
                      >
                        {advancing === s.stage ? "Generating…" : "Advance →"}
                      </button>
                    )}
                  </div>
                </Fragment>
              );
            })}
          </div>
          <div style={{ fontSize: 12, color: "var(--text-muted)", marginTop: 10 }}>
            {stages.find((s) => s.stage === stage)?.description}
          </div>
          {/* What actually changed at the selected stage (transform output) */}
          {(() => {
            const sel = stages.find((s) => s.stage === stage);
            const changes = sel?.meta?.changes ?? [];
            if (!changes.length) return null;
            return (
              <div style={{
                marginTop: 10, padding: "8px 12px", borderRadius: 6,
                background: "rgba(16,185,129,0.08)", border: "1px solid rgba(16,185,129,0.35)",
              }}>
                <div style={{ fontSize: 11, fontWeight: 700, color: "var(--success, #047857)", marginBottom: 4 }}>
                  ✦ CHANGES APPLIED AT THIS STAGE{sel?.meta?.by ? ` · by ${sel.meta.by}` : ""}
                </div>
                <ul style={{ margin: 0, paddingLeft: 18, fontSize: 12, color: "var(--text)" }}>
                  {changes.map((c, i) => <li key={i}>{c}</li>)}
                </ul>
              </div>
            );
          })()}
        </div>
      )}

      {/* Empty state */}
      {!runId && !loadingRuns && runs.length === 0 && (
        <div className="center-state">
          <div style={{ fontSize: 48, marginBottom: 12 }}>📭</div>
          <h3>No completed pipeline runs yet</h3>
          <p>Upload documents on the Pipeline screen, then come back to compare.</p>
        </div>
      )}

      {loadingPreview && (
        <div className="center-state">
          <div className="spinner" />
          <h3>Loading document preview…</h3>
        </div>
      )}

      {error && (
        <div className="error-msg"><strong>Failed to load</strong>{error}</div>
      )}

      {flash && (
        <div style={{
          marginTop: 12, padding: "8px 14px", borderRadius: 6,
          background: "var(--primary-bg)", color: "var(--primary-dark)",
          border: "1px solid var(--primary)", fontSize: 13, fontWeight: 500,
        }}>
          {flash}
        </div>
      )}

      {!loadingPreview && !error && preview && (
        <div style={{ marginTop: 12 }}>
          <BeforeAfter
            preview={preview}
            afterPath={doc ?? undefined}
            afterTitle={stages.find((s) => s.stage === stage)?.label}
            onLinkClick={handleLinkClick}
            runId={runId ?? undefined}
            scrollTarget={scrollTarget}
            runDocs={docOptions}
            onSelectRelatedDoc={(td) => {
              // Jump the compare view to the clicked related document. docOptions
              // entries may be paths; match on basename.
              const match = docOptions.find((o) => (o.split(/[\\/]/).pop() ?? o) === td);
              if (!match) { showFlash(`${td} isn't part of this run.`); return; }
              if (match === doc) { showFlash(`Already viewing ${td}`); return; }
              setScrollTarget(undefined);
              setDoc(match);
              showFlash(`Viewing → ${td.replace(/_linked\.(docx|pdf)$/i, "")}`);
              // Scroll back to the panels so the switch (and the banner) is
              // visible even when the user clicked a card far down the list.
              window.requestAnimationFrame(() =>
                window.scrollTo({ top: 0, behavior: "smooth" }),
              );
            }}
          />
        </div>
      )}
    </div>
  );
}
