"""Deterministic field extraction from OCR or PDF text, with source page and region.

Fields are found by label (on the same line, or on the next lines when a form puts labels
above values, choosing the value nearest the label horizontally) and by pattern. Each value
is normalized and checked where a check exists (CPF/CNPJ check digits, real calendar dates).
Filiation (parents' names) is deliberately not extracted: the workflow does not need it.
"""

import re
from dataclasses import dataclass, field
from datetime import date, timedelta

from app.pipeline.normalize import (
    CEP_RE,
    CNPJ_RE,
    CPF_RE,
    DATE_LONG_RE,
    DATE_MON_RE,
    DATE_RE,
    clean_name,
    digits,
    fold,
    format_cnpj,
    format_cpf,
    parse_date,
    valid_cnpj,
    valid_cpf,
)
from app.pipeline import financial as fin
from app.pipeline import governance
from app.pipeline.ocr.base import Line, PageText


@dataclass
class FieldValue:
    name: str
    value: str | None
    raw: str | None
    confidence: float
    page: int | None
    bbox: list[float] | None
    valid: bool | None = None
    note: str | None = None
    source: str = "ocr"
    alternatives: list[str] = field(default_factory=list)


LABELS: dict[str, list[str]] = {
    "nome": ["NOME E SOBRENOME", "NOME COMPLETO", "NOME DO TITULAR", "NOME DO CLIENTE", "NOME", "TITULAR", "CLIENTE"],
    "cpf": ["CPF"],
    "cnpj": ["NUMERO DE INSCRICAO", "CNPJ"],
    "rg_numero": ["REGISTRO GERAL", "N DO RG", "NO RG", "RG"],
    "cnh_registro": ["N REGISTRO", "NO REGISTRO", "N DE REGISTRO", "REGISTRO"],
    "data_nascimento": ["DATA DE NASCIMENTO", "DATA NASCIMENTO", "DATA NASC", "NASCIMENTO"],
    "data_expedicao": ["DATA DE EXPEDICAO", "DATA EXPEDICAO", "DATA EXPED", "EXPEDICAO"],
    "data_emissao": ["DATA DE EMISSAO", "DATA DA EMISSAO", "DATA EMISSAO", "EMITIDO EM", "EMISSAO", "DATA BASE", "DATA-BASE", "DATA DA VISITA", "VISITA REALIZADA EM", "DATA DO CASAMENTO", "LAVRADA EM"],
    "validade": ["DATA DE VALIDADE", "VALIDO ATE", "VALIDADE"],
    "orgao_expedidor": ["ORGAO EXPEDIDOR", "ORGAO EMISSOR", "EXPEDIDOR"],
    "endereco": ["ENDERECO DE ENTREGA", "ENDERECO", "LOGRADOURO"],
    "cep": ["CEP"],
    "razao_social": ["NOME EMPRESARIAL", "RAZAO SOCIAL", "DENOMINACAO SOCIAL"],
    "situacao_cadastral": ["SITUACAO CADASTRAL"],
    "data_registro": ["REGISTRADO EM", "DATA DO REGISTRO", "ARQUIVADO EM", "DATA DE REGISTRO"],
}

NAME_EXCLUDE = ("MAE", "PAI", "FILIACAO", "EMPRESARIAL", "SOCIAL", "FANTASIA", "SOCIO", "MUNICIPIO")
# column headings that share a line with a label on card layouts (CNH: "NOME E SOBRENOME  1ª HABILITAÇÃO")
COLUMN_HEADINGS = ("HABILITACAO", "CAT HAB", "ACC", "ASSINATURA")
ALL_LABEL_WORDS = sorted({lbl for labels in LABELS.values() for lbl in labels} | set(COLUMN_HEADINGS), key=len, reverse=True)
ISSUER_RE = re.compile(r"\b(SSP|SESP|SDS|PC|IFP|IIRGD|DETRAN|SENATRAN|DENATRAN|DGPC|SJS|SSPDS|POLICIA CIVIL)\s*[-/ ]?\s*([A-Z]{2})?\b")
SITUACOES = ("ATIVA", "BAIXADA", "SUSPENSA", "INAPTA", "NULA")
UFS = set("AC AL AP AM BA CE DF ES GO MA MT MS MG PA PB PR PE PI RJ RN RS RO RR SC SP SE TO".split())


@dataclass
class _Loc:
    page: PageText
    line_idx: int
    label_end: int  # char offset in folded line text after the label
    label_x: float


def _line_text_with_offsets(line: Line) -> tuple[str, list[tuple[int, int]]]:
    parts, offsets, pos = [], [], 0
    for w in line.words:
        t = fold(w.text)
        offsets.append((pos, pos + len(t)))
        parts.append(t)
        pos += len(t) + 1
    return " ".join(parts), offsets


def _words_in_span(line: Line, offsets: list[tuple[int, int]], start: int, end: int):
    return [w for w, (a, b) in zip(line.words, offsets) if a < end and b > start]


def _bbox(words) -> list[float] | None:
    if not words:
        return None
    return [
        round(min(w.bbox[0] for w in words), 4),
        round(min(w.bbox[1] for w in words), 4),
        round(max(w.bbox[2] for w in words), 4),
        round(max(w.bbox[3] for w in words), 4),
    ]


def _conf(words) -> float:
    return round(sum(w.conf for w in words) / len(words), 3) if words else 0.0


def _find_labels(pages: list[PageText], labels: list[str], exclude: tuple[str, ...] = ()) -> list[_Loc]:
    found = []
    for page in pages:
        for li, line in enumerate(page.lines):
            text, offsets = _line_text_with_offsets(line)
            for label in labels:
                m = re.search(rf"(?<![A-Z]){re.escape(label)}(?![A-Z])", text)
                if not m:
                    continue
                if exclude and any(x in text[m.start(): m.end() + 25] for x in exclude):
                    continue
                label_words = _words_in_span(line, offsets, m.start(), m.end())
                found.append(_Loc(page, li, m.end(), label_words[0].bbox[0] if label_words else 0.0))
                break
    return found


def _match_near(loc: _Loc, pattern: re.Pattern, lookahead: int = 2):
    """Value matching `pattern`: first after the label on its line, else nearest-in-x on the next lines."""
    line = loc.page.lines[loc.line_idx]
    text, offsets = _line_text_with_offsets(line)
    rest = text[loc.label_end:]
    m = pattern.search(rest)
    if m:
        start, end = loc.label_end + m.start(), loc.label_end + m.end()
        return m, _words_in_span(line, offsets, start, end), loc.page.index
    for nxt in range(loc.line_idx + 1, min(loc.line_idx + 1 + lookahead, len(loc.page.lines))):
        line = loc.page.lines[nxt]
        text, offsets = _line_text_with_offsets(line)
        best = None
        for m in pattern.finditer(text):
            words = _words_in_span(line, offsets, m.start(), m.end())
            if not words:
                continue
            dist = abs(words[0].bbox[0] - loc.label_x)
            if best is None or dist < best[0]:
                best = (dist, m, words)
        if best:
            return best[1], best[2], loc.page.index
    return None


_ANY_DATE = re.compile(f"{DATE_RE.pattern}|{DATE_LONG_RE.pattern}|{DATE_MON_RE.pattern}")


def _date_field(name: str, pages: list[PageText]) -> FieldValue | None:
    for loc in _find_labels(pages, LABELS[name]):
        hit = _match_near(loc, _ANY_DATE)
        if not hit:
            continue
        m, words, page = hit
        parsed = parse_date(m.group(0))
        return FieldValue(
            name=name,
            value=parsed.isoformat() if parsed else None,
            raw=m.group(0),
            confidence=_conf(words) if parsed else 0.2,
            page=page,
            bbox=_bbox(words),
            valid=parsed is not None,
            note=None if parsed else "Data ilegível ou inexistente no calendário.",
        )
    return None


def _id_field(name: str, pages: list[PageText], rx: re.Pattern, check, fmt) -> FieldValue | None:
    candidates = []
    for loc in _find_labels(pages, LABELS[name]):
        hit = _match_near(loc, rx)
        if hit:
            candidates.append((True, *hit))
    if not candidates:  # unlabeled: any well-formed number on the document
        for page in pages:
            for line in page.lines:
                text, offsets = _line_text_with_offsets(line)
                for m in rx.finditer(text):
                    candidates.append((False, m, _words_in_span(line, offsets, m.start(), m.end()), page.index))
    if not candidates:
        return None
    candidates.sort(key=lambda c: (not check(c[1].group(0)), not c[0]))
    labelled, m, words, page = candidates[0]
    d = digits(m.group(0))
    ok = check(d)
    others = sorted({fmt(digits(c[1].group(0))) for c in candidates[1:] if digits(c[1].group(0)) != d})
    conf = _conf(words) * (1.0 if labelled else 0.8)
    return FieldValue(
        name=name,
        value=fmt(d),
        raw=m.group(0),
        confidence=round(conf if ok else min(conf, 0.3), 3),
        page=page,
        bbox=_bbox(words),
        valid=ok,
        note=None if ok else "Dígitos verificadores não conferem: leitura incorreta ou número inválido.",
        alternatives=others,
    )


def _text_after_label(name: str, pages: list[PageText], exclude: tuple[str, ...] = (), cleaner=None) -> FieldValue | None:
    for loc in _find_labels(pages, LABELS[name], exclude):
        line = loc.page.lines[loc.line_idx]
        text, offsets = _line_text_with_offsets(line)
        rest = text[loc.label_end:]
        # stop at the next known label on the same line
        cut = len(rest)
        for lbl in ALL_LABEL_WORDS:
            m = re.search(rf"(?<![A-Z]){re.escape(lbl)}(?![A-Z])", rest)
            if m and m.start() > 1:
                cut = min(cut, m.start())
        value = rest[:cut].strip(" :.-")
        start = loc.label_end + (len(rest[:cut]) - len(rest[:cut].lstrip(" :.-")))
        words = _words_in_span(line, offsets, start, loc.label_end + cut)
        page = loc.page.index
        if len(re.sub(r"[^A-Z]", "", value)) < 3 and loc.line_idx + 1 < len(loc.page.lines):
            nxt = loc.page.lines[loc.line_idx + 1]
            value, _ = _line_text_with_offsets(nxt)
            words = nxt.words
        if cleaner:
            value = cleaner(value)
        if len(re.sub(r"[^A-Z0-9]", "", fold(value))) < 3:
            continue
        return FieldValue(name=name, value=value, raw=value, confidence=_conf(words), page=page, bbox=_bbox(words), valid=True)
    return None


def _issuer(pages: list[PageText]) -> FieldValue | None:
    locs = _find_labels(pages, LABELS["orgao_expedidor"])
    for loc in locs:
        hit = _match_near(loc, ISSUER_RE)
        if hit:
            m, words, page = hit
            return _issuer_value(m, words, page, 1.0)
    for page in pages:
        for line in page.lines:
            text, offsets = _line_text_with_offsets(line)
            m = ISSUER_RE.search(text)
            if m and (m.group(2) in UFS or m.group(1) in ("DETRAN", "SENATRAN", "DENATRAN")):
                return _issuer_value(m, _words_in_span(line, offsets, m.start(), m.end()), page.index, 0.8)
    return None


def _issuer_value(m, words, page, factor) -> FieldValue:
    org, uf = m.group(1), m.group(2)
    value = f"{org}/{uf}" if uf in UFS else org
    return FieldValue("orgao_expedidor", value, m.group(0), round(_conf(words) * factor, 3), page, _bbox(words), True)


def _situacao(pages: list[PageText]) -> FieldValue | None:
    rx = re.compile(r"\b(" + "|".join(SITUACOES) + r")\b")
    for loc in _find_labels(pages, LABELS["situacao_cadastral"]):
        hit = _match_near(loc, rx)
        if hit:
            m, words, page = hit
            return FieldValue("situacao_cadastral", m.group(1), m.group(0), _conf(words), page, _bbox(words), True)
    return None


def _cep(pages: list[PageText]) -> FieldValue | None:
    locs = _find_labels(pages, LABELS["cep"])
    for loc in locs:
        hit = _match_near(loc, CEP_RE)
        if hit:
            m, words, page = hit
            return FieldValue("cep", f"{m.group(1)}-{m.group(2)}", m.group(0), _conf(words), page, _bbox(words), True)
    return None


_SOCIO_RE = re.compile(r"^([A-Z][A-Z ]{6,80}?),\s*(BRASILEIR|PORTUGUES|ARGENTIN|NACIONALIDADE)")


def _socios(pages: list[PageText]) -> FieldValue | None:
    names, words_all, page_idx = [], [], None
    for page in pages:
        for line in page.lines:
            text, offsets = _line_text_with_offsets(line)
            m = _SOCIO_RE.search(text)
            if m:
                names.append(m.group(1).strip())
                words_all.extend(_words_in_span(line, offsets, m.start(1), m.end(1)))
                page_idx = page.index if page_idx is None else page_idx
    if not names:
        return None
    return FieldValue("socios", "; ".join(dict.fromkeys(names)), None, _conf(words_all), page_idx, None, True)


def _emissor(pages: list[PageText]) -> FieldValue | None:
    if not pages or not pages[0].lines:
        return None
    for line in pages[0].lines[:4]:
        t = line.text.strip()
        if len(re.sub(r"[^A-Za-z]", "", t)) >= 4 and line.conf > 0.5:
            return FieldValue("emissor", t[:120], t, round(line.conf * 0.5, 3), 0, _bbox(line.words), True,
                              note="Inferido da primeira linha do documento; confirme na revisão.")
    return None


def _fv(name, value, raw, page, conf=0.8, note=None) -> FieldValue:
    return FieldValue(name=name, value=value, raw=(raw or "")[:300], confidence=conf, page=page, bbox=None, valid=True, note=note)


def _money_field(name, labels):
    def run(pages):
        hit = fin.labelled_money(pages, labels)
        return _fv(name, fin.format_money(hit[0]), hit[1], hit[2]) if hit else None
    return run


def _exercicio(pages):
    hit = fin.exercicio(pages)
    return _fv("exercicio", hit[0], hit[1], hit[2], 0.85) if hit else None


def _revenue(pages):
    table = fin.revenue_table(pages)
    if not table:
        return None
    return _fv("faturamento_mensal", fin.as_json(table), None, 0, 0.75, "Tabela mensal lida do documento; confira os valores no original.")


def _revenue_total(pages):
    table = fin.revenue_table(pages)
    if not table:
        return None
    totals = {y: round(sum(m.values()), 2) for y, m in table["years"].items()}
    latest = max(totals)
    return _fv("faturamento_total", fin.format_money(totals[latest]), f"{latest}: soma de {len(table['years'][latest])} meses", 0, 0.75)


def _period_end(pages):
    table = fin.revenue_table(pages)
    last = fin.last_month(table) if table else None
    if not last:
        return None
    y, m = map(int, last.split("-"))
    end = (date(y + (m == 12), m % 12 + 1, 1) - timedelta(days=1)).isoformat()
    return _fv("periodo_fim", end, f"último mês informado: {m:02d}/{y}", 0, 0.75)


def _debt_total(pages):
    _items, total = fin.debt_items(pages)
    return _fv("endividamento_total", fin.format_money(total), None, 0, 0.75) if total is not None else None


def _debt_items(pages):
    items, _total = fin.debt_items(pages)
    return _fv("endividamento_itens", fin.as_json(items), None, 0, 0.7) if items else None


def _concentration(pages):
    rows = fin.concentration(pages)
    return _fv("concentracao_clientes", fin.as_json(rows[:10]), None, 0, 0.7) if rows else None


def _crc(pages):
    hit = fin.accountant(pages)
    return _fv("crc_contador", hit[0], hit[1], hit[2], 0.85) if hit else None


def _rep(pages):
    hit = fin.representative(pages)
    return _fv("assinatura_representante", hit[0], hit[1], hit[2], 0.6, "Indica o bloco de assinatura; a assinatura em si é conferida por uma pessoa.") if hit else None


def _regime(pages):
    hit = fin.regime_bens(pages)
    return _fv("regime_bens", hit[0], hit[1], hit[2], 0.85) if hit else None


FINANCIAL = {
    "exercicio": _exercicio,
    "faturamento_mensal": _revenue,
    "faturamento_total": _revenue_total,
    "periodo_fim": _period_end,
    "endividamento_total": _debt_total,
    "endividamento_itens": _debt_items,
    "concentracao_clientes": _concentration,
    "crc_contador": _crc,
    "assinatura_representante": _rep,
    "regime_bens": _regime,
    "receita_liquida": _money_field("receita_liquida", ["RECEITA LIQUIDA", "RECEITA OPERACIONAL LIQUIDA"]),
    "lucro_liquido": _money_field("lucro_liquido", ["LUCRO LIQUIDO", "PREJUIZO LIQUIDO", "RESULTADO LIQUIDO", r"LUCRO \(PREJUIZO\) LIQUIDO"]),
    "patrimonio_liquido": _money_field("patrimonio_liquido", ["PATRIMONIO LIQUIDO"]),
    "ativo_total": _money_field("ativo_total", ["ATIVO TOTAL", "TOTAL DO ATIVO"]),
    "patrimonio_declarado": _money_field("patrimonio_declarado", ["BENS E DIREITOS", "TOTAL DE BENS"]),
    "dividas_onus": _money_field("dividas_onus", ["DIVIDAS E ONUS"]),
    "lucros_dividendos": _money_field("lucros_dividendos", ["LUCROS E DIVIDENDOS"]),
}


def extract(doc_type: str | None, wanted: list[str], pages: list[PageText]) -> dict[str, FieldValue]:
    out: dict[str, FieldValue] = {}
    gov = None
    for name in wanted:
        fv: FieldValue | None = None
        if name in governance.GOVERNANCE_FIELDS:
            if gov is None:
                partners = (_socios(pages) or FieldValue("socios", "", None, 0, None, None)).value.split("; ")
                gov = governance.read(pages, [p for p in partners if p])
            g = gov.get(name)
            if g:
                fv = FieldValue(name, g["value"], g["evidence"], 0.6, g["page"], None, True,
                                note="Lido da cláusula do contrato pelas regras; confirme no original.")
        elif name == "cpf":
            fv = _id_field("cpf", pages, CPF_RE, valid_cpf, format_cpf)
        elif name == "cnpj":
            fv = _id_field("cnpj", pages, CNPJ_RE, valid_cnpj, format_cnpj)
        elif name in ("data_nascimento", "data_expedicao", "data_emissao", "validade", "data_registro"):
            fv = _date_field(name, pages)
        elif name == "nome":
            fv = _text_after_label("nome", pages, NAME_EXCLUDE, cleaner=clean_name)
        elif name in ("razao_social", "endereco"):
            fv = _text_after_label(name, pages)
        elif name == "rg_numero":
            fv = _id_field("rg_numero", pages, re.compile(r"(?<![\d])(\d{1,2}\.?\d{3}\.?\d{3}\s*-?\s*[\dX])(?![\d])"), lambda _: True, lambda d: d)
            if fv:
                fv.value = re.sub(r"[^\dX]", "", fold(fv.raw or ""))
        elif name == "cnh_registro":
            fv = _id_field("cnh_registro", pages, re.compile(r"(?<!\d)(\d{11})(?!\d)"), lambda d: len(d) == 11, lambda d: d)
        elif name == "orgao_expedidor":
            fv = _issuer(pages)
        elif name == "situacao_cadastral":
            fv = _situacao(pages)
        elif name == "cep":
            fv = _cep(pages)
        elif name == "socios":
            fv = _socios(pages)
        elif name == "emissor":
            fv = _emissor(pages)
        elif name in FINANCIAL:
            fv = FINANCIAL[name](pages)
        if fv is not None:
            if pages and pages[0].source == "pdf_text" and fv.page is not None:
                fv.source = "pdf_text"
            out[name] = fv
    return out
