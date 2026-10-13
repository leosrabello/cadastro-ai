"""Azure AI Document Intelligence (prebuilt-read) over its REST API.

Written against the 2024-11-30 GA API and covered by tests with recorded response shapes.
It has not been exercised against a live Azure resource from this repository: that needs
AZURE_DI_ENDPOINT and AZURE_DI_KEY for a resource in a region approved by the DPO
(Brazil South keeps processing in Brazil).
"""

import io
import time

import httpx
from PIL import Image

from app.pipeline.ocr.base import OcrFailed, OcrUnavailable, PageText, Word, lines_from_words

API_VERSION = "2024-11-30"


class AzureDocumentIntelligenceOcr:
    name = "azure-di"

    def __init__(self, endpoint: str, key: str, client: httpx.Client | None = None, poll_seconds: float = 1.0, timeout: float = 60.0):
        self.endpoint = endpoint.rstrip("/")
        self.key = key
        self.client = client or httpx.Client(timeout=30.0)
        self.poll_seconds = poll_seconds
        self.timeout = timeout

    def recognize(self, image: Image.Image, page_index: int) -> PageText:
        buf = io.BytesIO()
        image.convert("RGB").save(buf, format="PNG")
        url = f"{self.endpoint}/documentintelligence/documentModels/prebuilt-read:analyze?api-version={API_VERSION}"
        headers = {"Ocp-Apim-Subscription-Key": self.key, "Content-Type": "application/octet-stream"}
        try:
            resp = self.client.post(url, content=buf.getvalue(), headers=headers)
        except httpx.HTTPError as exc:
            raise OcrUnavailable(f"azure unreachable: {exc}") from exc
        self._raise_for(resp)
        op_url = resp.headers.get("Operation-Location")
        if not op_url:
            raise OcrFailed("azure response without Operation-Location")

        deadline = time.monotonic() + self.timeout
        while True:
            try:
                poll = self.client.get(op_url, headers={"Ocp-Apim-Subscription-Key": self.key})
            except httpx.HTTPError as exc:
                raise OcrUnavailable(f"azure unreachable while polling: {exc}") from exc
            self._raise_for(poll)
            body = poll.json()
            status = body.get("status")
            if status == "succeeded":
                return self._to_page(body, image.size, page_index)
            if status == "failed":
                raise OcrFailed(f"azure analysis failed: {body.get('error')}")
            if time.monotonic() > deadline:
                raise OcrUnavailable("azure analysis timed out")
            time.sleep(self.poll_seconds)

    @staticmethod
    def _raise_for(resp: httpx.Response) -> None:
        if resp.status_code in (429, 500, 502, 503, 504):
            raise OcrUnavailable(f"azure transient error {resp.status_code}")
        if resp.status_code >= 400:
            raise OcrFailed(f"azure error {resp.status_code}: {resp.text[:300]}")

    def _to_page(self, body: dict, size: tuple[int, int], page_index: int) -> PageText:
        pages = body.get("analyzeResult", {}).get("pages", [])
        if not pages:
            return PageText(index=page_index, source=f"ocr:{self.name}")
        page = pages[0]
        pw = page.get("width") or size[0]
        ph = page.get("height") or size[1]
        words: list[Word] = []
        lines = page.get("lines", [])
        spans_to_line = []
        for li, line in enumerate(lines):
            for span in line.get("spans", []):
                spans_to_line.append((span["offset"], span["offset"] + span["length"], li))
        for w in page.get("words", []):
            poly = w.get("polygon") or [0, 0, 0, 0, 0, 0, 0, 0]
            xs, ys = poly[0::2], poly[1::2]
            offset = w.get("span", {}).get("offset", -1)
            line_idx = next((li for a, b, li in spans_to_line if a <= offset < b), 0)
            words.append(
                Word(
                    text=w.get("content", ""),
                    conf=float(w.get("confidence", 0.0)),
                    bbox=(min(xs) / pw, min(ys) / ph, max(xs) / pw, max(ys) / ph),
                    line=line_idx,
                )
            )
        return PageText(index=page_index, source=f"ocr:{self.name}", lines=lines_from_words(words))
