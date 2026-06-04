import base64
import json

from ..config import get_settings

settings = get_settings()

SYSTEM_PROMPT = (
    "You are a fraud-analysis assistant for a bank's document verification team. "
    "You DO NOT see the raw image. You only receive structured detector evidence "
    "(tamper scores, anomaly reasons) and OCR text. Based ONLY on this evidence, "
    "produce a concise, factual risk assessment. Never invent findings not present "
    "in the evidence. Respond ONLY with a JSON object matching the requested schema."
)

RESPONSE_SCHEMA_HINT = {
    "decision": "accept | review | reject",
    "confidence": "number between 0 and 1",
    "risk_level": "low | medium | high",
    "summary": "1-3 sentence human-readable explanation",
    "key_findings": ["short bullet strings citing the evidence"],
    "recommended_action": "short next step for the reviewer",
}


def _fallback(evidence: dict) -> dict:
    agg = evidence.get("aggregate", {})
    decision = agg.get("decision", "review")
    score = agg.get("tamper_score", 0.0)
    risk = "high" if decision == "reject" else "medium" if decision == "review" else "low"
    findings: list[str] = []
    for det in evidence.get("detectors", []):
        for reason in det.get("reasons", []):
            if "No " not in reason and "skipped" not in reason.lower():
                findings.append(f"{det['name']}: {reason}")
    return {
        "decision": decision,
        "confidence": round(min(0.5 + score / 2, 0.99), 2),
        "risk_level": risk,
        "summary": (
            f"Deterministic detectors produced a tamper score of {score}. "
            f"Recommended decision: {decision}. (LLM summary unavailable; using rule-based fallback.)"
        ),
        "key_findings": findings or ["No specific anomalies were flagged by the detectors."],
        "recommended_action": (
            "Escalate to manual review." if decision != "accept" else "No action required."
        ),
        "source": "fallback",
    }


def _build_client():
    """Build an AzureOpenAI client (API key or managed identity)."""
    if settings.foundry_api_key:
        from openai import AzureOpenAI

        return AzureOpenAI(
            azure_endpoint=settings.foundry_endpoint,
            api_key=settings.foundry_api_key,
            api_version=settings.foundry_api_version,
        )
    from azure.identity import DefaultAzureCredential, get_bearer_token_provider
    from openai import AzureOpenAI

    token_provider = get_bearer_token_provider(
        DefaultAzureCredential(),
        "https://cognitiveservices.azure.com/.default",
    )
    return AzureOpenAI(
        azure_endpoint=settings.foundry_endpoint,
        azure_ad_token_provider=token_provider,
        api_version=settings.foundry_api_version,
    )


def summarize(evidence: dict) -> dict:
    """Ask the Foundry model to explain the detector evidence as strict JSON.

    Falls back to a deterministic rule-based summary if the endpoint is not
    configured or the call/parse fails.
    """
    if not settings.foundry_endpoint:
        return _fallback(evidence)

    try:
        client = _build_client()

        user_content = (
            "Evidence (JSON):\n"
            + json.dumps(evidence, indent=2)
            + "\n\nReturn JSON with exactly these keys: "
            + json.dumps(RESPONSE_SCHEMA_HINT)
        )

        completion = client.chat.completions.create(
            model=settings.foundry_deployment,
            response_format={"type": "json_object"},
            temperature=0.1,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_content},
            ],
        )
        raw = completion.choices[0].message.content or "{}"
        parsed = json.loads(raw)
        parsed.setdefault("source", "foundry")
        return parsed
    except Exception:
        return _fallback(evidence)


VISION_JUDGE_PROMPT = (
    "You are a forensic document examiner. You are shown an image of a document. "
    "Inspect it visually for signs of tampering or AI generation, using this "
    "rubric: (1) font/kerning/baseline inconsistencies within a field or line "
    "(edited values often use a slightly different font or alignment); "
    "(2) mismatched anti-aliasing, blur, or compression around specific fields "
    "vs the rest of the page (a splice/overlay); (3) misaligned table cells, rows "
    "or borders; (4) inconsistent lighting/shadows on stamps, signatures or "
    "photos; (5) unnatural perfection or texture typical of AI-generated images; "
    "(6) logo/seal rendering that looks pasted or low quality. "
    "Judge ONLY what you can actually see. Respond with a strict JSON object: "
    '{"tamper_likelihood": 0.0-1.0, "findings": ["short visual observations"], '
    '"suspect_regions": ["where on the page"]}. If the document looks genuine, '
    "return a low likelihood and say so."
)


def vision_judge(image_bytes: bytes, content_type: str = "image/png") -> dict:
    """Tier 4 — multimodal LLM that visually inspects the rendered page.

    Returns a detector-style dict so it plugs straight into the aggregator.
    No-op (neutral) when disabled or unconfigured. This is independent visual
    reasoning, NOT a narration of the other detectors.
    """
    if not settings.enable_vision_judge or not settings.foundry_endpoint or not image_bytes:
        return {
            "name": "vision_judge",
            "score": 0.0,
            "reasons": [
                "Multimodal vision judge disabled or unconfigured "
                "(set ENABLE_VISION_JUDGE=true and a vision-capable "
                "FOUNDRY_DEPLOYMENT). Skipped."
            ],
            "details": {"enabled": False},
        }

    try:
        client = _build_client()
        b64 = base64.b64encode(image_bytes).decode("ascii")
        data_url = f"data:{content_type or 'image/png'};base64,{b64}"

        completion = client.chat.completions.create(
            model=settings.foundry_deployment,
            response_format={"type": "json_object"},
            temperature=0.1,
            messages=[
                {"role": "system", "content": VISION_JUDGE_PROMPT},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "Examine this document for tampering or AI generation."},
                        {"type": "image_url", "image_url": {"url": data_url}},
                    ],
                },
            ],
        )
        raw = completion.choices[0].message.content or "{}"
        parsed = json.loads(raw)
        score = float(parsed.get("tamper_likelihood", 0.0) or 0.0)
        findings = parsed.get("findings") or []
        regions = parsed.get("suspect_regions") or []

        reasons = [f"Vision examiner: {f}" for f in findings[:6]] or [
            "Vision examiner found no visible signs of tampering."
        ]
        return {
            "name": "vision_judge",
            "score": round(min(max(score, 0.0), 1.0), 3),
            "reasons": reasons,
            "details": {"enabled": True, "suspect_regions": regions, "source": "foundry-vision"},
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "name": "vision_judge",
            "score": 0.0,
            "reasons": [f"Vision judge call failed: {exc}"],
            "details": {"enabled": True, "error": str(exc)},
        }
