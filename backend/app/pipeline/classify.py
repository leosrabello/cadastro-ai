from dataclasses import dataclass

from app.pipeline.normalize import fold


@dataclass
class Classification:
    doc_type: str | None
    confidence: float
    matched: list[str]
    scores: dict[str, int]


def classify(text: str, document_types: dict) -> Classification:
    """Keyword scoring against the configured document types.

    Confidence is the share of keyword hits held by the winning type, discounted when
    there are few hits. It is a ranking signal, not a probability.
    """
    folded = fold(text)
    scores: dict[str, int] = {}
    matched: dict[str, list[str]] = {}
    for key, spec in document_types.items():
        hits = [kw for kw in spec.get("keywords", []) if fold(kw) in folded]
        # longer, more specific phrases count more
        scores[key] = sum(2 if len(kw) > 12 else 1 for kw in hits)
        matched[key] = hits
    if not scores or max(scores.values()) == 0:
        return Classification(None, 0.0, [], scores)
    ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
    best, best_score = ranked[0]
    runner_up = ranked[1][1] if len(ranked) > 1 else 0
    share = best_score / (best_score + runner_up) if (best_score + runner_up) else 0.0
    evidence = min(1.0, best_score / 4)
    return Classification(best, round(share * evidence, 3), matched[best], scores)
