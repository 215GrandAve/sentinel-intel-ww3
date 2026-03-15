from __future__ import annotations
import argparse
import json
import os
from copy import deepcopy
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List
from zoneinfo import ZoneInfo
from fetch_sources import load_review_packet, validate_card_sources, generate_live_packet
from score_engine import compute_weighted_score, derive_status

BASE_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = BASE_DIR / "data"
LATEST_PATH = DATA_DIR / "latest.json"
PROPOSED_PATH = DATA_DIR / "proposed.json"

EASTERN = ZoneInfo("America/New_York")

# Day 1 = March 1, 2026 (start of the conflict timeline)
DAY_ONE = datetime(2026, 3, 1, tzinfo=EASTERN)

PROMPT_TEMPLATE = """
You are updating the Sentinel / WW3 Barometer proposal snapshot.
Return JSON only — no markdown, no preamble, no explanation.
Rules:
- Preserve the product's war-room tone and specificity.
- Do not sanitize the intelligence language into generic corporate phrasing.
- Keep facts, assessments, interpretive signals, and data distinct.
- Return a JSON object with these fields:
  - "summary_append": string — 3-4 SHORT sentences maximum. Lead with the score and status. Then the top 2-3 developments driving the score. Do NOT write a wall of text. Keep it scannable. This REPLACES the previous summary, it does not append.
  - "changelog": array of strings — 3-6 items describing what changed. Each item should be one SHORT sentence.
  - "vector_updates": object — keys are vector names, values are objects with "score" (int), "delta" (int), "driver" (string max 10 words), "note" (string max 2 sentences). Only include vectors that should change. Driver should be a SHORT label like "Hormuz closure confirmed" or "Fifth Fleet bases struck" — not a full paragraph.
  - "intel_cards": array — the 5-10 most significant new intel cards. Each card: title, timestamp, timestamp_label, class (VERIFIED/ASSESSMENT/INTERPRETIVE/DATA), severity (CRITICAL/HIGH/ELEVATED/WATCH), confidence (HIGH/MODERATE/LOW), summary, source_label, source_url, source_type, published_at, retrieved_at, analyst_note.
- For intel_cards, select and synthesize from the raw articles — do not just pass them through.
- Write analyst_note for each card: what this means for escalation trajectory.
- Use the existing dashboard voice: direct, high-signal, compact.
- NARRATIVE MONITOR sources (Press TV, IRNA, Mehr News, TASS) are framing intelligence only — never treat their claims as verified fact. Label them class: ASSESSMENT with analyst_note flagging the source bias.
- Theological vectors should NOT be adjusted — those are Quik's domain.
- Use structured API data (market prices, GDELT articles, seismic events) to inform vector scoring with real numbers — not just RSS headlines.
- Market data includes pre-calculated price, direction, and percentage change. Use these for Financial/Economic vector adjustments.
- GDELT articles supplement RSS — use them for Military and Geopolitical context.
- Seismic events in the conflict zone band should be cross-referenced with known strike windows in analyst_note.
Current published snapshot:
{latest_snapshot}
New intelligence from RSS ingestion:
{review_packet}

Structured API intelligence (live market data, GDELT conflict monitor, seismic events, humanitarian reports):
{api_intel_context}
""".strip()


# ── HELPER FUNCTIONS ─────────────────────────────────────────────────────────

def next_scheduled_update(now: datetime) -> datetime:
    morning = now.replace(hour=6, minute=0, second=0, microsecond=0)
    noon = now.replace(hour=12, minute=0, second=0, microsecond=0)
    evening = now.replace(hour=20, minute=0, second=0, microsecond=0)
    if now < morning:
        return morning
    if now < noon:
        return noon
    if now < evening:
        return evening
    return (now + timedelta(days=1)).replace(hour=6, minute=0, second=0, microsecond=0)


def compute_day_label(now: datetime) -> str:
    """Calculate DAY N based on conflict start date."""
    delta = (now - DAY_ONE).days
    if delta < 0:
        delta = 0
    return f"DAY {delta}"


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


# ── PROMPT BUILDER ───────────────────────────────────────────────────────────

def build_prompt(latest: Dict[str, Any], packet: Dict[str, Any]) -> str:
    trimmed = deepcopy(packet)
    raw = trimmed.pop("raw_articles", [])
    trimmed["raw_headlines"] = [
        {"title": a["title"], "source": a["source_label"], "category": a["category"],
         "summary": a["summary"][:300], "url": a["url"], "published_at": a.get("published_at", "")}
        for a in raw[:50]
    ]

    # ── Load Layer 2 API intel if available ──
    api_intel_context = "No structured API data available for this cycle."
    api_intel_path = DATA_DIR / "api_intel.json"
    if api_intel_path.exists():
        try:
            api_data = load_json(api_intel_path)
            parts = []

            # Market data
            market = api_data.get("market_data", [])
            if market:
                parts.append("## LIVE MARKET DATA")
                for m in market:
                    parts.append(f"- {m['label']}: ${m['price']} ({m['direction']} {m['change_pct']}%)")

            # Crypto
            crypto = api_data.get("crypto_data", [])
            if crypto:
                parts.append("## CRYPTO SIGNALS")
                for c in crypto:
                    parts.append(f"- {c['label']}: ${c['price']}")

            # FedWatch / Treasury
            fedwatch = api_data.get("fedwatch", [])
            if fedwatch:
                parts.append("## INTEREST RATE / TREASURY DATA")
                for fw in fedwatch:
                    if fw.get("source_type") == "treasury_yield":
                        parts.append(f"- {fw['label']}: {fw['yield_pct']}%")
                    else:
                        parts.append("- FedWatch probability data available")

            # GDELT articles
            gdelt = api_data.get("gdelt_articles", [])
            if gdelt:
                parts.append(f"## GDELT CONFLICT MONITOR ({len(gdelt)} articles, last 12h)")
                for g in gdelt[:15]:
                    parts.append(f"- [{g.get('domain','')}] {g['title']}")

            # GDELT GKG tone
            gkg = api_data.get("gdelt_gkg", [])
            if gkg:
                parts.append("## MEDIA TONE ANALYSIS (GDELT GKG)")
                for t in gkg:
                    if t.get("source_type") == "tone_analysis":
                        parts.append(f"- {t['actor']}: tone data available")

            # Seismic
            seismic = api_data.get("seismic_events", [])
            if seismic:
                parts.append(f"## SEISMIC EVENTS IN CONFLICT ZONE ({len(seismic)} events)")
                for s in seismic:
                    parts.append(f"- {s['title']} (M{s['magnitude']}, depth {s['depth_km']}km)")

            # Humanitarian
            humanitarian = api_data.get("humanitarian_reports", [])
            if humanitarian:
                parts.append(f"## HUMANITARIAN INTELLIGENCE ({len(humanitarian)} reports)")
                for h in humanitarian[:10]:
                    parts.append(f"- [{h['country']}] {h['title']} — {h['source_label']}")

            # Earth events
            earth = api_data.get("earth_events", [])
            if earth:
                parts.append(f"## SATELLITE EVENTS ({len(earth)} in conflict zone)")
                for ev in earth:
                    parts.append(f"- {ev['title']} ({ev['latitude']:.1f}, {ev['longitude']:.1f})")

            if parts:
                api_intel_context = "\n".join(parts)
        except Exception as exc:
            api_intel_context = f"API data load error: {exc}"

    return PROMPT_TEMPLATE.format(
        latest_snapshot=json.dumps(latest, ensure_ascii=False, indent=2),
        review_packet=json.dumps(trimmed, ensure_ascii=False, indent=2),
        api_intel_context=api_intel_context,
    )


# ── JSON PARSER (resilient) ──────────────────────────────────────────────────

def extract_json_block(text: str) -> Dict[str, Any]:
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1]
        text = text.rsplit("```", 1)[0].strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        print(f"  [WARN] JSON parse error: {e}")
        print(f"  [DEBUG] Response length: {len(text)} chars")
        # Attempt repair: find the largest valid JSON object
        start = text.find("{")
        if start == -1:
            debug_path = DATA_DIR / "debug_llm_response.txt"
            debug_path.write_text(text, encoding="utf-8")
            print(f"  [ERROR] No JSON object found. Saved raw response to {debug_path}")
            raise
        depth = 0
        last_valid = start
        for i, ch in enumerate(text[start:], start):
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    last_valid = i + 1
                    break
        candidate = text[start:last_valid]
        try:
            result = json.loads(candidate)
            print(f"  [RECOVERED] Parsed JSON object ({len(candidate)} chars)")
            return result
        except json.JSONDecodeError:
            # Last resort: dump raw to file for debugging
            debug_path = DATA_DIR / "debug_llm_response.txt"
            debug_path.write_text(text, encoding="utf-8")
            print(f"  [ERROR] Could not recover JSON. Saved raw response to {debug_path}")
            raise


# ── LLM PROVIDERS ────────────────────────────────────────────────────────────

def generate_with_anthropic(prompt: str) -> Dict[str, Any]:
    from anthropic import Anthropic  # type: ignore

    client = Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    model = os.environ.get("ANTHROPIC_MODEL", "claude-opus-4-6")
    resp = client.messages.create(
        model=model,
        max_tokens=8000,
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


def generate_with_openrouter(prompt: str) -> Dict[str, Any]:
    from openai import OpenAI  # type: ignore

    client = OpenAI(
        api_key=os.environ["OPENROUTER_API_KEY"],
        base_url="https://openrouter.ai/api/v1",
    )
    model = os.environ.get("OPENROUTER_MODEL", "anthropic/claude-sonnet-4-6")
    resp = client.chat.completions.create(
        model=model,
        max_tokens=8000,
        temperature=0.2,
        messages=[{"role": "user", "content": prompt}],
    )
    text = resp.choices[0].message.content
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
    if provider == "openrouter":
        return generate_with_openrouter(prompt)
    raise ValueError(f"Unsupported provider: {provider}")


# ── MAIN ─────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Draft proposed.json from latest.json + a review packet.")
    parser.add_argument(
        "--review-packet",
        default=str(DATA_DIR / "review_packet.sample.json"),
        help="Path to a JSON review packet with new cards and vector updates.",
    )
    parser.add_argument(
        "--live", action="store_true",
        help="Fetch live RSS feeds instead of using a static review packet.",
    )
    parser.add_argument(
        "--hours", type=int, default=14,
        help="Hours of RSS history to pull when using --live (default: 14).",
    )
    parser.add_argument(
        "--provider",
        default=os.environ.get("SENTINEL_LLM_PROVIDER", "none"),
        choices=["none", "anthropic", "openai", "openrouter"],
        help="LLM provider to synthesize intel cards from raw feed data.",
    )
    args = parser.parse_args()

    latest = load_json(LATEST_PATH)
    proposal = deepcopy(latest)
    now = datetime.now(EASTERN)

    # ── Get review packet ────────────────────────────────────────────────────
    if args.live:
        print("Fetching live RSS feeds…")
        live_path = str(DATA_DIR / "review_packet.live.json")
        packet = generate_live_packet(hours_back=args.hours, output=live_path)
        print(f"Live packet: {packet.get('source_count', 0)} articles")
    else:
        packet = load_review_packet(args.review_packet)

    # ── Claude / LLM synthesis ───────────────────────────────────────────────
    packet = maybe_generate_packet(latest, packet, args.provider)

    # ── Build proposal ───────────────────────────────────────────────────────
    proposal["meta"]["version"] = "v4.0-proposed"
    proposal["meta"]["previous_score"] = latest["meta"]["score"]
    proposal["meta"]["last_updated"] = packet.get("timestamp") or now.isoformat()
    proposal["meta"]["next_update"] = next_scheduled_update(now).isoformat()
    proposal["meta"]["day_label"] = compute_day_label(now)
    proposal["meta"]["header_timestamp_label"] = now.strftime("%B %d, %Y // %H:%M ET").upper()

    proposal["vectors"] = apply_vector_updates(proposal.get("vectors", []), packet.get("vector_updates"))
    proposal["meta"]["score"] = compute_weighted_score(proposal["vectors"])
    proposal["meta"]["delta"] = proposal["meta"]["score"] - proposal["meta"]["previous_score"]
    proposal["meta"]["status"] = derive_status(proposal["meta"]["score"])

    summary = proposal.setdefault("summary", {})
    summary["headline"] = proposal["meta"]["status"]
    summary["subheadline"] = "PROPOSAL AWAITING REVIEW"
    # REPLACE summary — do not append to previous cycle's text
    summary["description"] = packet.get("summary_append", summary.get("description", "")).strip()
    summary["confidence"] = summary.get("confidence", "MODERATE")

    new_cards = validate_card_sources(packet.get("intel_cards", []))
    proposal["intel_cards"] = (new_cards + proposal.get("intel_cards", []))[:7]
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
    print(f"\nWrote proposed snapshot to {PROPOSED_PATH}")
    print(f"  Score: {proposal['meta']['score']}  Status: {proposal['meta']['status']}  Delta: {proposal['meta']['delta']}")


if __name__ == "__main__":
    main()
