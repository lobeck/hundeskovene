#!/usr/bin/env python3
"""
Build a single, concise hundeskove.json from one-file-per-forest in data/forests/.
Run from project root: python3 scripts/build_hundeskove.py
Output: data/hundeskove.json (compact JSON for fast loading, one request).
"""

import json
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
FORESTS_DIR = PROJECT_ROOT / "data" / "forests"
OUTPUT_FILE = PROJECT_ROOT / "data" / "hundeskove.json"


def natural_sort_key(p: Path) -> tuple:
    """Sort by numeric id if filename is a number, else by name."""
    stem = p.stem
    try:
        return (0, int(stem))
    except ValueError:
        return (1, stem)


def main() -> None:
    features = []
    for path in sorted(FORESTS_DIR.glob("*.json"), key=natural_sort_key):
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        if data.get("type") == "Feature":
            features.append(data)
        elif "features" in data:
            features.extend(data["features"])
        else:
            features.append(data)

    out = {"type": "FeatureCollection", "features": features}
    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, separators=(",", ":"))

    print(f"Wrote {len(features)} forests to {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
