from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

FIELD_NAMES = [
    "nome", "cpf", "cnpj", "rg_numero", "cnh_registro", "data_nascimento", "data_expedicao",
    "data_emissao", "validade", "orgao_expedidor", "endereco", "cep", "razao_social",
    "situacao_cadastral", "socios", "data_registro", "emissor", "exercicio", "receita_liquida", "lucro_liquido",
    "patrimonio_liquido", "ativo_total", "faturamento_total", "periodo_fim", "endividamento_total", "crc_contador",
    "assinatura_representante", "patrimonio_declarado", "dividas_onus", "lucros_dividendos", "regime_bens",
]


class AiField(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(max_length=40)
    value: str = Field(max_length=400)
    page: int = Field(ge=0, le=50)
    evidence_text: str = Field(max_length=400)


class AiObservation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["inconsistency", "possible_alteration", "missing_element", "illegible", "other"]
    severity: Literal["info", "low", "medium", "high"]
    field: str = Field(max_length=40)
    page: int = Field(ge=0, le=50)
    explanation: str = Field(min_length=3, max_length=800)
    evidence_text: str = Field(max_length=400)
    certainty: Literal["low", "medium", "high"]
    recommended_action: str = Field(max_length=300)


class AiAnalysis(BaseModel):
    model_config = ConfigDict(extra="forbid")
    document_type: str = Field(max_length=40)
    issuer: str = Field(max_length=200)
    fields: list[AiField] = Field(max_length=40)
    observations: list[AiObservation] = Field(max_length=20)
    embedded_instructions_detected: bool
    summary: str = Field(max_length=600)


def json_schema(doc_types: list[str]) -> dict:
    """Schema sent to the provider. Kept free of nulls and optional keys for strict decoding."""
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["document_type", "issuer", "fields", "observations", "embedded_instructions_detected", "summary"],
        "properties": {
            "document_type": {"type": "string", "enum": [*doc_types, "desconhecido"]},
            "issuer": {"type": "string"},
            "fields": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["name", "value", "page", "evidence_text"],
                    "properties": {
                        "name": {"type": "string", "enum": FIELD_NAMES},
                        "value": {"type": "string"},
                        "page": {"type": "integer"},
                        "evidence_text": {"type": "string"},
                    },
                },
            },
            "observations": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["kind", "severity", "field", "page", "explanation", "evidence_text", "certainty", "recommended_action"],
                    "properties": {
                        "kind": {"type": "string", "enum": ["inconsistency", "possible_alteration", "missing_element", "illegible", "other"]},
                        "severity": {"type": "string", "enum": ["info", "low", "medium", "high"]},
                        "field": {"type": "string"},
                        "page": {"type": "integer"},
                        "explanation": {"type": "string"},
                        "evidence_text": {"type": "string"},
                        "certainty": {"type": "string", "enum": ["low", "medium", "high"]},
                        "recommended_action": {"type": "string"},
                    },
                },
            },
            "embedded_instructions_detected": {"type": "boolean"},
            "summary": {"type": "string"},
        },
    }
