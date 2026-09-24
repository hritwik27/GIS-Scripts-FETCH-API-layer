"""make_zones_geojson.py -- Developer/admin utility script to generate zones.geojson
from zones.py's bounding boxes.

Run from hazard_platform/ or hazard_platform/scripts/:
    python scripts/make_zones_geojson.py
"""
import json
import sys
from pathlib import Path

# Add hazard_platform root to sys.path
HP_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HP_ROOT))

from zones import list_zones

def generate_zones_geojson(output_path: Path = HP_ROOT / "zones.geojson"):
    features = []
    for zone in list_zones():
        features.append({
            "type": "Feature",
            "properties": {"zone_id": zone.zone_id, "name": zone.name},
            "geometry": {
                "type": "Polygon",
                "coordinates": [[
                    [zone.min_lon, zone.min_lat],
                    [zone.max_lon, zone.min_lat],
                    [zone.max_lon, zone.max_lat],
                    [zone.min_lon, zone.max_lat],
                    [zone.min_lon, zone.min_lat],
                ]],
            },
        })

    geojson = {"type": "FeatureCollection", "features": features}
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(geojson, f, indent=2)

    print(f"Wrote {len(features)} zone(s) to {output_path}")

if __name__ == "__main__":
    generate_zones_geojson()
