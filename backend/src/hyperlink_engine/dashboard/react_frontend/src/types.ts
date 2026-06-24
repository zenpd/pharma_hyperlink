// ── API response shapes matching FastAPI backend ────────────────────────────
//
// Ported verbatim from simple_frontend so the two dashboards share the exact
// same backend contract. Do not diverge these shapes from the backend.

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

export interface DocPreviewParagraph {
  index: number;
  text: string;
}

export interface DocPreview {
  doc_name: string;
  orig_path: string;
  paragraphs: DocPreviewParagraph[];
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
