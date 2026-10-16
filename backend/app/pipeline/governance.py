"""Who runs the company and how it signs, read from the articles of association (contrato social or
an amendment): administrators, who signs for the company, sole or joint signature, and whether the
document consolidates the articles. Clauses vary a lot; these rules catch the usual wording and the
AI reads the clause when it is on. Every value keeps the sentence it came from.
"""

import re

from app.pipeline.normalize import fold
from app.pipeline.ocr.base import PageText

GOVERNANCE_FIELDS = ("administradores", "responsaveis_assinatura", "forma_assinatura", "consolidado")

_ADMIN_START = re.compile(
    r"(ADMINISTRACAO DA SOCIEDADE|SOCIEDADE SERA ADMINISTRADA|SERA ADMINISTRADA|ADMINISTRADA POR|DESIGNAD[OA]S? (?:COMO |PARA O CARGO DE )?ADMINISTRADOR|"
    r"NOMEAD[OA]S? (?:COMO |PARA O CARGO DE )?ADMINISTRADOR|INVESTID[OA]S? NO CARGO DE ADMINISTRADOR|EXERCERA[O]? A ADMINISTRACAO)"
)
_SIGN_START = re.compile(r"(USO DO NOME EMPRESARIAL|USO DA DENOMINACAO|USO DA FIRMA|REPRESENTACAO (?:ATIVA E PASSIVA|DA SOCIEDADE)|REPRESENTAR A SOCIEDADE|ASSINATURA)")
_JOINT = re.compile(r"\b(EM CONJUNTO|CONJUNTAMENTE|SEMPRE EM CONJUNTO|ASSINATURA CONJUNTA|AMBOS OS ADMINISTRADORES|DOIS ADMINISTRADORES)\b")
_SOLE = re.compile(r"\b(ISOLADAMENTE|INDIVIDUALMENTE|ISOLADA|SEPARADAMENTE|INDISTINTAMENTE|QUALQUER UM DELES|CADA UM DELES)\b")
_CONSOLIDATED = re.compile(r"\b(CONSOLIDACAO|CONSOLIDAD[OA]|CONSOLIDAR|CONSOLIDA-SE|CONSOLIDANDO)\b")
_AMENDMENT = re.compile(r"\b(\d+\s*[ªAO]?\s*ALTERACAO CONTRATUAL|ALTERACAO CONTRATUAL|INSTRUMENTO PARTICULAR DE ALTERACAO)\b")
# capitalised names in the original text: two to six words, each starting with a capital letter
_NAME = re.compile(r"\b([A-ZÁÉÍÓÚÂÊÔÃÕÇ][A-ZÁÉÍÓÚÂÊÔÃÕÇ'’]+(?:\s+(?:D[AEO]S?|E)?\s*[A-ZÁÉÍÓÚÂÊÔÃÕÇ][A-ZÁÉÍÓÚÂÊÔÃÕÇ'’]+){1,5})\b")
_NOT_NAMES = {"SOCIEDADE", "LTDA", "EIRELI", "ADMINISTRACAO", "ADMINISTRADOR", "ADMINISTRADORES", "CONTRATO", "SOCIAL", "CLAUSULA", "PARAGRAFO",
              "BRASILEIRO", "BRASILEIRA", "CPF", "RG", "CNPJ", "JUNTA", "COMERCIAL", "ESTADO", "NOME", "EMPRESARIAL", "SOCIO", "SOCIA", "SOCIOS",
              "QUOTAS", "CAPITAL", "UNICO", "UNICA", "ALTERACAO", "CONSOLIDACAO", "INSTRUMENTO", "PARTICULAR", "REAIS", "LIMITADA"}


def _sentences(pages: list[PageText]):
    """(page, original sentence, folded sentence) over the whole document, sentences spanning lines."""
    for page in pages:
        text = " ".join(line.text for line in page.lines)
        for raw in re.split(r"(?<=[.;:])\s+(?=[A-ZÁÉÍÓÚÂÊÔÃÕÇ0-9§])", text):
            raw = raw.strip()
            if len(raw) > 12:
                yield page.index, raw, fold(raw)


def _names(raw: str, partners: list[str]) -> list[str]:
    found = []
    folded = fold(raw)
    for p in partners:  # partners named in the clause, however the clause is typed
        if p and fold(p) in folded:
            found.append(p)
    if not found:
        for m in _NAME.finditer(raw):
            words = fold(m.group(1)).split()
            if len(words) >= 2 and not (set(words) & _NOT_NAMES):
                found.append(m.group(1).upper())
    return list(dict.fromkeys(found))


def read(pages: list[PageText], partners: list[str]) -> dict[str, dict]:
    """{field: {value, page, evidence}} for the fields found."""
    out: dict[str, dict] = {}
    sentences = list(_sentences(pages))

    for page, raw, f in sentences:
        if _ADMIN_START.search(f):
            names = _names(raw, partners)
            if names:
                out["administradores"] = {"value": "; ".join(names), "page": page, "evidence": raw[:400]}
                if _SIGN_START.search(f) or "REPRESENT" in f:
                    out["responsaveis_assinatura"] = {"value": "; ".join(names), "page": page, "evidence": raw[:400]}
                break

    for page, raw, f in sentences:
        if not (_ADMIN_START.search(f) or _SIGN_START.search(f) or "ADMINISTRADOR" in f):
            continue
        joint, sole = bool(_JOINT.search(f)), bool(_SOLE.search(f))
        if joint or sole:
            value = "Isolada ou conjunta, conforme o ato (ver cláusula)" if joint and sole else ("Conjunta" if joint else "Isolada")
            out["forma_assinatura"] = {"value": value, "page": page, "evidence": raw[:400]}
            break

    head = " ".join(f for _, _, f in sentences[:12])
    whole = " ".join(f for _, _, f in sentences)
    if _CONSOLIDATED.search(whole):
        page, raw = next(((p, r) for p, r, f in sentences if _CONSOLIDATED.search(f)), (0, ""))
        out["consolidado"] = {"value": "Sim", "page": page, "evidence": raw[:400]}
    elif _AMENDMENT.search(head):
        page, raw = next(((p, r) for p, r, f in sentences if _AMENDMENT.search(f)), (0, ""))
        out["consolidado"] = {"value": "Não", "page": page, "evidence": raw[:400]}
    return out
