from app.config import get_settings
from app.pipeline.ocr.base import OcrFailed, OcrProvider, OcrUnavailable, PageText

_override: OcrProvider | None = None


def set_provider(provider: OcrProvider | None) -> None:
    """Test hook: replace the configured provider."""
    global _override
    _override = provider


def get_provider() -> OcrProvider:
    if _override is not None:
        return _override
    s = get_settings()
    if s.ocr_provider == "azure":
        if not (s.azure_di_endpoint and s.azure_di_key):
            raise OcrUnavailable("OCR_PROVIDER=azure but AZURE_DI_ENDPOINT/AZURE_DI_KEY are not set")
        from app.pipeline.ocr.azure import AzureDocumentIntelligenceOcr

        return AzureDocumentIntelligenceOcr(s.azure_di_endpoint, s.azure_di_key)
    from app.pipeline.ocr.tesseract import TesseractOcr

    return TesseractOcr(lang=s.tesseract_lang)


__all__ = ["OcrFailed", "OcrProvider", "OcrUnavailable", "PageText", "get_provider", "set_provider"]
