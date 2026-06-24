import type {
  Anomaly,
  Link,
  ScoreResponse,
  DocPreview,
  LinkSnippet,
  RunStages,
  DetectionTraceData,
  RunSummary,
  ReviewRun,
  ComplianceResult,
  AgentCatalog,
  PipelineProfile,
} from "./types";

const BASE = "/api/dossiers";
const DOSSIER = "demo";
const PIPELINE_BASE = "/api/pipeline";
const REVIEW_BASE = "/api/review";
const COMPLIANCE_BASE = "/api/compliance";

interface AnomaliesResponse {
  dossier_id: string;
  anomalies: Anomaly[];
  count: number;
}

interface LinksResponse {
  dossier_id: string;
  links: Link[];
  count: number;
}

async function get<T>(path: string): Promise<T> {
  const res = await fetch(path);
  if (!res.ok) {
    const msg = await res.text().catch(() => res.statusText);
    throw new Error(`API ${res.status}: ${msg}`);
  }
  return res.json() as Promise<T>;
}

async function post<T>(path: string, body?: unknown): Promise<T> {
  const res = await fetch(path, {
    method: "POST",
    headers: body ? { "Content-Type": "application/json" } : {},
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) {
    const msg = await res.text().catch(() => res.statusText);
    throw new Error(`API ${res.status}: ${msg}`);
  }
  return res.json() as Promise<T>;
}

// Report endpoints accept an optional `runId`. When a non-empty run id is
// passed they hit the live run-scoped pipeline endpoints
// (/api/pipeline/run/{id}/...); otherwise they fall back to the seeded demo
// dossier (/api/dossiers/demo/...). This lets the Reports/Analysis screens
// follow the pipeline run selected in the Run Selector, while staying
// backward-compatible with callers that pass no argument.
const rid = (v: unknown): string => (typeof v === "string" ? v : "");

export const api = {
  // ── Report endpoints (demo seed OR live run) ─────────────────────────────
  score: (runId = "") =>
    get<ScoreResponse>(
      rid(runId) ? `${PIPELINE_BASE}/run/${rid(runId)}/score` : `${BASE}/${DOSSIER}/score`,
    ),

  anomalies: async (runId = "") => {
    const url = rid(runId) ? `${PIPELINE_BASE}/run/${rid(runId)}/anomalies` : `${BASE}/${DOSSIER}/anomalies`;
    const data = await get<AnomaliesResponse>(url);
    return data.anomalies;
  },

  links: async (runId = "") => {
    const url = rid(runId) ? `${PIPELINE_BASE}/run/${rid(runId)}/links` : `${BASE}/${DOSSIER}/links`;
    const data = await get<LinksResponse>(url);
    return data.links;
  },

  documentPreview: (docName: string, runId = "") =>
    rid(runId)
      ? get<DocPreview>(`${PIPELINE_BASE}/run/${rid(runId)}/document-preview?doc=${encodeURIComponent(docName)}`)
      : get<DocPreview>(`${BASE}/${DOSSIER}/document-preview?doc_name=${encodeURIComponent(docName)}`),

  detectionTrace: (runId = "") =>
    get<DetectionTraceData>(
      rid(runId) ? `${PIPELINE_BASE}/run/${rid(runId)}/detection-trace` : `${BASE}/${DOSSIER}/detection-trace`,
    ),

  exportCsv: (runId = "") => {
    const id = rid(runId);
    window.open(id ? `${PIPELINE_BASE}/run/${id}/export.csv` : `${BASE}/${DOSSIER}/export.csv`, "_blank");
  },
  exportXlsx: (runId = "") => {
    const id = rid(runId);
    window.open(id ? `${PIPELINE_BASE}/run/${id}/export.xlsx` : `${BASE}/${DOSSIER}/export.xlsx`, "_blank");
  },

  // ── Agent catalog (Plan Three) ──────────────────────────────────────────
  agents: () => get<AgentCatalog>(`/api/agents`),

  // ── Pipeline (Plan Two) ─────────────────────────────────────────────────

  pipeline: {
    /**
     * Upload .docx/.pdf files. Optional `profile` selects a preset
     * (fast/balanced/max); optional `agents` is a per-layer override map.
     */
    upload: async (
      files: File[],
      dossierId = "",
      profile?: PipelineProfile,
    ): Promise<{ run_id: string; dossier_id: string; files_received: string[]; preset?: string; agent_profile?: Record<string, string> }> => {
      const form = new FormData();
      // Append each file with its relative path (folder uploads via
      // webkitdirectory) so the backend can recreate the nested structure.
      // `paths[i]` lines up with `files[i]`; plain file picks send the bare name.
      files.forEach((f) => {
        form.append("files", f);
        form.append("paths", f.webkitRelativePath || f.name);
      });
      form.append("dossier_id", dossierId);
      if (profile?.preset) form.append("profile", profile.preset);
      if (profile?.overrides && Object.keys(profile.overrides).length > 0) {
        form.append("agents", JSON.stringify(profile.overrides));
      }
      const res = await fetch(`${PIPELINE_BASE}/upload`, { method: "POST", body: form });
      if (!res.ok) throw new Error(`Upload failed: ${await res.text()}`);
      return res.json();
    },

    /** Kick off background pipeline execution */
    run: (runId: string) =>
      post<{ run_id: string; status: string }>(`${PIPELINE_BASE}/run/${runId}`),

    /** Open a live SSE stream — caller must close EventSource when done */
    stream: (runId: string): EventSource =>
      new EventSource(`${PIPELINE_BASE}/stream/${runId}`),

    /** One-shot status snapshot */
    status: (runId: string) => get<RunSummary>(`${PIPELINE_BASE}/status/${runId}`),

    /** Final results after completion */
    results: (runId: string) => get<RunSummary & { anomalies: Anomaly[] }>(`${PIPELINE_BASE}/run/${runId}/results`),

    /** All runs this server session */
    listRuns: () => get<{ runs: RunSummary[] }>(`${PIPELINE_BASE}/runs`),

    /** Download a linked output file */
    downloadLinked: (runId: string, filename: string) => {
      window.open(`${PIPELINE_BASE}/run/${runId}/download/${encodeURIComponent(filename)}`, "_blank");
    },

    /** Download the validation CSV for a run */
    downloadCsv: (runId: string) => {
      window.open(`${PIPELINE_BASE}/run/${runId}/csv`, "_blank");
    },

    /** Before/after preview for one document in a finished run */
    documentPreview: (runId: string, doc: string) =>
      get<DocPreview>(`${PIPELINE_BASE}/run/${runId}/document-preview?doc=${encodeURIComponent(doc)}`),

    /** Google-style destination preview for a link (target heading + excerpt) */
    linkSnippet: (runId: string, doc: string, anchor = "") =>
      get<LinkSnippet>(
        `${PIPELINE_BASE}/run/${runId}/snippet?doc=${encodeURIComponent(doc)}&anchor=${encodeURIComponent(anchor)}`,
      ),

    /** Submission-lifecycle stages for a run (raw → linked → compliance → FDA) */
    stages: (runId: string) =>
      get<RunStages>(`${PIPELINE_BASE}/run/${runId}/stages`),

    /** Snapshot the prior stage into a new lifecycle stage */
    advanceStage: (runId: string, stage: string, note = "") =>
      post<{ run_id: string; stage: string; doc_count: number }>(
        `${PIPELINE_BASE}/run/${runId}/advance-stage`, { stage, note },
      ),

    /** Before/after preview for one document at a specific lifecycle stage */
    stagePreview: (runId: string, doc: string, stage: string) =>
      get<DocPreview>(
        `${PIPELINE_BASE}/run/${runId}/stage-preview?doc=${encodeURIComponent(doc)}&stage=${encodeURIComponent(stage)}`,
      ),
  },

  // ── Review queue (HITL) ────────────────────────────────────────────────

  review: {
    queue: () => get<{ runs: ReviewRun[] }>(`${REVIEW_BASE}/queue`),
    approve: (runId: string, comment = "") =>
      post<{ status: string }>(`${REVIEW_BASE}/${runId}/approve`, { comment }),
    reject: (runId: string, comment: string) =>
      post<{ status: string }>(`${REVIEW_BASE}/${runId}/reject`, { comment }),
  },

  // ── Compliance gate ────────────────────────────────────────────────────

  compliance: {
    check: (runId: string) => get<ComplianceResult>(`${COMPLIANCE_BASE}/${runId}`),
    submit: (runId: string, authority: string) =>
      post<{ status: string; reference_number: string }>(`${COMPLIANCE_BASE}/${runId}/submit`, { authority }),
  },
};
