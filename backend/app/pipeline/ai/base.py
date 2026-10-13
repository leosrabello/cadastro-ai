from dataclasses import dataclass, field
from typing import Protocol

from app.pipeline.ai.schemas import AiAnalysis


class AiUnavailable(Exception):
    """Transient: timeout, rate limit, provider outage. The document stays usable; AI can be retried."""


class AiFailed(Exception):
    """Permanent for this request: refusal, invalid output after retry, or a configuration error."""


@dataclass
class AiRequest:
    doc_type_hint: str | None
    doc_types: dict[str, str]  # key -> label
    wanted_fields: list[str]
    pages_text: list[str]
    rule_fields: dict[str, str]
    reference_date: str
    images: list[bytes] = field(default_factory=list)  # PNG, only when sending images is allowed


@dataclass
class AiResult:
    analysis: AiAnalysis
    model: str
    input_tokens: int
    output_tokens: int
    cost_usd: float


class AiProvider(Protocol):
    name: str

    def analyze(self, request: AiRequest) -> AiResult: ...
