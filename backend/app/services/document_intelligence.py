import logging

from ..config import get_settings

logger = logging.getLogger("docuguard.docintel")
settings = get_settings()


def _local_ocr(image_bytes: bytes) -> dict:
    """Local OCR fallback using Tesseract (pytesseract).

    Lets the content/figure consistency checks run without Azure. Returns an
    explicit 'available: False' result if Tesseract is not installed, with
    guidance, so the pipeline still completes.
    """
    try:
        import io

        import pytesseract
        from PIL import Image

        text = pytesseract.image_to_string(Image.open(io.BytesIO(image_bytes)))
        if not text.strip():
            return {"available": False, "reason": "Local OCR produced no text.", "text": ""}
        return {"available": True, "text": text[:6000], "fields": {}, "source": "tesseract"}
    except Exception as exc:  # noqa: BLE001
        return {
            "available": False,
            "reason": (
                "No OCR available. Configure Azure Document Intelligence "
                "(DOCINTEL_ENDPOINT) or install Tesseract for local OCR. "
                f"({exc})"
            ),
            "text": "",
        }


def extract(image_bytes: bytes) -> dict:
    """Run Azure Document Intelligence OCR + layout on the uploaded document.

    Returns a compact, LLM-friendly summary: full text, key-value fields, and
    table count. Falls back to local Tesseract OCR when Document Intelligence
    is not configured so figure-consistency checks still run locally.
    """
    if not settings.docintel_endpoint:
        return _local_ocr(image_bytes)

    try:
        from azure.ai.documentintelligence import DocumentIntelligenceClient
        from azure.ai.documentintelligence.models import AnalyzeDocumentRequest

        if settings.docintel_key:
            from azure.core.credentials import AzureKeyCredential

            credential = AzureKeyCredential(settings.docintel_key)
        else:
            from azure.identity import DefaultAzureCredential

            credential = DefaultAzureCredential()

        client = DocumentIntelligenceClient(
            endpoint=settings.docintel_endpoint, credential=credential
        )
        poller = client.begin_analyze_document(
            settings.docintel_model_id,
            AnalyzeDocumentRequest(bytes_source=image_bytes),
        )
        result = poller.result()

        fields: dict[str, str] = {}
        for kv in getattr(result, "key_value_pairs", None) or []:
            if kv.key and kv.value:
                fields[kv.key.content] = kv.value.content

        text = getattr(result, "content", "") or ""
        return {
            "available": True,
            "text": text[:6000],
            "fields": fields,
            "page_count": len(getattr(result, "pages", []) or []),
            "table_count": len(getattr(result, "tables", []) or []),
        }
    except Exception:  # noqa: BLE001
        # Azure call failed; try local OCR so figure checks still run.
        logger.exception("Document Intelligence call failed; falling back to local OCR")
        return _local_ocr(image_bytes)
