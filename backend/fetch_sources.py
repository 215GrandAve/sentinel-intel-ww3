from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

REQUIRED_SOURCE_KEYS = {
    "source_label",
    "source_url",
    "source_type",
    "published_at",
    "retrieved_at",
}


def load_review_packet(path: str | Path) -> Dict[str, Any]:
    packet_path = Path(path)
    with packet_path.open("r", encoding="utf-8") as f:
        return json.load(f)


def validate_card_sources(cards: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    cleaned = []
    for card in cards:
        for key in REQUIRED_SOURCE_KEYS:
            card.setdefault(key, "")
        cleaned.append(card)
    return cleaned
