"""Untrusted-file screening, shared by every intake channel.

The declared extension and content type are never trusted: the type is decided from the
file's own bytes and must agree with the extension. PDFs carrying active content are refused.
"""

import io
import re
from dataclasses import dataclass

import fitz  # PyMuPDF
from PIL import Image, UnidentifiedImageError

from app.config import get_settings
from app.ingestion.office import OFFICE_TYPES, OfficeRejected, sniff_office

Image.MAX_IMAGE_PIXELS = 60_000_000  # decompression-bomb guard (~60 MP)

ALLOWED = {
    "application/pdf": {".pdf"},
    "image/jpeg": {".jpg", ".jpeg"},
    "image/png": {".png"},
    **OFFICE_TYPES,
}
ACCEPTED_LABEL = "PDF, JPEG, PNG, Word (.docx, .doc) ou Excel (.xlsx, .xls)"

_ACTIVE_PDF_KEYS = ("/JavaScript", "/JS", "/Launch", "/EmbeddedFile", "/RichMedia", "/XFA")


class RejectedFile(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass
class ScreenedFile:
    mime_type: str
    extension: str
    page_count: int
    safe_name: str
    rendition: bytes | None = None  # PDF made from a Word/Excel file; the original is kept as received


def sniff(data: bytes) -> str | None:
    try:
        office = sniff_office(data)
    except OfficeRejected as exc:
        raise RejectedFile(exc.code, exc.message)
    if office:
        return office
    if data.startswith(b"%PDF-"):
        return "application/pdf"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    return None


def safe_display_name(name: str) -> str:
    base = name.replace("\\", "/").rsplit("/", 1)[-1]
    base = re.sub(r"[\x00-\x1f<>:\"|?*]", "_", base).strip(" .")
    return (base or "documento")[:200]


def screen(data: bytes, filename: str) -> ScreenedFile:
    settings = get_settings()
    if not data:
        raise RejectedFile("empty_file", "O arquivo está vazio.")
    if len(data) > settings.max_upload_mb * 1024 * 1024:
        raise RejectedFile("too_large", f"O arquivo passa do limite de {settings.max_upload_mb} MB.")

    display = safe_display_name(filename)
    ext = ("." + display.rsplit(".", 1)[-1].lower()) if "." in display else ""
    mime = sniff(data)
    if mime is None:
        raise RejectedFile("unsupported_type", f"Formato não aceito. Envie {ACCEPTED_LABEL}.")
    if ext not in ALLOWED[mime]:
        raise RejectedFile(
            "type_mismatch",
            f"A extensão '{ext or 'sem extensão'}' não corresponde ao conteúdo do arquivo ({mime}).",
        )

    rendition = None
    if mime in OFFICE_TYPES:
        from app.ingestion.office import to_pdf

        try:
            rendition = to_pdf(data, ext)
        except OfficeRejected as exc:
            raise RejectedFile(exc.code, exc.message)
        pages = _screen_pdf(rendition, settings.max_pages)
    elif mime == "application/pdf":
        pages = _screen_pdf(data, settings.max_pages)
    else:
        pages = _screen_image(data)
    return ScreenedFile(mime_type=mime, extension=ext, page_count=pages, safe_name=display, rendition=rendition)


def _screen_pdf(data: bytes, max_pages: int) -> int:
    if b"%%EOF" not in data[-2048:]:
        raise RejectedFile("corrupted", "O PDF está incompleto (transferência interrompida ou arquivo cortado).")
    try:
        doc = fitz.open(stream=data, filetype="pdf")
    except Exception:
        raise RejectedFile("corrupted", "O PDF está corrompido ou incompleto e não pôde ser aberto.")
    with doc:
        if getattr(doc, "is_repaired", False):
            raise RejectedFile("corrupted", "O PDF está danificado e só abriria com reparos automáticos. Peça uma nova cópia.")
        if doc.needs_pass or doc.is_encrypted:
            raise RejectedFile("encrypted", "O PDF está protegido por senha. Peça uma versão sem senha.")
        if doc.page_count == 0:
            raise RejectedFile("corrupted", "O PDF não tem páginas.")
        if doc.page_count > max_pages:
            raise RejectedFile("too_many_pages", f"O documento tem {doc.page_count} páginas; o limite é {max_pages}. Divida o arquivo em partes.")
        for xref in range(1, doc.xref_length()):
            try:
                obj = doc.xref_object(xref, compressed=False)
            except Exception:
                continue
            if any(key in obj for key in _ACTIVE_PDF_KEYS):
                raise RejectedFile(
                    "active_content",
                    "O PDF contém conteúdo ativo (script, anexo ou ação automática) e foi recusado por segurança.",
                )
        try:
            doc[0].get_pixmap(dpi=20)
        except Exception:
            raise RejectedFile("corrupted", "O PDF não pôde ser renderizado.")
        return doc.page_count


def _screen_image(data: bytes) -> int:
    try:
        with Image.open(io.BytesIO(data)) as img:
            img.verify()
        with Image.open(io.BytesIO(data)) as img:
            img.load()
            if img.width < 200 or img.height < 200:
                raise RejectedFile("too_small", "A imagem é pequena demais para leitura (mínimo 200×200 px).")
    except RejectedFile:
        raise
    except Image.DecompressionBombError:
        raise RejectedFile("too_large", "A imagem tem resolução grande demais.")
    except (UnidentifiedImageError, OSError, SyntaxError):
        raise RejectedFile("corrupted", "A imagem está corrompida ou incompleta.")
    return 1
