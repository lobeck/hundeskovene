#!/usr/bin/env python3
# /// script
# dependencies = [
#   "osmium>=3.0",
# ]
# ///
"""
Refresh forest data from a local OSM PBF file (Denmark extract).
By default uses the latest .osm.pbf (or .pbf) file in data/ by modification time.
Merges optional data/forest_overrides.json and data/forest_updates.csv,
writes data/forests/*.json, then builds data/hundeskove.json (via build_hundeskove).

Run from project root: uv run scripts/refresh_forest_data_local.py [--pbf PATH]

Performance: uses pyosmium FileProcessor (iterator) instead of SimpleHandler; pass 2
reads only nodes+ways (entities=NODE|WAY), skipping relations. Use --no-reverse-geocode
to skip Nominatim lookups for faster runs.
"""

import argparse
import json
import sys
import time
from pathlib import Path

# Progress reporting: pass 1 uses TagFilter so we only see dog_parks (report every N)
_PROGRESS_PASS1_INTERVAL = 50
# Pass 2 scans full file (nodes+ways only)
_PROGRESS_NODE_INTERVAL = 500_000
_PROGRESS_WAY_INTERVAL = 100_000

PROJECT_ROOT = Path(__file__).resolve().parent.parent
_SCRIPTS_DIR = Path(__file__).resolve().parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

# Reuse all conversion, merge, geocode and write logic from the Overpass-based script
from refresh_forest_data import (
    FORESTS_DIR,
    OVERRIDES_FILE,
    CSV_FILE,
    osm_element_sort_key,
    element_to_feature,
    load_overrides,
    load_csv_updates,
    merge_overrides,
    enrich_addresses_with_reverse_geocode,
    build_hundeskove,
)

DATA_DIR = PROJECT_ROOT / "data"


def _latest_pbf_in_data() -> Path | None:
    """Return the path to the most recently modified .osm.pbf or .pbf file in data/, or None."""
    candidates = list(DATA_DIR.glob("*.osm.pbf")) + list(DATA_DIR.glob("*.pbf"))
    if not candidates:
        return None
    return max(candidates, key=lambda p: p.stat().st_mtime)


def _tags_dict(osmium_obj) -> dict:
    """Build a plain dict from osmium tags (only when we need to store the element)."""
    return dict(osmium_obj.tags) if osmium_obj.tags else {}


def _way_geometry_from_nodes(way) -> list | None:
    """Build geometry list [{lat, lon}, ...] from a way's nodes (requires locations=True)."""
    geom = [{"lat": n.location.lat, "lon": n.location.lon} for n in way.nodes if n.location.valid()]
    return geom if len(geom) >= 2 else None


def extract_dog_parks_from_pbf(pbf_path: Path):
    """
    Read PBF with pyosmium FileProcessor and extract dog_park elements in Overpass-like dict format.
    Returns (dog_park_elements, ways_by_id for relation member ways).
    Uses TagFilter(leisure=dog_park) so only matching objects reach Python; pass 2 skips relations.
    """
    try:
        import osmium
    except ImportError:
        print("Error: pyosmium is required. Run: uv run scripts/refresh_forest_data_local.py", file=sys.stderr)
        sys.exit(1)

    # TagFilter: only leisure=dog_park objects reach Python (skipped at C level)
    dog_park_filter = osmium.filter.TagFilter(("leisure", "dog_park"))

    dog_park_nodes = []
    dog_park_ways = []
    dog_park_relations = []
    member_way_ids = set()
    progress = {"nodes": 0, "ways": 0, "relations": 0}

    # Pass 1: FileProcessor with filter + locations — only dog_park elements iterated
    print("Reading PBF (pass 1): extracting dog parks (TagFilter leisure=dog_park)...", flush=True)
    t0 = time.perf_counter()
    fp = (
        osmium.FileProcessor(str(pbf_path))
        .with_filter(dog_park_filter)
        .with_locations()
    )
    for obj in fp:
        if obj.is_node():
            progress["nodes"] += 1
            total = progress["nodes"] + progress["ways"] + progress["relations"]
            if total and total % _PROGRESS_PASS1_INTERVAL == 0:
                print(f"  Pass 1: {progress['nodes']:,} nodes, {progress['ways']:,} ways, {progress['relations']:,} relations...", flush=True)
            dog_park_nodes.append({
                "type": "node",
                "id": obj.id,
                "tags": _tags_dict(obj),
                "lat": obj.location.lat,
                "lon": obj.location.lon,
            })
        elif obj.is_way():
            progress["ways"] += 1
            total = progress["nodes"] + progress["ways"] + progress["relations"]
            if total and total % _PROGRESS_PASS1_INTERVAL == 0:
                print(f"  Pass 1: {progress['nodes']:,} nodes, {progress['ways']:,} ways, {progress['relations']:,} relations...", flush=True)
            geom = _way_geometry_from_nodes(obj)
            if geom:
                dog_park_ways.append({"type": "way", "id": obj.id, "tags": _tags_dict(obj), "geometry": geom})
        elif obj.is_relation():
            progress["relations"] += 1
            total = progress["nodes"] + progress["ways"] + progress["relations"]
            if total and total % _PROGRESS_PASS1_INTERVAL == 0:
                print(f"  Pass 1: {progress['nodes']:,} nodes, {progress['ways']:,} ways, {progress['relations']:,} relations...", flush=True)
            members = [
                {"type": "way" if m.type == "w" else "node" if m.type == "n" else "relation", "ref": m.ref, "role": m.role or ""}
                for m in obj.members
            ]
            for m in obj.members:
                if m.type == "w":
                    member_way_ids.add(m.ref)
            dog_park_relations.append({"type": "relation", "id": obj.id, "tags": _tags_dict(obj), "members": members})

    print(f"  Pass 1 done in {time.perf_counter() - t0:.1f}s ({progress['nodes']:,} nodes, {progress['ways']:,} ways, {progress['relations']:,} relations)", flush=True)

    # Pass 2: only NODE | WAY (skip relations) to load member way geometries — faster
    ways_by_id = {}
    if member_way_ids:
        n_member = len(member_way_ids)
        progress2 = {"nodes": 0, "ways": 0}
        print(f"Reading PBF (pass 2): loading {n_member} relation member ways (nodes + ways only)...", flush=True)
        t1 = time.perf_counter()
        fp2 = osmium.FileProcessor(
            str(pbf_path),
            entities=osmium.osm.NODE | osmium.osm.WAY,
        ).with_locations()
        for obj in fp2:
            if obj.is_node():
                progress2["nodes"] += 1
                if progress2["nodes"] and progress2["nodes"] % _PROGRESS_NODE_INTERVAL == 0:
                    print(f"  Pass 2: {progress2['nodes']:,} nodes, {progress2['ways']:,} ways (have {len(ways_by_id)}/{n_member} member ways)...", flush=True)
            elif obj.is_way():
                progress2["ways"] += 1
                if progress2["ways"] and progress2["ways"] % _PROGRESS_WAY_INTERVAL == 0:
                    print(f"  Pass 2: {progress2['nodes']:,} nodes, {progress2['ways']:,} ways (have {len(ways_by_id)}/{n_member} member ways)...", flush=True)
                if obj.id in member_way_ids:
                    geom = _way_geometry_from_nodes(obj)
                    if geom:
                        ways_by_id[obj.id] = {"type": "way", "id": obj.id, "geometry": geom}
        print(f"  Pass 2 done in {time.perf_counter() - t1:.1f}s", flush=True)

    elements = dog_park_nodes + dog_park_ways + dog_park_relations
    elements.sort(key=osm_element_sort_key)
    return elements, ways_by_id


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Refresh forest data from a local Denmark OSM PBF file.",
    )
    parser.add_argument(
        "--pbf",
        type=Path,
        default=None,
        help="Path to OSM PBF file (default: latest .osm.pbf/.pbf in data/)",
    )
    parser.add_argument(
        "--no-reverse-geocode",
        action="store_true",
        help="Skip reverse geocoding; keep address as 'Danmark' when OSM has no addr tags",
    )
    args = parser.parse_args()
    if args.pbf is not None:
        pbf_path = args.pbf if args.pbf.is_absolute() else (PROJECT_ROOT / args.pbf)
    else:
        pbf_path = _latest_pbf_in_data()
        if pbf_path is None:
            print("Error: No .osm.pbf or .pbf file found in data/. Specify one with --pbf PATH.", file=sys.stderr)
            sys.exit(1)

    if not pbf_path.exists():
        print(f"Error: PBF file not found: {pbf_path}", file=sys.stderr)
        sys.exit(1)

    print(f"Using PBF: {pbf_path}", flush=True)
    t_start = time.perf_counter()
    elements, ways_by_id = extract_dog_parks_from_pbf(pbf_path)
    print(f"  Extract total: {time.perf_counter() - t_start:.1f}s", flush=True)

    n_nodes = sum(1 for el in elements if el.get("type") == "node")
    n_ways = sum(1 for el in elements if el.get("type") == "way")
    n_relations = sum(1 for el in elements if el.get("type") == "relation")
    print(f"  Found {len(elements)} dog parks ({n_nodes} nodes, {n_ways} ways, {n_relations} relations)", flush=True)

    print("Converting to features...", flush=True)
    t_convert = time.perf_counter()
    features = []
    n_el = len(elements)
    step = max(20, n_el // 10) if n_el else 1
    for i, el in enumerate(elements):
        if (i + 1) % step == 0 or i + 1 == n_el:
            print(f"  {i + 1}/{n_el} elements...", flush=True)
        numeric_id = str(i + 1)
        feat = element_to_feature(el, numeric_id, ways_by_id=ways_by_id)
        if feat:
            features.append(feat)
    print(f"  {len(features)} features in {time.perf_counter() - t_convert:.1f}s", flush=True)

    print("Merging overrides and CSV updates...", flush=True)
    overrides = load_overrides()
    csv_updates = load_csv_updates()
    features = merge_overrides(features, overrides, csv_updates)

    if not args.no_reverse_geocode:
        enrich_addresses_with_reverse_geocode(features)

    FORESTS_DIR.mkdir(parents=True, exist_ok=True)
    for p in FORESTS_DIR.glob("*.json"):
        p.unlink()

    print(f"Writing {len(features)} forest files...", flush=True)
    t_write = time.perf_counter()
    for idx, feat in enumerate(features):
        props = feat["properties"]
        osm_id = props.get("_osm_id", "")
        filename = osm_id.replace("/", "_") + ".json" if osm_id else props.get("id", "") + ".json"
        path = FORESTS_DIR / filename
        props.pop("_osm_id", None)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(feat, f, ensure_ascii=False, separators=(",", ":"))
        if (idx + 1) % 100 == 0 or idx + 1 == len(features):
            print(f"  {idx + 1}/{len(features)}", flush=True)
    print(f"  Wrote {len(features)} forests in {time.perf_counter() - t_write:.1f}s", flush=True)

    print("Building hundeskove.json...", flush=True)
    n = build_hundeskove()
    print(f"  Wrote {n} forests to {PROJECT_ROOT / 'data' / 'hundeskove.json'}", flush=True)
    print(f"Done. Total: {time.perf_counter() - t_start:.1f}s", flush=True)


if __name__ == "__main__":
    main()
