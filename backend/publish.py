from __future__ import annotations

import json
import shutil
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = BASE_DIR / "data"
LATEST_PATH = DATA_DIR / "latest.json"
PROPOSED_PATH = DATA_DIR / "proposed.json"
ARCHIVE_DIR = DATA_DIR / "archive"
ARCHIVE_INDEX_PATH = ARCHIVE_DIR / "index.json"


def load_json(path: Path):
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def write_json(path: Path, payload):
    with path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)
        f.write("\n")


def archive_latest(latest_payload) -> str:
    ts = latest_payload["meta"]["last_updated"]
    safe_name = ts.replace(":", "-") + ".json"
    archive_path = ARCHIVE_DIR / safe_name
    write_json(archive_path, latest_payload)
    return safe_name


def update_archive_index(latest_payload, file_name: str) -> None:
    index = load_json(ARCHIVE_INDEX_PATH) if ARCHIVE_INDEX_PATH.exists() else {"snapshots": []}
    record = {
        "file": file_name,
        "last_updated": latest_payload["meta"]["last_updated"],
        "score": latest_payload["meta"]["score"],
        "delta": latest_payload["meta"]["delta"],
        "status": latest_payload["meta"]["status"],
        "summary": latest_payload.get("summary", {}).get("description", ""),
        "top_drivers": [v.get("driver", "") for v in latest_payload.get("vectors", [])[:3]],
    }
    index["snapshots"] = [record] + [item for item in index.get("snapshots", []) if item.get("file") != file_name]
    write_json(ARCHIVE_INDEX_PATH, index)


def main() -> None:
    if not PROPOSED_PATH.exists():
      raise SystemExit("proposed.json does not exist. Run update.py first.")

    latest = load_json(LATEST_PATH)
    proposed = load_json(PROPOSED_PATH)

    archive_file = archive_latest(latest)
    update_archive_index(latest, archive_file)

    shutil.copyfile(PROPOSED_PATH, LATEST_PATH)
    print(f"Promoted {PROPOSED_PATH.name} to {LATEST_PATH.name}")


if __name__ == "__main__":
    main()
