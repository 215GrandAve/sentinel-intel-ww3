from __future__ import annotations

"""
Sentinel fetch_sources.py — Live RSS ingestion for the WW3 Barometer.

Wave 1 sources: conflict, geopolitical, and key news RSS feeds.
No API keys required. All free, all RSS.

Usage:
  # Generate a live review packet from RSS feeds:
  python fetch_sources.py --output data/review_packet.live.json

  # Called internally by update.py when --live flag is used.
"""

import argparse
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from time import mktime
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

try:
    import feedparser
except ImportError:
    raise SystemExit(
        "feedparser not installed. Run:\n"
        "  source /var/www/sentinel/backend/.venv/bin/activate\n"
        "  pip install feedparser"
    )

EASTERN = ZoneInfo("America/New_York")
BASE_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = BASE_DIR / "data"

REQUIRED_SOURCE_KEYS = {
    "source_label",
    "source_url",
    "source_type",
    "published_at",
    "retrieved_at",
}

# ── RSS FEED REGISTRY ─────────────────────────────────────────────────────────
# (url, source_label, source_type, category)

RSS_FEEDS: list[tuple[str, str, str, str]] = [
    # ── CONFLICT & MILITARY ──
    ("https://isw.pub/feed",                                "ISW",              "think tank",          "military"),
    ("https://bellingcat.com/feed",                         "Bellingcat",       "OSINT",               "military"),
    ("https://thecradle.co/feed",                           "The Cradle",       "media report",        "military"),
    ("https://criticalthreats.org/rss",                     "Critical Threats", "think tank",          "military"),
    ("https://reliefweb.int/updates/rss.xml",               "ReliefWeb",        "UN agency",           "humanitarian"),

    # ── GEOPOLITICAL / NEWS ──
    ("https://www.aljazeera.com/xml/rss/all.xml",           "Al Jazeera",       "media report",        "geopolitical"),
    ("http://feeds.bbci.co.uk/news/world/rss.xml",          "BBC News",         "media report",        "geopolitical"),
    ("https://rss.nytimes.com/services/xml/rss/nyt/World.xml", "NYT",           "media report",        "geopolitical"),
    ("https://feeds.reuters.com/reuters/worldNews",         "Reuters",          "wire service",        "geopolitical"),
    ("https://apnews.com/rss",                              "AP News",          "wire service",        "geopolitical"),
    ("https://www.timesofisrael.com/feed/",                 "Times of Israel",  "media report",        "geopolitical"),
    ("https://www.jpost.com/rss/rssfeedsfrontpage.aspx",    "Jerusalem Post",   "media report",        "geopolitical"),
    ("https://www.middleeasteye.net/rss",                   "Middle East Eye",  "media report",        "geopolitical"),
    ("https://www.middleeastmonitor.com/feed/",             "MEMO",             "media report",        "geopolitical"),
    ("https://www.rudaw.net/english/rss",                   "Rudaw",            "media report",        "geopolitical"),
    ("https://www.dawn.com/feeds/home",                     "Dawn",             "media report",        "geopolitical"),
    ("https://www.dailysabah.com/rssFeed/todays_world",     "Daily Sabah",      "media report",        "geopolitical"),

    # ── FINANCIAL / ENERGY ──
    ("https://www.investing.com/rss/news.rss",              "Investing.com",    "financial media",     "financial"),

    # ── WEAPONS & ARMS CONTROL ──
    ("https://www.armscontrol.org/rss",                     "Arms Control Assoc", "think tank",        "military"),
    ("https://fas.org/feed/",                               "FAS",              "think tank",          "military"),
    ("https://www.iaea.org/newscenter/news/rss",            "IAEA",             "UN agency",           "military"),

    # ── HUMANITARIAN ──
    ("https://www.msf.org/rss",                             "MSF",              "NGO",                 "humanitarian"),
    ("https://www.amnesty.org/en/latest/rss.xml",           "Amnesty Intl",     "NGO",                 "humanitarian"),
    ("https://www.hrw.org/rss",                             "Human Rights Watch","NGO",                "humanitarian"),

    # ── NARRATIVE MONITORS (framing intel only — never for fact verification) ──
    ("https://www.presstv.ir/Section/10101/rss",            "Press TV",         "state media (Iran)",  "narrative"),
    ("https://en.irna.ir/rss",                              "IRNA",             "state media (Iran)",  "narrative"),
    ("https://en.mehrnews.com/rss",                         "Mehr News",        "state media (Iran)",  "narrative"),
    ("https://tass.com/rss/v2.xml",                         "TASS",             "state media (Russia)","narrative"),
]

# ── RELEVANCE KEYWORDS ────────────────────────────────────────────────────────

RELEVANCE_PATTERNS = [
    r"iran", r"tehran", r"irgc", r"hormuz", r"strait",
    r"israel", r"idf", r"netanyahu", r"hezbollah", r"houthi",
    r"yemen", r"gaza", r"west\s*bank", r"lebanon", r"syria", r"iraq",
    r"centcom", r"pentagon", r"strike", r"missile", r"drone",
    r"nuclear", r"enrichment", r"sanction",
    r"oil\s*price", r"crude", r"brent", r"opec",
    r"natanz", r"fordow",
    r"al[\-\s]?aqsa", r"temple\s*mount", r"third\s*temple",
    r"escalat", r"retaliat", r"war\s*power",
    r"ceasefire", r"diplomacy", r"negotiat",
    r"proxy", r"militia", r"ballistic", r"hypersonic",
    r"aircraft\s*carrier", r"naval", r"blockade", r"tanker",
    r"refinery", r"pipeline",
    r"cyber\s*attack", r"information\s*warfare", r"disinformation",
    r"nato", r"brics", r"russia.*iran", r"china.*iran",
    r"de-?dollar", r"gold.*surge", r"market.*crash", r"oil.*spike",
    r"ww3", r"world\s*war",
    r"ramadan", r"messianic", r"eschatolog", r"prophec",
]

_RELEVANCE_RE = re.compile("|".join(RELEVANCE_PATTERNS), re.IGNORECASE)


# ── FEED PARSING ──────────────────────────────────────────────────────────────

def parse_pub_date(entry: dict) -> Optional[datetime]:
    """Extract publication datetime from a feedparser entry."""
    for field in ("published_parsed", "updated_parsed"):
        tp = entry.get(field)
        if tp:
            try:
                return datetime.fromtimestamp(mktime(tp), tz=timezone.utc)
            except Exception:
                continue
    for field in ("published", "updated"):
        raw = entry.get(field, "")
        if raw:
            try:
                return datetime.fromisoformat(raw.replace("Z", "+00:00"))
            except Exception:
                pass
    return None


def is_relevant(title: str, summary: str) -> bool:
    """Check if an article matches escalation-relevant keywords."""
    return bool(_RELEVANCE_RE.search(f"{title} {summary}"))


def fetch_single_feed(
    url: str,
    label: str,
    source_type: str,
    category: str,
    cutoff: datetime,
) -> list[dict]:
    """Fetch one RSS feed and return relevant articles."""
    items = []
    try:
        feed = feedparser.parse(url, agent="SentinelBot/1.0")
        for entry in feed.entries[:30]:
            pub_dt = parse_pub_date(entry)
            if pub_dt and pub_dt < cutoff:
                continue

            title = entry.get("title", "").strip()
            summary = entry.get("summary", entry.get("description", "")).strip()
            summary = re.sub(r"<[^>]+>", "", summary).strip()
            if len(summary) > 500:
                summary = summary[:500] + "…"

            link = entry.get("link", "")

            if not is_relevant(title, summary):
                continue

            items.append({
                "title":        title,
                "summary":      summary,
                "url":          link,
                "published_at": pub_dt.isoformat() if pub_dt else "",
                "source_label": label,
                "source_type":  source_type,
                "category":     category,
            })
    except Exception as e:
        print(f"  WARN: Failed to fetch {label} ({url}): {e}")

    return items


def fetch_all_feeds(hours_back: int = 14) -> list[dict]:
    """Fetch all RSS feeds, return relevant articles from last N hours."""
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=hours_back)
    all_items = []

    print(f"Fetching {len(RSS_FEEDS)} feeds (cutoff: {hours_back}h ago)…")
    for url, label, stype, category in RSS_FEEDS:
        items = fetch_single_feed(url, label, stype, category, cutoff)
        if items:
            print(f"  ✓ {label}: {len(items)} relevant")
        all_items.extend(items)

    # Deduplicate by normalized title
    seen = set()
    deduped = []
    for item in all_items:
        key = re.sub(r"[^a-z0-9]", "", item["title"].lower())[:80]
        if key not in seen:
            seen.add(key)
            deduped.append(item)

    deduped.sort(key=lambda x: x.get("published_at", ""), reverse=True)
    print(f"\nTotal relevant articles: {len(deduped)}")
    return deduped


# ── REVIEW PACKET GENERATION ─────────────────────────────────────────────────

def build_review_packet(articles: list[dict]) -> dict:
    """
    Package raw articles into a review packet for update.py.

    When update.py uses --provider anthropic, Claude will synthesize
    these into proper intel cards, vector score adjustments, and changelog.
    When --provider none, they pass through as raw cards.
    """
    now = datetime.now(EASTERN)
    retrieved_at = now.isoformat()

    intel_cards = []
    for art in articles[:40]:
        wire = art["source_type"] in ("wire service", "UN agency", "official statement")
        intel_cards.append({
            "title":           art["title"],
            "timestamp":       art.get("published_at", retrieved_at),
            "timestamp_label": f"▲ {art['source_label'].upper()} // {art['category'].upper()}",
            "class":           "VERIFIED" if wire else "ASSESSMENT",
            "severity":        "HIGH",
            "confidence":      "HIGH" if wire else "MODERATE",
            "summary":         art["summary"],
            "source_label":    art["source_label"],
            "source_url":      art["url"],
            "source_type":     art["source_type"],
            "published_at":    art.get("published_at", ""),
            "retrieved_at":    retrieved_at,
            "analyst_note":    "",
        })

    by_category: dict[str, list[str]] = {}
    for art in articles:
        by_category.setdefault(art["category"], []).append(art["title"])

    summary_parts = [f"{cat}: {len(titles)} signals" for cat, titles in by_category.items()]

    return {
        "timestamp":      retrieved_at,
        "source_count":   len(articles),
        "feed_count":     len(RSS_FEEDS),
        "summary_append": f"Live RSS ingestion: {len(articles)} relevant articles across {len(by_category)} categories. {'; '.join(summary_parts)}.",
        "changelog":      [
            f"RSS ingestion: {len(articles)} articles from {len(RSS_FEEDS)} feeds.",
            f"Active categories: {', '.join(by_category.keys())}.",
        ],
        "intel_cards":    intel_cards,
        "raw_articles":   articles,
    }


def generate_live_packet(hours_back: int = 14, output: Optional[str] = None) -> dict:
    """
    Convenience function for update.py --live integration.
    Returns the packet dict, optionally writes to disk.
    """
    articles = fetch_all_feeds(hours_back=hours_back)
    packet = build_review_packet(articles)

    if output:
        out_path = Path(output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with out_path.open("w", encoding="utf-8") as f:
            json.dump(packet, f, indent=2, ensure_ascii=False)
            f.write("\n")
        print(f"Wrote review packet to {out_path}")

    return packet


# ── LEGACY API (used by update.py) ───────────────────────────────────────────

def load_review_packet(path: str | Path) -> Dict[str, Any]:
    """Load a review packet from disk."""
    with Path(path).open("r", encoding="utf-8") as f:
        return json.load(f)


def validate_card_sources(cards: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Ensure every card has required source fields."""
    cleaned = []
    for card in cards:
        for key in REQUIRED_SOURCE_KEYS:
            card.setdefault(key, "")
        cleaned.append(card)
    return cleaned


# ── CLI ───────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch live RSS feeds and build a review packet.")
    parser.add_argument("--output", "-o", default=str(DATA_DIR / "review_packet.live.json"),
                        help="Output path for the review packet.")
    parser.add_argument("--hours", "-H", type=int, default=14,
                        help="Hours of history to pull (default: 14).")
    args = parser.parse_args()

    articles = fetch_all_feeds(hours_back=args.hours)
    if not articles:
        print("No relevant articles found. Packet will be minimal.")

    packet = build_review_packet(articles)
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as f:
        json.dump(packet, f, indent=2, ensure_ascii=False)
        f.write("\n")

    print(f"\nWrote review packet to {out}")
    print(f"  Articles: {len(articles)}")
    print(f"  Intel cards: {len(packet['intel_cards'])}")


if __name__ == "__main__":
    main()

