from __future__ import annotations

from typing import Iterable, Mapping

DEFAULT_WEIGHTS = {
    "Military Escalation": 0.24,
    "Geopolitical Stability": 0.16,
    "Financial / Economic": 0.18,
    "Theological Convergence": 0.16,
    "Third Temple / Al-Aqsa": 0.14,
    "Information Warfare": 0.12,
}


def compute_weighted_score(vectors: Iterable[Mapping[str, object]]) -> int:
    total = 0.0
    weight_total = 0.0
    for vector in vectors:
        name = str(vector.get("name", ""))
        score = float(vector.get("score", 0))
        weight = DEFAULT_WEIGHTS.get(name, 0.10)
        total += score * weight
        weight_total += weight
    if weight_total == 0:
        return 0
    return round(total / weight_total)


def derive_status(score: int) -> str:
    if score >= 90:
        return "THRESHOLD / EXTREME"
    if score >= 75:
        return "SEVERE / CRITICAL"
    if score >= 60:
        return "HIGH"
    if score >= 40:
        return "ELEVATED"
    return "LOW / WATCH"
