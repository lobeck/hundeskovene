#!/usr/bin/env python3
"""
Refresh forest data from OpenStreetMap (Overpass API) for Denmark.
Merges optional data/forest_overrides.json and data/forest_updates.csv,
writes data/forests/*.json, then builds data/hundeskove.json (via build_hundeskove).

Run from project root: python3 scripts/refresh_forest_data.py
"""

import argparse
import csv
import json
import math
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent
_SCRIPTS_DIR = Path(__file__).resolve().parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))
from build_hundeskove import build_hundeskove

FORESTS_DIR = PROJECT_ROOT / "data" / "forests"
OVERRIDES_FILE = PROJECT_ROOT / "data" / "forest_overrides.json"
CSV_FILE = PROJECT_ROOT / "data" / "forest_updates.csv"
GEOCODE_CACHE_FILE = PROJECT_ROOT / "data" / "geocode_cache.json"

# Denmark: query by country boundary (area) instead of bbox
# ISO 3166-1 alpha-2 country code for Denmark
DENMARK_ISO = "DK"

# Overpass API endpoint
OVERPASS_URL = "https://overpass-api.de/api/interpreter"

# Nominatim (OSM) reverse geocoding - requires 1 request/sec, set User-Agent
NOMINATIM_URL = "https://nominatim.openstreetmap.org/reverse"
NOMINATIM_USER_AGENT = "hundeskov-map/1.0 (refresh forest data)"

# Retries on 429 Too Many Requests and 5xx server errors
MAX_RETRIES = 3
RETRY_BASE_SECONDS = 60

# App feature_keys that have locale translations (from locales/da.json)
VALID_FEATURE_KEYS = frozenset(
    {"fenced", "parking", "toilet", "water", "benches", "small_dogs", "accessible"}
)

# OSM tag key -> { value: app feature_key }
OSM_TAG_TO_FEATURE = {
    "barrier": {"fence": "fenced"},
    "amenity": {"watering_place": "water", "toilets": "toilet", "parking": "parking"},
    "bench": {"yes": "benches"},
    "leisure": {"bench": "benches"},
    "parking": {"yes": "parking", "surface": "parking"},
    "access": {"wheelchair": "accessible"},
    "wheelchair": {"yes": "accessible", "limited": "accessible"},
}


def overpass_query() -> str:
    """Query for dog parks inside Denmark (country boundary, not bbox)."""
    return f"""[out:json][timeout:120];
area["ISO3166-1"="{DENMARK_ISO}"]->.dk;
(
  node(area.dk)["leisure"="dog_park"];
  way(area.dk)["leisure"="dog_park"];
  relation(area.dk)["leisure"="dog_park"];
);
out body geom;
"""


def overpass_relation_members_query(relation_id: int) -> str:
    """Fetch a single relation and its member ways with geometry (for building relation geometry)."""
    return f"""[out:json][timeout:25];
relation({relation_id});
out ids;
relation({relation_id});
>>;
out body geom;
"""


def _is_too_many_requests(err: BaseException) -> bool:
    """True if the error indicates HTTP 429 Too Many Requests."""
    if isinstance(err, urllib.error.HTTPError):
        return err.code == 429
    if isinstance(err, urllib.error.URLError) and getattr(err, "reason", None):
        msg = str(err.reason).lower()
        return "429" in msg or "too many requests" in msg
    return False


def _is_server_error(err: BaseException) -> bool:
    """True if the error indicates an HTTP 5xx server error."""
    if isinstance(err, urllib.error.HTTPError):
        return 500 <= err.code < 600
    return False


def _should_retry_request(err: BaseException) -> bool:
    """True if the request should be retried (429, 5xx, or rate-limit URLError)."""
    if isinstance(err, urllib.error.HTTPError):
        return err.code == 429 or (500 <= err.code < 600)
    if isinstance(err, urllib.error.URLError) and getattr(err, "reason", None):
        msg = str(err.reason).lower()
        return "429" in msg or "too many requests" in msg
    return False


def _retry_after_seconds(err: urllib.error.HTTPError, attempt: int) -> int:
    """Return delay in seconds: use Retry-After header if present and valid (429), else exponential backoff."""
    if err.code == 429:
        ra = err.headers.get("Retry-After")
        if ra is not None:
            try:
                return max(1, int(ra))
            except ValueError:
                pass
    return RETRY_BASE_SECONDS * (2**attempt)


def _retry_message(err: BaseException, service: str) -> str:
    """Human-readable reason for retry."""
    if isinstance(err, urllib.error.HTTPError):
        if err.code == 429:
            return f"{service} 429 Too Many Requests"
        if 500 <= err.code < 600:
            return f"{service} {err.code} server error"
    if isinstance(err, urllib.error.URLError):
        return f"{service} rate limit / connection error"
    return f"{service} error"


def fetch_overpass(query: str, timeout: int = 120) -> dict:
    body = urllib.parse.urlencode({"data": query}).encode("utf-8")
    req = urllib.request.Request(
        OVERPASS_URL,
        data=body,
        method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    last_err = None
    for attempt in range(MAX_RETRIES + 1):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            last_err = e
            if _should_retry_request(e) and attempt < MAX_RETRIES:
                delay = _retry_after_seconds(e, attempt)
                print(f"  {_retry_message(e, 'Overpass')}, retrying in {delay}s (attempt {attempt + 1}/{MAX_RETRIES + 1})...", flush=True)
                time.sleep(delay)
            else:
                raise
        except urllib.error.URLError as e:
            last_err = e
            if _should_retry_request(e) and attempt < MAX_RETRIES:
                delay = RETRY_BASE_SECONDS * (2**attempt)
                print(f"  {_retry_message(e, 'Overpass')}, retrying in {delay}s (attempt {attempt + 1}/{MAX_RETRIES + 1})...", flush=True)
                time.sleep(delay)
            else:
                raise
    if last_err:
        raise last_err
    raise RuntimeError("fetch_overpass: unexpected")


def osm_element_sort_key(el: dict) -> tuple:
    t = el.get("type", "")
    tid = el.get("id", 0)
    return (0 if t == "node" else 1 if t == "way" else 2, tid)


def node_to_geometry(el: dict) -> Optional[tuple]:
    lat = el.get("lat")
    lon = el.get("lon")
    if lat is None or lon is None:
        return None
    return ("Point", [lon, lat])


def way_to_geometry(el: dict) -> Optional[tuple]:
    geom = el.get("geometry")
    if not geom or len(geom) < 2:
        return None
    coords = [[p["lon"], p["lat"]] for p in geom]
    if coords[0] != coords[-1]:
        coords.append(coords[0][:])
    return ("Polygon", [coords])


def way_ring_from_geom(geom: list) -> Optional[list]:
    """Build closed GeoJSON ring [lng,lat] from Overpass way geometry."""
    if not geom or len(geom) < 2:
        return None
    coords = [[p["lon"], p["lat"]] for p in geom]
    if coords[0] != coords[-1]:
        coords.append(coords[0][:])
    return coords


def relation_has_usable_geometry(el: dict) -> bool:
    """True if relation has a geometry array we can use (at least 2 points)."""
    geom = el.get("geometry")
    return bool(geom and len(geom) >= 2)


def relation_to_geometry(el: dict, ways_by_id: Optional[dict] = None) -> Optional[tuple]:
    """Build Polygon or MultiPolygon from relation. Uses relation['geometry'] if present,
    otherwise builds from member ways using ways_by_id (required when geometry missing)."""
    ways_by_id = ways_by_id or {}
    geom = el.get("geometry")
    if relation_has_usable_geometry(el):
        coords = [[p["lon"], p["lat"]] for p in geom]
        if coords[0] != coords[-1]:
            coords.append(coords[0][:])
        return ("Polygon", [coords])

    # Build from member ways (Overpass often does not fill relation geometry)
    members = el.get("members") or []
    outers = []
    inners = []
    for m in members:
        if m.get("type") != "way":
            continue
        ref = m.get("ref")
        way_el = ways_by_id.get(ref)
        if not way_el:
            continue
        ring = way_ring_from_geom(way_el.get("geometry"))
        if not ring:
            continue
        role = (m.get("role") or "").lower()
        if role == "outer":
            outers.append(ring)
        elif role == "inner":
            inners.append(ring)

    if not outers:
        return None

    # Single polygon: [outer, inner, ...]; multi: [ [outer, inner, ...], [outer2, ... ], ... ]
    if len(outers) == 1 and not inners:
        return ("Polygon", [outers[0]])
    if len(outers) == 1:
        return ("Polygon", [outers[0]] + inners)
    # Multiple outer rings -> MultiPolygon; assign inners to nearest outer by containment (simplified: append all inners to first outer)
    polygons = []
    for o in outers:
        polygons.append([o])
    if inners:
        polygons[0].extend(inners)
    return ("MultiPolygon", polygons)


def _ring_area_hectares(coords: list) -> Optional[float]:
    """Approximate area of one closed ring in hectares (shoelace in lat/lon)."""
    if len(coords) < 3:
        return None
    n = len(coords)
    if coords[0] != coords[-1]:
        coords = coords + [coords[0]]
        n = len(coords)
    area_deg2 = 0.0
    for i in range(n - 1):
        area_deg2 += coords[i][0] * coords[i + 1][1] - coords[i + 1][0] * coords[i][1]
    area_deg2 = abs(area_deg2) * 0.5
    mean_lat = sum(c[1] for c in coords) / n
    mean_lat_rad = math.radians(mean_lat)
    meters_per_deg_lon = 111320 * math.cos(mean_lat_rad)
    meters_per_deg_lat = 111320
    area_m2 = area_deg2 * meters_per_deg_lat * meters_per_deg_lon
    return area_m2 / 10000.0


def polygon_area_hectares(coords: list) -> Optional[float]:
    """Area of one ring (list of [lng,lat]) or GeoJSON polygon rings [outer, inner, ...] in hectares."""
    if not coords:
        return None
    outer = _ring_area_hectares(coords[0])
    if outer is None:
        return None
    if len(coords) == 1:
        return outer
    for ring in coords[1:]:
        inner = _ring_area_hectares(ring)
        if inner is not None:
            outer -= inner
    return max(0.0, outer)


def geometry_area_hectares(geom_type: str, geom_coords: list) -> Optional[float]:
    """Area in hectares for Polygon or MultiPolygon."""
    if geom_type == "Polygon":
        return polygon_area_hectares(geom_coords)
    if geom_type == "MultiPolygon":
        total = 0.0
        for poly in geom_coords:
            a = polygon_area_hectares(poly)
            if a is not None:
                total += a
        return total if total else None
    return None


def tags_to_feature_keys(tags: dict) -> list[str]:
    out = set()
    for key, val in (tags or {}).items():
        key_lower = key.lower()
        val_lower = str(val).lower().strip() if val else ""
        if key_lower not in OSM_TAG_TO_FEATURE:
            continue
        value_map = OSM_TAG_TO_FEATURE[key_lower]
        if val_lower in value_map:
            fk = value_map[val_lower]
            if fk in VALID_FEATURE_KEYS:
                out.add(fk)
    return sorted(out)


def tags_to_address(tags: dict) -> str:
    for k in ("addr:city", "addr:municipality", "addr:place", "addr:county"):
        if tags.get(k):
            return tags[k]
    return "Danmark"


def element_to_feature(el: dict, numeric_id: str, ways_by_id: Optional[dict] = None) -> dict | None:
    el_type = el.get("type", "")
    osm_id = f'{el_type}/{el.get("id", "")}'
    tags = el.get("tags") or {}

    if el_type == "node":
        geom = node_to_geometry(el)
        size_hectares = None
    elif el_type == "way":
        geom = way_to_geometry(el)
        if geom and geom[0] == "Polygon" and geom[1]:
            size_hectares = polygon_area_hectares(geom[1])  # geom[1] = [exterior_ring] or [outer, inner, ...]
        else:
            size_hectares = None
    elif el_type == "relation":
        geom = relation_to_geometry(el, ways_by_id=ways_by_id)
        size_hectares = geometry_area_hectares(geom[0], geom[1]) if geom else None
    else:
        return None

    if not geom:
        return None

    name = tags.get("name") or "Hundeskov (OSM)"
    address = tags_to_address(tags)
    feature_keys = tags_to_feature_keys(tags)
    description = tags.get("description") or ""

    return {
        "type": "Feature",
        "geometry": {"type": geom[0], "coordinates": geom[1]},
        "properties": {
            "id": numeric_id,
            "name": name,
            "address": address,
            "size_hectares": size_hectares,
            "feature_keys": feature_keys,
            "description": description,
            "_osm_id": osm_id,
        },
    }


def load_overrides() -> dict:
    if not OVERRIDES_FILE.exists():
        return {}
    with open(OVERRIDES_FILE, encoding="utf-8") as f:
        data = json.load(f)
    return data if isinstance(data, dict) else {}


def load_csv_updates() -> dict:
    """Return dict keyed by id (string) with optional name, address, size_hectares, description, feature_keys."""
    if not CSV_FILE.exists():
        return {}
    out = {}
    with open(CSV_FILE, encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            id_val = row.get("id", "").strip()
            if not id_val:
                continue
            entry = {}
            if row.get("name"):
                entry["name"] = row["name"].strip()
            if row.get("address"):
                entry["address"] = row["address"].strip()
            if row.get("size_hectares"):
                try:
                    entry["size_hectares"] = float(row["size_hectares"])
                except ValueError:
                    pass
            if row.get("description"):
                entry["description"] = row["description"].strip()
            if row.get("feature_keys"):
                keys = [k.strip() for k in row["feature_keys"].replace(";", ",").split(",") if k.strip()]
                entry["feature_keys"] = [k for k in keys if k in VALID_FEATURE_KEYS]
            if entry:
                out[id_val] = entry
    return out


def merge_overrides(
    features: list, overrides: dict, csv_updates: dict
) -> list:
    """Merge overrides and CSV into features by numeric id and _osm_id. Remove _osm_id from output."""
    for feat in features:
        props = feat["properties"]
        numeric_id = props.get("id", "")
        osm_id = props.get("_osm_id", "")

        # Apply overrides by numeric id and OSM id
        for key in (numeric_id, osm_id):
            if key in overrides:
                for k, v in overrides[key].items():
                    if k != "_osm_id":
                        props[k] = v
        if numeric_id in csv_updates:
            for k, v in csv_updates[numeric_id].items():
                props[k] = v
        if osm_id in csv_updates:
            for k, v in csv_updates[osm_id].items():
                props[k] = v

    return features


def feature_centroid(feat: dict) -> Optional[tuple]:
    """Return (lat, lon) of feature centroid, or None."""
    geom = feat.get("geometry") or {}
    gtype = geom.get("type")
    coords = geom.get("coordinates")
    if not coords:
        return None
    if gtype == "Point":
        return (coords[1], coords[0])
    if gtype == "Polygon" and coords and coords[0]:
        ring = coords[0]
        n = len(ring) - 1 if ring[0] == ring[-1] else len(ring)
        if n < 1:
            return None
        lat = sum(p[1] for p in ring[:n]) / n
        lon = sum(p[0] for p in ring[:n]) / n
        return (lat, lon)
    if gtype == "MultiPolygon" and coords and coords[0] and coords[0][0]:
        ring = coords[0][0]
        n = len(ring) - 1 if ring[0] == ring[-1] else len(ring)
        if n < 1:
            return None
        lat = sum(p[1] for p in ring[:n]) / n
        lon = sum(p[0] for p in ring[:n]) / n
        return (lat, lon)
    return None


# Rounded to ~0.0001 deg (~11 m); same key for nearby points so cache is reusable
GEOCODE_CACHE_PRECISION = 4


def _geocode_cache_key(lat: float, lon: float) -> str:
    return f"{round(lat, GEOCODE_CACHE_PRECISION)},{round(lon, GEOCODE_CACHE_PRECISION)}"


def load_geocode_cache() -> dict:
    """Load cache of (lat,lon) -> place name from data/geocode_cache.json."""
    if not GEOCODE_CACHE_FILE.exists():
        return {}
    try:
        with open(GEOCODE_CACHE_FILE, encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def save_geocode_cache(cache: dict) -> None:
    """Write cache to data/geocode_cache.json."""
    GEOCODE_CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(GEOCODE_CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=0)


def reverse_geocode(lat: float, lon: float) -> str:
    """Return place name (municipality, city, town, etc.) via Nominatim, or 'Danmark' on failure."""
    params = urllib.parse.urlencode({"lat": lat, "lon": lon, "format": "json", "addressdetails": 1})
    req = urllib.request.Request(
        f"{NOMINATIM_URL}?{params}",
        headers={"User-Agent": NOMINATIM_USER_AGENT},
    )
    last_err = None
    for attempt in range(MAX_RETRIES + 1):
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            break
        except (json.JSONDecodeError, KeyError):
            return "Danmark"
        except (urllib.error.HTTPError, urllib.error.URLError) as e:
            last_err = e
            if _should_retry_request(e) and attempt < MAX_RETRIES:
                delay = _retry_after_seconds(e, attempt) if isinstance(e, urllib.error.HTTPError) else RETRY_BASE_SECONDS * (2**attempt)
                print(f"  {_retry_message(e, 'Nominatim')}, retrying in {delay}s (attempt {attempt + 1}/{MAX_RETRIES + 1})...", flush=True)
                time.sleep(delay)
            else:
                return "Danmark"
    else:
        return "Danmark"
    addr = data.get("address") or {}
    place = (
        addr.get("village")
        or addr.get("town")
        or addr.get("city")
        or addr.get("municipality")
        or addr.get("county")
        or addr.get("state")
        or addr.get("country")
    )
    return place or "Danmark"


def enrich_addresses_with_reverse_geocode(features: list) -> None:
    """Replace address 'Danmark' with reverse-geocoded place name. Uses file cache; only calls Nominatim for misses."""
    to_fill = [f for f in features if (f.get("properties") or {}).get("address") == "Danmark"]
    if not to_fill:
        return
    cache = load_geocode_cache()
    misses = 0
    for feat in to_fill:
        lat_lon = feature_centroid(feat)
        if not lat_lon:
            continue
        key = _geocode_cache_key(lat_lon[0], lat_lon[1])
        if key in cache:
            feat["properties"]["address"] = cache[key]
        else:
            place = reverse_geocode(lat_lon[0], lat_lon[1])
            cache[key] = place
            feat["properties"]["address"] = place
            misses += 1
            save_geocode_cache(cache)
            if misses % 50 == 0:
                print(f"  {misses} new lookups...", flush=True)
            time.sleep(1.1)
    n = len(to_fill)
    if misses == 0:
        print(f"Resolving place names for {n} forests: all from cache.", flush=True)
    else:
        print(f"Resolving place names for {n} forests: {n - misses} from cache, {misses} new (Nominatim, 1 req/sec).", flush=True)
    print("  Done.", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="Refresh forest data from OpenStreetMap (Denmark).")
    parser.add_argument(
        "--no-reverse-geocode",
        action="store_true",
        help="Skip reverse geocoding; keep address as 'Danmark' when OSM has no addr tags",
    )
    args = parser.parse_args()
    print("Fetching dog parks from OpenStreetMap (Denmark, by country boundary)...", flush=True)
    print("  (main Overpass query may take 1–2 minutes)", flush=True)
    query = overpass_query()
    try:
        data = fetch_overpass(query)
    except urllib.error.HTTPError as e:
        print(f"Overpass request failed: HTTP {e.code} {e.reason}", file=sys.stderr)
        sys.exit(1)
    except urllib.error.URLError as e:
        print(f"Overpass request failed: {e}", file=sys.stderr)
        sys.exit(1)
    except json.JSONDecodeError as e:
        print(f"Invalid Overpass response: {e}", file=sys.stderr)
        sys.exit(1)

    elements = data.get("elements", [])
    n_nodes = sum(1 for el in elements if el.get("type") == "node")
    n_ways = sum(1 for el in elements if el.get("type") == "way")
    n_relations = sum(1 for el in elements if el.get("type") == "relation")
    print(f"  Got {len(elements)} elements ({n_nodes} nodes, {n_ways} ways, {n_relations} relations)", flush=True)

    ways_by_id = {el["id"]: el for el in elements if el.get("type") == "way"}
    dog_park_elements = [el for el in elements if (el.get("tags") or {}).get("leisure") == "dog_park"]
    dog_park_elements.sort(key=osm_element_sort_key)
    print(f"  {len(dog_park_elements)} dog parks to process", flush=True)

    # Fetch member ways for relations that have no usable geometry (Overpass often omits or returns empty)
    relations_to_fetch = [
        el for el in dog_park_elements
        if el.get("type") == "relation" and el.get("id") and not relation_has_usable_geometry(el)
    ]
    if relations_to_fetch:
        total = len(relations_to_fetch)
        print(f"Fetching geometry for {total} relations (one request per relation)...", flush=True)
        for idx, el in enumerate(relations_to_fetch, 1):
            try:
                rdata = fetch_overpass(overpass_relation_members_query(el["id"]), timeout=60)
                for e in rdata.get("elements", []):
                    if e.get("type") == "way":
                        ways_by_id[e["id"]] = e
                    # Main query often omits relation members; copy from follow-up so we can build geometry.
                    # Response may list the relation twice (e.g. "out ids" then "out body"); keep the one with members.
                    if e.get("type") == "relation" and e.get("id") == el.get("id"):
                        new_members = e.get("members") or []
                        if len(new_members) > len(el.get("members") or []):
                            el["members"] = new_members
            except urllib.error.HTTPError as err:
                print(f"  Warning: relation {el.get('id')} geometry fetch failed: HTTP {err.code} {err.reason}", file=sys.stderr)
            except (urllib.error.URLError, json.JSONDecodeError, KeyError) as err:
                print(f"  Warning: relation {el.get('id')} geometry fetch failed: {type(err).__name__}: {err}", file=sys.stderr)
            if idx % 10 == 0 or idx == total:
                print(f"  {idx}/{total} relations", flush=True)
        print("  Done.", flush=True)

    print("Converting to features...", flush=True)
    features = []
    for i, el in enumerate(dog_park_elements):
        numeric_id = str(i + 1)
        feat = element_to_feature(el, numeric_id, ways_by_id=ways_by_id)
        if feat:
            features.append(feat)
    print(f"  {len(features)} features", flush=True)

    print("Merging overrides and CSV updates...", flush=True)
    overrides = load_overrides()
    csv_updates = load_csv_updates()
    features = merge_overrides(features, overrides, csv_updates)

    if not args.no_reverse_geocode:
        enrich_addresses_with_reverse_geocode(features)

    FORESTS_DIR.mkdir(parents=True, exist_ok=True)
    # Remove existing JSON files so we replace the set entirely
    for p in FORESTS_DIR.glob("*.json"):
        p.unlink()

    print(f"Writing {len(features)} forest files...", flush=True)
    for idx, feat in enumerate(features):
        props = feat["properties"]
        osm_id = props.get("_osm_id", "")
        filename = osm_id.replace("/", "_") + ".json" if osm_id else props.get("id", "") + ".json"
        path = FORESTS_DIR / filename
        props.pop("_osm_id", None)  # do not write to JSON
        with open(path, "w", encoding="utf-8") as f:
            json.dump(feat, f, ensure_ascii=False, separators=(",", ":"))
        if (idx + 1) % 100 == 0 or idx + 1 == len(features):
            print(f"  {idx + 1}/{len(features)}", flush=True)
    print(f"Wrote {len(features)} forests to {FORESTS_DIR}", flush=True)

    print("Building hundeskove.json...", flush=True)
    n = build_hundeskove()
    print(f"Wrote {n} forests to {PROJECT_ROOT / 'data' / 'hundeskove.json'}", flush=True)
    print("Done.", flush=True)


if __name__ == "__main__":
    main()
