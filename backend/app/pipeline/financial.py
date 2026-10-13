"""Readers for the financial documents of a credit analysis: revenue statements, debt
statements, balance sheets, income-tax returns, customer concentration, and the accountant's
signature block. Values are kept as read; nothing here interprets them."""

import json
import re

from app.pipeline.normalize import MONEY_RE, digits, fold, format_money, month_index, parse_money
from app.pipeline.ocr.base import PageText

YEAR_RE = re.compile(r"(?<!\d)(20\d{2})(?!\d)")
CRC_RE = re.compile(r"\bCRC\s*[-/:]?\s*([A-Z]{2})?\s*[-/]?\s*(\d{1,3}\.?\d{3}(?:/[A-Z0-9-]{1,4})?)")


def _lines(pages: list[PageText]):
    for p in pages:
        for i, line in enumerate(p.lines):
            yield p, i, fold(line.text), line


def exercicio(pages: list[PageText]) -> tuple[str, str, int] | None:
    """The fiscal year the document refers to."""
    patterns = [
        r"EXERCICIO\s*(?:DE|SOCIAL|FINDO EM|:)?\s*(?:\d{2}/\d{2}/)?(20\d{2})",
        r"ANO[- ]CALENDARIO\s*:?\s*(20\d{2})",
        r"ENCERRADO EM\s*\d{2}/\d{2}/(20\d{2})",
        r"(?:EM|ATE)\s*31/12/(20\d{2})",
        r"FATURAMENTO\s*(?:MENSAL|FECHADO|DE)?\s*(?:DO ANO DE)?\s*(20\d{2})",
        r"BALANCETE.*?(20\d{2})",
    ]
    for p, _i, text, line in _lines(pages):
        for pat in patterns:
            m = re.search(pat, text)
            if m:
                return m.group(1), line.text, p.index
    return None


def labelled_money(pages: list[PageText], labels: list[str]) -> tuple[float, str, int] | None:
    """The first money value on the line of a label (or the next line)."""
    for p, i, text, line in _lines(pages):
        if any(re.search(rf"(?<![A-Z]){lbl}(?![A-Z])", text) for lbl in labels):
            for candidate in (text, fold(p.lines[i + 1].text) if i + 1 < len(p.lines) else ""):
                values = [parse_money(m.group(0)) for m in MONEY_RE.finditer(candidate)]
                values = [v for v in values if v is not None]
                if values:
                    return values[-1], line.text, p.index
    return None


def revenue_table(pages: list[PageText]) -> dict | None:
    """Monthly revenue. Year columns come from a header line listing years; each month line
    then carries its values in that order. Returns {"years": {"2026": {"1": 13088786.0, ...}}}."""
    years: list[str] = []
    table: dict[str, dict[str, float]] = {}
    for _p, _i, text, _line in _lines(pages):
        found_years = YEAR_RE.findall(text)
        words = text.split()
        first = words[0] if words else ""
        m_idx = month_index(first) if first else None
        if m_idx is None and len(found_years) >= 1 and not MONEY_RE.search(text.replace(" ".join(found_years), "")):
            years = found_years
            continue
        if m_idx is not None and years:
            values = [parse_money(m.group(0)) for m in MONEY_RE.finditer(text)]
            values = [v for v in values if v is not None]
            for y, v in zip(years, values):
                table.setdefault(y, {})[str(m_idx)] = v
    if not table:
        return None
    return {"years": table}


def last_month(table: dict) -> str | None:
    best = None
    for y, months in table.get("years", {}).items():
        for m, v in months.items():
            if v:
                key = f"{y}-{int(m):02d}"
                best = max(best or key, key)
    return best


def debt_items(pages: list[PageText]) -> tuple[list[dict], float | None]:
    """Institution lines with limit and amount taken, and the declared total."""
    items, total = [], None
    for _p, _i, text, line in _lines(pages):
        values = [parse_money(m.group(0)) for m in MONEY_RE.finditer(text)]
        values = [v for v in values if v is not None]
        if not values:
            continue
        name = MONEY_RE.split(line.text)[0].strip(" :-|R$")
        if fold(name).startswith(("TOTAL", "VALOR TOTAL")):
            total = values[-1]
        elif len(re.sub(r"[^A-Za-z]", "", name)) >= 3 and not fold(name).startswith(("DATA", "EMITIDO", "CNPJ")):
            items.append({"instituicao": name[:60], "limite": values[0] if len(values) > 1 else None, "tomado": values[-1]})
    if total is None and items:
        total = round(sum(i["tomado"] for i in items), 2)
    return items, total


def concentration(pages: list[PageText]) -> list[dict]:
    """Customer lines with a percentage share, largest first."""
    rows = []
    for _p, _i, text, line in _lines(pages):
        m = re.search(r"(\d{1,2}(?:,\d{1,2})?)\s*%", text)
        if not m:
            continue
        name = re.split(r"\s{2,}|\d", line.text)[0].strip(" :-")
        if len(re.sub(r"[^A-Za-z]", "", name)) < 3 or fold(name).startswith(("TOTAL", "CLIENTE ", "CLASSE")):
            continue
        rows.append({"cliente": name[:50], "percentual": float(m.group(1).replace(",", "."))})
    rows.sort(key=lambda r: r["percentual"], reverse=True)
    return rows


def accountant(pages: list[PageText]) -> tuple[str, str, int] | None:
    for p, _i, text, line in _lines(pages):
        m = CRC_RE.search(text)
        if m:
            return (f"CRC {m.group(1) or ''} {m.group(2)}").replace("  ", " ").strip(), line.text, p.index
    return None


def representative(pages: list[PageText]) -> tuple[str, str, int] | None:
    for p, _i, text, line in _lines(pages):
        if re.search(r"(SOCIO[- ]ADMINISTRADOR|REPRESENTANTE LEGAL|ADMINISTRADOR|DIRETOR PRESIDENTE|DIRETOR)\b", text) and not CRC_RE.search(text):
            return line.text.strip()[:120], line.text, p.index
    return None


def regime_bens(pages: list[PageText]) -> tuple[str, str, int] | None:
    for p, _i, text, line in _lines(pages):
        m = re.search(r"(SEPARACAO (?:TOTAL|CONVENCIONAL|OBRIGATORIA|ABSOLUTA) DE BENS|COMUNHAO (?:PARCIAL|UNIVERSAL) DE BENS|PARTICIPACAO FINAL NOS AQUESTOS)", text)
        if m:
            return m.group(1).capitalize(), line.text, p.index
    return None


def as_json(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


__all__ = ["accountant", "as_json", "concentration", "debt_items", "digits", "exercicio", "format_money", "labelled_money",
           "last_month", "regime_bens", "representative", "revenue_table"]
