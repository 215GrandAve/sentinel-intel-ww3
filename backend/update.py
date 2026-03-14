from __future__ import annotations

import argparse
import json
import os
from copy import deepcopy
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List
from zoneinfo import ZoneInfo

from fetch_sources import load_review_packet, validate_card_sources
from score_engine import compute_weighted_score, derive_status

BASE_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = BASE_DIR / "data"
LATEST_PATH = DATA_DIR / "latest.json"
PROPOSED_PATH = DATA_DIR / "proposed.json"
EASTERN = ZoneInfo("America/New_York")

PROMPT_TEMPLATE = """
You are updating the Sentinel / WW3 Barometer proposal snapshot.
Return JSON only.

Rules:
- Preserve the product's war-room tone and specificity.
- Do not sanitize the intelligence language into generic corporate phrasing.
- Keep facts, assessments, interpretive signals, and data distinct.
- Return fields for: summary_append, changelog, vector_updates, intel_cards.
- Intel cards must include: title, timestamp, timestamp_label, class, severity, confidence, summary, source_label, source_url, source_type, published_at, retrieved_at, analyst_note.
- Use the existing dashboard voice: direct, high-signal, compact.

Current published snapshot:
{latest_snapshot}

Review packet / new source material:
{review_packet}
""".strip()


def next_scheduled_update(now: datetime) -> datetime:
    morning = now.replace(hour=6, minute=0, second=0, microsecond=0)
    evening = now.replace(hour=18, minute=0, second=0, microsecond=0)
    if now < morning:
        return morning
    if now < evening:
        return evening
    return (now + timedelta(days=1)).replace(hour=6, minute=0, second=0, microsecond=0)


def load_json(path: Path):
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def write_json(path: Path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)
        f.write("\n")


def apply_vector_updates(vectors, updates):
    lookup = {v["name"]: v for v in vectors}
    for name, delta in (updates or {}).items():
        if name in lookup:
            lookup[name].update(delta)
    return list(lookup.values())


def build_prompt(latest: Dict[str, Any], packet: Dict[str, Any]) -> str:
    return PROMPT_TEMPLATE.format(
        latest_snapshot=json.dumps(latest, ensure_ascii=False, indent=2),
        review_packet=json.dumps(packet, ensure_ascii=False, indent=2),
    )


def extract_json_block(text: str) -> Dict[str, Any]:
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1]
        text = text.rsplit("```", 1)[0].strip()
    return json.loads(text)


def generate_with_anthropic(prompt: str) -> Dict[str, Any]:
    from anthropic import Anthropic  # type: ignore

    client = Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    model = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-5")
    resp = client.messages.create(
        model=model,
        max_tokens=3000,
        temperature=0.2,
        messages=[{"role": "user", "content": prompt}],
    )
    chunks: List[str] = []
    for block in resp.content:
        if getattr(block, "type", "") == "text":
            chunks.append(block.text)
    return extract_json_block("\n".join(chunks))


def generate_with_openai(prompt: str) -> Dict[str, Any]:
    from openai import OpenAI  # type: ignore

    client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
    model = os.environ.get("OPENAI_MODEL", "gpt-5.4")
    resp = client.responses.create(
        model=model,
        input=prompt,
        temperature=0.2,
    )
    text = getattr(resp, "output_text", "")
    return extract_json_block(text)


def maybe_generate_packet(latest: Dict[str, Any], packet: Dict[str, Any], provider: str) -> Dict[str, Any]:
    provider = provider.lower().strip()
    if provider == "none":
        return packet
    prompt = build_prompt(latest, packet)
    if provider == "anthropic":
        return generate_with_anthropic(prompt)
    if provider == "openai":
        return generate_with_openai(prompt)
    raise ValueError(f"Unsupported provider: {provider}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Draft proposed.json from latest.json + a review packet.")
    parser.add_argument(
        "--review-packet",
        default=str(DATA_DIR / "review_packet.sample.json"),
        help="Path to a JSON review packet with new cards and vector updates.",
    )
    parser.add_argument(
        "--provider",
        default=os.environ.get("SENTINEL_LLM_PROVIDER", "none"),
        choices=["none", "anthropic", "openai"],
        help="Optional provider to transform the review packet into a richer proposal packet.",
    )
    args = parser.parse_args()

    latest = load_json(LATEST_PATH)
    proposal = deepcopy(latest)
    packet = load_review_packet(args.review_packet)
    packet = maybe_generate_packet(latest, packet, args.provider)
    now = datetime.now(EASTERN)

    proposal["meta"]["version"] = "v4.0-proposed"
    proposal["meta"]["previous_score"] = latest["meta"]["score"]
    proposal["meta"]["last_updated"] = packet.get("timestamp") or now.isoformat()
    proposal["meta"]["next_update"] = next_scheduled_update(now).isoformat()
    proposal["meta"]["day_label"] = latest["meta"].get("day_label", "DAY")
    proposal["meta"]["header_timestamp_label"] = datetime.fromisoformat(proposal["meta"]["last_updated"]).strftime("%B %d, %Y // %H:%M ET").upper()

    proposal["vectors"] = apply_vector_updates(proposal.get("vectors", []), packet.get("vector_updates"))
    proposal["meta"]["score"] = compute_weighted_score(proposal["vectors"])
    proposal["meta"]["delta"] = proposal["meta"]["score"] - proposal["meta"]["previous_score"]
    proposal["meta"]["status"] = derive_status(proposal["meta"]["score"])

    summary = proposal.setdefault("summary", {})
    summary["headline"] = proposal["meta"]["status"]
    summary["subheadline"] = "PROPOSAL AWAITING REVIEW"
    summary["description"] = (latest.get("summary", {}).get("description", "") + " " + packet.get("summary_append", "")).strip()
    summary["confidence"] = summary.get("confidence", "MODERATE")

    new_cards = validate_card_sources(packet.get("intel_cards", []))
    proposal["intel_cards"] = new_cards + proposal.get("intel_cards", [])
    proposal["changelog"] = packet.get("changelog", []) + [
        f"Draft score is now {proposal['meta']['score']}.",
        "Awaiting human approval before publish.",
    ]
    proposal["alerts"] = [
        "Proposed snapshot awaiting review",
        f"Draft score: {proposal['meta']['score']}",
        "Human approval required",
    ]
    proposal["alert_tape"] = "PROPOSED SNAPSHOT AWAITING REVIEW — HUMAN APPROVAL REQUIRED — LAST KNOWN GOOD REMAINS LIVE"
    proposal["meta"]["fallback_notice"] = "Displaying most recent published snapshot until a proposal is approved."

    write_json(PROPOSED_PATH, proposal)
    print(f"Wrote proposed snapshot to {PROPOSED_PATH}")


if __name__ == "__main__":
    main()
