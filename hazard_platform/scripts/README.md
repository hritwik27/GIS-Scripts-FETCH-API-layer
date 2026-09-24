# Utility & Data Generation Scripts

This directory contains standalone data generation, extraction, and offline maintenance scripts.
These scripts are run during initial setup or periodic offline updates and are separated from the live runtime code.

- **`make_zones_geojson.py`**: Reads all 50 zone definitions from `zones.py` and creates `hazard_platform/zones.geojson`.
- **`fetch_shelters_osm.py`**: Queries the Overpass API for schools, community centers, and shelters within the bounding boxes of each zone and writes `hazard_platform/shelters.csv`.
