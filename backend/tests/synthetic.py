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
