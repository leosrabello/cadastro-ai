from app.config import get_settings
from app.pipeline.ai.base import AiFailed, AiProvider, AiRequest, AiResult, AiUnavailable

_override: AiProvider | None = None
_override_set = False


def set_provider(provider: AiProvider | None) -> None:
    """Test hook. set_provider(None) clears the override."""
    global _override, _override_set
    _override = provider
    _override_set = provider is not None


def get_provider() -> AiProvider | None:
    """The configured provider, or None when no provider is configured."""
    if _override_set:
        return _override
    s = get_settings()
    if not s.ai_configured:
        return None
    from app.pipeline.ai.anthropic_provider import AnthropicProvider

    return AnthropicProvider(api_key=s.anthropic_api_key or "", model=s.ai_model, timeout=s.ai_timeout_seconds)


__all__ = ["AiFailed", "AiProvider", "AiRequest", "AiResult", "AiUnavailable", "get_provider", "set_provider"]
