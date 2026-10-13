"""Azure Document Intelligence adapter against recorded response shapes (no network)."""

import httpx
import pytest
from PIL import Image

from app.pipeline.ocr.azure import AzureDocumentIntelligenceOcr
from app.pipeline.ocr.base import OcrFailed, OcrUnavailable

RESULT = {
    "status": "succeeded",
    "analyzeResult": {
        "pages": [{
            "width": 1000, "height": 500, "unit": "pixel",
            "lines": [{"content": "CPF 123.456.789-09", "spans": [{"offset": 0, "length": 18}]}],
            "words": [
                {"content": "CPF", "polygon": [10, 10, 60, 10, 60, 30, 10, 30], "confidence": 0.99, "span": {"offset": 0, "length": 3}},
                {"content": "123.456.789-09", "polygon": [70, 10, 300, 10, 300, 30, 70, 30], "confidence": 0.93, "span": {"offset": 4, "length": 14}},
            ],
        }]
    },
}


def provider(handler):
    client = httpx.Client(transport=httpx.MockTransport(handler))
    return AzureDocumentIntelligenceOcr("https://exemplo.cognitiveservices.azure.com", "chave-de-teste", client=client, poll_seconds=0)


def test_reads_words_lines_and_boxes():
    calls = []

    def handler(req: httpx.Request):
        calls.append(req)
        if req.method == "POST":
            assert req.headers["Ocp-Apim-Subscription-Key"] == "chave-de-teste"
            assert "prebuilt-read:analyze" in str(req.url)
            return httpx.Response(202, headers={"Operation-Location": "https://exemplo/op/1"})
        return httpx.Response(200, json=RESULT)

    page = provider(handler).recognize(Image.new("RGB", (1000, 500), "white"), 0)
    assert page.text == "CPF 123.456.789-09"
    w = page.lines[0].words[1]
    assert w.conf == 0.93 and w.bbox == pytest.approx((0.07, 0.02, 0.3, 0.06))


def test_rate_limit_is_transient():
    with pytest.raises(OcrUnavailable):
        provider(lambda req: httpx.Response(429)).recognize(Image.new("RGB", (300, 300)), 0)


def test_bad_request_is_permanent():
    with pytest.raises(OcrFailed):
        provider(lambda req: httpx.Response(400, text="InvalidImage")).recognize(Image.new("RGB", (300, 300)), 0)


def test_failed_analysis_is_permanent():
    def handler(req):
        if req.method == "POST":
            return httpx.Response(202, headers={"Operation-Location": "https://exemplo/op/2"})
        return httpx.Response(200, json={"status": "failed", "error": {"code": "x"}})

    with pytest.raises(OcrFailed):
        provider(handler).recognize(Image.new("RGB", (300, 300)), 0)
