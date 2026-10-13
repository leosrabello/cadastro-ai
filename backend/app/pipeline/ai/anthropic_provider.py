import base64
import json
import logging

import anthropic
from pydantic import ValidationError

from app.pipeline.ai.base import AiFailed, AiRequest, AiResult, AiUnavailable
from app.pipeline.ai.prompts import SYSTEM, user_text
from app.pipeline.ai.schemas import AiAnalysis, json_schema

log = logging.getLogger(__name__)

# USD per million tokens (input, output), first-party API list prices as of 2026-10.
PRICES = {
    "claude-opus-5-5": (4.00, 20.00),
    "claude-sonnet-5-5": (2.00, 10.00),
    "claude-haiku-5-5": (0.10, 0.50),
}


class AnthropicProvider:
    name = "anthropic"

    def __init__(self, api_key: str, model: str, timeout: float = 120.0, client: anthropic.Anthropic | None = None, workspace_id: str | None = None):
        self.model = model
        # keys not scoped to a workspace must name one on every request
        headers = {"anthropic-workspace-id": workspace_id} if workspace_id else None
        self.client = client or anthropic.Anthropic(api_key=api_key, timeout=timeout, max_retries=2, default_headers=headers)

    def analyze(self, request: AiRequest) -> AiResult:
        content: list[dict] = [
            {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": base64.standard_b64encode(img).decode()}}
            for img in request.images
        ]
        content.append({"type": "text", "text": user_text(request)})
        schema = json_schema(list(request.doc_types))

        last_error: Exception | None = None
        total_in = total_out = 0
        for _attempt in range(2):  # one retry on malformed or schema-invalid output
            response = self._call(content, schema)
            total_in += response.usage.input_tokens
            total_out += response.usage.output_tokens
            if response.stop_reason == "refusal":
                raise AiFailed("o provedor recusou a análise deste documento")
            if response.stop_reason == "max_tokens":
                last_error = AiFailed("resposta truncada")
                continue
            text = next((b.text for b in response.content if b.type == "text"), "")
            try:
                analysis = AiAnalysis.model_validate(json.loads(text))
            except (json.JSONDecodeError, ValidationError) as exc:
                log.warning("AI output failed validation: %s", str(exc)[:300])
                last_error = exc
                continue
            price_in, price_out = PRICES.get(response.model, PRICES.get(self.model, (0.0, 0.0)))
            cost = (total_in * price_in + total_out * price_out) / 1_000_000
            return AiResult(analysis, response.model, total_in, total_out, round(cost, 5))
        raise AiFailed(f"resposta da IA fora do formato esperado: {str(last_error)[:200]}")

    def _call(self, content: list[dict], schema: dict):
        try:
            return self.client.beta.messages.create(
                model=self.model,
                max_tokens=16000,
                betas=["server-side-fallback-2026-07-01"],
                fallbacks="default",
                system=SYSTEM,
                messages=[{"role": "user", "content": content}],
                output_config={"effort": "medium", "format": {"type": "json_schema", "schema": schema}},
            )
        except anthropic.RateLimitError as exc:
            raise AiUnavailable("limite de requisições do provedor de IA") from exc
        except (anthropic.APITimeoutError, anthropic.APIConnectionError) as exc:
            raise AiUnavailable("provedor de IA inacessível ou lento") from exc
        except anthropic.AuthenticationError as exc:
            raise AiFailed("credencial do provedor de IA inválida") from exc
        except anthropic.PermissionDeniedError as exc:
            raise AiFailed("credencial do provedor de IA sem permissão") from exc
        except anthropic.BadRequestError as exc:
            raise AiFailed(f"requisição recusada pelo provedor: {exc.message[:200]}") from exc
        except anthropic.APIStatusError as exc:
            if exc.status_code >= 500:
                raise AiUnavailable(f"erro {exc.status_code} no provedor de IA") from exc
            raise AiFailed(f"erro {exc.status_code} no provedor de IA") from exc
