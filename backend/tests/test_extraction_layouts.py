"""Layouts the analysts corrected in production, with invented data: the rules must now read them."""

from app.pipeline import financial as fin
from app.pipeline.extract import extract
from app.pipeline.ocr.base import Line, PageText, Word


def pages(*texts: str) -> list[PageText]:
    out = []
    for pi, text in enumerate(texts):
        lines = []
        for li, row in enumerate(text.strip("\n").splitlines()):
            words = [Word(t, 0.95, (0.05 + 0.05 * wi, 0.02 * li, 0.09 + 0.05 * wi, 0.02 * li + 0.015), li) for wi, t in enumerate(row.split())]
            lines.append(Line(row, words))
        out.append(PageText(pi, "ocr:tesseract", lines))
    return out


CARTAO = """
REPÚBLICA FEDERATIVA DO BRASIL
CADASTRO NACIONAL DA PESSOA JURÍDICA
NOME EMPRESARIAL
DATA DE CONSTITUIÇÃO
A & B CONFECCOES LTDA
12/03/2015
LOGRADOURO
NÚMERO
COMPLEMENTO
R DAS FLORES
120
********
CEP
BAIRRO/DISTRITO
MUNICÍPIO
UF
80.010-000
CENTRO
CURITIBA
PR
"""


def test_cartao_cnpj_with_stacked_headings():
    f = extract("cartao_cnpj", ["razao_social", "endereco"], pages(CARTAO))
    assert f["razao_social"].value == "A & B CONFECCOES LTDA"
    assert f["endereco"].value == "R DAS FLORES, 120, 80.010-000, CENTRO - CURITIBA/PR"


def test_contract_company_name_without_preposition_or_clause_heading():
    text = """
CLÁUSULA PRIMEIRA - DA RAZÃO SOCIAL, TIPO DE SOCIEDADE, E SEDE
A sociedade gira sob a denominação social de A & B CONFECCOES LTDA, com sede em Curitiba
"""
    assert extract("contrato_social", ["razao_social"], pages(text))["razao_social"].value == "A & B CONFECCOES LTDA"


ENERGISA = """
DANF3E - DOCUMENTO AUXILIAR DA NOTA FISCAL
DE ENERGIA ELÉTRICA ELETRÔNICA
ENERGISA MINAS RIO - DISTRIBUIDORA DE ENERGIA S.A.
Av Central, 100 - Distrito Industrial
Cataguases / MG - CEP 36770-000
CNPJ 19.527.639/0001-58 Insc.Est. 153.045152-0011
Classificação: MTC-CONVENCIONAL BAIXA TENSÃO
Tipo de Fornecimento: Trifásico
B1 RESIDENCIAL/RESIDENCIAL
Disp.:100
Lim. min.: 117
TENSÃO NOMINAL EM VOLTS
JOAO DA SILVA PEREIRA
NÚMERO DA UC
RUA DAS PEDRAS, S/N LOTE 5 - CENTRO
CEP 36878000 - ROSARIO DA LIMEIRA/MG
DATA EMISSÂO/APRESENTAÇÂO:05/07/2026
"""

COPEL = """
DANF3E - DOCUMENTO AUXILIAR DA
NOTA FISCAL ELETRÔNICA DE ENERGIA ELÉTRICA
Cope! Distribuição SA
R Jose Izidoro Biazetto, 158 - Bloco A - Mossungue
CEP: 81200-240 - Curitiba - PR
CNPJ 04.368.898/0001-06
"""


def test_utility_bill_issuer_and_customer_cep():
    f = extract("comprovante_endereco", ["emissor", "cep", "data_emissao"], pages(ENERGISA))
    assert f["emissor"].value == "ENERGISA MINAS RIO - DISTRIBUIDORA DE ENERGIA S.A."
    assert f["cep"].value == "36878-000"
    assert f["data_emissao"].value == "2026-07-05"
    c = extract("comprovante_endereco", ["emissor", "cep"], pages(COPEL))
    assert c["emissor"].value == "Copel Distribuição SA"
    assert "cep" not in c  # only the distributor's CEP is legible: better empty than the wrong one


def test_marriage_certificate_garbage_is_not_a_name():
    assert "nome" not in extract("certidao_casamento", ["nome"], pages("NOME\nDE E MARIA\n"))


BALANCO = """
DEMONSTRAÇÕES CONTÁBEIS
Em 31 de dezembro de 2025 e 2024
No último trimestre do exercício de 2023, a totalidade do capital social foi adquirida
BALANÇOS PATRIMONIAIS DOS EXERCÍCIOS FINDOS
EM 31 DE DEZEMBRO
2025
2024
PATRIMÔNIO LÍQUIDO
1.000.000,00
Capital Social
TOTAL DO PASSIVO E PATRIMÔNIO LÍQUIDO 52.300.000,00 48.100.000,00
LUCRO LÍQUIDO DO EXERCÍCIO 3.200.000,00 2.900.000,00
"""


def test_comparative_statement_reads_the_current_year():
    f = extract("balanco_dre", ["exercicio", "patrimonio_liquido", "lucro_liquido"], pages(BALANCO))
    assert f["exercicio"].value == "2025"
    assert "patrimonio_liquido" not in f  # the bare heading is followed by the capital account, not the total
    assert f["lucro_liquido"].value == "R$ 3.200.000,00"
    assert fin.exercicio(pages("BALANÇO PATRIMONIAL\nEM 31 DE DEZEMBRO\n2025\n2024\n"))[0] == "2025"


def test_equity_total_on_its_line():
    f = extract("balanco_dre", ["patrimonio_liquido"], pages("PATRIMONIO LIQUIDO 12.500.000,00 10.100.000,00\n2025 2024\n"))
    assert f["patrimonio_liquido"].value == "R$ 12.500.000,00"


def test_accountant_registration_keeps_the_suffix():
    cases = {
        "Contador - CRCPR-012345-O/8": "CRC PR 012345-O/8",
        "Contador – CRC/PR 012.345/O-8": "CRC PR 012.345/O-8",
        "CPF: 123.456.789-09 CRC: PR-012345-O/8": "CRC PR 012345-O/8",
        "Reg. no CRC - PR sob o No. 012345/O-8": "CRC PR 012345/O-8",
        "CRC-PR nº. 1.234/O-5": "CRC PR 1.234/O-5",
        "CRC.: SP-123456/O-7": "CRC SP 123456/O-7",
        "CRC: 1-SP-123456/0-7 - Contador": "CRC SP 123456/O-7",
        "CRCMG 12345": "CRC MG 12345",
    }
    for line, expected in cases.items():
        assert fin.accountant(pages(line))[0] == expected, line
