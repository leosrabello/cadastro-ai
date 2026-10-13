"""Synthetic Brazilian onboarding documents for tests, demos and evaluation.

Every document is printed with "DOCUMENTO SINTÉTICO — SEM VALOR" and uses generated
identifiers. Layouts imitate the information structure of real documents, not their design.
"""

import io
import random
from dataclasses import dataclass, field
from datetime import date

import fitz
from PIL import Image, ImageDraw, ImageFont

FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
FONT_BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"


def _font(size: int, bold: bool = False):
    return ImageFont.truetype(FONT_BOLD if bold else FONT, size)


def make_cpf(seed: int) -> str:
    rnd = random.Random(seed)
    d = [rnd.randint(0, 9) for _ in range(9)]
    for n in (9, 10):
        total = sum(d[i] * ((n + 1) - i) for i in range(n))
        d.append((total * 10) % 11 % 10)
    s = "".join(map(str, d))
    return f"{s[:3]}.{s[3:6]}.{s[6:9]}-{s[9:]}"


def make_cnpj(seed: int) -> str:
    rnd = random.Random(seed)
    d = [rnd.randint(0, 9) for _ in range(8)] + [0, 0, 0, 1]
    w1 = [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]
    for weights in (w1, [6] + w1):
        r = sum(x * w for x, w in zip(d, weights)) % 11
        d.append(0 if r < 2 else 11 - r)
    s = "".join(map(str, d))
    return f"{s[:2]}.{s[2:5]}.{s[5:8]}/{s[8:12]}-{s[12:]}"


def br(d: date) -> str:
    return d.strftime("%d/%m/%Y")


@dataclass
class Canvas:
    width: int = 1700
    height: int = 1100
    lines: list = field(default_factory=list)

    def __post_init__(self):
        self.img = Image.new("RGB", (self.width, self.height), (250, 250, 247))
        self.draw = ImageDraw.Draw(self.img)

    def text(self, x, y, s, size=34, bold=False, fill=(20, 20, 20)):
        self.draw.text((x, y), s, font=_font(size, bold), fill=fill)

    def banner(self):
        self.draw.rectangle([0, self.height - 60, self.width, self.height], fill=(230, 230, 225))
        self.text(40, self.height - 50, "DOCUMENTO SINTÉTICO — SEM VALOR — GERADO PARA TESTES", 26, fill=(90, 90, 90))

    def png(self) -> bytes:
        buf = io.BytesIO()
        self.img.save(buf, "PNG")
        return buf.getvalue()

    def jpeg(self, quality=88) -> bytes:
        buf = io.BytesIO()
        self.img.save(buf, "JPEG", quality=quality)
        return buf.getvalue()


def rg(name: str, cpf: str, rg_num: str, birth: date, issued: date, issuer: str = "SSP/SP") -> Canvas:
    c = Canvas()
    c.text(60, 40, "REPÚBLICA FEDERATIVA DO BRASIL", 40, True)
    c.text(60, 95, "SECRETARIA DA SEGURANÇA PÚBLICA — CARTEIRA DE IDENTIDADE", 30)
    c.text(60, 190, f"REGISTRO GERAL: {rg_num}", 36)
    c.text(900, 190, f"DATA DE EXPEDIÇÃO: {br(issued)}", 36)
    c.text(60, 290, f"NOME: {name}", 38)
    c.text(60, 390, f"DATA DE NASCIMENTO: {br(birth)}", 36)
    c.text(60, 490, f"CPF: {cpf}", 36)
    c.text(60, 590, f"ÓRGÃO EXPEDIDOR: {issuer}", 36)
    c.text(60, 690, "NATURALIDADE: SÃO PAULO - SP", 36)
    c.banner()
    return c


def cnh(name: str, cpf: str, registro: str, birth: date, emissao: date, validade: date, issuer: str = "DETRAN-SP") -> Canvas:
    c = Canvas()
    c.text(60, 40, "REPÚBLICA FEDERATIVA DO BRASIL", 40, True)
    c.text(60, 95, "CARTEIRA NACIONAL DE HABILITAÇÃO", 34)
    c.text(60, 140, "MINISTÉRIO DOS TRANSPORTES — SENATRAN", 28)
    c.text(60, 230, "NOME", 28, fill=(80, 80, 80))
    c.text(60, 270, name, 38)
    # labels above values, side by side: exercises positional extraction
    c.text(60, 370, "DATA NASCIMENTO", 28, fill=(80, 80, 80))
    c.text(560, 370, "CPF", 28, fill=(80, 80, 80))
    c.text(1060, 370, "Nº REGISTRO", 28, fill=(80, 80, 80))
    c.text(60, 410, br(birth), 36)
    c.text(560, 410, cpf, 36)
    c.text(1060, 410, registro, 36)
    c.text(60, 520, "DATA EMISSÃO", 28, fill=(80, 80, 80))
    c.text(560, 520, "VALIDADE", 28, fill=(80, 80, 80))
    c.text(1060, 520, "CATEGORIA", 28, fill=(80, 80, 80))
    c.text(60, 560, br(emissao), 36)
    c.text(560, 560, br(validade), 36)
    c.text(1060, 560, "AB", 36)
    c.text(60, 680, f"ÓRGÃO EMISSOR: {issuer}", 32)
    c.banner()
    return c


def comprovante(holder: str, address: str, cep: str, emissao: date, company: str = "COMPANHIA PAULISTA DE ENERGIA SINTÉTICA", extra: list[str] | None = None) -> Canvas:
    c = Canvas()
    c.text(60, 40, company, 36, True)
    c.text(60, 100, "CONTA DE ENERGIA ELÉTRICA — SEGUNDA VIA", 30)
    c.text(60, 200, f"TITULAR: {holder}", 36)
    c.text(60, 280, f"ENDEREÇO: {address}", 32)
    c.text(60, 350, f"CEP: {cep}", 32)
    c.text(60, 440, f"DATA DE EMISSÃO: {br(emissao)}", 34)
    c.text(60, 510, "CONSUMO DO MÊS: 212 KWH      VALOR: R$ 187,40", 32)
    y = 600
    for line in extra or []:
        c.text(60, y, line, 30)
        y += 60
    c.banner()
    return c


def cartao_cnpj_pdf(cnpj: str, razao: str, situacao: str, emissao: date, address: str = "AV PAULISTA 1000 SAO PAULO SP") -> bytes:
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    y = 60
    for text, size in [
        ("REPUBLICA FEDERATIVA DO BRASIL", 14),
        ("CADASTRO NACIONAL DA PESSOA JURIDICA", 12),
        ("COMPROVANTE DE INSCRICAO E DE SITUACAO CADASTRAL", 11),
        (f"NUMERO DE INSCRICAO: {cnpj}", 11),
        (f"NOME EMPRESARIAL: {razao}", 11),
        (f"LOGRADOURO: {address}", 10),
        (f"SITUACAO CADASTRAL: {situacao}", 11),
        (f"DATA DE EMISSAO: {br(emissao)}", 11),
        ("Emitido pela RECEITA FEDERAL (SINTETICO)", 9),
        ("DOCUMENTO SINTETICO - SEM VALOR - GERADO PARA TESTES", 8),
    ]:
        page.insert_text((50, y), text, fontsize=size, fontname="helv")
        y += 34
    out = doc.tobytes()
    doc.close()
    return out


def contrato_social_pdf(razao: str, cnpj: str, socios: list[str], registered: date) -> bytes:
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    lines = [
        "CONTRATO SOCIAL - CONSOLIDACAO",
        f"RAZAO SOCIAL: {razao}",
        f"CNPJ: {cnpj}",
        "CLAUSULA PRIMEIRA - DOS SOCIOS",
        *[f"{s}, brasileiro(a), empresario(a), residente em Sao Paulo" for s in socios],
        "CLAUSULA SEGUNDA - DO CAPITAL: 100.000 QUOTAS",
        f"REGISTRADO EM: {br(registered)} JUNTA COMERCIAL (SINTETICO)",
        "DOCUMENTO SINTETICO - SEM VALOR - GERADO PARA TESTES",
    ]
    y = 60
    for text in lines:
        page.insert_text((50, y), text, fontsize=10, fontname="helv")
        y += 30
    out = doc.tobytes()
    doc.close()
    return out


def image_pdf(canvas: Canvas, producer: str | None = None, hidden_text: str | None = None) -> bytes:
    """A 'scanned' PDF: the page is an image. Optionally with an invisible text layer and producer."""
    doc = fitz.open()
    page = doc.new_page(width=842, height=545)
    page.insert_image(page.rect, stream=canvas.png())
    if hidden_text:
        y = 40
        for line in hidden_text.split("\n"):
            page.insert_text((40, y), line, fontsize=11, render_mode=3)
            y += 18
    if producer:
        doc.set_metadata({"producer": producer, "creator": producer})
    out = doc.tobytes()
    doc.close()
    return out


@dataclass
class Person:
    name: str
    cpf: str
    birth: date
    rg: str
    cnh: str


def person(seed: int, name: str = "MARIA APARECIDA DOS SANTOS SILVA") -> Person:
    rnd = random.Random(seed)
    return Person(
        name=name,
        cpf=make_cpf(seed),
        birth=date(1960 + rnd.randint(0, 40), rnd.randint(1, 12), rnd.randint(1, 28)),
        rg=f"{rnd.randint(10, 59)}.{rnd.randint(100, 999)}.{rnd.randint(100, 999)}-{rnd.randint(0, 9)}",
        cnh="".join(str(rnd.randint(0, 9)) for _ in range(11)),
    )


# ---------- company (FIDC) credit documents ----------

BANNER = "DOCUMENTO SINTETICO - SEM VALOR - GERADO PARA TESTES"
MESES = ["JANEIRO", "FEVEREIRO", "MARCO", "ABRIL", "MAIO", "JUNHO", "JULHO", "AGOSTO", "SETEMBRO", "OUTUBRO", "NOVEMBRO", "DEZEMBRO"]


def money(v: float) -> str:
    s = f"{abs(v):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return ("-" if v < 0 else "") + s


def text_pdf(lines: list[str], size: float = 10, photo: Image.Image | None = None) -> bytes:
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    y = 56
    for text in lines:
        if y > 800:
            page = doc.new_page(width=595, height=842)
            y = 56
        page.insert_text((48, y), text, fontsize=size, fontname="helv")
        y += size * 2.1
    if photo is not None:
        buf = io.BytesIO()
        photo.convert("RGB").save(buf, "JPEG", quality=80)
        page.insert_image(fitz.Rect(48, y + 10, 330, y + 190), stream=buf.getvalue())
    page.insert_text((48, 820), BANNER, fontsize=7, fontname="helv")
    out = doc.tobytes()
    doc.close()
    return out


@dataclass
class Company:
    razao: str
    cnpj: str
    partners: list[Person]


def company(seed: int = 500) -> Company:
    return Company(
        razao="RECICLAGEM VALE VERDE LTDA",
        cnpj=make_cnpj(seed),
        partners=[person(seed + 1, "SIDNEI DALMORO"), person(seed + 2, "JAQUELINE PRADO DALMORO")],
    )


def signature_block(rep: str, crc: bool = True) -> list[str]:
    lines = ["", f"{rep} - SOCIO ADMINISTRADOR"]
    if crc:
        lines.append("ANA PAULA REIS - CONTADORA - CRC PR-045123/O-8")
    return lines


def certidao_simplificada_pdf(c: Company, issued: date) -> bytes:
    return text_pdf([
        "JUNTA COMERCIAL DO ESTADO (SINTETICA)",
        "CERTIDAO SIMPLIFICADA",
        "CERTIFICAMOS QUE AS INFORMACOES ABAIXO CONSTAM DOS ATOS ARQUIVADOS",
        f"NOME EMPRESARIAL: {c.razao}",
        f"CNPJ: {c.cnpj}",
        "NIRE: 41201234567",
        "CLAUSULA DOS SOCIOS",
        *[f"{p.name}, brasileiro(a), empresario(a)" for p in c.partners],
        f"DATA DE EMISSAO: {br(issued)}",
    ])


def balanco_pdf(c: Company, year: int, receita: float, lucro: float, pl: float, ativo: float, signed: bool = True) -> bytes:
    return text_pdf([
        f"{c.razao}",
        f"CNPJ: {c.cnpj}",
        f"BALANCO PATRIMONIAL E DEMONSTRACAO DO RESULTADO DO EXERCICIO FINDO EM 31/12/{year}",
        f"ATIVO CIRCULANTE                       {money(ativo * 0.6)}",
        f"ATIVO NAO CIRCULANTE                   {money(ativo * 0.4)}",
        f"ATIVO TOTAL                            {money(ativo)}",
        f"PASSIVO CIRCULANTE                     {money(ativo * 0.45)}",
        f"PATRIMONIO LIQUIDO                     {money(pl)}",
        "DEMONSTRACAO DO RESULTADO",
        f"RECEITA LIQUIDA                        {money(receita)}",
        f"LUCRO LIQUIDO DO EXERCICIO             {money(lucro)}",
        *signature_block(c.partners[0].name, crc=signed),
    ])


def balancete_pdf(c: Company, year: int, receita: float) -> bytes:
    return text_pdf([
        f"{c.razao}",
        f"CNPJ: {c.cnpj}",
        f"BALANCETE DE VERIFICACAO - EXERCICIO {year} - ATE 31/08/{year}",
        "CONTA                      SALDO ANTERIOR      DEBITO      CREDITO",
        f"RECEITA LIQUIDA            {money(receita)}",
        *signature_block(c.partners[0].name),
    ])


def faturamento_pdf(c: Company, year: int, values: dict[int, float], signed: bool = True) -> bytes:
    lines = [f"{c.razao}", f"CNPJ: {c.cnpj}", f"RELACAO DE FATURAMENTO MENSAL {year}", f"MES        {year}"]
    for m, v in sorted(values.items()):
        lines.append(f"{MESES[m - 1]}        R$ {money(v)}")
    lines.append(f"TOTAL      R$ {money(sum(values.values()))}")
    return text_pdf(lines + signature_block(c.partners[0].name, crc=signed))


def endividamento_pdf(c: Company, issued: date, items: list[tuple[str, float, float]]) -> bytes:
    lines = [f"{c.razao}", f"CNPJ: {c.cnpj}", "RELACAO DE ENDIVIDAMENTO FINANCEIRO", f"DATA BASE: {br(issued)}",
             "INSTITUICAO            LIMITE            SALDO DEVEDOR"]
    for name, limit, taken in items:
        lines.append(f"{name}    R$ {money(limit)}    R$ {money(taken)}")
    lines.append(f"TOTAL    R$ {money(sum(t for _n, _l, t in items))}")
    return text_pdf(lines + signature_block(c.partners[0].name, crc=False))


def curva_abc_pdf(c: Company, issued: date, rows: list[tuple[str, float]]) -> bytes:
    lines = [f"{c.razao}", "CURVA ABC DE CLIENTES", f"DATA DE EMISSAO: {br(issued)}", "CLIENTE                         PARTICIPACAO"]
    lines += [f"{name}    {str(p).replace('.', ',')}%" for name, p in rows]
    return text_pdf(lines)


def irpf_pdf(p: Person, exercicio_: int, bens: float, dividas: float, dividendos: float) -> bytes:
    return text_pdf([
        "MINISTERIO DA FAZENDA - RECEITA FEDERAL (SINTETICO)",
        "IMPOSTO SOBRE A RENDA - PESSOA FISICA",
        f"DECLARACAO DE AJUSTE ANUAL - EXERCICIO {exercicio_} ANO-CALENDARIO {exercicio_ - 1}",
        f"NOME: {p.name}",
        f"CPF: {p.cpf}",
        f"BENS E DIREITOS EM 31/12/{exercicio_ - 1}      R$ {money(bens)}",
        f"DIVIDAS E ONUS REAIS                  R$ {money(dividas)}",
        f"LUCROS E DIVIDENDOS RECEBIDOS         R$ {money(dividendos)}",
    ])


def relatorio_visita_pdf(c: Company, visited: date) -> bytes:
    photo = Image.new("RGB", (560, 360), (120, 128, 120))
    d = ImageDraw.Draw(photo)
    d.rectangle([40, 120, 520, 330], fill=(170, 170, 160))
    d.rectangle([90, 200, 200, 330], fill=(80, 80, 80))
    d.text((44, 40), "FOTO SINTETICA DA FACHADA", fill=(250, 250, 250), font=_font(22))
    return text_pdf([
        "RELATORIO DE VISITA COMERCIAL",
        f"EMPRESA: {c.razao}",
        f"DATA DA VISITA: {br(visited)}",
        "Estrutura ampla e organizada, compativel com o porte das operacoes.",
        "REGISTRO FOTOGRAFICO:",
    ], photo=photo)


def certidao_casamento_pdf(a: Person, b: Person, married: date, regime: str = "COMUNHAO PARCIAL DE BENS") -> bytes:
    return text_pdf([
        "REPUBLICA FEDERATIVA DO BRASIL - REGISTRO CIVIL (SINTETICO)",
        "CERTIDAO DE CASAMENTO",
        f"NOME: {a.name}",
        f"CONTRAENTE: {b.name}",
        f"DATA DO CASAMENTO: {br(married)}",
        f"REGIME DE BENS: {regime}",
    ])
