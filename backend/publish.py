from __future__ import annotations

"""
Sentinel publish.py — Auto-publish with theological threshold gate.

Behaviour:
- Auto-publishes all updates immediately EXCEPT when the
  Theological Convergence or Third Temple / Al-Aqsa vector
  score shifts by more than THEOLOGICAL_THRESHOLD points.
- When threshold is exceeded: publishes everything else but
  FREEZES theological vectors at their previous scores.
  Quik can release them later with --force.
- Override: pass --force to publish ALL vectors including theology.
- Pass --status to check current hold state without publishing.
- On publish, proposal markers ("AWAITING REVIEW", "-proposed")
  are stripped so the live site never shows draft language.

Exit codes:
  0 — published successfully (auto, partial, or forced)
  1 — error (missing files, bad JSON, etc.)
"""

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from score_engine import compute_weighted_score, derive_status

BASE_DIR           = Path(__file__).resolve().parents[1]
DATA_DIR           = BASE_DIR / "data"
LATEST_PATH        = DATA_DIR / "latest.json"
PROPOSED_PATH      = DATA_DIR / "proposed.json"
ARCHIVE_DIR        = DATA_DIR / "archive"
ARCHIVE_INDEX_PATH = ARCHIVE_DIR / "index.json"
HOLD_PATH          = DATA_DIR / "theological_hold.json"

# ── CONFIGURATION ─────────────────────────────────────────────────────────────
THEOLOGICAL_VECTORS   = {"Theological Convergence", "Third Temple / Al-Aqsa"}
THEOLOGICAL_THRESHOLD = 3
EASTERN               = ZoneInfo("America/New_York")


# ── HELPERS ───────────────────────────────────────────────────────────────────
def load_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)
        f.write("\n")


def get_vector_scores(snapshot: dict) -> dict[str, int]:
    return {
        v["name"]: int(v.get("score", 0))
        for v in snapshot.get("vectors", [])
    }


def check_theological_gate(latest: dict, proposed: dict) -> list[dict]:
    """
    Compare theological vector scores between latest and proposed.
    Returns list of flagged vectors that exceed the threshold.
    Empty list = safe to auto-publish everything.
    """
    latest_scores   = get_vector_scores(latest)
    proposed_scores = get_vector_scores(proposed)
    flags = []
    for vec in THEOLOGICAL_VECTORS:
        old   = latest_scores.get(vec, 0)
        new   = proposed_scores.get(vec, 0)
        delta = abs(new - old)
        if delta > THEOLOGICAL_THRESHOLD:
            flags.append({
                "vector":    vec,
                "old_score": old,
                "new_score": new,
                "delta":     delta,
                "threshold": THEOLOGICAL_THRESHOLD,
            })
    return flags


def clean_proposal_markers(data: dict) -> dict:
    """Strip proposal-specific language so the published snapshot looks clean."""
    meta = data.get("meta", {})

    # Clean version tag
    meta["version"] = meta.get("version", "v4.0").replace("-proposed", "")
    meta.pop("fallback_notice", None)

    # Clean summary subheadline
    summary = data.get("summary", {})
    if "AWAITING" in summary.get("subheadline", "").upper():
        summary["subheadline"] = meta.get("status", "")

    # Clean alert tape
    tape = data.get("alert_tape", "")
    if "AWAITING" in tape.upper() or "PROPOSED" in tape.upper():
        score = meta.get("score", 0)
        status = meta.get("status", "ELEVATED")
        delta = meta.get("delta", 0)
        sign = "+" if delta > 0 else ""
        data["alert_tape"] = f"SCORE {score} / {status} — {sign}{delta} SINCE LAST UPDATE — LIVE"

    # Clean alerts array
    data["alerts"] = [
        a for a in data.get("alerts", [])
        if "AWAITING" not in a.upper() and "PROPOSED" not in a.upper()
    ]
    if not data["alerts"]:
        score = meta.get("score", 0)
        status = meta.get("status", "ELEVATED")
        data["alerts"] = [f"Score: {score}", f"Status: {status}", "Published snapshot — live"]

    # Clean changelog
    data["changelog"] = [
        c for c in data.get("changelog", [])
        if "awaiting" not in c.lower()
    ]

    return data


def archive_latest(latest_payload: dict) -> str:
    ts           = latest_payload["meta"]["last_updated"]
    safe_name    = ts.replace(":", "-") + ".json"
    archive_path = ARCHIVE_DIR / safe_name
    write_json(archive_path, latest_payload)
    return safe_name


def update_archive_index(latest_payload: dict, file_name: str) -> None:
    index = load_json(ARCHIVE_INDEX_PATH) if ARCHIVE_INDEX_PATH.exists() else {"snapshots": []}
    record = {
        "file":         file_name,
        "last_updated": latest_payload["meta"]["last_updated"],
        "score":        latest_payload["meta"]["score"],
        "delta":        latest_payload["meta"]["delta"],
        "status":       latest_payload["meta"]["status"],
        "summary":      latest_payload.get("summary", {}).get("description", ""),
        "top_drivers":  [v.get("driver", "") for v in latest_payload.get("vectors", [])[:3]],
    }
    index["snapshots"] = [record] + [
        item for item in index.get("snapshots", [])
        if item.get("file") != file_name
    ]
    write_json(ARCHIVE_INDEX_PATH, index)


def write_hold_file(flags: list[dict], proposed: dict) -> None:
    hold = {
        "held_at":         datetime.now(EASTERN).isoformat(),
        "reason":          "Theological vector threshold exceeded — vectors frozen, rest published. Quik review required to release.",
        "flags":           flags,
        "proposed_score":  proposed["meta"]["score"],
        "proposed_status": proposed["meta"]["status"],
        "instructions":    (
            "Run: python backend/publish.py --force   to release theological vectors. "
            "Or adjust theological scores in data/proposed.json then re-run."
        ),
    }
    write_json(HOLD_PATH, hold)


def clear_hold_file() -> None:
    if HOLD_PATH.exists():
        HOLD_PATH.unlink()


def promote(latest: dict, proposed: dict, freeze_theology: bool = False) -> None:
    """Archive current latest, clean proposal markers, write new latest."""
    archive_file = archive_latest(latest)
    update_archive_index(latest, archive_file)

    if freeze_theology:
        # Keep theological vectors at their old scores
        old_scores = get_vector_scores(latest)
        for v in proposed.get("vectors", []):
            if v["name"] in THEOLOGICAL_VECTORS:
                v["score"] = old_scores.get(v["name"], v["score"])
                v["note"] = v.get("note", "") + " [HELD — awaiting Quik review]"
        # Recalculate master score with frozen theology
        proposed["meta"]["score"] = compute_weighted_score(proposed["vectors"])
        proposed["meta"]["status"] = derive_status(proposed["meta"]["score"])
        proposed["meta"]["delta"] = proposed["meta"]["score"] - latest["meta"]["score"]

    published = clean_proposal_markers(proposed)
    write_json(LATEST_PATH, published)

    # Only clear hold file if theology was NOT frozen
    if not freeze_theology:
        clear_hold_file()

    # def notify_quik():
    #     """Wire Telegram bot notification here later."""
    #     pass


# ── MAIN ──────────────────────────────────────────────────────────────────────
def main() -> None:
    parser = argparse.ArgumentParser(
        description="Publish proposed.json to latest.json with theological gate."
    )
    parser.add_argument(
        "--force", action="store_true",
        help="Bypass theological threshold and publish ALL vectors including theology."
    )
    parser.add_argument(
        "--status", action="store_true",
        help="Show current hold state and exit. Does not publish."
    )
    args = parser.parse_args()

    # ── STATUS CHECK ─────────────────────────────────────────────────────────
    if args.status:
        if HOLD_PATH.exists():
            hold = load_json(HOLD_PATH)
            print("\n⚠️  THEOLOGICAL HOLD ACTIVE (vectors frozen, rest published)")
            print(f"   Held at : {hold.get('held_at')}")
            print(f"   Reason  : {hold.get('reason')}")
            for f in hold.get("flags", []):
                print(f"   Vector  : {f['vector']}  {f['old_score']} → {f['new_score']}  (Δ{f['delta']}  threshold={f['threshold']})")
            print(f"   Proposed: score={hold.get('proposed_score')}  status={hold.get('proposed_status')}")
            print(f"\n   {hold.get('instructions')}\n")
            sys.exit(0)
        else:
            if PROPOSED_PATH.exists():
                proposed = load_json(PROPOSED_PATH)
                print(f"\n✅  No hold active. Proposed score: {proposed['meta']['score']}  Ready to publish.\n")
            else:
                print("\n✅  No hold active. No proposed.json — run update.py first.\n")
            sys.exit(0)

    # ── VALIDATE ─────────────────────────────────────────────────────────────
    if not PROPOSED_PATH.exists():
        print("ERROR: proposed.json not found. Run update.py first.")
        sys.exit(1)

    latest   = load_json(LATEST_PATH)
    proposed = load_json(PROPOSED_PATH)

    # ── FORCE OVERRIDE ───────────────────────────────────────────────────────
    if args.force:
        promote(latest, proposed, freeze_theology=False)
        clear_hold_file()
        print(f"✅  FORCED publish — ALL vectors released.")
        print(f"   Score: {proposed['meta']['score']}  Status: {proposed['meta']['status']}")
        sys.exit(0)

    # ── THEOLOGICAL GATE ─────────────────────────────────────────────────────
    flags = check_theological_gate(latest, proposed)

    if flags:
        write_hold_file(flags, proposed)
        # Publish everything EXCEPT theological vectors
        promote(latest, proposed, freeze_theology=True)
        score  = proposed["meta"]["score"]
        status = proposed["meta"]["status"]
        print(f"\n⚠️  PARTIAL PUBLISH — Theological vectors frozen, rest updated.")
        print(f"   Score: {score}  Status: {status}")
        for f in flags:
            print(f"   {f['vector']}: held at {f['old_score']} (proposed was {f['new_score']}, Δ{f['delta']})")
        print(f"   Quik: review and run 'python backend/publish.py --force' to release theology.")
        sys.exit(0)

    # ── AUTO-PUBLISH ─────────────────────────────────────────────────────────
    promote(latest, proposed, freeze_theology=False)
    score  = proposed["meta"]["score"]
    status = proposed["meta"]["status"]
    delta  = proposed["meta"].get("delta", 0)
    sign   = "+" if delta >= 0 else ""
    print(f"✅  AUTO-PUBLISHED — Score: {score}  ({sign}{delta})  Status: {status}")
    print(f"   Theological vectors within threshold ({THEOLOGICAL_THRESHOLD}pts) — no review needed.")


if __name__ == "__main__":
    main()
