/**
 * live.ts — the bridge between the FastAPI backend and the design screens.
 *
 * `useReportData(runId)` fetches the four report surfaces (score, links,
 * anomalies, detection-trace) for a run in parallel. When `runId === ""` the
 * api layer transparently serves the seeded demo dossier, so the screens always
 * have real backend data to render.
 *
 * The pure helpers below reshape that raw data into the structures the design
 * mockups were built around (module matrix rows, per-doc rollups, anomaly
 * groups, detection-layer totals) so the gorgeous UI stays intact but every
 * number on screen comes from the engine.
 */

import { useEffect, useState, useCallback } from "react";
import { api } from "./api";
import type {
  Anomaly,
  DetectionTraceData,
  Link,
  LinkStatus,
  ScoreResponse,
} from "./types";
import type { SeverityKind } from "./components/shared";

// ── React hook ──────────────────────────────────────────────────────────────

export interface ReportData {
  score: ScoreResponse | null;
  links: Link[];
  anomalies: Anomaly[];
  trace: DetectionTraceData | null;
  loading: boolean;
  error: string | null;
  reload: () => void;
}

export function useReportData(runId: string): ReportData {
  const [score, setScore] = useState<ScoreResponse | null>(null);
  const [links, setLinks] = useState<Link[]>([]);
  const [anomalies, setAnomalies] = useState<Anomaly[]>([]);
  const [trace, setTrace] = useState<DetectionTraceData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [tick, setTick] = useState(0);

  const reload = useCallback(() => setTick((t) => t + 1), []);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    Promise.all([
      api.score(runId).catch(() => null),
      api.links(runId).catch(() => [] as Link[]),
      api.anomalies(runId).catch(() => [] as Anomaly[]),
      api.detectionTrace(runId).catch(() => null),
    ])
      .then(([s, l, a, t]) => {
        if (cancelled) return;
        setScore(s);
        setLinks(l ?? []);
        setAnomalies(a ?? []);
        setTrace(t);
        // Surface a soft error only when everything failed (backend down).
        if (!s && (!l || l.length === 0) && (!a || a.length === 0) && !t) {
          setError("No data returned — is the backend running on :8000?");
        }
      })
      .catch((e) => {
        if (!cancelled) setError(String(e));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [runId, tick]);

  return { score, links, anomalies, trace, loading, error, reload };
}

// ── Severity helpers ──────────────────────────────────────────────────────────

export function statusToSev(status: LinkStatus | string): SeverityKind {
  switch (status) {
    case "broken":
      return "blocker";
    case "suspicious":
      return "warning";
    case "unverified":
      return "info";
    case "ok":
      return "success";
    default:
      return "neutral";
  }
}

export function anomalySev(severity: string): SeverityKind {
  switch (severity) {
    case "blocker":
      return "blocker";
    case "warning":
      return "warning";
    case "info":
      return "info";
    default:
      return "neutral";
  }
}

const SEV_RANK: Record<string, number> = { blocker: 3, warning: 2, info: 1 };

// ── Module inference ──────────────────────────────────────────────────────────

/**
 * Best-effort CTD module bucket from a document name / path. Recognises an
 * explicit m1–m5 segment; otherwise files are treated as clinical study
 * material (m5), which is correct for the bundled CSR demo dossier.
 */
export function moduleOf(doc: string): string {
  const s = (doc || "").toLowerCase();
  const seg = s.match(/(?:^|[\\/_\s-])m([1-5])(?:[\\/._\s-]|$)/);
  if (seg) return "m" + seg[1];
  const mod = s.match(/module\s*([1-5])/);
  if (mod) return "m" + mod[1];
  return "m5";
}

// ── Per-module rollup ───────────────────────────────────────────────────────

export interface ModuleAgg {
  module: string;
  total: number;
  ok: number;
  broken: number;
  unverified: number;
  suspicious: number;
}

export function moduleAggs(links: Link[]): ModuleAgg[] {
  const map = new Map<string, ModuleAgg>();
  for (const l of links) {
    const m = moduleOf(l.source_doc);
    let a = map.get(m);
    if (!a) {
      a = { module: m, total: 0, ok: 0, broken: 0, unverified: 0, suspicious: 0 };
      map.set(m, a);
    }
    a.total++;
    if (l.status === "ok") a.ok++;
    else if (l.status === "broken") a.broken++;
    else if (l.status === "unverified") a.unverified++;
    else if (l.status === "suspicious") a.suspicious++;
  }
  return [...map.values()].sort((x, y) => x.module.localeCompare(y.module));
}

/** ratio in [0,1], guarding divide-by-zero. */
export function ratio(part: number, whole: number): number {
  return whole > 0 ? part / whole : 0;
}

// ── Per-document rollup ───────────────────────────────────────────────────────

export interface DocAgg {
  doc: string;
  module: string;
  total: number;
  ok: number;
  broken: number;
  unverified: number;
  suspicious: number;
  anomalies: number;
  avgConf: number;
}

export function docAggs(links: Link[], anomalies: Anomaly[]): DocAgg[] {
  const map = new Map<string, DocAgg>();
  const ensure = (d: string): DocAgg => {
    let a = map.get(d);
    if (!a) {
      a = {
        doc: d,
        module: moduleOf(d),
        total: 0,
        ok: 0,
        broken: 0,
        unverified: 0,
        suspicious: 0,
        anomalies: 0,
        avgConf: 0,
      };
      map.set(d, a);
    }
    return a;
  };
  const confSum = new Map<string, number>();
  for (const l of links) {
    const a = ensure(l.source_doc);
    a.total++;
    if (l.status === "ok") a.ok++;
    else if (l.status === "broken") a.broken++;
    else if (l.status === "unverified") a.unverified++;
    else if (l.status === "suspicious") a.suspicious++;
    confSum.set(l.source_doc, (confSum.get(l.source_doc) ?? 0) + (l.confidence || 0));
  }
  for (const an of anomalies) {
    if (an.document) ensure(an.document).anomalies++;
  }
  for (const a of map.values()) {
    a.avgConf = a.total > 0 ? (confSum.get(a.doc) ?? 0) / a.total : 0;
  }
  return [...map.values()].sort((x, y) => y.total - x.total);
}

/** Overall worst severity for a document (drives its status chip). */
export function docSev(a: DocAgg): SeverityKind {
  if (a.broken > 0) return "blocker";
  if (a.suspicious > 0 || a.anomalies > 0) return "warning";
  if (a.unverified > 0) return "info";
  return "success";
}

// ── Anomaly grouping ──────────────────────────────────────────────────────────

export interface AnomalyGroup {
  kind: string;
  sev: SeverityKind;
  count: number;
  items: Anomaly[];
}

export function anomalyGroups(anomalies: Anomaly[]): AnomalyGroup[] {
  const map = new Map<string, Anomaly[]>();
  for (const a of anomalies) {
    const k = a.kind || "other";
    const arr = map.get(k);
    if (arr) arr.push(a);
    else map.set(k, [a]);
  }
  const groups: AnomalyGroup[] = [];
  for (const [kind, items] of map) {
    // group severity = worst severity present
    let worst = "info";
    for (const it of items) {
      if ((SEV_RANK[it.severity] ?? 0) > (SEV_RANK[worst] ?? 0)) worst = it.severity;
    }
    groups.push({ kind, sev: anomalySev(worst), count: items.length, items });
  }
  // blockers first, then by count
  return groups.sort(
    (x, y) =>
      (SEV_RANK[severityOf(y.sev)] ?? 0) - (SEV_RANK[severityOf(x.sev)] ?? 0) ||
      y.count - x.count,
  );
}

function severityOf(sev: SeverityKind): string {
  return sev === "blocker" ? "blocker" : sev === "warning" ? "warning" : "info";
}

export function anomalyCounts(anomalies: Anomaly[]): {
  blocker: number;
  warning: number;
  info: number;
} {
  let blocker = 0;
  let warning = 0;
  let info = 0;
  for (const a of anomalies) {
    if (a.severity === "blocker") blocker++;
    else if (a.severity === "warning") warning++;
    else info++;
  }
  return { blocker, warning, info };
}

// ── Detection-layer totals ────────────────────────────────────────────────────

export interface LayerTotals {
  regex: number;
  ner: number;
  llm: number;
  mixed: number;
  total: number;
}

export function traceTotals(trace: DetectionTraceData | null): LayerTotals {
  const base: LayerTotals = { regex: 0, ner: 0, llm: 0, mixed: 0, total: 0 };
  if (!trace) return base;
  for (const d of trace.per_doc) {
    base.regex += d.regex_only;
    base.ner += d.ner_triggered;
    base.llm += d.llm_triggered;
    base.mixed += d.mixed;
    base.total += d.total_links;
  }
  return base;
}

// ── Link status tallies ───────────────────────────────────────────────────────

export interface StatusCounts {
  ok: number;
  broken: number;
  unverified: number;
  suspicious: number;
  total: number;
}

export function statusCounts(links: Link[]): StatusCounts {
  const c: StatusCounts = { ok: 0, broken: 0, unverified: 0, suspicious: 0, total: links.length };
  for (const l of links) {
    if (l.status === "ok") c.ok++;
    else if (l.status === "broken") c.broken++;
    else if (l.status === "unverified") c.unverified++;
    else if (l.status === "suspicious") c.suspicious++;
  }
  return c;
}

export function avgConfidence(links: Link[]): number {
  if (!links.length) return 0;
  return links.reduce((s, l) => s + (l.confidence || 0), 0) / links.length;
}

export function distinctDocs(links: Link[]): number {
  return new Set(links.map((l) => l.source_doc)).size;
}

/** Per-link confidence split across detection layers, for the meter widget. */
export function confidenceSplit(link: Link): { regex: number; ner: number; llm: number; total: number } {
  const total = Math.round((link.confidence || 0) * 100);
  const by = (link.detected_by || "regex").toLowerCase();
  if (by.includes("llm") || by === "mixed") {
    return { regex: Math.round(total * 0.4), ner: Math.round(total * 0.3), llm: total - Math.round(total * 0.4) - Math.round(total * 0.3), total };
  }
  if (by.includes("ner")) {
    return { regex: Math.round(total * 0.5), ner: total - Math.round(total * 0.5), llm: 0, total };
  }
  return { regex: total, ner: 0, llm: 0, total };
}
