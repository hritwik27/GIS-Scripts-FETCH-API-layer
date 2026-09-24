"""load_population.py — one-time (re-run periodically, e.g. yearly)
ingestion of `population` (evacuation demand base input P_i) from a
WorldPop population-count raster, via spatial_join.py's raster_sum mode.

SOURCE (free, no login):
  WorldPop Population Counts, Unconstrained individual countries,
  1km resolution, UN-adjusted:
    https://hub.worldpop.org/geodata/summary?id=36808
  Direct download (India, 2017, ~17MB):
    https://data.worldpop.org/GIS/Population/Global_2000_2020_1km_UNadj/2017/IND/ind_ppp_2017_1km_Aggregated_UNadj.tif

WHAT YOU GET: a GeoTIFF where each ~1km pixel holds an estimated number
of people (a COUNT, not a density) -- UN-adjusted, meaning WorldPop
calibrated it against official UN population totals.

HOW TO GENERATE THE CSV: zones.py's zones are small bounding boxes, not
real OSM-recognized administrative polygons, so spatial_join.py's
default OSM auto-fetch will not find them -- generate a zones GeoJSON
directly from zones.py's own bboxes first (see make_zones_geojson.py),
then run spatial_join.py against it in raster_sum mode:

    python scripts/make_zones_geojson.py
    python -m data_pipeline.static_datasets.spatial_join \\
        --zones-file zones.geojson \\
        --mode raster_sum \\
        --raster-path data_pipeline/static_datasets/data/ind_ppp_2017_1km_Aggregated_UNadj.tif \\
        --dataset data_pipeline/static_datasets/data/ind_ppp_2017_1km_Aggregated_UNadj.tif \\
        --out population.csv

THEN RUN:
    python3 -m data_pipeline.static_datasets.load_population \\
        population.csv --source "WorldPop_2017_1km_UNadj"
"""

from __future__ import annotations

import argparse
import sys

from .load_from_csv import load_csv
from .store import StaticDatasetStore

FIELD_NAME = "population"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("csv_path", help="CSV with columns: zone_id,value")
    parser.add_argument("--source", default="WorldPop_2017_1km_UNadj", help="Dataset name + vintage year")
    parser.add_argument("--db", default="static_zone_data.db")
    args = parser.parse_args(argv)

    store = StaticDatasetStore(db_path=args.db)
    summary = load_csv(args.csv_path, FIELD_NAME, args.source, store)
    print(f"population: loaded {len(summary['loaded'])} zone(s): {summary['loaded']}")
    if summary["skipped"]:
        print(f"  skipped: {summary['skipped']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))