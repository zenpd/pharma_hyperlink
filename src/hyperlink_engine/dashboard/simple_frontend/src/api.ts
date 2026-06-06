import type { Anomaly, Link, ScoreResponse, DocPreview, DetectionTraceData } from "./types";

const BASE = "/api/dossiers";
const DOSSIER = "demo";

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

export const api = {
  score: () => get<ScoreResponse>(`${BASE}/${DOSSIER}/score`),

  anomalies: async () => {
    const data = await get<AnomaliesResponse>(`${BASE}/${DOSSIER}/anomalies`);
    return data.anomalies;
  },

  links: async () => {
    const data = await get<LinksResponse>(`${BASE}/${DOSSIER}/links`);
    return data.links;
  },

  documentPreview: (docName: string) =>
    get<DocPreview>(`${BASE}/${DOSSIER}/document-preview?doc_name=${encodeURIComponent(docName)}`),

  detectionTrace: () =>
    get<DetectionTraceData>(`${BASE}/${DOSSIER}/detection-trace`),

  exportCsv: () => {
    window.open(`${BASE}/${DOSSIER}/export.csv`, "_blank");
  },

  exportXlsx: () => {
    window.open(`${BASE}/${DOSSIER}/export.xlsx`, "_blank");
  },
};
