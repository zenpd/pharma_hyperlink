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

export interface Link {
  source_doc: string;
  link_text: string;
  link_location_descriptor: string;
  target_doc: string;
  target_anchor: string;
  status: "ok" | "broken" | "unverified";
  confidence: number;
  error_msg: string | null;
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

export type Screen = "dashboard" | "issues" | "comparison" | "detection-trace";
export type SeverityFilter = "all" | "blocker" | "warning" | "info";
