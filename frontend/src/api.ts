import type {
  Anomaly,
  Link,
  LinkEdit,
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
  Me,
  SecurityMode,
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

/**
 * PLAN SEVEN — session cookies + 401 broadcast.
 *
 * Sessions are httpOnly cookies set by the backend's SuperTokens middleware;
 * `credentials: "include"` makes every call carry them even if the SPA is
 * ever served from a different origin (same-origin dev via the Vite proxy
 * works either way). A 401 means "no valid session" — broadcast it so the
 * Auth context can flip the app to the login screen.
 */
const CREDS: RequestCredentials = "include";

export const UNAUTHORIZED_EVENT = "hyperlink:unauthorized";

function broadcastIfUnauthorized(status: number): void {
  if (status === 401) {
    window.dispatchEvent(new CustomEvent(UNAUTHORIZED_EVENT));
  }
}

/**
 * Error thrown by the API helpers. Carries the HTTP status plus the parsed
 * FastAPI `detail` message so screens can render friendly, status-aware
 * errors (e.g. a 🔒 access-denied card for 403) instead of raw JSON bodies.
 * `message` stays human-readable for screens that just print it.
 */
export class ApiError extends Error {
  readonly status: number;
  readonly detail: string;

  constructor(status: number, body: string) {
    let detail = body || `HTTP ${status}`;
    try {
      const parsed = JSON.parse(body);
      if (typeof parsed?.detail === "string") detail = parsed.detail;
    } catch {
      /* body wasn't JSON — keep the raw text */
    }
    super(`API ${status}: ${detail}`);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
  }
}

async function get<T>(path: string): Promise<T> {
  const res = await fetch(path, { credentials: CREDS });
  if (!res.ok) {
    broadcastIfUnauthorized(res.status);
    const msg = await res.text().catch(() => res.statusText);
    throw new ApiError(res.status, msg);
  }
  return res.json() as Promise<T>;
}

async function post<T>(path: string, body?: unknown): Promise<T> {
  const res = await fetch(path, {
    method: "POST",
    credentials: CREDS,
    headers: body ? { "Content-Type": "application/json" } : {},
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) {
    broadcastIfUnauthorized(res.status);
    const msg = await res.text().catch(() => res.statusText);
    throw new ApiError(res.status, msg);
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
      classification?: "classified" | "unclassified" | "",
    ): Promise<{ run_id: string; dossier_id: string; files_received: string[]; preset?: string; agent_profile?: Record<string, string>; classification?: string }> => {
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
      if (classification) form.append("classification", classification);
      const res = await fetch(`${PIPELINE_BASE}/upload`, {
        method: "POST", body: form, credentials: CREDS,
      });
      if (!res.ok) {
        broadcastIfUnauthorized(res.status);
        throw new Error(`Upload failed: ${await res.text()}`);
      }
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

    /**
     * Open the ORIGINAL uploaded PDF inline in a new browser tab (PLAN TWELVE),
     * scrolled to `page` via the `#page=N` URL fragment (Edge/Chrome/Firefox all
     * honor it). `filename` may be the `_linked` name — the backend strips it and
     * serves the raw upload. Omit `page` to open at page 1.
     */
    openPdfAtPage: (runId: string, filename: string, page?: number | null) => {
      const frag = page && page > 0 ? `#page=${page}` : "";
      window.open(
        `${PIPELINE_BASE}/run/${runId}/view/${encodeURIComponent(filename)}${frag}`,
        "_blank",
        "noopener,noreferrer",
      );
    },

    /**
     * Open a WORD (or any non-PDF) target in a new browser tab (PLAN TWELVE,
     * Word path). Browsers can't render .docx inline, so we deep-link to the
     * app's own DocViewer (`#/docview`) which renders the document and scrolls to
     * `ref`. Same origin/path so the SPA bundle + session cookie are reused.
     */
    openDocViewer: (runId: string, doc: string, ref?: string) => {
      const qs = new URLSearchParams({ run: runId, doc });
      if (ref) qs.set("ref", ref);
      const url = `${window.location.origin}${window.location.pathname}#/docview?${qs.toString()}`;
      window.open(url, "_blank", "noopener,noreferrer");
    },

    /** Download the validation CSV for a run */
    downloadCsv: (runId: string) => {
      window.open(`${PIPELINE_BASE}/run/${runId}/csv`, "_blank");
    },

    /** Cancel a running pipeline (signals the runner to stop after current node) */
    cancel: (runId: string) =>
      post<{ run_id: string; signalled: boolean }>(`${PIPELINE_BASE}/run/${runId}/cancel`, {}),

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

    /**
     * Inline hyperlink edit — updates target_doc, target_anchor, and/or status
     * for a specific link identified by (source_doc, link_text).
     * Persists to in-memory run store and Neo4j (best-effort).
     */
    updateLink: async (runId: string, sourceDoc: string, linkText: string, edit: LinkEdit): Promise<Link> => {
      const params = new URLSearchParams({ source_doc: sourceDoc, link_text: linkText });
      const res = await fetch(`${PIPELINE_BASE}/run/${runId}/link?${params.toString()}`, {
        method: "PATCH",
        credentials: CREDS,
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(edit),
      });
      if (!res.ok) {
        broadcastIfUnauthorized(res.status);
        throw new Error(`Update failed: ${await res.text()}`);
      }
      const data = await res.json() as { updated: Link };
      return data.updated;
    },
  },

  // ── Auth + security (PLAN SEVEN) ───────────────────────────────────────
  //
  // The backend mounts SuperTokens' REST routes under /api/auth/* (cookie
  // sessions). The SPA talks to them with plain fetch — no SDK import — so
  // the app builds and runs identically when auth is off / the core is down.

  auth: {
    /** Session probe. Throws (401) when the gate is on and nobody is logged in. */
    me: () => get<Me>(`/api/me`),

    /** Email + password sign-in against the SuperTokens emailpassword recipe. */
    login: async (email: string, password: string): Promise<Me> => {
      const res = await fetch(`/api/auth/signin`, {
        method: "POST",
        credentials: CREDS,
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          formFields: [
            { id: "email", value: email },
            { id: "password", value: password },
          ],
        }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok || data.status !== "OK") {
        const reason =
          data.status === "WRONG_CREDENTIALS_ERROR"
            ? "Wrong email or password."
            : data?.formFields?.[0]?.error || data.status || `HTTP ${res.status}`;
        throw new Error(reason);
      }
      // Cookies are set — resolve the principal (roles come from the session).
      return get<Me>(`/api/me`);
    },

    /** Self-service sign-up (POC). New accounts start with no roles. */
    signup: async (email: string, password: string): Promise<Me> => {
      const res = await fetch(`/api/auth/signup`, {
        method: "POST",
        credentials: CREDS,
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          formFields: [
            { id: "email", value: email },
            { id: "password", value: password },
          ],
        }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok || data.status !== "OK") {
        const reason =
          data.status === "EMAIL_ALREADY_EXISTS_ERROR"
            ? "An account with this email already exists."
            : data?.formFields?.[0]?.error || data.status || `HTTP ${res.status}`;
        throw new Error(reason);
      }
      return get<Me>(`/api/me`);
    },

    logout: async (): Promise<void> => {
      await fetch(`/api/auth/signout`, { method: "POST", credentials: CREDS }).catch(() => {});
    },
  },

  security: {
    /** Gate status — public, safe to call whether or not auth is configured. */
    mode: () => get<SecurityMode>(`/api/security/mode`),
    /** Flip the gate (admin-only while active). Audit-logged server-side. */
    setMode: (enabled: boolean) => post<SecurityMode>(`/api/security/mode`, { enabled }),
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
