import re
import unicodedata
from datetime import date

_MONTHS = {
    "JANEIRO": 1, "FEVEREIRO": 2, "MARCO": 3, "ABRIL": 4, "MAIO": 5, "JUNHO": 6,
    "JULHO": 7, "AGOSTO": 8, "SETEMBRO": 9, "OUTUBRO": 10, "NOVEMBRO": 11, "DEZEMBRO": 12,
    "JAN": 1, "FEV": 2, "MAR": 3, "ABR": 4, "MAI": 5, "JUN": 6,
    "JUL": 7, "AGO": 8, "SET": 9, "OUT": 10, "NOV": 11, "DEZ": 12,
}

DATE_RE = re.compile(r"\b(\d{1,2})\s*[/.\-]\s*(\d{1,2})\s*[/.\-]\s*(\d{2,4})\b")
DATE_LONG_RE = re.compile(r"\b(\d{1,2})\s+DE\s+([A-Z]+)\s+DE\s+(\d{4})\b")
DATE_MON_RE = re.compile(r"\b(\d{1,2})\s*[/.\-]?\s*(JAN|FEV|MAR|ABR|MAI|JUN|JUL|AGO|SET|OUT|NOV|DEZ)\s*[/.\-]?\s*(\d{4})\b")
CPF_RE = re.compile(r"(?<!\d)(\d{3})\s*\.?\s*(\d{3})\s*\.?\s*(\d{3})\s*[-–.]?\s*(\d{2})(?!\d)")
CNPJ_RE = re.compile(r"(?<!\d)(\d{2})\s*\.?\s*(\d{3})\s*\.?\s*(\d{3})\s*/?\s*(\d{4})\s*[-–.]?\s*(\d{2})(?!\d)")
CEP_RE = re.compile(r"(?<!\d)(\d{5})\s*-?\s*(\d{3})(?!\d)")


def fold(text: str) -> str:
    """Upper-case, strip accents, collapse whitespace. Used for matching, never for display."""
    decomposed = unicodedata.normalize("NFKD", text)
    stripped = "".join(c for c in decomposed if not unicodedata.combining(c))
    return re.sub(r"[ \t]+", " ", stripped.upper()).strip()


def digits(text: str) -> str:
    return re.sub(r"\D", "", text or "")


def valid_cpf(value: str) -> bool:
    d = digits(value)
    if len(d) != 11 or d == d[0] * 11:
        return False
    for n in (9, 10):
        total = sum(int(d[i]) * ((n + 1) - i) for i in range(n))
        check = (total * 10) % 11 % 10
        if check != int(d[n]):
            return False
    return True


def valid_cnpj(value: str) -> bool:
    d = digits(value)
    if len(d) != 14 or d == d[0] * 14:
        return False
    w1 = [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]
    w2 = [6] + w1
    for weights, pos in ((w1, 12), (w2, 13)):
        total = sum(int(d[i]) * w for i, w in enumerate(weights))
        r = total % 11
        check = 0 if r < 2 else 11 - r
        if check != int(d[pos]):
            return False
    return True


def format_cpf(d: str) -> str:
    return f"{d[:3]}.{d[3:6]}.{d[6:9]}-{d[9:]}" if len(d) == 11 else d


def format_cnpj(d: str) -> str:
    return f"{d[:2]}.{d[2:5]}.{d[5:8]}/{d[8:12]}-{d[12:]}" if len(d) == 14 else d


def _year(y: str) -> int:
    n = int(y)
    if len(y) == 2:
        return 2000 + n if n <= 50 else 1900 + n
    return n


def parse_date(text: str) -> date | None:
    """Parse the first Brazilian-format date in text (dd/mm/yyyy, '12 de março de 2024', 12/MAR/2024)."""
    t = fold(text)
    for rx, month_lookup in ((DATE_RE, False), (DATE_LONG_RE, True), (DATE_MON_RE, True)):
        m = rx.search(t)
        if not m:
            continue
        try:
            day = int(m.group(1))
            month = _MONTHS.get(m.group(2)) if month_lookup else int(m.group(2))
            if month is None:
                continue
            return date(_year(m.group(3)), month, day)
        except ValueError:
            return None
    return None


def find_dates(text: str) -> list[tuple[date, str]]:
    out = []
    t = fold(text)
    for m in DATE_RE.finditer(t):
        try:
            out.append((date(_year(m.group(3)), int(m.group(2)), int(m.group(1))), m.group(0)))
        except ValueError:
            continue
    return out


_PARTICLES = {"DE", "DA", "DO", "DOS", "DAS", "E", "D"}


def name_tokens(name: str, ignore: set[str] | None = None) -> list[str]:
    ignore = _PARTICLES if ignore is None else ignore
    cleaned = re.sub(r"[^A-Z ]", " ", fold(name))
    return [t for t in cleaned.split() if t and t not in ignore]


def clean_name(text: str) -> str:
    t = re.sub(r"[^A-Za-zÀ-ÿ' ]", " ", text)
    return re.sub(r"\s+", " ", t).strip().upper()


# identifiers (CPF 942.228.949-15, CNPJ 78.827.730/0001-58) are excluded by the lookahead
MONEY_RE = re.compile(r"(?<![\d.,/])(-?\s?R?\$?\s?-?\d{1,3}(?:\.\d{3})+(?:,\d{2})?|-?\s?R?\$?\s?-?\d+,\d{2})(?![\d/]|-\d|\.\d)")
MONTH_NAMES = ["JANEIRO", "FEVEREIRO", "MARCO", "ABRIL", "MAIO", "JUNHO", "JULHO", "AGOSTO", "SETEMBRO", "OUTUBRO", "NOVEMBRO", "DEZEMBRO"]


def parse_money(text: str) -> float | None:
    """Brazilian money: '1.234.567,89', 'R$ 13.088.786', '-R$ 997.712'. Returns None if not a number."""
    t = text.replace("R$", "").replace(" ", "").strip()
    negative = t.startswith("-") or t.endswith("-")
    t = t.strip("-")
    if not re.fullmatch(r"\d{1,3}(?:\.\d{3})*(?:,\d{1,2})?|\d+(?:,\d{1,2})?", t):
        return None
    value = float(t.replace(".", "").replace(",", "."))
    return -value if negative else value


def format_money(value: float) -> str:
    s = f"{abs(value):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"-R$ {s}" if value < 0 else f"R$ {s}"


def month_index(token: str) -> int | None:
    t = fold(token)
    for i, m in enumerate(MONTH_NAMES):
        if t.startswith(m[:3]) and (len(t) <= 4 or m.startswith(t[: len(m)])):
            return i + 1
    return None
