"""Fixed-window rate limiting in Redis. Fails open if Redis is unreachable, and says so in the log."""

import logging
import time
from functools import lru_cache

import redis

from app.config import get_settings
from app.errors import ApiError

log = logging.getLogger(__name__)


@lru_cache
def _client() -> redis.Redis:
    return redis.Redis.from_url(get_settings().redis_url, socket_timeout=0.5)


def hit(bucket: str, limit: int, window_seconds: int) -> None:
    window = int(time.time() // window_seconds)
    key = f"rl:{bucket}:{window}"
    try:
        pipe = _client().pipeline()
        pipe.incr(key)
        pipe.expire(key, window_seconds + 1)
        count = pipe.execute()[0]
    except redis.RedisError as exc:
        log.warning("rate limiter unavailable, allowing request: %s", exc)
        return
    if count > limit:
        raise ApiError(429, "rate_limited", "Muitas tentativas. Aguarde um momento e tente de novo.")
