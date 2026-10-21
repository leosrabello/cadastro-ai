"""Readers for the financial documents of a credit analysis: revenue statements, debt
statements, balance sheets, income-tax returns, customer concentration, and the accountant's
signature block. Values are kept as read; nothing here interprets them."""

import json
import re

from app.pipeline.normalize import MONEY_RE, digits, fold, format_money, month_index, parse_money
from app.pipeline.ocr.base import PageText

YEAR_RE = re.compile(r"(?<!\d)(20\d{2})(?!\d)")
# CRC-PR 012345/O-8, CRCPR-012345-O/8, CRC: 1-SP-123456/O-7, Reg. no CRC - PR sob o No. 012345/O-8, CRCMG 12345
CRC_RE = re.compile(r"\bCRC[\s.:/-]*(?:\d\s*-\s*)?([A-Z]{2})?[\s/-]*(?:SOB O\s+)?(?:N[O0]?\.?\s*)?"
                    r"(\d{1,3}\.?\d{3})(\s*[-/]\s*[O0T]\s*[-/]\s*\d)?")


def _lines(pages: list[PageText]):
    for p in pages:
        for i, line in enumerate(p.lines):
            yield p, i, fold(line.text), line


def exercicio(pages: list[PageText]) -> tuple[str, str, int] | None:
    """The fiscal year the document refers to. Comparative statements ('Em 31 de dezembro de 2025
    e 2024', or the two years as column headings) refer to the later year."""
    patterns = [
        r"31\s*(?:DE\s*)?DEZEMBRO\s*(?:DE\s*)?(20\d{2})(?:\s*E\s*(20\d{2}))?",
        r"EXERCICIO\s*(?:DE|SOCIAL|FINDO EM|:)?\s*(?:\d{2}/\d{2}/)?(20\d{2})",
        r"ANO[- ]CALENDARIO\s*:?\s*(20\d{2})",
        r"ENCERRADO EM\s*\d{2}/\d{2}/(20\d{2})",
        r"(?:EM|ATE)\s*31/12/(20\d{2})",
        r"FATURAMENTO\s*(?:MENSAL|FECHADO|DE)?\s*(?:DO ANO DE)?\s*(20\d{2})",
        r"BALANCETE.*?(20\d{2})",
    ]
    for p, i, text, line in _lines(pages):
        if re.search(r"31\s*(?:DE\s*)?DEZEMBRO\s*(?:DE)?$", text) and i + 1 < len(p.lines):
            years = YEAR_RE.findall(" ".join(fold(x.text) for x in p.lines[i + 1: i + 3]))
            if years and re.fullmatch(r"(20\d{2}\s*)+", fold(p.lines[i + 1].text)):
                return max(years), line.text, p.index
        for pat in patterns:
            m = re.search(pat, text)
            if m:
                return max(y for y in m.groups() if y), line.text, p.index
    return None


def comparative(pages: list[PageText]) -> bool:
    """Statements with the year's and the previous year's columns side by side, the current year first."""
    prev = ""
    for _p, _i, text, _line in _lines(pages):
        m = re.search(r"(?<!\d)(20\d{2})\s*(?:E\s+)?(20\d{2})(?!\d)", text)
        if m and int(m.group(1)) == int(m.group(2)) + 1:
            return True
        if re.fullmatch(r"20\d{2}", text) and re.fullmatch(r"20\d{2}", prev) and int(prev) == int(text) + 1:
            return True
        prev = text
    return False


def labelled_money(pages: list[PageText], labels: list[str], same_line: bool = False,
                   exclude: tuple[str, ...] = ()) -> tuple[float, str, int] | None:
    """The money value on the line of a label (or the next line): the first column of a comparative
    statement, otherwise the last (a trial balance's closing balance)."""
    first = comparative(pages)
    for p, i, text, line in _lines(pages):
        if any(x in text for x in exclude):
            continue
        if any(re.search(rf"(?<![A-Z]){lbl}(?![A-Z])", text) for lbl in labels):
            nxt = fold(p.lines[i + 1].text) if i + 1 < len(p.lines) and not same_line else ""
            for candidate in (text, nxt):
                values = [parse_money(m.group(0)) for m in MONEY_RE.finditer(candidate)]
                values = [v for v in values if v is not None]
                if values:
                    return values[0] if first else values[-1], line.text, p.index
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
            suffix = re.sub(r"\s|(?<=[-/])0(?=[-/])", lambda x: "O" if x.group(0) == "0" else "", m.group(3) or "")
            return (f"CRC {m.group(1) or ''} {m.group(2)}{suffix}").replace("  ", " ").strip(), line.text, p.index
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
