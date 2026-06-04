import { useEffect, useRef, useState } from "react";
import {
  AnalysisResult,
  getAnalysis,
  getHealth,
  requestSecondOpinion,
  submitAnalysis,
} from "./api";

const DOC_TYPES = [
  { value: "kyc", label: "KYC Document" },
  { value: "id_card", label: "ID / PAN / Aadhaar" },
  { value: "passport", label: "Passport" },
  { value: "claim", label: "Insurance Claim" },
  { value: "bank_statement", label: "Bank Statement" },
  { value: "invoice", label: "Invoice" },
  { value: "unknown", label: "Other" },
];

const SCAN_STEPS = [
  "Inspecting metadata & EXIF signatures",
  "Error-level analysis (splice detection)",
  "Copy-move / clone scan",
  "AI-generation & rendering check",
  "OCR + content/figure validation",
  "Aggregating risk & generating summary",
];

function decisionClass(decision: string): string {
  if (decision === "reject") return "badge badge-reject";
  if (decision === "review") return "badge badge-review";
  if (decision === "accept") return "badge badge-accept";
  return "badge";
}

export default function App() {
  const [file, setFile] = useState<File | null>(null);
  const [preview, setPreview] = useState<string>("");
  const [docType, setDocType] = useState("kyc");
  const [result, setResult] = useState<AnalysisResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [secondOpinionLoading, setSecondOpinionLoading] = useState(false);
  const [secondOpinionError, setSecondOpinionError] = useState("");
  const [foundryConfigured, setFoundryConfigured] = useState(false);
  const pollRef = useRef<number | null>(null);

  useEffect(() => {
    return () => {
      if (pollRef.current) window.clearInterval(pollRef.current);
    };
  }, []);

  useEffect(() => {
    getHealth()
      .then((h) => setFoundryConfigured(Boolean(h.foundry_configured)))
      .catch(() => setFoundryConfigured(false));
  }, []);

  function onFile(f: File | null) {
    setFile(f);
    setResult(null);
    setError("");
    setSecondOpinionError("");
    if (f && f.type.startsWith("image/")) setPreview(URL.createObjectURL(f));
    else setPreview("");
  }

  async function onSubmit() {
    if (!file) return;
    setLoading(true);
    setError("");
    setSecondOpinionError("");
    setResult(null);
    try {
      const { analysis_id } = await submitAnalysis(file, docType);
      pollRef.current = window.setInterval(async () => {
        try {
          const r = await getAnalysis(analysis_id);
          setResult(r);
          if (r.status === "completed" || r.status === "failed") {
            if (pollRef.current) window.clearInterval(pollRef.current);
            setLoading(false);
          }
        } catch (e) {
          // keep polling; transient errors are expected early on
        }
      }, 1200);
    } catch (e) {
      setError((e as Error).message);
      setLoading(false);
    }
  }

  async function onSecondOpinion() {
    if (!result) return;
    setSecondOpinionLoading(true);
    setSecondOpinionError("");
    try {
      const updated = await requestSecondOpinion(result.analysis_id);
      setResult(updated);
    } catch (e) {
      setSecondOpinionError((e as Error).message);
    } finally {
      setSecondOpinionLoading(false);
    }
  }

  const allDetectors = result?.detector_scores?.detectors ?? [];
  // The vision judge is advisory; never list it among the deterministic detectors.
  const detectors = allDetectors.filter((d) => d.name !== "vision_judge");
  const llm = result?.llm_summary;
  const secondOpinion = result?.detector_scores?.second_opinion;
  const secondOpinionApplied = Boolean(secondOpinion?.details?.enabled);
  const sr = secondOpinion?.details?.suspect_regions;
  const suspectRegions = Array.isArray(sr) ? (sr as string[]) : [];
  const isProcessing =
    loading &&
    (!result || (result.status !== "completed" && result.status !== "failed"));

  return (
    <div className="app">
      <header className="topbar">
        <div className="brand">
          <span className="brand-mark">DG</span>
          <div>
            <div className="brand-name">DocuGuard</div>
            <div className="brand-sub">AI TamperLens</div>
          </div>
        </div>
        <div className="topbar-tag">Document Integrity &amp; Fraud Screening</div>
      </header>

      <main className="container">
        <section className="card upload-card">
          <h2 className="card-title">Verify a Document</h2>
          <p className="card-help">
            Upload a banking, KYC, or claims document image. DocuGuard runs forensic
            tamper checks and produces an explainable risk decision.
          </p>

          <label className="field-label">Document type</label>
          <select
            className="select"
            value={docType}
            onChange={(e) => setDocType(e.target.value)}
          >
            {DOC_TYPES.map((d) => (
              <option key={d.value} value={d.value}>
                {d.label}
              </option>
            ))}
          </select>

          <label
            className="dropzone"
            onDragOver={(e) => e.preventDefault()}
            onDrop={(e) => {
              e.preventDefault();
              onFile(e.dataTransfer.files?.[0] ?? null);
            }}
          >
            <input
              type="file"
              accept="image/png,image/jpeg,image/tiff,image/webp,application/pdf"
              onChange={(e) => onFile(e.target.files?.[0] ?? null)}
              hidden
            />
            {preview ? (
              <img src={preview} alt="preview" className="preview" />
            ) : file ? (
              <div className="dropzone-empty">
                <div className="dropzone-icon">📄</div>
                <div>{file.name}</div>
                <div className="dropzone-hint">PDF selected — ready to analyze</div>
              </div>
            ) : (
              <div className="dropzone-empty">
                <div className="dropzone-icon">⬆</div>
                <div>Click or drag a document here</div>
                <div className="dropzone-hint">PDF, JPG, PNG, TIFF, WEBP — up to 15 MB</div>
              </div>
            )}
          </label>

          <button
            className="btn-primary"
            disabled={!file || loading}
            onClick={onSubmit}
          >
            {loading ? "Analyzing…" : "Run Tamper Analysis"}
          </button>
          {error && <div className="error">{error}</div>}
        </section>

        <section className="card result-card">
          <h2 className="card-title">Analysis Result</h2>

          {!result && !loading && (
            <div className="placeholder">Results will appear here after analysis.</div>
          )}

          {isProcessing && (
            <div className="analyzing">
              <div className="scan-wrap">
                {preview ? (
                  <img src={preview} alt="scanning" className="scan-img" />
                ) : (
                  <div className="scan-img scan-img-empty" />
                )}
                <div className="scan-line" />
                <div className="scan-grid" />
              </div>

              <div className="analyzing-status">
                <div className="spinner" />
                <span>
                  {result?.status === "processing"
                    ? "Running forensic detectors…"
                    : "Submitting document…"}
                </span>
              </div>

              <ul className="scan-steps">
                {SCAN_STEPS.map((s, i) => (
                  <li
                    key={s}
                    className="scan-step"
                    style={{ animationDelay: `${i * 0.45}s` }}
                  >
                    <span className="scan-step-dot" />
                    {s}
                  </li>
                ))}
              </ul>

              <div className="skeleton skeleton-line w-90" />
              <div className="skeleton skeleton-line w-70" />
              <div className="skeleton skeleton-line w-80" />
            </div>
          )}

          {result?.status === "failed" && (
            <div className="error">Analysis failed: {result.error}</div>
          )}

          {result?.status === "completed" && (
            <div className="result-body">
              <div className="decision-row">
                <span className={decisionClass(result.decision)}>
                  {result.decision.toUpperCase()}
                </span>
                <div className="score-block">
                  <div className="score-value">
                    {(result.tamper_score * 100).toFixed(0)}
                    <span className="score-unit">/100</span>
                  </div>
                  <div className="score-label">Tamper Score</div>
                </div>
              </div>

              <div className="meter">
                <div
                  className="meter-fill"
                  style={{ width: `${result.tamper_score * 100}%` }}
                />
              </div>

              {llm?.summary && (
                <div className="summary">
                  <div className="summary-title">
                    Risk Summary
                    {llm.source && <span className="src-tag">{llm.source}</span>}
                  </div>
                  <p>{llm.summary}</p>
                  {llm.key_findings && llm.key_findings.length > 0 && (
                    <ul>
                      {llm.key_findings.map((k, i) => (
                        <li key={i}>{k}</li>
                      ))}
                    </ul>
                  )}
                  {llm.recommended_action && (
                    <p className="reco">
                      <strong>Recommended action:</strong> {llm.recommended_action}
                    </p>
                  )}
                </div>
              )}

              <div className="second-opinion">
                {secondOpinionApplied ? (
                  <div className="second-opinion-result">
                    <div className="second-opinion-done">
                      <span className="src-tag">AI vision</span>
                      AI second opinion (advisory) — an independent multimodal model
                      visually inspected this document. This does{" "}
                      <strong>not</strong> change the tamper score or decision above.
                    </div>
                    <div className="second-opinion-verdict">
                      Vision tamper likelihood:{" "}
                      <strong>
                        {((secondOpinion?.score ?? 0) * 100).toFixed(0)}/100
                      </strong>
                    </div>
                    {secondOpinion?.reasons?.length ? (
                      <ul className="reasons">
                        {secondOpinion.reasons.map((r, i) => (
                          <li key={i}>{r}</li>
                        ))}
                      </ul>
                    ) : null}
                    {suspectRegions.length > 0 && (
                      <div className="second-opinion-regions">
                        <strong>Suspect regions:</strong> {suspectRegions.join(", ")}
                      </div>
                    )}
                  </div>
                ) : (
                  <>
                    <div className="second-opinion-copy">
                      <strong>Want a stronger check?</strong> The base result uses
                      fast, deterministic forensic detectors. You can ask an AI
                      multimodal model to visually inspect the document and give an
                      independent second opinion.
                    </div>
                    <button
                      className="btn-secondary"
                      disabled={secondOpinionLoading || !foundryConfigured}
                      onClick={onSecondOpinion}
                      title={
                        foundryConfigured
                          ? "Run the AI vision judge on this document"
                          : "Unavailable: no AI model endpoint configured"
                      }
                    >
                      {secondOpinionLoading
                        ? "Consulting AI examiner…"
                        : "🔎 Get AI Second Opinion"}
                    </button>
                    {!foundryConfigured && (
                      <div className="second-opinion-hint">
                        AI second opinion is unavailable — no model endpoint is
                        configured for this environment.
                      </div>
                    )}
                    {secondOpinionError && (
                      <div className="error">{secondOpinionError}</div>
                    )}
                  </>
                )}
              </div>

              <div className="detectors">
                <div className="detectors-title">Forensic Detectors</div>
                {detectors.map((d) => (
                  <div key={d.name} className="detector">
                    <div className="detector-head">
                      <span className="detector-name">
                        {d.name.replace(/_/g, " ")}
                      </span>
                      <span className="detector-score">
                        {(d.score * 100).toFixed(0)}
                      </span>
                    </div>
                    <div className="meter meter-sm">
                      <div
                        className="meter-fill"
                        style={{ width: `${d.score * 100}%` }}
                      />
                    </div>
                    <ul className="reasons">
                      {d.reasons.map((r, i) => (
                        <li key={i}>{r}</li>
                      ))}
                    </ul>
                  </div>
                ))}
              </div>

              {result.overlay_uri && (
                <div className="overlay-note">
                  Heatmap artifact generated (ELA overlay stored).
                </div>
              )}
            </div>
          )}
        </section>
      </main>

      <footer className="footer">
        DocuGuard AI TamperLens — Demo MVP. Decisions are advisory and require human review.
      </footer>
    </div>
  );
}
