"""Detects text in a document that addresses an automated system.

A genuine identity document or utility bill never tells a reader to approve anything or to
ignore instructions. Such text is reported as an integrity finding for a human, and the
document text is in any case passed to the AI only as quoted data (see ai/prompts.py).
"""

import re

from app.pipeline.normalize import fold

_PATTERNS = [
    r"IGNOR(E|AR|EM)\s+(ALL\s+|TODAS?\s+|TUDO\s+)?(AS\s+|OS\s+|THE\s+|YOUR\s+|SUAS\s+)?(PREVIOUS|PRIOR|ABOVE|ANTERIORES|INSTRUC|REGRAS|RULES|ORIENTAC)",
    r"(DISREGARD|FORGET)\s+(ALL|PREVIOUS|YOUR)",
    r"SYSTEM\s*PROMPT|PROMPT\s+DO\s+SISTEMA",
    r"YOU\s+ARE\s+(NOW|AN?)\s+",
    r"VOCE\s+(AGORA\s+)?E\s+UM",
    r"(APROVE|APROVAR|APPROVE)\s+(ESTE|ESSE|THIS|O|A)\s+(CADASTRO|DOCUMENTO|REGISTRATION|CLIENTE|CUSTOMER)",
    r"(MARK|MARQUE|MARCAR)\s+(AS|COMO)\s+(VALID|VALIDO|AUTENTIC|APROVAD|GENUINE)",
    r"(ASSISTANT|ASSISTENTE|AI|IA|LLM|MODELO)\s*[:,]\s*(PLEASE|POR FAVOR|DEVE|MUST)",
    r"</?\s*(SYSTEM|INSTRUCTIONS?|DOCUMENT_TEXT)\s*>",
    r"NAO\s+(REPORTE|RELATE|SINALIZE)",
    r"DO\s+NOT\s+(REPORT|FLAG|MENTION)",
]
_RX = [re.compile(p) for p in _PATTERNS]


def scan(text: str) -> list[str]:
    folded = fold(text)
    hits = []
    for line in folded.splitlines():
        if any(rx.search(line) for rx in _RX):
            hits.append(line.strip()[:200])
    return hits
