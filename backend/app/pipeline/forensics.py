"""Conventional integrity signals. Each is an indication for a reviewer, never proof.

- PDF producer/creator naming an image editor, and incremental saves after creation.
- EXIF software tags naming an image editor.
- Error level analysis (ELA) on JPEGs: regions recompressing very differently from the rest.
- Embedded PDF text that does not match what OCR sees on the rendered page.
- Exact (SHA-256) and near (perceptual hash) reuse of a file or image in another registration.
"""

import io
import re

import imagehash
import numpy as np
from PIL import Image, ImageChops
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models import DocStatus, Document
from app.pipeline.findings import FindingDraft, evidence
from app.pipeline.normalize import digits, find_dates, fold
from app.pipeline.ocr.base import PageText

EDITORS = re.compile(r"PHOTOSHOP|GIMP|CANVA|PIXLR|PAINT\.NET|AFFINITY|CORELDRAW|ILLUSTRATOR|INKSCAPE|PICSART|SNAPSEED|PDF-?XCHANGE EDITOR|FOXIT PHANTOM|SEJDA|PDFESCAPE|ACROBAT PRO.*EDIT", re.I)


def phash(image: Image.Image) -> str:
    return str(imagehash.phash(image))


def metadata_findings(meta: dict, doc_id) -> list[FindingDraft]:
    out = []
    tools = " ".join(str(meta.get(k, "")) for k in ("producer", "creator"))
    exif_sw = " ".join(str(v) for k, v in (meta.get("exif") or {}).items() if k in ("Software", "ProcessingSoftware"))
    for origin, value in (("metadados do PDF", tools), ("metadados EXIF", exif_sw)):
        m = EDITORS.search(value or "")
        if m:
            out.append(FindingDraft(
                code="EDITOR_METADATA", category="integrity", severity="medium", source="forensics", key=origin,
                title="Arquivo passou por editor de imagem",
                explanation=f"Os {origin} citam '{m.group(0)}'. Documentos oficiais escaneados ou emitidos digitalmente raramente passam por editores. Pode ser apenas um recorte ou ajuste de brilho.",
                recommended_action="Compare com atenção nome, números e datas. Na dúvida, peça o arquivo original emitido pelo órgão.",
                evidence=[evidence("Ferramenta registrada", value.strip()[:160], document_id=doc_id)],
                confidence=None, confidence_basis="Sinal de metadados; não indica o que foi alterado.",
                document_id=doc_id, rule_id="forensics.editor",
            ))
    if (meta.get("eof_markers") or 0) > 1:
        out.append(FindingDraft(
            code="PDF_INCREMENTAL_SAVE", category="integrity", severity="low", source="forensics",
            title="PDF modificado depois de criado",
            explanation=f"O PDF tem {meta['eof_markers']} seções de salvamento. Isso acontece com assinaturas digitais e formulários preenchidos, mas também com edições posteriores.",
            recommended_action="Verifique se o documento deveria ter sido alterado após a emissão.",
            evidence=[evidence("Seções de salvamento", meta["eof_markers"], document_id=doc_id)],
            confidence_basis="Estrutura do arquivo; comum também em arquivos legítimos.",
            document_id=doc_id, rule_id="forensics.incremental",
        ))
    return out


def ela_finding(data: bytes, mime: str, doc_id) -> FindingDraft | None:
    if mime != "image/jpeg":
        return None
    with Image.open(io.BytesIO(data)) as raw:
        original = raw.convert("RGB")
    buf = io.BytesIO()
    original.save(buf, "JPEG", quality=90)
    buf.seek(0)
    with Image.open(buf) as resaved:
        diff = np.asarray(ImageChops.difference(original, resaved.convert("RGB")), dtype=np.float32).mean(axis=2)
    h, w = diff.shape
    bs = max(16, min(h, w) // 24)
    rows, cols = h // bs, w // bs
    if rows < 4 or cols < 4:
        return None
    blocks = diff[: rows * bs, : cols * bs].reshape(rows, bs, cols, bs).mean(axis=(1, 3))
    median = float(np.median(blocks))
    p99 = float(np.percentile(blocks, 99))
    peak = float(blocks.max())
    # an isolated hot block: far above the image's typical level and above its own top percentile
    if peak < 4.0 or peak < 6 * max(median, 0.5) or peak < 1.5 * p99:
        return None
    r, c = np.unravel_index(int(blocks.argmax()), blocks.shape)
    bbox = [round(c * bs / w, 4), round(r * bs / h, 4), round((c + 1) * bs / w, 4), round((r + 1) * bs / h, 4)]
    return FindingDraft(
        code="ELA_HOTSPOT", category="integrity", severity="low", source="forensics",
        title="Região com compressão diferente do resto da imagem",
        explanation=f"Na análise de nível de erro (ELA), uma região reage à recompressão {peak / max(median, 0.5):.0f}× mais que a mediana da imagem. Colagens e edições localizadas costumam produzir esse padrão; reflexos, carimbos e fotos 3×4 também.",
        recommended_action="Olhe a região destacada no original. Escale apenas se houver outro sinal de alteração.",
        evidence=[evidence("Região", None, document_id=doc_id, page=0, bbox=bbox, note=f"pico {peak:.1f}, mediana {median:.2f}")],
        confidence_basis="Heurística com muitos falsos positivos; não é prova de edição.",
        document_id=doc_id, rule_id="forensics.ela",
    )


_KEY_TOKEN = re.compile(r"\d{3}\.?\d{3}\.?\d{3}-?\d{2}|\d{2}\.?\d{3}\.?\d{3}/?\d{4}-?\d{2}|\d{1,2}/\d{1,2}/\d{4}")


def text_layer_findings(text_layer: PageText, ocr_page: PageText, doc_id) -> list[FindingDraft]:
    """Identifiers and dates present in the embedded text but absent from what is visibly printed."""
    hidden = []
    ocr_digits = digits(ocr_page.text)
    ocr_dates = {d for d, _ in find_dates(ocr_page.text)}
    for m in _KEY_TOKEN.finditer(fold(text_layer.text)):
        token = m.group(0)
        if "/" in token and len(token) <= 10:
            parsed = find_dates(token)
            if parsed and parsed[0][0] not in ocr_dates:
                hidden.append(token)
        elif digits(token) not in ocr_digits:
            hidden.append(token)
    if not hidden or ocr_page.mean_conf < 0.55:
        return []
    return [FindingDraft(
        code="TEXT_LAYER_MISMATCH", category="integrity", severity="high", source="forensics", key=str(text_layer.index),
        title="Texto embutido diferente do conteúdo visível",
        explanation=f"O PDF traz no texto embutido {len(hidden)} número(s) ou data(s) que não aparecem na página renderizada. Isso ocorre quando o texto foi sobreposto ou substituído depois da emissão.",
        recommended_action="Compare os valores com a imagem da página. Se divergirem, escale para o supervisor e peça o documento ao emissor.",
        evidence=[evidence("Só no texto embutido", t, document_id=doc_id, page=text_layer.index) for t in hidden[:6]],
        confidence=None, confidence_basis="Comparação direta entre texto embutido e OCR da página; erros de OCR podem gerar falsos positivos.",
        document_id=doc_id, rule_id="forensics.text_layer",
    )]


def identity_keys(fields) -> set[str]:
    v = {f.name: (f.value or "").strip() for f in fields if f.value and f.valid is not False}
    keys = set()
    for name in ("cpf", "cnpj", "rg_numero", "cnh_registro"):
        if v.get(name) and len(digits(v[name])) >= 7:
            keys.add(f"{name}:{digits(v[name])}")
    if v.get("nome") and v.get("data_nascimento"):
        keys.add(f"nome+nascimento:{fold(v['nome'])}|{v['data_nascimento']}")
    if v.get("nome") and v.get("endereco"):
        keys.add(f"nome+endereco:{fold(v['nome'])}|{fold(v['endereco'])}")
    return keys


def duplicate_findings(db: Session, doc: Document, distance: int) -> list[FindingDraft]:
    out = []
    others = db.execute(
        select(Document).where(
            Document.id != doc.id,
            Document.status != DocStatus.PURGED,
            Document.sha256 == doc.sha256,
        )
    ).scalars().all()
    for other in others:
        if other.registration_id == doc.registration_id:
            continue
        out.append(FindingDraft(
            code="FILE_REUSED", category="integrity", severity="high", source="forensics", key=str(other.id),
            title="Mesmo arquivo em outro cadastro",
            explanation="Um arquivo idêntico, byte a byte, já foi recebido em outro cadastro. Documentos pessoais de uma pessoa não deveriam aparecer no cadastro de outra.",
            recommended_action="Abra o outro cadastro e verifique se há relação legítima (por exemplo, sócio em comum). Caso contrário, escale.",
            evidence=[evidence("Documento igual", other.original_filename, document_id=other.id, note="SHA-256 idêntico")],
            confidence=1.0, confidence_basis="Hash criptográfico idêntico.",
            document_id=doc.id, rule_id="forensics.sha256",
        ))
    if doc.phash:
        # Documents of one type share a printed template, so visual similarity alone matches
        # unrelated people, and so does boilerplate text. A near-duplicate is reported only when
        # the page looks alike AND carries the same identity data (same CPF, document number,
        # name with birth date, or name with address): the same person's document, rescanned
        # or re-photographed, inside another registration.
        mine = imagehash.hex_to_hash(doc.phash)
        my_keys = identity_keys(doc.fields)
        if not my_keys:
            return out
        candidates = db.execute(
            select(Document).options(selectinload(Document.fields)).where(
                Document.id != doc.id, Document.phash.is_not(None), Document.status != DocStatus.PURGED,
                Document.sha256 != doc.sha256,
            )
        ).scalars().all()
        for other in candidates:
            if other.registration_id == doc.registration_id:
                continue
            d = mine - imagehash.hex_to_hash(other.phash)
            shared = my_keys & identity_keys(other.fields)
            oid, oname = other.id, other.original_filename
            if d <= distance and shared:
                out.append(FindingDraft(
                    code="IMAGE_REUSED", category="integrity", severity="medium", source="forensics", key=str(oid),
                    title="Mesmo documento em outro cadastro",
                    explanation=f"A página é visualmente quase igual (distância perceptual {d} de 64) a um documento de outro cadastro e traz os mesmos dados de identificação ({', '.join(sorted(k.split(':')[0] for k in shared))}), embora os arquivos sejam diferentes. Costuma ser o mesmo documento digitalizado de novo.",
                    recommended_action="Compare os dois documentos lado a lado antes de decidir.",
                    evidence=[evidence("Documento parecido", oname, document_id=oid, note=f"distância {d}")],
                    confidence=round(1 - d / 64, 2), confidence_basis="Semelhança da imagem com dados de identificação iguais; não é identidade de arquivo.",
                    document_id=doc.id, rule_id="forensics.phash",
                ))
    return out
