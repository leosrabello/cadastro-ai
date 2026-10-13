import io
from dataclasses import dataclass, field

import fitz
from PIL import ExifTags, Image, ImageOps

from app.pipeline.ocr.base import PageText, Word, lines_from_words


@dataclass
class RenderedPage:
    index: int
    image: Image.Image
    text_layer: PageText | None  # only for PDFs with embedded text
    image_boxes: list[tuple[float, float, float, float]] = field(default_factory=list)  # embedded pictures, as page fractions


@dataclass
class Rendered:
    pages: list[RenderedPage]
    metadata: dict


def render(data: bytes, mime: str, dpi: int = 200, max_pages: int = 15) -> Rendered:
    if mime == "application/pdf":
        return _render_pdf(data, dpi, max_pages)
    return _render_image(data)


def render_page_png(data: bytes, mime: str, page: int, dpi: int = 110) -> bytes:
    if mime == "application/pdf":
        with fitz.open(stream=data, filetype="pdf") as doc:
            return doc[page].get_pixmap(dpi=dpi).tobytes("png")
    with Image.open(io.BytesIO(data)) as img:
        img = ImageOps.exif_transpose(img).convert("RGB")
        img.thumbnail((2600, 2600))
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()


def _render_pdf(data: bytes, dpi: int, max_pages: int) -> Rendered:
    pages: list[RenderedPage] = []
    with fitz.open(stream=data, filetype="pdf") as doc:
        meta = {k: v for k, v in (doc.metadata or {}).items() if v}
        meta["page_count"] = doc.page_count
        meta["eof_markers"] = data.count(b"%%EOF")
        meta["has_text_layer"] = False
        for i in range(min(doc.page_count, max_pages)):
            page = doc[i]
            pix = page.get_pixmap(dpi=dpi)
            image = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
            pw, ph = page.rect.width, page.rect.height
            words = []
            for x0, y0, x1, y1, text, block, line, _wn in page.get_text("words"):
                if text.strip():
                    words.append(Word(text=text, conf=0.99, bbox=(x0 / pw, y0 / ph, x1 / pw, y1 / ph), line=block * 1000 + line))
            text_layer = None
            if len(words) >= 5:
                meta["has_text_layer"] = True
                text_layer = PageText(index=i, source="pdf_text", lines=lines_from_words(words))
            boxes = []
            for info in page.get_image_info():
                x0, y0, x1, y1 = info["bbox"]
                if (x1 - x0) * (y1 - y0) >= 0.01 * pw * ph:  # ignore logos and seals
                    boxes.append((max(0.0, x0 / pw), max(0.0, y0 / ph), min(1.0, x1 / pw), min(1.0, y1 / ph)))
            pages.append(RenderedPage(index=i, image=image, text_layer=text_layer, image_boxes=boxes))
    return Rendered(pages=pages, metadata=meta)


def _render_image(data: bytes) -> Rendered:
    with Image.open(io.BytesIO(data)) as raw:
        exif = {}
        try:
            for tag, value in (raw.getexif() or {}).items():
                name = ExifTags.TAGS.get(tag, str(tag))
                if name in {"Software", "DateTime", "Make", "Model", "ProcessingSoftware"}:
                    exif[name] = str(value)[:120]
        except Exception:
            pass
        fmt = raw.format
        quant = getattr(raw, "quantization", None)
        image = ImageOps.exif_transpose(raw).convert("RGB")
    meta = {"format": fmt, "exif": exif, "width": image.width, "height": image.height, "jpeg_tables": len(quant) if quant else None}
    return Rendered(pages=[RenderedPage(index=0, image=image, text_layer=None)], metadata=meta)
