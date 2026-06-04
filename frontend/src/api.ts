export interface DetectorResult {
  name: string;
  score: number;
  reasons: string[];
  details: Record<string, unknown>;
}

export interface AggregateResult {
  tamper_score: number;
  decision: string;
  hard_triggers: string[];
}

export interface LlmSummary {
  decision?: string;
  confidence?: number;
  risk_level?: string;
  summary?: string;
  key_findings?: string[];
  recommended_action?: string;
  source?: string;
}

export interface AnalysisResult {
  analysis_id: string;
  doc_type: string;
  status: string;
  file_uri: string;
  overlay_uri: string;
  detector_scores: { detectors?: DetectorResult[]; aggregate?: AggregateResult };
  ocr_summary: Record<string, unknown>;
  tamper_score: number;
  decision: string;
  llm_summary: LlmSummary;
  error: string;
  created_at: string | null;
  completed_at: string | null;
}

export async function submitAnalysis(file: File, docType: string): Promise<{ analysis_id: string }> {
  const form = new FormData();
  form.append("file", file);
  form.append("doc_type", docType);
  const res = await fetch("/api/analyze", { method: "POST", body: form });
  if (!res.ok) {
    const detail = await res.json().catch(() => ({}));
    throw new Error(detail.detail || `Upload failed (${res.status})`);
  }
  return res.json();
}

export async function getAnalysis(id: string): Promise<AnalysisResult> {
  const res = await fetch(`/api/analyze/${id}`);
  if (!res.ok) throw new Error(`Fetch failed (${res.status})`);
  return res.json();
}

export async function requestSecondOpinion(id: string): Promise<AnalysisResult> {
  const res = await fetch(`/api/analyze/${id}/second-opinion`, { method: "POST" });
  if (!res.ok) {
    const detail = await res.json().catch(() => ({}));
    throw new Error(detail.detail || `Second opinion failed (${res.status})`);
  }
  return res.json();
}

export async function getHealth(): Promise<{ foundry_configured?: boolean }> {
  const res = await fetch("/api/health");
  if (!res.ok) throw new Error(`Health check failed (${res.status})`);
  return res.json();
}
