#!/usr/bin/env python3
"""
Build a single, concise hundeskove.json from one-file-per-forest in data/forests/.
Run from project root: python3 scripts/build_hundeskove.py
Output: data/hundeskove.json (compact JSON for fast loading, one request).
"""

import json
from pathlib import Path
from typing import Optional

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


def build_hundeskove(
    forests_dir: Optional[Path] = None,
    output_file: Optional[Path] = None,
) -> int:
    """Build a single FeatureCollection from one-file-per-forest JSON under forests_dir.
    Returns the number of features written. Use defaults (data/forests, data/hundeskove.json) when None."""
    dir_path = forests_dir if forests_dir is not None else FORESTS_DIR
    out_path = output_file if output_file is not None else OUTPUT_FILE
    features = []
    for path in sorted(dir_path.glob("*.json"), key=natural_sort_key):
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        if data.get("type") == "Feature":
            features.append(data)
        elif "features" in data:
            features.extend(data["features"])
        else:
            features.append(data)

    out = {"type": "FeatureCollection", "features": features}
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, separators=(",", ":"))
    return len(features)


def main() -> None:
    n = build_hundeskove()
    print(f"Wrote {n} forests to {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
