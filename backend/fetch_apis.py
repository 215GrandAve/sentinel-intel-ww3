#!/usr/bin/env python3
"""
SENTINEL // LAYER 2 — STRUCTURED API SOURCES (v3 — GDELT + ReliefWeb fixes)
=============================================================================
v3 changelog:
  - GDELT: reverted to simple single-keyword queries (OR syntax returned empty
    HTML, not JSON). Added 5s delay between queries. 3 queries max.
    Added non-JSON response detection before parsing.
  - ReliefWeb: fixed POST body to use "filter" structure instead of "query"
    (v2 query format returned 400). Added GET fallback with proper headers.
  - All other collectors unchanged from v2.

Drop this as backend/fetch_apis.py — replaces v2 entirely.
"""

import json
import urllib.request
import urllib.parse
import urllib.error
import ssl
import os
import sys
import time
from datetime import datetime, timedelta, timezone

# ---------------------------------------------------------------------------
# CONFIG
# ---------------------------------------------------------------------------
DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data")
OUTPUT_FILE = os.path.join(DATA_DIR, "api_intel.json")
REQUEST_TIMEOUT = 20

SSL_CTX = ssl.create_default_context()

BROWSER_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
}

API_HEADERS = {
    "User-Agent": "SentinelIntel/2.0 (sentinel-intel.live; geopolitical monitoring dashboard)",
    "Accept": "application/json",
}


def _fetch_json(url, timeout=REQUEST_TIMEOUT, headers=None, retries=1):
    """Fetch JSON from a URL with optional retry. Detects non-JSON responses."""
    hdrs = headers or API_HEADERS
    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(url, headers=hdrs)
            with urllib.request.urlopen(req, timeout=timeout, context=SSL_CTX) as resp:
                raw = resp.read().decode("utf-8")
                stripped = raw.strip()
                if not stripped or stripped[0] not in ('{', '['):
                    print(f"  [WARN] Non-JSON response from {url[:60]}... (HTML or empty body)")
                    return None
                return json.loads(stripped)
        except Exception as e:
            if attempt < retries:
                wait = 3 * (attempt + 1)
                print(f"  [RETRY] {url[:60]}... — waiting {wait}s ({e})")
                time.sleep(wait)
            else:
                print(f"  [WARN] Failed to fetch {url[:80]}... — {e}")
                return None


def _post_json(url, body, timeout=REQUEST_TIMEOUT, headers=None):
    """POST JSON body and return parsed response. Shows error body on failure."""
    hdrs = headers or {**API_HEADERS, "Content-Type": "application/json"}
    try:
        data = json.dumps(body).encode("utf-8")
        req = urllib.request.Request(url, data=data, headers=hdrs, method="POST")
        with urllib.request.urlopen(req, timeout=timeout, context=SSL_CTX) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        err_body = ""
        try:
            err_body = e.read().decode("utf-8")[:200]
        except:
            pass
        print(f"  [WARN] POST {url[:60]}... — HTTP {e.code}: {err_body[:120]}")
        return None
    except Exception as e:
        print(f"  [WARN] POST {url[:80]}... — {e}")
        return None


def _now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ===========================================================================
# 1. GDELT PROJECT — v3: simple queries, 5s delays, non-JSON detection
# ===========================================================================
def fetch_gdelt():
    """
    Pull latest escalation-relevant articles from GDELT.
    Uses simple single-topic queries with 5s delays to avoid 429.
    """
    print("[API] GDELT Project...")
    results = []

    # Simple keyword queries — no OR/AND operators
    queries = [
        "Iran+Israel+strike",
        "Hormuz+tanker+military",
        "nuclear+IAEA+enrichment",
    ]

    seen_urls = set()
    for i, q in enumerate(queries):
        if i > 0:
            time.sleep(5)

        url = (
            f"https://api.gdeltproject.org/api/v2/doc/doc?"
            f"query={q}&mode=ArtList&maxrecords=20&format=json"
            f"&timespan=12h&sort=DateDesc"
        )
        data = _fetch_json(url, timeout=25, retries=1)
        if not data or "articles" not in data:
            continue

        for art in data["articles"]:
            article_url = art.get("url", "")
            if article_url in seen_urls:
                continue
            seen_urls.add(article_url)

            results.append({
                "source": "GDELT",
                "source_type": "event_monitor",
                "title": art.get("title", ""),
                "url": article_url,
                "domain": art.get("domain", ""),
                "language": art.get("language", "English"),
                "seendate": art.get("seendate", ""),
                "retrieved_at": _now_iso(),
                "vector_targets": ["military_escalation", "geopolitical_stability"],
                "class": "DATA",
            })

    print(f"  → {len(results)} GDELT articles collected")
    return results


# ===========================================================================
# 2. GDELT GKG — v3: longer delays, skip volume if rate-limited
# ===========================================================================
def fetch_gdelt_gkg():
    """Tone/theme analysis from GDELT GKG for information warfare signal."""
    print("[API] GDELT GKG (tone analysis)...")
    results = []

    actors = [
        ("Iran", "Iran"),
        ("Israel", "Israel"),
        ("Hezbollah", "Hezbollah"),
    ]

    for i, (query, label) in enumerate(actors):
        if i > 0:
            time.sleep(4)

        url = (
            f"https://api.gdeltproject.org/api/v2/doc/doc?"
            f"query={query}&mode=ToneChart&format=json&timespan=24h"
        )
        data = _fetch_json(url, timeout=25, retries=1)
        if data:
            results.append({
                "source": "GDELT_GKG",
                "source_type": "tone_analysis",
                "actor": label,
                "data": data,
                "retrieved_at": _now_iso(),
                "vector_targets": ["information_warfare"],
                "class": "DATA",
            })

    if len(results) >= 2:
        time.sleep(4)
        theme_url = (
            "https://api.gdeltproject.org/api/v2/doc/doc?"
            "query=war+conflict+military&mode=TimelineVolInfo&format=json&timespan=7d"
        )
        theme_data = _fetch_json(theme_url, timeout=25, retries=0)
        if theme_data:
            results.append({
                "source": "GDELT_GKG",
                "source_type": "volume_timeline",
                "metric": "global_conflict_media_volume",
                "data": theme_data,
                "retrieved_at": _now_iso(),
                "vector_targets": ["information_warfare"],
                "class": "DATA",
            })

    print(f"  → {len(results)} GKG signals collected")
    return results


# ===========================================================================
# 3. YAHOO FINANCE
# ===========================================================================
def fetch_yahoo_finance():
    print("[API] Yahoo Finance...")
    results = []

    symbols = {
        "CL=F": {"label": "WTI Crude Oil", "signal": "energy_price"},
        "GC=F": {"label": "Gold Futures", "signal": "safe_haven"},
        "SI=F": {"label": "Silver Futures", "signal": "safe_haven"},
        "DX-Y.NYB": {"label": "US Dollar Index", "signal": "dollar_strength"},
        "ITA": {"label": "iShares US Aerospace & Defense ETF", "signal": "defense_sector"},
        "^VIX": {"label": "CBOE Volatility Index", "signal": "fear_gauge"},
    }

    for symbol, meta in symbols.items():
        url = (
            f"https://query1.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(symbol)}"
            f"?interval=1d&range=5d"
        )
        data = _fetch_json(url)
        if not data:
            continue
        try:
            result = data["chart"]["result"][0]
            quote = result["indicators"]["quote"][0]
            closes = [c for c in quote.get("close", []) if c is not None]
            if len(closes) >= 2:
                current = closes[-1]
                previous = closes[-2]
                change_pct = ((current - previous) / previous) * 100
                direction = "up" if change_pct > 0 else "down" if change_pct < 0 else "flat"
                results.append({
                    "source": "Yahoo Finance",
                    "source_type": "market_data",
                    "symbol": symbol,
                    "label": meta["label"],
                    "signal_type": meta["signal"],
                    "price": round(current, 2),
                    "previous_close": round(previous, 2),
                    "change_pct": round(change_pct, 2),
                    "direction": direction,
                    "retrieved_at": _now_iso(),
                    "vector_targets": ["financial_economic"],
                    "class": "DATA",
                })
        except (KeyError, IndexError, TypeError) as e:
            print(f"  [WARN] Yahoo parse error for {symbol}: {e}")

    print(f"  → {len(results)} market datapoints collected")
    return results


# ===========================================================================
# 4. COINBASE
# ===========================================================================
def fetch_coinbase():
    print("[API] Coinbase...")
    results = []
    for pair, label in [("BTC-USD", "Bitcoin"), ("ETH-USD", "Ethereum")]:
        spot = _fetch_json(f"https://api.coinbase.com/v2/prices/{pair}/spot")
        if spot and "data" in spot:
            results.append({
                "source": "Coinbase",
                "source_type": "crypto_price",
                "symbol": pair,
                "label": label,
                "price": float(spot["data"]["amount"]),
                "currency": spot["data"]["currency"],
                "retrieved_at": _now_iso(),
                "vector_targets": ["financial_economic"],
                "class": "DATA",
            })
    print(f"  → {len(results)} crypto prices collected")
    return results


# ===========================================================================
# 5. CME FEDWATCH — browser headers + Treasury yield fallback
# ===========================================================================
def fetch_cme_fedwatch():
    print("[API] CME FedWatch...")
    url = "https://www.cmegroup.com/CmeWS/mvc/MeetingRate/gld/1"
    cme_headers = {
        **BROWSER_HEADERS,
        "Referer": "https://www.cmegroup.com/markets/interest-rates/cme-fedwatch-tool.html",
        "Origin": "https://www.cmegroup.com",
    }
    data = _fetch_json(url, headers=cme_headers, retries=1)
    if data:
        print(f"  → FedWatch data collected")
        return [{
            "source": "CME FedWatch",
            "source_type": "rate_probability",
            "data": data,
            "retrieved_at": _now_iso(),
            "vector_targets": ["financial_economic"],
            "class": "DATA",
        }]

    print("  [INFO] CME blocked — falling back to Treasury yield proxy")
    fallback = {
        "^TNX": {"label": "10-Year Treasury Yield", "signal": "treasury_10y"},
        "^FVX": {"label": "5-Year Treasury Yield", "signal": "treasury_5y"},
        "^IRX": {"label": "13-Week Treasury Bill", "signal": "treasury_13w"},
    }
    results = []
    for symbol, meta in fallback.items():
        yurl = (
            f"https://query1.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(symbol)}"
            f"?interval=1d&range=5d"
        )
        ydata = _fetch_json(yurl)
        if not ydata:
            continue
        try:
            r = ydata["chart"]["result"][0]
            closes = [c for c in r["indicators"]["quote"][0].get("close", []) if c is not None]
            if closes:
                results.append({
                    "source": "Yahoo Finance (FedWatch proxy)",
                    "source_type": "treasury_yield",
                    "symbol": symbol,
                    "label": meta["label"],
                    "signal_type": meta["signal"],
                    "yield_pct": round(closes[-1], 3),
                    "retrieved_at": _now_iso(),
                    "vector_targets": ["financial_economic"],
                    "class": "DATA",
                    "analyst_note": "Treasury yield proxy. Inverted curve signals recession/stress.",
                })
        except (KeyError, IndexError, TypeError):
            pass
    print(f"  → {len(results)} Treasury yield proxies collected (FedWatch fallback)")
    return results


# ===========================================================================
# 6. USGS EARTHQUAKE
# ===========================================================================
def fetch_usgs_earthquake():
    print("[API] USGS Earthquake...")
    url = (
        "https://earthquake.usgs.gov/fdsnws/event/1/query?"
        "format=geojson&starttime={start}&endtime={end}"
        "&minmagnitude=2.5"
        "&minlatitude=20&maxlatitude=45"
        "&minlongitude=25&maxlongitude=75"
    ).format(
        start=(datetime.now(timezone.utc) - timedelta(hours=24)).strftime("%Y-%m-%dT%H:%M:%S"),
        end=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S"),
    )
    data = _fetch_json(url, retries=1)
    if not data or "features" not in data:
        print("  → No USGS data returned")
        return []

    results = []
    for feat in data["features"][:20]:
        props = feat.get("properties", {})
        coords = feat.get("geometry", {}).get("coordinates", [None, None, None])
        results.append({
            "source": "USGS",
            "source_type": "seismic_event",
            "title": props.get("title", ""),
            "magnitude": props.get("mag"),
            "place": props.get("place", ""),
            "time": props.get("time"),
            "longitude": coords[0],
            "latitude": coords[1],
            "depth_km": coords[2],
            "url": props.get("url", ""),
            "retrieved_at": _now_iso(),
            "vector_targets": ["military_escalation"],
            "class": "DATA",
            "analyst_note": "Cross-reference with known strike windows. Shallow events (<5km) near military sites may indicate subsurface detonation.",
        })
    print(f"  → {len(results)} seismic events in conflict zone band")
    return results


# ===========================================================================
# 7. RELIEFWEB — v3: filter-based POST + GET fallback
# ===========================================================================
def fetch_reliefweb():
    """
    v3 fix: POST body uses 'filter' instead of 'query' (which caused 400).
    Falls back to GET with filter params if POST also fails.
    """
    print("[API] ReliefWeb (UN OCHA)...")
    countries = ["Iran", "Israel", "Lebanon", "Syria", "Iraq", "Yemen"]
    results = []

    for country in countries:
        report = None

        # Attempt 1: POST with filter structure
        body = {
            "appname": "sentinel-intel",
            "filter": {
                "field": "country.name",
                "value": [country]
            },
            "limit": 5,
            "sort": ["date.created:desc"],
            "fields": {
                "include": ["title", "url_alias", "date.created", "source.name", "country.name"]
            }
        }
        report = _post_json(
            "https://api.reliefweb.int/v1/reports",
            body,
            headers={
                "User-Agent": "SentinelIntel/2.0 (sentinel-intel.live)",
                "Content-Type": "application/json",
                "Accept": "application/json",
            }
        )

        # Attempt 2: GET with filter params
        if not report or "data" not in report:
            get_url = (
                f"https://api.reliefweb.int/v1/reports?"
                f"appname=sentinel-intel"
                f"&filter[field]=country.name"
                f"&filter[value][]={urllib.parse.quote(country)}"
                f"&limit=5"
                f"&sort[]=date.created:desc"
                f"&fields[include][]=title"
                f"&fields[include][]=url_alias"
                f"&fields[include][]=date.created"
                f"&fields[include][]=source.name"
            )
            report = _fetch_json(get_url, headers={
                "User-Agent": "SentinelIntel/2.0 (sentinel-intel.live; humanitarian monitoring)",
                "Accept": "application/json",
            })

        if not report or "data" not in report:
            continue

        for item in report["data"]:
            fields = item.get("fields", {})
            sources = fields.get("source", [])
            if isinstance(sources, list):
                source_names = [s.get("name", "") if isinstance(s, dict) else str(s) for s in sources]
            else:
                source_names = ["UN OCHA"]

            url_alias = fields.get("url_alias", "")
            report_url = f"https://reliefweb.int{url_alias}" if url_alias else ""

            results.append({
                "source": "ReliefWeb",
                "source_type": "humanitarian_report",
                "title": fields.get("title", ""),
                "url": report_url,
                "published_at": fields.get("date", {}).get("created", ""),
                "source_label": ", ".join(source_names[:3]),
                "country": country,
                "retrieved_at": _now_iso(),
                "vector_targets": ["geopolitical_stability"],
                "class": "VERIFIED",
            })

        time.sleep(0.5)

    print(f"  → {len(results)} humanitarian reports collected")
    return results


# ===========================================================================
# 8. NASA EONET
# ===========================================================================
def fetch_nasa_eonet():
    print("[API] NASA EONET...")
    url = "https://eonet.gsfc.nasa.gov/api/v3/events?status=open&limit=50"
    data = _fetch_json(url, retries=1)
    if not data or "events" not in data:
        print("  → No EONET data returned")
        return []

    results = []
    for event in data["events"]:
        categories = [c.get("title", "") for c in event.get("categories", [])]
        for geo in event.get("geometry", []):
            coords = geo.get("coordinates", [None, None])
            if coords[0] is None or coords[1] is None:
                continue
            lon, lat = coords[0], coords[1]
            if 10 <= lat <= 50 and 20 <= lon <= 80:
                results.append({
                    "source": "NASA EONET",
                    "source_type": "earth_event",
                    "title": event.get("title", ""),
                    "categories": categories,
                    "longitude": lon,
                    "latitude": lat,
                    "date": geo.get("date", ""),
                    "url": event.get("link", ""),
                    "retrieved_at": _now_iso(),
                    "vector_targets": ["military_escalation"],
                    "class": "DATA",
                    "analyst_note": "Satellite-detected event in conflict zone.",
                })
                break
    print(f"  → {len(results)} EONET events in conflict zone")
    return results


# ===========================================================================
# MAIN
# ===========================================================================
def run_all():
    print("=" * 60)
    print(f"SENTINEL // LAYER 2 API FETCH v3 — {_now_iso()}")
    print("=" * 60)

    all_intel = {
        "meta": {
            "fetched_at": _now_iso(),
            "version": "3.0",
            "source_count": 0,
            "sources_queried": [],
            "sources_succeeded": [],
            "sources_failed": [],
        },
        "gdelt_articles": [],
        "gdelt_gkg": [],
        "market_data": [],
        "crypto_data": [],
        "fedwatch": [],
        "seismic_events": [],
        "humanitarian_reports": [],
        "earth_events": [],
    }

    collectors = [
        ("GDELT", "gdelt_articles", fetch_gdelt),
        ("GDELT_GKG", "gdelt_gkg", fetch_gdelt_gkg),
        ("Yahoo Finance", "market_data", fetch_yahoo_finance),
        ("Coinbase", "crypto_data", fetch_coinbase),
        ("CME FedWatch", "fedwatch", fetch_cme_fedwatch),
        ("USGS", "seismic_events", fetch_usgs_earthquake),
        ("ReliefWeb", "humanitarian_reports", fetch_reliefweb),
        ("NASA EONET", "earth_events", fetch_nasa_eonet),
    ]

    for name, key, func in collectors:
        try:
            result = func()
            all_intel[key] = result
            count = len(result)
            all_intel["meta"]["source_count"] += count
            if count > 0:
                all_intel["meta"]["sources_succeeded"].append(name)
            else:
                all_intel["meta"]["sources_failed"].append(name)
            all_intel["meta"]["sources_queried"].append(name)
        except Exception as e:
            print(f"  [ERROR] {name} collector failed: {e}")
            all_intel["meta"]["sources_queried"].append(name)
            all_intel["meta"]["sources_failed"].append(f"{name} (EXCEPTION)")

    os.makedirs(DATA_DIR, exist_ok=True)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(all_intel, f, indent=2, ensure_ascii=False)

    ok = len(all_intel["meta"]["sources_succeeded"])
    fail = len(all_intel["meta"]["sources_failed"])
    total = all_intel["meta"]["source_count"]

    print()
    print("=" * 60)
    print(f"OUTPUT: {OUTPUT_FILE}")
    print(f"TOTAL DATAPOINTS: {total}")
    print(f"SOURCES: {ok} succeeded / {fail} returned 0 / {ok + fail} total")
    if all_intel["meta"]["sources_failed"]:
        print(f"ZERO DATA: {', '.join(all_intel['meta']['sources_failed'])}")
    print("=" * 60)

    return all_intel


if __name__ == "__main__":
    run_all()
