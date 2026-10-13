from dataclasses import dataclass, field
from typing import Protocol

from PIL import Image


class OcrUnavailable(Exception):
    """Transient: provider unreachable, timed out or rate limited. The job is retried."""


class OcrFailed(Exception):
    """Permanent for this input: the provider rejected or could not read it."""


@dataclass
class Word:
    text: str
    conf: float  # 0..1 as reported by the provider
    bbox: tuple[float, float, float, float]  # x0, y0, x1, y1 as fractions of the page
    line: int


@dataclass
class Line:
    text: str
    words: list[Word]

    @property
    def conf(self) -> float:
        return sum(w.conf for w in self.words) / len(self.words) if self.words else 0.0


@dataclass
class PageText:
    index: int
    source: str  # ocr:<provider> | pdf_text | pdf_text+ocr:<provider>
    lines: list[Line] = field(default_factory=list)

    @property
    def text(self) -> str:
        return "\n".join(line.text for line in self.lines)

    @property
    def mean_conf(self) -> float:
        words = [w for line in self.lines for w in line.words]
        return sum(w.conf for w in words) / len(words) if words else 0.0

    def to_json(self) -> dict:
        return {
            "index": self.index,
            "source": self.source,
            "mean_conf": round(self.mean_conf, 3),
            "lines": [
                {"text": ln.text, "words": [{"t": w.text, "c": round(w.conf, 3), "b": [round(x, 4) for x in w.bbox]} for w in ln.words]}
                for ln in self.lines
            ],
        }


def lines_from_words(words: list[Word]) -> list[Line]:
    by_line: dict[int, list[Word]] = {}
    for w in words:
        by_line.setdefault(w.line, []).append(w)
    lines = []
    for key in sorted(by_line, key=lambda k: (min(w.bbox[1] for w in by_line[k]), k)):
        ws = sorted(by_line[key], key=lambda w: w.bbox[0])
        lines.append(Line(text=" ".join(w.text for w in ws), words=ws))
    return lines


def merge_image_text(text_layer: PageText, ocr_page: PageText, image_boxes, min_conf: float = 0.5) -> PageText:
    """Adds what OCR read inside a PDF's embedded pictures (a CNH Digital is a picture of the card
    under a text layer that only carries the boilerplate). Words the text layer already has are kept
    from the text layer."""
    def inside(b, box, pad=0.0):
        cx, cy = (b[0] + b[2]) / 2, (b[1] + b[3]) / 2
        return box[0] - pad <= cx <= box[2] + pad and box[1] - pad <= cy <= box[3] + pad

    layer_words = [w for line in text_layer.lines for w in line.words]
    extra = [
        Word(text=w.text, conf=w.conf, bbox=w.bbox, line=10**9 + w.line)
        for line in ocr_page.lines
        for w in line.words
        if w.conf >= min_conf
        and any(inside(w.bbox, box) for box in image_boxes)
        and not any(inside(w.bbox, lw.bbox, pad=0.004) for lw in layer_words)
    ]
    if not extra:
        return text_layer
    return PageText(index=text_layer.index, source=f"pdf_text+{ocr_page.source}", lines=lines_from_words(layer_words + extra))


class OcrProvider(Protocol):
    name: str

    def recognize(self, image: Image.Image, page_index: int) -> PageText: ...
