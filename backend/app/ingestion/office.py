"""Word and Excel files: identified from their own bytes, refused when they carry macros or a
password, and converted to PDF with LibreOffice so the rest of the pipeline (text, OCR, AI, page
viewer) works on them like on any PDF. The original file is kept as received.
"""

import io
import os
import shutil
import subprocess
import tempfile
import zipfile

OOXML_DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
OOXML_XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
MS_DOC = "application/msword"
MS_XLS = "application/vnd.ms-excel"
OFFICE_TYPES = {OOXML_DOCX: {".docx"}, OOXML_XLSX: {".xlsx"}, MS_DOC: {".doc"}, MS_XLS: {".xls"}}

OLE_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
MAX_UNZIPPED = 300 * 1024 * 1024  # zip-bomb guard
CONVERT_TIMEOUT = 180


class OfficeRejected(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def _utf16(name: str) -> bytes:
    return name.encode("utf-16-le")


def sniff_office(data: bytes) -> str | None:
    """MIME type of a Word/Excel file from its bytes, or None. Raises OfficeRejected for macros,
    passwords and malformed archives."""
    if data.startswith(b"PK\x03\x04"):
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as z:
                names = set(z.namelist())
                if sum(i.file_size for i in z.infolist()) > MAX_UNZIPPED:
                    raise OfficeRejected("too_large", "O arquivo compactado é grande demais quando aberto.")
        except zipfile.BadZipFile:
            raise OfficeRejected("corrupted", "O arquivo está corrompido ou incompleto.")
        if "[Content_Types].xml" not in names:
            return None
        if any(n.lower().endswith("vbaproject.bin") for n in names):
            raise OfficeRejected("active_content", "O arquivo tem macros e foi recusado por segurança. Salve como .docx ou .xlsx comum (sem macros).")
        if "word/document.xml" in names:
            return OOXML_DOCX
        if "xl/workbook.xml" in names:
            return OOXML_XLSX
        return None
    if data.startswith(OLE_MAGIC):
        if _utf16("EncryptedPackage") in data or _utf16("EncryptionInfo") in data:
            raise OfficeRejected("encrypted", "O arquivo está protegido por senha. Peça uma versão sem senha.")
        if _utf16("_VBA_PROJECT") in data:  # the stream every VBA project has, Word and Excel alike
            raise OfficeRejected("active_content", "O arquivo tem macros e foi recusado por segurança. Salve como .docx ou .xlsx comum (sem macros).")
        if _utf16("WordDocument") in data:
            return MS_DOC
        if _utf16("Workbook") in data or _utf16("Book") in data:
            return MS_XLS
        return None
    return None


def to_pdf(data: bytes, extension: str) -> bytes:
    """Converts with a throwaway LibreOffice profile, no network, no macros, bounded in time."""
    soffice = shutil.which("soffice") or shutil.which("libreoffice")
    if soffice is None:
        raise OfficeRejected("unavailable", "O servidor não está preparado para ler arquivos do Word ou Excel.")
    with tempfile.TemporaryDirectory(prefix="office-") as tmp:
        src = os.path.join(tmp, "documento" + extension)
        with open(src, "wb") as f:
            f.write(data)
        cmd = [soffice, "--headless", "--norestore", "--nolockcheck", "--nodefault",
               f"-env:UserInstallation=file://{tmp}/profile", "--convert-to", "pdf", "--outdir", tmp, src]
        try:
            subprocess.run(cmd, capture_output=True, timeout=CONVERT_TIMEOUT, check=False, env={**os.environ, "HOME": tmp})
        except subprocess.TimeoutExpired:
            raise OfficeRejected("conversion_failed", "O arquivo demorou demais para ser aberto. Envie em PDF.")
        out = os.path.join(tmp, "documento.pdf")
        if not os.path.exists(out) or os.path.getsize(out) == 0:
            raise OfficeRejected("conversion_failed", "Não foi possível abrir o arquivo (corrompido ou protegido). Envie em PDF.")
        with open(out, "rb") as f:
            return f.read()
