/**
 * Screen: Pipeline
 *
 * Stage 1 of the architecture:
 *   Upload docs → AI hyperlink injection → live progress → per-doc results
 *
 * Features:
 *  - Drag-and-drop / click file upload (.docx / .pdf)
 *  - POST /api/pipeline/upload   → run_id
 *  - POST /api/pipeline/run/{id} → starts background pipeline
 *  - SSE  /api/pipeline/stream/{id} → live 9-node stepper
 *  - Per-document link table (4-5 links each, Plan Two)
 *  - Download linked files + CSV when done
 */

import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import { useAuth } from "../contexts/Auth";
import type { AgentCatalog, PipelineEvent, PipelineNodeState, RunSummary } from "../types";

interface Props {
  onBack: () => void;
  onGoToReview: () => void;
  onCompareDoc?: (runId: string, doc: string) => void;
}

// Human labels for the six selectable layers (matches backend Layer enum order)
const LAYER_LABELS: { key: string; label: string }[] = [
  { key: "ingest",   label: "Ingest" },
  { key: "parse",    label: "Parse" },
  { key: "detect",   label: "Detect" },
  { key: "inject",   label: "Inject" },
  { key: "validate", label: "Validate" },
  { key: "report",   label: "Report" },
];

const PRESET_ORDER = ["fast", "balanced", "max"];

// ── Node definitions (matches orchestration/runner.py _NODES order) ──────────

const NODE_DEFS: { key: string; label: string }[] = [
  { key: "load_dossier",      label: "Load Dossier" },
  { key: "parse_all",         label: "Parse Docs" },
  { key: "detect_references", label: "Detect Refs" },
  { key: "resolve_targets",   label: "Resolve Targets" },
  { key: "inject_links",      label: "Inject Links" },
  { key: "validate",          label: "Validate" },
  { key: "score_and_report",  label: "Score & Report" },
  { key: "push_dossplorer",   label: "Push / Flag" },
  { key: "__end__",           label: "Done" },
];

function initNodes(): PipelineNodeState[] {
  return NODE_DEFS.map((n) => ({ name: n.key, label: n.label, status: "pending" }));
}

type PageState = "idle" | "uploading" | "running" | "done" | "error" | "cancelled";

interface DocRow {
  filename: string;
  links: number;
  // PLAN FIFTEEN — per-document link-type breakdown (mirrors BeforeAfter).
  // internal + crossDoc + external === links; broken is a status overlay.
  internal: number;
  crossDoc: number;
  external: number;
  broken: number;
  downloadName: string;
}

// ── Status dot ────────────────────────────────────────────────────────────────

function StatusDot({ status }: { status: string }) {
  const color =
    status === "done" ? "var(--success)" :
    status === "running" ? "var(--brand)" :
    status === "error" ? "var(--danger)" :
    "var(--border-color)";
  const ring = status === "running"
    ? { boxShadow: "0 0 0 4px rgba(99,102,241,0.18)", animation: "spin-pulse 1.4s infinite" }
    : {};
  return (
    <div style={{
      width: 22, height: 22, borderRadius: "50%",
      background: color,
      display: "grid", placeItems: "center",
      flexShrink: 0,
      border: status === "pending" ? "2px solid var(--border-color)" : "none",
      ...ring,
    }}>
      {status === "done" && <span style={{ color: "#fff", fontSize: 12, fontWeight: 700 }}>✓</span>}
      {status === "error" && <span style={{ color: "#fff", fontSize: 12 }}>✕</span>}
      {status === "running" && (
        <div style={{ width: 8, height: 8, borderRadius: "50%", background: "#fff" }} />
      )}
    </div>
  );
}

// ── Link-type count cell (PLAN FIFTEEN) ─────────────────────────────────────────
// One bucket of the per-document breakdown, rendered as a bare number in its own
// column. Colors mirror the BeforeAfter stat row (Internal=neutral, Cross-Doc=
// green, External=amber, Broken=red); a zero dims to muted so a clean run reads
// quietly rather than shouting red/amber.

function NumCell({ count, color }: { count: number; color: string }) {
  const dim = count === 0;
  return (
    <td style={{
      textAlign: "center", padding: "8px 8px",
      fontFamily: "monospace", fontWeight: 600, fontSize: 13,
      color: dim ? "var(--text-muted)" : color,
    }}>
      {count}
    </td>
  );
}

// ── Main component ─────────────────────────────────────────────────────────────

export function Pipeline({ onBack, onGoToReview, onCompareDoc }: Props) {
  const { mode, user } = useAuth();
  const [pageState, setPageState] = useState<PageState>("idle");
  const [dragging, setDragging] = useState(false);
  const [files, setFiles] = useState<File[]>([]);
  const [dossierId, setDossierId] = useState("DOS-2026-DEMO");
  // PLAN SEVEN Feature B — only admins may mark an upload classified, and the
  // control only appears while the security gate is on (it is meaningless
  // otherwise: with the gate off everything is readable anyway).
  const canClassify = !!mode?.enabled && !!user?.is_admin;
  const [classification, setClassification] =
    useState<"classified" | "unclassified">("classified");
  // Agent configuration (Plan Three)
  const [catalog, setCatalog] = useState<AgentCatalog | null>(null);
  const [preset, setPreset] = useState<string>("balanced");
  const [overrides, setOverrides] = useState<Record<string, string>>({});
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [runId, setRunId] = useState<string | null>(null);
  const [nodes, setNodes] = useState<PipelineNodeState[]>(initNodes());
  const [currentNode, setCurrentNode] = useState<string | null>(null);
  const [result, setResult] = useState<RunSummary | null>(null);
  const [docRows, setDocRows] = useState<DocRow[]>([]);
  const [errorMsg, setErrorMsg] = useState("");
  const [logLines, setLogLines] = useState<string[]>([]);
  const esRef = useRef<EventSource | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const folderInputRef = useRef<HTMLInputElement | null>(null);
  const logRef = useRef<HTMLDivElement>(null);

  // `webkitdirectory` isn't in React's typings, and the input can be remounted
  // (the upload card unmounts during a run and remounts on reset). A ref
  // callback re-applies the attributes every mount — more reliable than a
  // one-shot useEffect, which wouldn't re-run after a remount.
  const attachFolderInput = (el: HTMLInputElement | null) => {
    folderInputRef.current = el;
    if (el) {
      el.setAttribute("webkitdirectory", "");
      el.setAttribute("directory", "");
      el.setAttribute("mozdirectory", "");
    }
  };

  // Auto-scroll log
  useEffect(() => {
    if (logRef.current) logRef.current.scrollTop = logRef.current.scrollHeight;
  }, [logLines]);

  // Cleanup SSE on unmount
  useEffect(() => () => { esRef.current?.close(); }, []);

  // Load the agent catalog once
  useEffect(() => {
    api.agents()
      .then((c) => {
        setCatalog(c);
        // Seed preset from the backend default if recognizable
        if (c.presets && !c.presets[preset]) {
          setPreset(Object.keys(c.presets)[0] ?? "balanced");
        }
      })
      .catch(() => { /* catalog optional — UI degrades to default profile */ });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  /** Effective agent id for a layer = override ?? preset's profile entry. */
  function effectiveAgent(layer: string): string {
    if (overrides[layer]) return overrides[layer];
    return catalog?.presets[preset]?.profile[layer] ?? catalog?.default_profile[layer] ?? "";
  }

  function selectPreset(p: string) {
    setPreset(p);
    setOverrides({});  // presets reset manual overrides
  }

  function setLayerOverride(layer: string, agentId: string) {
    setOverrides((prev) => {
      const presetAgent = catalog?.presets[preset]?.profile[layer];
      const next = { ...prev };
      if (agentId === presetAgent) delete next[layer];  // back to preset default
      else next[layer] = agentId;
      return next;
    });
  }

  function addLog(msg: string) {
    const ts = new Date().toLocaleTimeString();
    setLogLines((prev) => [...prev.slice(-200), `[${ts}] ${msg}`]);
  }

  // ── File handling ──────────────────────────────────────────────────────

  // Stable identity for a staged file. For folder uploads two files can share
  // the same basename in different sub-folders, so we key on the relative path
  // when the browser provides it (webkitdirectory), else fall back to the name.
  function fileKey(f: File): string {
    return f.webkitRelativePath || f.name;
  }

  function addFiles(arr: File[]) {
    const filtered = arr.filter((f) => f.name.endsWith(".docx") || f.name.endsWith(".pdf"));
    if (filtered.length === 0) return;
    setFiles((prev) => {
      const keys = new Set(prev.map(fileKey));
      return [...prev, ...filtered.filter((f) => !keys.has(fileKey(f)))];
    });
  }

  function onFiles(fileList: FileList | null) {
    if (!fileList) return;
    addFiles(Array.from(fileList));
  }

  // Recursively read a dropped folder via the WebKit Entries API. Plain file
  // drops don't carry folder structure, so this walks directory entries and
  // stamps each File with a webkitRelativePath so nested paths are preserved.
  async function readDropEntry(entry: any, prefix: string): Promise<File[]> {
    if (!entry) return [];
    if (entry.isFile) {
      const file: File = await new Promise((res, rej) => entry.file(res, rej));
      const rel = prefix ? `${prefix}/${file.name}` : file.name;
      try {
        Object.defineProperty(file, "webkitRelativePath", { value: rel, configurable: true });
      } catch { /* some browsers freeze File — fall back to bare name */ }
      return [file];
    }
    if (entry.isDirectory) {
      const reader = entry.createReader();
      const entries: any[] = await new Promise((res) => {
        const acc: any[] = [];
        const readBatch = () => reader.readEntries((batch: any[]) => {
          if (!batch.length) { res(acc); return; }
          acc.push(...batch);
          readBatch();   // directories paginate — keep reading until empty
        }, () => res(acc));
        readBatch();
      });
      const nested = await Promise.all(
        entries.map((e) => readDropEntry(e, prefix ? `${prefix}/${entry.name}` : entry.name)),
      );
      return nested.flat();
    }
    return [];
  }

  async function onDrop(dt: DataTransfer) {
    // Prefer the Entries API (handles dropped folders); fall back to flat files.
    const items = dt.items ? Array.from(dt.items) : [];
    const entries = items
      .map((it) => (it.webkitGetAsEntry ? it.webkitGetAsEntry() : null))
      .filter(Boolean);
    if (entries.length > 0) {
      const collected = await Promise.all(entries.map((e) => readDropEntry(e, "")));
      addFiles(collected.flat());
    } else {
      onFiles(dt.files);
    }
  }

  function removeFile(key: string) {
    setFiles((prev) => prev.filter((f) => fileKey(f) !== key));
  }

  // ── SSE listener ──────────────────────────────────────────────────────

  function startStream(rid: string) {
    esRef.current?.close();
    const es = api.pipeline.stream(rid);
    esRef.current = es;

    es.onmessage = (e: MessageEvent) => {
      try {
        const evt = JSON.parse(e.data) as PipelineEvent;
        const { node, status, details } = evt;

        addLog(`${node} → ${status}${details ? " · " + JSON.stringify(details) : ""}`);
        setCurrentNode(node);

        setNodes((prev) =>
          prev.map((n) =>
            n.name === node
              ? { ...n, status: status === "done" ? "done" : status === "error" ? "error" : "running", details: details ?? undefined }
              : n.status === "running" && n.name !== node
              ? { ...n, status: "done" }
              : n
          )
        );

        if (node === "__end__") {
          es.close();
          if (status === "cancelled") {
            setNodes((prev) => prev.map((n) => (n.status === "running" ? { ...n, status: "pending" } : n)));
            addLog("Pipeline cancelled.");
            setPageState("cancelled");
            return;
          }
          // On a successful finish every stage that ran is complete — mark all
          // non-errored nodes done. This reliably greens the terminal
          // "Push / Flag" stage even when its final SSE events arrive in the
          // same burst as __end__ (otherwise it can be left looking pending).
          const ok = status !== "error";
          setNodes((prev) => prev.map((n) =>
            n.status === "error" ? n : ok ? { ...n, status: "done" } : (n.status === "running" ? { ...n, status: "done" } : n)
          ));
          // Fetch final results
          api.pipeline.results(rid).then((res) => {
            setResult(res as RunSummary);
            // Build per-doc rows from the backend's real per-document counts.
            // Fall back to the average only if per_doc is unavailable.
            const perDoc = res.per_doc ?? [];
            const byName = new Map(perDoc.map((d) => [d.filename, d]));
            const rows: DocRow[] = (res.linked_files ?? []).map((fname) => {
              const pd = byName.get(fname);
              const links = pd
                ? pd.links
                : res.total_links > 0
                ? Math.round(res.total_links / Math.max(res.linked_files.length, 1))
                : 0;
              return {
                filename: fname,
                links,
                // Breakdown when the backend supplied it; otherwise fall back to
                // "all internal" so the average-estimate path still renders sanely.
                internal: pd?.internal ?? links,
                crossDoc: pd?.cross_doc ?? 0,
                external: pd?.external ?? 0,
                broken: pd?.broken ?? 0,
                downloadName: fname,
              };
            });
            setDocRows(rows);
            setPageState(status === "error" ? "error" : "done");
          }).catch(() => setPageState("done"));
        }
      } catch {
        // ignore parse errors
      }
    };

    es.onerror = () => {
      addLog("SSE connection closed");
      es.close();
    };
  }

  // ── Run pipeline ──────────────────────────────────────────────────────

  async function handleRun() {
    if (files.length === 0) return;
    setPageState("uploading");
    setNodes(initNodes());
    setLogLines([]);
    setResult(null);
    setDocRows([]);
    setErrorMsg("");

    try {
      addLog(`Uploading ${files.length} file(s)… [profile: ${preset}${Object.keys(overrides).length ? " + overrides" : ""}]`);
      const upload = await api.pipeline.upload(
        files, dossierId, { preset, overrides },
        canClassify ? classification : undefined,
      );
      const rid = upload.run_id;
      setRunId(rid);
      addLog(`Run ID: ${rid} — starting pipeline…`);

      setPageState("running");
      startStream(rid);
      await api.pipeline.run(rid);
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      setErrorMsg(msg);
      setPageState("error");
      addLog(`ERROR: ${msg}`);
    }
  }

  async function handleCancel() {
    if (!runId) return;
    addLog("Cancelling run…");
    try {
      await api.pipeline.cancel(runId);
    } catch (e) {
      addLog(`Cancel request failed: ${e instanceof Error ? e.message : String(e)}`);
    }
    // The runner stops at the next node boundary and emits a "cancelled" __end__
    // event; the SSE handler turns that into the cancelled page state.
  }

  function handleReset() {
    esRef.current?.close();
    setFiles([]);
    setNodes(initNodes());
    setLogLines([]);
    setResult(null);
    setDocRows([]);
    setErrorMsg("");
    setRunId(null);
    setCurrentNode(null);
    setPageState("idle");
  }

  // ── Grade color ───────────────────────────────────────────────────────

  function gradeColor(g: string | null) {
    if (g === "A") return "var(--success)";
    if (g === "B") return "#f59e0b";
    return "var(--danger)";
  }

  // ── Render ─────────────────────────────────────────────────────────────

  return (
    <div className="page page--wide">
      <button className="back-btn" onClick={onBack}>← Back to Dashboard</button>
      <div className="page-title">🚀 Pipeline Run</div>
      <div className="page-subtitle">
        Upload dossier documents · AI detects & injects hyperlinks · live progress
      </div>

      {/* ── Agent configuration (idle / uploading) ── */}
      {(pageState === "idle" || pageState === "uploading") && catalog && (
        <div className="card" style={{ padding: "16px 24px" }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 12 }}>
            <span style={{ fontSize: 13, fontWeight: 600 }}>⚙️ Agent Configuration</span>
            <span style={{ fontSize: 11, color: "var(--text-muted)" }}>
              choose how each layer of the engine behaves
            </span>
            <button
              className="btn-ghost btn-sm"
              style={{ marginLeft: "auto" }}
              onClick={() => setShowAdvanced((v) => !v)}
            >
              {showAdvanced ? "Hide advanced ▲" : "Advanced ▼"}
            </button>
          </div>

          {/* Preset selector */}
          <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
            {PRESET_ORDER.filter((p) => catalog.presets[p]).map((p) => {
              const active = preset === p;
              return (
                <button
                  key={p}
                  onClick={() => selectPreset(p)}
                  style={{
                    flex: "1 1 180px", textAlign: "left", cursor: "pointer",
                    padding: "10px 14px", borderRadius: 8,
                    border: `2px solid ${active ? "var(--brand, #6366f1)" : "var(--border-color)"}`,
                    background: active ? "rgba(99,102,241,0.06)" : "transparent",
                  }}
                >
                  <div style={{ fontSize: 13, fontWeight: 600, color: active ? "var(--brand, #6366f1)" : "var(--text-primary)" }}>
                    {p === "fast" ? "⚡ Fast" : p === "max" ? "🎯 Max accuracy" : "⚖️ Balanced"}
                  </div>
                  <div style={{ fontSize: 11, color: "var(--text-muted)", marginTop: 2 }}>
                    {catalog.presets[p].label}
                  </div>
                </button>
              );
            })}
          </div>

          {/* Advanced per-layer overrides */}
          {showAdvanced && (
            <div style={{
              marginTop: 14, paddingTop: 14, borderTop: "1px solid var(--border-color)",
              display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))", gap: 12,
            }}>
              {LAYER_LABELS.map(({ key, label }) => {
                const opts = catalog.agents[key] ?? [];
                const presetAgent = catalog.presets[preset]?.profile[key];
                const current = effectiveAgent(key);
                return (
                  <div key={key}>
                    <label style={{ fontSize: 10, color: "var(--text-muted)", textTransform: "uppercase", letterSpacing: "0.06em", display: "block", marginBottom: 4 }}>
                      {label}{overrides[key] ? " *" : ""}
                    </label>
                    <select
                      value={current}
                      onChange={(e) => setLayerOverride(key, e.target.value)}
                      disabled={opts.length <= 1}
                      style={{
                        width: "100%", padding: "6px 8px", borderRadius: 6, fontSize: 12,
                        border: "1px solid var(--border-color)",
                        background: "var(--card-bg)", color: "var(--text-primary)",
                        opacity: opts.length <= 1 ? 0.6 : 1,
                      }}
                    >
                      {opts.map((a) => (
                        <option key={a.id} value={a.id}>
                          {a.label}{a.id === presetAgent ? " (preset)" : ""}
                        </option>
                      ))}
                    </select>
                  </div>
                );
              })}
            </div>
          )}
        </div>
      )}

      {/* ── Upload area (idle / uploading) ── */}
      {(pageState === "idle" || pageState === "uploading") && (
        <div className="card" style={{ padding: 24 }}>
          <div style={{ marginBottom: 16, display: "flex", gap: 12, alignItems: "center", flexWrap: "wrap" }}>
            <div>
              <label style={{ fontSize: 12, color: "var(--text-muted)", display: "block", marginBottom: 4 }}>
                Dossier ID
              </label>
              <input
                type="text"
                value={dossierId}
                onChange={(e) => setDossierId(e.target.value)}
                style={{
                  padding: "6px 10px", borderRadius: 6, border: "1px solid var(--border-color)",
                  fontSize: 13, fontFamily: "monospace", width: 200,
                  background: "var(--card-bg)", color: "var(--text-primary)",
                }}
              />
            </div>

            {/* Classification (admin-only while the security gate is on) */}
            {canClassify && (
              <div>
                <label style={{ fontSize: 12, color: "var(--text-muted)", display: "block", marginBottom: 4 }}>
                  Classification
                </label>
                <select
                  value={classification}
                  onChange={(e) =>
                    setClassification(e.target.value as "classified" | "unclassified")
                  }
                  title="Classified runs are visible only to cleared users (admins). Non-admin uploads are always unclassified."
                  style={{
                    padding: "6px 10px", borderRadius: 6, border: "1px solid var(--border-color)",
                    fontSize: 13,
                    background: "var(--card-bg)", color: "var(--text-primary)",
                  }}
                >
                  <option value="classified">🔒 Classified</option>
                  <option value="unclassified">🔓 Unclassified</option>
                </select>
              </div>
            )}
          </div>

          {/* Drop zone */}
          <div
            onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
            onDragLeave={() => setDragging(false)}
            onDrop={(e) => { e.preventDefault(); setDragging(false); void onDrop(e.dataTransfer); }}
            onClick={() => fileInputRef.current?.click()}
            style={{
              border: `2px dashed ${dragging ? "var(--brand)" : "var(--border-color)"}`,
              borderRadius: 10,
              padding: "32px 20px",
              textAlign: "center",
              cursor: "pointer",
              background: dragging ? "rgba(99,102,241,0.06)" : "transparent",
              transition: "all 0.15s",
            }}
          >
            <div style={{ fontSize: 32, marginBottom: 8 }}>📂</div>
            <div style={{ fontSize: 14, fontWeight: 600, marginBottom: 4 }}>
              Drop .docx / .pdf files — or a whole folder — here
            </div>
            <div style={{ fontSize: 12, color: "var(--text-muted)", marginBottom: 12 }}>
              or use a button below — single files or a whole nested folder
            </div>
            <div style={{ display: "flex", gap: 10, justifyContent: "center" }}>
              <button
                className="btn-ghost btn-sm"
                onClick={(e) => { e.stopPropagation(); fileInputRef.current?.click(); }}
              >
                📄 Browse files
              </button>
              <button
                className="btn-ghost btn-sm"
                onClick={(e) => { e.stopPropagation(); folderInputRef.current?.click(); }}
              >
                📁 Browse folder
              </button>
            </div>
            <input
              ref={fileInputRef}
              type="file"
              multiple
              accept=".docx,.pdf"
              style={{ display: "none" }}
              // Stop the programmatic .click() from bubbling back up to the drop
              // zone's onClick, which would re-open the file dialog a second time.
              onClick={(e) => e.stopPropagation()}
              onChange={(e) => onFiles(e.target.files)}
            />
            {/* Folder picker — recursively yields every nested .docx/.pdf.
                webkitdirectory/directory attributes are applied by the ref cb. */}
            <input
              ref={attachFolderInput}
              type="file"
              multiple
              style={{ display: "none" }}
              onClick={(e) => e.stopPropagation()}
              onChange={(e) => onFiles(e.target.files)}
            />
          </div>

          {/* File list */}
          {files.length > 0 && (
            <div style={{ marginTop: 16 }}>
              <div style={{ fontSize: 12, fontWeight: 600, marginBottom: 8, color: "var(--text-muted)" }}>
                STAGED ({files.length} file{files.length > 1 ? "s" : ""})
              </div>
              {files.map((f) => (
                <div key={fileKey(f)} style={{
                  display: "flex", alignItems: "center", gap: 8,
                  padding: "6px 10px", borderRadius: 6,
                  background: "var(--surface-sunken, rgba(0,0,0,0.03))",
                  marginBottom: 6,
                }}>
                  <span style={{ fontSize: 16 }}>{f.name.endsWith(".pdf") ? "📄" : "📝"}</span>
                  <span style={{ flex: 1, fontSize: 13, fontFamily: "monospace" }}>{fileKey(f)}</span>
                  <span style={{ fontSize: 11, color: "var(--text-muted)" }}>
                    {(f.size / 1024).toFixed(0)} KB
                  </span>
                  <button
                    style={{ background: "none", border: "none", cursor: "pointer", color: "var(--danger)", fontSize: 14 }}
                    onClick={(e) => { e.stopPropagation(); removeFile(fileKey(f)); }}
                  >✕</button>
                </div>
              ))}

              <div className="btn-row" style={{ marginTop: 16 }}>
                <button
                  className="btn-primary"
                  disabled={pageState === "uploading" || files.length === 0}
                  onClick={handleRun}
                >
                  {pageState === "uploading" ? "⏳ Uploading…" : "▶ Run Pipeline"}
                </button>
                <button className="btn-ghost" onClick={handleReset}>Clear</button>
              </div>
            </div>
          )}

          {files.length === 0 && (
            <div className="btn-row" style={{ marginTop: 16, justifyContent: "flex-end" }}>
              <button className="btn-ghost btn-sm" onClick={() => {
                // Load demo dossier files hint
                addLog("Tip: upload files from data/synthetic/demo_dossier/m5/53-clin-stud-rep/");
              }}>
                💡 Use demo dossier
              </button>
            </div>
          )}
        </div>
      )}

      {/* ── Live stepper (running / done / error / cancelled) ── */}
      {(pageState === "running" || pageState === "done" || pageState === "error" || pageState === "cancelled") && (
        <>
          {/* Run metadata */}
          <div className="card" style={{ padding: "12px 20px", display: "flex", gap: 24, alignItems: "center", flexWrap: "wrap" }}>
            <div>
              <div style={{ fontSize: 10, color: "var(--text-muted)", textTransform: "uppercase", letterSpacing: "0.06em" }}>Run ID</div>
              <div style={{ fontFamily: "monospace", fontSize: 13, fontWeight: 600 }}>{runId}</div>
            </div>
            <div>
              <div style={{ fontSize: 10, color: "var(--text-muted)", textTransform: "uppercase", letterSpacing: "0.06em" }}>Dossier</div>
              <div style={{ fontFamily: "monospace", fontSize: 13 }}>{dossierId}</div>
            </div>
            <div>
              <div style={{ fontSize: 10, color: "var(--text-muted)", textTransform: "uppercase", letterSpacing: "0.06em" }}>Files</div>
              <div style={{ fontSize: 13 }}>{files.length} uploaded</div>
            </div>
            {result && (
              <>
                <div>
                  <div style={{ fontSize: 10, color: "var(--text-muted)", textTransform: "uppercase", letterSpacing: "0.06em" }}>Score</div>
                  <div style={{ fontSize: 20, fontWeight: 700, fontFamily: "monospace", color: gradeColor(result.grade) }}>
                    {result.score?.toFixed(1) ?? "—"}
                  </div>
                </div>
                <div>
                  <div style={{ fontSize: 10, color: "var(--text-muted)", textTransform: "uppercase", letterSpacing: "0.06em" }}>Grade</div>
                  <div style={{ fontSize: 20, fontWeight: 700, color: gradeColor(result.grade) }}>{result.grade ?? "—"}</div>
                </div>
                <div>
                  <div style={{ fontSize: 10, color: "var(--text-muted)", textTransform: "uppercase", letterSpacing: "0.06em" }}>Links</div>
                  <div style={{ fontSize: 20, fontWeight: 700, fontFamily: "monospace" }}>{result.total_links}</div>
                </div>
              </>
            )}
            {pageState === "running" && (
              <span style={{ marginLeft: "auto", display: "flex", alignItems: "center", gap: 10 }}>
                <span style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 13, color: "var(--brand)" }}>
                  <div className="spinner" style={{ width: 14, height: 14, borderWidth: 2 }} />
                  Running · {currentNode ?? "starting"}
                </span>
                <button
                  className="btn-ghost btn-sm"
                  onClick={handleCancel}
                  style={{ color: "var(--danger)", borderColor: "var(--danger)" }}
                  title="Stop the pipeline at the next stage boundary"
                >
                  ⏹ Cancel
                </button>
              </span>
            )}
            {pageState === "done" && (
              <span style={{ marginLeft: "auto", fontSize: 13, color: "var(--success)", fontWeight: 600 }}>
                ✓ Complete
              </span>
            )}
            {pageState === "error" && (
              <span style={{ marginLeft: "auto", fontSize: 13, color: "var(--danger)", fontWeight: 600 }}>
                ✕ Error
              </span>
            )}
            {pageState === "cancelled" && (
              <span style={{ marginLeft: "auto", fontSize: 13, color: "var(--danger)", fontWeight: 600 }}>
                ⏹ Cancelled
              </span>
            )}
          </div>

          {/* 9-node stepper */}
          <div className="card" style={{ padding: "16px 20px" }}>
            <div style={{ fontSize: 12, fontWeight: 600, marginBottom: 14, color: "var(--text-muted)", textTransform: "uppercase", letterSpacing: "0.06em" }}>
              Pipeline Stages
            </div>
            <div style={{ display: "flex", alignItems: "flex-start", gap: 0, overflowX: "auto" }}>
              {nodes.map((n, i) => (
                <div key={n.name} style={{ flex: "1 0 80px", minWidth: 72, position: "relative", textAlign: "center" }}>
                  {/* connector line */}
                  {i < nodes.length - 1 && (
                    <div style={{
                      position: "absolute", top: 10, left: "50%", right: "-50%", height: 2,
                      background: n.status === "done" ? "var(--success)" : "var(--border-color)",
                      zIndex: 0,
                    }} />
                  )}
                  <div style={{ position: "relative", zIndex: 1, display: "flex", justifyContent: "center" }}>
                    <StatusDot status={n.status} />
                  </div>
                  <div style={{
                    marginTop: 8, fontSize: 10, lineHeight: 1.3,
                    color: n.status === "pending" ? "var(--text-muted)" : "var(--text-primary)",
                    fontWeight: n.status === "running" ? 700 : 400,
                  }}>
                    {n.label}
                  </div>
                  {n.details && n.status !== "pending" && (
                    <div style={{ fontSize: 9, color: "var(--text-muted)", marginTop: 2 }}>
                      {Object.entries(n.details).slice(0, 2).map(([k, v]) => (
                        <div key={k}>{k}: {String(v)}</div>
                      ))}
                    </div>
                  )}
                </div>
              ))}
            </div>
          </div>

          {/* Per-document results table */}
          {pageState === "done" && docRows.length > 0 && (
            <div className="card" style={{ padding: "16px 20px" }}>
              <div style={{ display: "flex", alignItems: "center", marginBottom: 14 }}>
                <div style={{ fontSize: 13, fontWeight: 600 }}>Per-Document Results</div>
                <span style={{ marginLeft: "auto", fontSize: 11, color: "var(--text-muted)" }}>
                  ~{docRows.length > 0 ? Math.round(docRows.reduce((s, r) => s + r.links, 0) / docRows.length) : 0} links/doc average
                </span>
              </div>
              <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
                <thead>
                  <tr style={{ borderBottom: "2px solid var(--border-color)" }}>
                    <th style={{ textAlign: "left", padding: "6px 8px", fontWeight: 600, fontSize: 11, color: "var(--text-muted)", textTransform: "uppercase" }}>Document</th>
                    <th style={{ textAlign: "center", padding: "6px 8px", fontWeight: 600, fontSize: 11, color: "#475569", textTransform: "uppercase" }}>Internal</th>
                    <th style={{ textAlign: "center", padding: "6px 8px", fontWeight: 600, fontSize: 11, color: "var(--success)", textTransform: "uppercase" }}>Cross-Doc</th>
                    <th style={{ textAlign: "center", padding: "6px 8px", fontWeight: 600, fontSize: 11, color: "#b45309", textTransform: "uppercase" }}>External</th>
                    <th style={{ textAlign: "center", padding: "6px 8px", fontWeight: 600, fontSize: 11, color: "var(--danger)", textTransform: "uppercase" }}>Broken</th>
                    <th style={{ textAlign: "center", padding: "6px 8px", fontWeight: 600, fontSize: 11, color: "var(--text-muted)", textTransform: "uppercase" }}>Links Injected</th>
                    <th style={{ textAlign: "center", padding: "6px 8px", fontWeight: 600, fontSize: 11, color: "var(--text-muted)", textTransform: "uppercase" }}>Status</th>
                    <th style={{ textAlign: "right", padding: "6px 8px", fontWeight: 600, fontSize: 11, color: "var(--text-muted)", textTransform: "uppercase" }}>Download</th>
                  </tr>
                </thead>
                <tbody>
                  {docRows.map((row, i) => (
                    <tr key={row.filename} style={{ borderBottom: "1px solid var(--border-color)", background: i % 2 === 0 ? "transparent" : "rgba(0,0,0,0.015)" }}>
                      <td style={{ padding: "8px 8px", fontFamily: "monospace", fontSize: 12 }}>
                        📄 {row.filename}
                      </td>
                      <NumCell count={row.internal} color="#475569" />
                      <NumCell count={row.crossDoc} color="var(--success)" />
                      <NumCell count={row.external} color="#b45309" />
                      <NumCell count={row.broken} color="var(--danger)" />
                      <td style={{ textAlign: "center", padding: "8px 8px", fontWeight: 600, fontFamily: "monospace" }}>
                        <span style={{
                          display: "inline-block", padding: "2px 10px",
                          borderRadius: 10,
                          background: "var(--success-bg, rgba(34,197,94,0.1))",
                          color: "var(--success)",
                          fontSize: 12,
                        }}>
                          {row.links}
                        </span>
                      </td>
                      <td style={{ textAlign: "center", padding: "8px 8px" }}>
                        <span style={{ color: "var(--success)", fontSize: 12 }}>✓ linked</span>
                      </td>
                      <td style={{ textAlign: "right", padding: "8px 8px", whiteSpace: "nowrap" }}>
                        {onCompareDoc && (
                          <button
                            className="btn-ghost btn-sm"
                            style={{ marginRight: 6 }}
                            onClick={() => onCompareDoc(runId!, row.downloadName)}
                          >
                            🆚 Compare
                          </button>
                        )}
                        <button
                          className="btn-ghost btn-sm"
                          onClick={() => api.pipeline.downloadLinked(runId!, row.downloadName)}
                        >
                          ⬇ {row.downloadName.toLowerCase().endsWith(".pdf") ? ".pdf" : ".docx"}
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          {/* Action buttons when done */}
          {pageState === "done" && (
            <div className="card" style={{ padding: 16 }}>
              <div className="btn-row">
                <button className="btn-success" onClick={() => api.pipeline.downloadCsv(runId!)}>
                  ⬇ Download Report CSV
                </button>
                <button className="btn-primary" onClick={onGoToReview}>
                  → Send to Review Queue
                </button>
                <button className="btn-ghost" onClick={handleReset}>
                  ↩ New Run
                </button>
              </div>
            </div>
          )}

          {/* Error */}
          {pageState === "error" && (
            <div className="error-msg">
              <strong>Pipeline Error</strong>
              {errorMsg || "An unexpected error occurred."}
              <br />
              <button className="btn-ghost btn-sm" style={{ marginTop: 8 }} onClick={handleReset}>
                ↩ Try Again
              </button>
            </div>
          )}

          {/* Cancelled */}
          {pageState === "cancelled" && (
            <div className="card" style={{ padding: 16 }}>
              <div style={{ fontSize: 13, fontWeight: 600, color: "var(--danger)" }}>⏹ Pipeline cancelled</div>
              <div style={{ fontSize: 12, color: "var(--text-muted)", marginTop: 4 }}>
                The run was stopped before completion — no results were produced.
              </div>
              <button className="btn-ghost btn-sm" style={{ marginTop: 10 }} onClick={handleReset}>
                ↩ New Run
              </button>
            </div>
          )}

          {/* Live log */}
          <div className="card" style={{ padding: 0, overflow: "hidden" }}>
            <div style={{
              padding: "10px 16px", borderBottom: "1px solid var(--border-color)",
              fontSize: 12, fontWeight: 600, display: "flex", alignItems: "center", gap: 8,
            }}>
              <span>📋 Live Log</span>
              {pageState === "running" && (
                <span style={{ fontSize: 10, color: "var(--brand)", display: "flex", alignItems: "center", gap: 4 }}>
                  <div className="spinner" style={{ width: 10, height: 10, borderWidth: 2 }} /> streaming
                </span>
              )}
              <span style={{ marginLeft: "auto", fontSize: 11, color: "var(--text-muted)" }}>{logLines.length} lines</span>
            </div>
            <div
              ref={logRef}
              style={{
                maxHeight: 180, overflowY: "auto", fontFamily: "monospace",
                fontSize: 11, lineHeight: 1.6, padding: "8px 14px",
                background: "var(--surface-sunken, rgba(0,0,0,0.02))",
              }}
            >
              {logLines.map((l, i) => (
                <div key={i} style={{ color: l.includes("ERROR") ? "var(--danger)" : "var(--text-muted)" }}>
                  {l}
                </div>
              ))}
              {logLines.length === 0 && (
                <div style={{ color: "var(--text-muted)", opacity: 0.5 }}>Waiting for pipeline events…</div>
              )}
            </div>
          </div>
        </>
      )}
    </div>
  );
}