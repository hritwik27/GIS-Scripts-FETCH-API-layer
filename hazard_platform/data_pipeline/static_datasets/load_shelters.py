"""
load_shelters.py -- ingest shelters.csv (from fetch_shelters_osm.py) into ShelterStore.

Save as: hazard_platform/data_pipeline/static_datasets/load_shelters.py
Mirrors load_population.py's CLI shape.

Usage (from hazard_platform/):
    python -m data_pipeline.static_datasets.load_shelters shelters.csv

CSV columns expected (written by fetch_shelters_osm.py):
    zone_id, osm_type, osm_id, name, amenity, lat, lon,
    footprint_m2, capacity, capacity_source, sq_m_per_person_used

Note: capacity_source is passed through as-is from the CSV
("osm_tag" / "footprint_estimate" / "unknown"), NOT overwritten with
ShelterStore.upsert()'s default "gis_estimated" -- only
"footprint_estimate" rows are actually GIS-estimated; "osm_tag" rows
carry a real OSM-authored capacity value, and collapsing the two would
misrepresent the data's actual provenance.
"""

import argparse
import csv
from pathlib import Path

from data_pipeline.static_datasets.shelters_store import ShelterStore


def _to_float(value: str):
    value = (value or "").strip()
    if not value:
        return None
    try:
        return float(value)
    except ValueError:
        return None


def load_shelters(csv_path: str, db_path: str = "shelters.db") -> None:
    store = ShelterStore(db_path=db_path)

    zones_seen: set[str] = set()
    loaded = 0
    skipped = 0

    with Path(csv_path).open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            zone_id = (row.get("zone_id") or "").strip()
            osm_type = (row.get("osm_type") or "").strip()
            osm_id = (row.get("osm_id") or "").strip()

            if not zone_id or not osm_type or not osm_id:
                skipped += 1
                continue

            lat = _to_float(row.get("lat"))
            lon = _to_float(row.get("lon"))
            if lat is None or lon is None:
                skipped += 1
                continue

            shelter_id = f"osm-{osm_type}-{osm_id}"
            capacity_source = (row.get("capacity_source") or "unknown").strip()

            store.upsert(
                shelter_id=shelter_id,
                zone_id=zone_id,
                name=(row.get("name") or "").strip() or None,
                lat=lat,
                lon=lon,
                osm_tag=(row.get("amenity") or "").strip(),
                footprint_area_sq_m=_to_float(row.get("footprint_m2")),
                nominal_capacity=_to_float(row.get("capacity")),
                capacity_source=capacity_source,
            )
            zones_seen.add(zone_id)
            loaded += 1

    print(f"shelters: loaded {loaded} shelter(s) across {len(zones_seen)} zone(s): "
          f"{sorted(zones_seen)}")
    if skipped:
        print(f"shelters: skipped {skipped} malformed row(s) (missing zone_id/osm id/lat/lon)")


def main() -> None:
    parser = argparse.ArgumentParser(description="Load shelters.csv into ShelterStore")
    parser.add_argument("csv_path", help="Path to shelters.csv produced by fetch_shelters_osm.py")
    parser.add_argument("--db-path", default="shelters.db", help="ShelterStore sqlite db path")
    args = parser.parse_args()
    load_shelters(args.csv_path, db_path=args.db_path)


if __name__ == "__main__":
    main()