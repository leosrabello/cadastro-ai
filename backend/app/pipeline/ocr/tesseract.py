"""Self-hosted OCR with Tesseract 5 (Portuguese model). No document leaves the server."""

import numpy as np
import pytesseract
from PIL import Image, ImageOps

from app.pipeline.ocr.base import OcrFailed, OcrUnavailable, PageText, Word, lines_from_words


class TesseractOcr:
    name = "tesseract"

    def __init__(self, lang: str = "por", timeout: int = 90):
        self.lang = lang
        self.timeout = timeout

    def recognize(self, image: Image.Image, page_index: int) -> PageText:
        gray = prepare(image)
        try:
            data = pytesseract.image_to_data(
                gray,
                lang=self.lang,
                config="--oem 1 --psm 3",
                output_type=pytesseract.Output.DICT,
                timeout=self.timeout,
            )
        except RuntimeError as exc:  # pytesseract raises RuntimeError on timeout
            raise OcrUnavailable(f"tesseract timeout: {exc}") from exc
        except pytesseract.TesseractNotFoundError as exc:
            raise OcrUnavailable("tesseract binary not installed") from exc
        except pytesseract.TesseractError as exc:
            raise OcrFailed(str(exc)) from exc

        w, h = gray.size
        words = []
        for i, text in enumerate(data["text"]):
            text = (text or "").strip()
            conf = float(data["conf"][i])
            if not text or conf < 0:
                continue
            x, y, bw, bh = data["left"][i], data["top"][i], data["width"][i], data["height"][i]
            line_key = data["block_num"][i] * 10_000 + data["par_num"][i] * 100 + data["line_num"][i]
            words.append(Word(text=text, conf=conf / 100.0, bbox=(x / w, y / h, (x + bw) / w, (y + bh) / h), line=line_key))
        return PageText(index=page_index, source=f"ocr:{self.name}", lines=lines_from_words(words))


def skew_angle(gray: Image.Image, limit: float = 4.0, step: float = 0.25) -> float:
    """Small-angle deskew by projection profile: the rotation whose row sums vary most."""
    small = gray.copy()
    small.thumbnail((900, 900))
    ink = ImageOps.invert(small).point(lambda p: 255 if p > 90 else 0)
    best, best_score = 0.0, -1.0
    angle = -limit
    while angle <= limit + 1e-9:
        rows = np.asarray(ink.rotate(angle, fillcolor=0), dtype=np.float32).sum(axis=1)
        score = float(np.var(rows))
        if score > best_score:
            best, best_score = angle, score
        angle += step
    return best


def prepare(image: Image.Image) -> Image.Image:
    """Grayscale, upscale small scans, straighten small rotations. Keeps the page size so
    word boxes stay valid as fractions of the original page."""
    gray = image.convert("L")
    if max(gray.size) < 1200:
        gray = gray.resize((gray.width * 2, gray.height * 2), Image.LANCZOS)
    angle = skew_angle(gray)
    if abs(angle) >= 0.25:
        gray = gray.rotate(angle, resample=Image.BICUBIC, fillcolor=255)
    return gray
