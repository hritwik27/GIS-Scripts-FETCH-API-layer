"""Standalone OSM shelter fetcher (no gis_fetcher dependency).

Run from hazard_platform/ or hazard_platform/scripts/:
    python scripts/fetch_shelters_osm.py

Reads:  zones.geojson   (made by make_zones_geojson.py)
Writes: shelters.csv    (one row per shelter candidate, keyed by zone_id)

Capacity source priority (matches FINAL doc section 5):
    1. numeric OSM `capacity` tag            -> capacity_source = "osm_tag"
    2. building footprint / SQ_M_PER_PERSON  -> capacity_source = "footprint_estimate"
    3. otherwise capacity left empty         -> capacity_source = "unknown"
       (fill these by hand in a manual CSV; do NOT invent a number)
"""

import csv
import json
import math
import re
import sys
import time
from pathlib import Path

import requests

HP_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HP_ROOT))

ZONES_GEOJSON = HP_ROOT / "zones.geojson"
OUT_CSV = HP_ROOT / "shelters.csv"
OVERPASS_URL = "https://overpass-api.de/api/interpreter"

# Configurable occupancy standard. Sphere: ~3.5 m2 covered floor per person
# for buildings (45 m2 is for open camp land, not building footprints).
SQ_M_PER_PERSON = 3.5
AMENITIES = ["shelter", "school", "community_centre"]
PAUSE_SECONDS = 5      # be polite to the free Overpass server
MAX_RETRIES = 3

# overpass-api.de returns HTTP 406 for the default python-requests User-Agent.
HEADERS = {"User-Agent": "hazard-platform-sih2026/1.0 (SIH26191 Rescue Arc)"}
RETRYABLE_STATUS = (429, 502, 503, 504)


def _walk(coords):
    if coords and isinstance(coords[0], (int, float)):
        yield coords
    else:
        for c in coords:
            yield from _walk(c)


def zone_bbox(feature):
    pts = list(_walk(feature["geometry"]["coordinates"]))
    lons = [p[0] for p in pts]
    lats = [p[1] for p in pts]
    return min(lats), min(lons), max(lats), max(lons)  # south, west, north, east


def zone_id_of(feature):
    props = feature.get("properties", {})
    return props.get("zone_id") or props.get("id") or props.get("name")


def polygon_area_m2(geometry):
    """Shoelace area on a local flat projection; fine at building scale."""
    if len(geometry) < 4:
        return None
    lat0 = sum(p["lat"] for p in geometry) / len(geometry)
    kx = 111320.0 * math.cos(math.radians(lat0))
    ky = 110540.0
    xy = [(p["lon"] * kx, p["lat"] * ky) for p in geometry]
    s = 0.0
    for (x1, y1), (x2, y2) in zip(xy, xy[1:] + xy[:1]):
        s += x1 * y2 - x2 * y1
    return abs(s) / 2.0


def query_overpass(south, west, north, east):
    pattern = "|".join(AMENITIES)
    q = (
        "[out:json][timeout:60];"
        f'nwr["amenity"~"^({pattern})$"]({south},{west},{north},{east});'
        "out tags center geom;"
    )
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            r = requests.post(OVERPASS_URL, data={"data": q}, headers=HEADERS, timeout=90)
            if r.status_code == 200:
                return r.json().get("elements", [])
            print(f"   HTTP {r.status_code}, retry {attempt}/{MAX_RETRIES}")
            if r.status_code not in RETRYABLE_STATUS:
                return None
        except requests.RequestException as exc:
            print(f"   {exc.__class__.__name__}, retry {attempt}/{MAX_RETRIES}")
        time.sleep(10 * attempt)
    return None


def parse_capacity_tag(tags):
    m = re.match(r"\s*(\d+)", tags.get("capacity", "") or "")
    return int(m.group(1)) if m else None


def to_row(zone_id, el):
    tags = el.get("tags", {})
    if el["type"] == "node":
        lat, lon = el.get("lat"), el.get("lon")
    else:
        c = el.get("center", {})
        lat, lon = c.get("lat"), c.get("lon")
    if lat is None or lon is None:
        return None

    area = None
    if el["type"] == "way" and el.get("geometry"):
        area = polygon_area_m2(el["geometry"])

    cap = parse_capacity_tag(tags)
    if cap is not None:
        source = "osm_tag"
    elif area:
        cap = int(area // SQ_M_PER_PERSON)
        source = "footprint_estimate"
    else:
        source = "unknown"

    return {
        "zone_id": zone_id,
        "osm_type": el["type"],
        "osm_id": el["id"],
        "name": tags.get("name", ""),
        "amenity": tags.get("amenity", ""),
        "lat": lat,
        "lon": lon,
        "footprint_m2": round(area, 1) if area else "",
        "capacity": cap if cap is not None else "",
        "capacity_source": source,
        "sq_m_per_person_used": SQ_M_PER_PERSON if source == "footprint_estimate" else "",
    }


def main():
    zones = json.loads(ZONES_GEOJSON.read_text(encoding="utf-8"))["features"]
    rows, empty_zones = [], []

    for feat in zones:
        zid = zone_id_of(feat)
        s, w, n, e = zone_bbox(feat)
        print(f"{zid}: querying bbox ({s:.3f},{w:.3f},{n:.3f},{e:.3f})")
        elements = query_overpass(s, w, n, e)
        if elements is None:
            print("   FAILED after retries - rerun later")
            empty_zones.append(zid)
        else:
            got = [r for r in (to_row(zid, el) for el in elements) if r]
            print(f"   {len(got)} shelter candidates")
            if not got:
                empty_zones.append(zid)
            rows.extend(got)
        time.sleep(PAUSE_SECONDS)

    fields = ["zone_id", "osm_type", "osm_id", "name", "amenity", "lat", "lon",
              "footprint_m2", "capacity", "capacity_source", "sq_m_per_person_used"]
    with OUT_CSV.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)

    print(f"\nWrote {len(rows)} rows to {OUT_CSV}")
    if empty_zones:
        print("Zones needing manual-CSV fallback:", empty_zones)


if __name__ == "__main__":
    main()
