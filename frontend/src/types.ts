// ── API response shapes matching FastAPI backend ────────────────────────────

export interface ScoreResponse {
  dossier_id: string;
  score: number;
  grade: string | null;
  broken_links: number;
  blocker_anomalies: number;
  is_submission_ready: boolean;
}

export interface Anomaly {
  kind: string;
  severity: "blocker" | "warning" | "info";
  document: string;
  text: string;
  suggested_fix: string;
  confidence: number;
  // local UI state (not from API)
  _id?: string;
  _status?: "open" | "fixed" | "ignored";
}

export type LinkStatus = "ok" | "broken" | "unverified" | "suspicious";

export interface Link {
  source_doc: string;
  link_text: string;
  link_location_descriptor: string;
  target_doc: string;
  target_anchor: string;
  /**
   * Authoritative link classification from the backend (node_validate):
   *   - "external_url"      → a real http(s) website (open in a new tab)
   *   - "cross_doc"         → points to another document in the run
   *   - "internal_bookmark" → a section/table anchor within this document
   *   - "cross_module"      → an eCTD cross-module reference
   * Optional for back-compat with runs that predate the field.
   */
  link_kind?: "external_url" | "internal_bookmark" | "cross_doc" | "cross_module" | string;
  /**
   * 1-based page of this reference's definition in the document the link opens
   * (PLAN TWELVE). Lets the Linked Documents pane open the target PDF in a new
   * tab at `#page=N`. Absent/None ⇒ open at page 1 (whole-document reference).
   */
  target_page?: number | null;
  status: LinkStatus;
  confidence: number;
  error_msg: string | null;
  detected_by?: string;
}

// Module matrix row
export interface ModuleRow {
  module: string;
  ok: number;
  broken: number;
  unverified: number;
  suspicious: number;
  total: number;
}

/**
 * One block of document content in reading order.
 *
 * `type` is the discriminator the UI renders on:
 *   - "paragraph" (or undefined, for back-compat) → a plain text paragraph
 *   - "table" → a real grid; `rows` holds the cell matrix
 *
 * `text` is always present (for tables it's a flattened mirror of the rows) so
 * legacy consumers — the demo Comparison screen, scroll-to-section search — keep
 * working without knowing about tables.
 */
export interface DocPreviewBlock {
  index: number;
  /** Index in doc.paragraphs (matches a link's location descriptor), so a link is
   * highlighted only in its own paragraph. Present for paragraph/image blocks. */
  para_index?: number;
  type?: "paragraph" | "table" | "image";
  text: string;
  rows?: string[][];
  /** Base64 data URI for an inline figure/chart (present when type === "image"). */
  src?: string;
}

/** @deprecated use DocPreviewBlock — kept as an alias for older imports. */
export type DocPreviewParagraph = DocPreviewBlock;

export interface DocPreview {
  doc_name: string;
  orig_path: string;
  paragraphs: DocPreviewBlock[];
  links: Link[];
  total_links: number;
  ok_links: number;
  unverified_links: number;
  broken_links: number;
}

// Google-style destination preview for a clicked link
export interface LinkSnippet {
  found: boolean;
  doc: string;
  found_in?: string;   // which document the section/table was located in
  anchor: string;
  matched?: boolean;
  is_table?: boolean;
  heading: string;
  snippet: string;
  message?: string;
}

// One stage in the document submission lifecycle (per-stage before/after)
export interface RunStage {
  stage: string;        // raw | linked | compliance_approved | fda_ready
  label: string;
  description: string;
  available: boolean;
  doc_count: number;
  meta?: { at?: string; by?: string; note?: string; changes?: string[] };
}

export interface RunStages {
  run_id: string;
  stages: RunStage[];
  docs: string[];
}

export interface DocumentComparison {
  source_doc: string;  // e.g., "study-001.docx"
  links_injected: number;
  links_ok: number;
  links_unverified: number;
  links_broken: number;
  input_path: string;   // e.g., "data/synthetic/m2/study-001.docx"
  output_path: string;  // e.g., "output/run1/m2/study-001.linked.docx"
}

export interface DetectionTracePerDoc {
  doc_name: string;
  total_links: number;
  regex_only: number;
  ner_triggered: number;
  llm_triggered: number;
  mixed: number;
}

export interface DetectionTraceData {
  total_docs: number;
  total_links: number;
  per_doc: DetectionTracePerDoc[];
}

export type Screen =
  | "dashboard"
  | "issues"
  | "comparison"
  | "detection-trace"
  | "pipeline"
  | "review"
  | "compliance"
  | "module-matrix"
  | "links-table"
  | "export"
  | "run-compare"
  | "reference-view";

// ── Selectable agents (Plan Three) ─────────────────────────────────────────────

export interface AgentSpec {
  id: string;
  layer: string;
  label: string;
  description: string;
  is_default: boolean;
}

export interface AgentCatalog {
  layers: string[];
  agents: Record<string, AgentSpec[]>;
  presets: Record<string, { label: string; profile: Record<string, string> }>;
  default_profile: Record<string, string>;
}

/** Per-run agent selection sent with an upload. */
export interface PipelineProfile {
  preset?: string;                      // "fast" | "balanced" | "max"
  overrides?: Record<string, string>;   // { layer: agent_id }
}

export type SeverityFilter = "all" | "blocker" | "warning" | "info";

/** Editable fields on a Link — used by the inline hyperlink editor. */
export interface LinkEdit {
  target_doc?: string;
  target_anchor?: string;
  status?: LinkStatus;
}

// ── Pipeline / Plan-Two types ─────────────────────────────────────────────────

export type PipelineNodeStatus = "pending" | "running" | "done" | "error";

export interface PipelineNodeState {
  name: string;
  label: string;
  status: PipelineNodeStatus;
  details?: Record<string, unknown>;
}

export interface PipelineEvent {
  run_id: string;
  node: string;
  status: string;
  details?: Record<string, unknown>;
}

export interface PerDocResult {
  filename: string;
  links: number;
  /**
   * PLAN FIFTEEN — per-document link-type breakdown (mirrors the BeforeAfter
   * stat row). `internal + cross_doc + external === links`; `broken` is a
   * status overlay counted independently. Optional for back-compat: the
   * average-fallback path (no per_doc) leaves these undefined.
   */
  internal?: number;
  cross_doc?: number;
  external?: number;
  broken?: number;
}

export interface RunSummary {
  run_id: string;
  dossier_id: string;
  status: string;
  current_node: string | null;
  score: number | null;
  grade: string | null;
  total_links: number;
  linked_files: string[];
  /** PLAN SEVEN Feature B — access tier; absent on legacy runs (= unclassified). */
  classification?: "classified" | "unclassified" | string;
  /** user_id of the uploader (audit trail). */
  owner?: string;
  /** Real per-document link counts (only present on the /results endpoint). */
  per_doc?: PerDocResult[];
  error: string | null;
}

export interface DocLinkSummary {
  filename: string;
  links_detected: number;
  links_injected: number;
  status: "ok" | "partial" | "error";
}

// ── Review queue types ────────────────────────────────────────────────────────

export type ReviewStatus = "pending_review" | "approved" | "rejected" | "submitted";

export interface ReviewRun {
  run_id: string;
  dossier_id: string;
  score: number;
  grade: string;
  total_links: number;
  broken_links: number;
  linked_files: string[];
  review_status: ReviewStatus;
  reviewer?: string;
  review_comment?: string;
  reviewed_at?: string;
  completed_at: string;
}

// ── Auth + security (PLAN SEVEN) ──────────────────────────────────────────────

/** The caller's resolved identity, from GET /api/me. */
export interface Me {
  user_id: string;
  email: string;
  roles: string[];
  is_admin: boolean;
  can_read_classified: boolean;
  security_enabled: boolean;
}

/** Security-gate status, from GET /api/security/mode. */
export interface SecurityMode {
  enabled: boolean;
  source: "settings" | "override" | string;
  supertokens_available: boolean;
}

// ── Compliance gate types ─────────────────────────────────────────────────────

export type ComplianceItemStatus = "pass" | "fail" | "warning" | "checking";

export interface ComplianceItem {
  id: string;
  label: string;
  description: string;
  status: ComplianceItemStatus;
  detail?: string;
}

export interface ComplianceResult {
  run_id: string;
  dossier_id: string;
  items: ComplianceItem[];
  overall_pass: boolean;
  ectd_version: string;
  checked_at: string;
}
