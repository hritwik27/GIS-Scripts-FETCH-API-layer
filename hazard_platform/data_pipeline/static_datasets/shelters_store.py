"""shelters_store.py — persistence for shelter records (location, OSM
source tag, footprint area, and derived capacity), fetched live from
OpenStreetMap via gis_fetcher's "osm" provider.

Deliberately a separate table (and separate store class) from
StaticDatasetStore (see store.py's docstring): that store is shaped for
exactly one scalar value per (zone_id, field_name) pair, which fits
population, mangrove_cover_pct, etc. Shelters are one-to-many per
zone -- a zone can have zero, one, or a dozen shelters, each with its
own lat/lon/capacity -- so they need their own table keyed by
shelter_id, not a field_name/value row.

capacity_source is "gis_estimated" for every row right now (tier 3 of
FINAL doc §5's three-tier capacity priority: authority-verified >
verified floor area > GIS-estimated area). This project has no
authority-verified shelter registry, so every row is honestly tier 3
-- not a placeholder, but flagged here the same way the AHP judgment
files flag their PLACEHOLDER convention, so a future reader doesn't
mistake this for verified data.
"""

from __future__ import annotations

import sqlite3
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

_SCHEMA = """
CREATE TABLE IF NOT EXISTS shelters (
    shelter_id TEXT PRIMARY KEY,
    zone_id TEXT NOT NULL,
    name TEXT,
    lat REAL NOT NULL,
    lon REAL NOT NULL,
    osm_tag TEXT NOT NULL,
    footprint_area_sq_m REAL,
    nominal_capacity REAL,
    capacity_source TEXT NOT NULL,
    ingested_at TEXT NOT NULL
);
"""


@dataclass
class ShelterRecord:
    shelter_id: str
    zone_id: str
    name: Optional[str]
    lat: float
    lon: float
    osm_tag: str
    footprint_area_sq_m: Optional[float]
    nominal_capacity: Optional[float]
    capacity_source: str
    ingested_at: datetime


class ShelterStore:
    def __init__(self, db_path: str = "shelters.db") -> None:
        self.db_path = db_path
        parent = Path(db_path).parent
        if str(parent) not in ("", "."):
            parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.db_path)) as conn:
            conn.executescript(_SCHEMA)
            conn.commit()

    def upsert(
        self,
        shelter_id: str,
        zone_id: str,
        name: Optional[str],
        lat: float,
        lon: float,
        osm_tag: str,
        footprint_area_sq_m: Optional[float],
        nominal_capacity: Optional[float],
        capacity_source: str = "gis_estimated",
    ) -> None:
        with closing(sqlite3.connect(self.db_path)) as conn:
            conn.execute(
                """INSERT INTO shelters
                   (shelter_id, zone_id, name, lat, lon, osm_tag,
                    footprint_area_sq_m, nominal_capacity, capacity_source, ingested_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(shelter_id) DO UPDATE SET
                       zone_id=excluded.zone_id, name=excluded.name, lat=excluded.lat,
                       lon=excluded.lon, osm_tag=excluded.osm_tag,
                       footprint_area_sq_m=excluded.footprint_area_sq_m,
                       nominal_capacity=excluded.nominal_capacity,
                       capacity_source=excluded.capacity_source,
                       ingested_at=excluded.ingested_at""",
                (
                    shelter_id, zone_id, name, lat, lon, osm_tag,
                    footprint_area_sq_m, nominal_capacity, capacity_source,
                    datetime.now(timezone.utc).isoformat(),
                ),
            )
            conn.commit()

    def get_all_for_zone(self, zone_id: str) -> list[ShelterRecord]:
        with closing(sqlite3.connect(self.db_path)) as conn:
            rows = conn.execute(
                """SELECT shelter_id, zone_id, name, lat, lon, osm_tag,
                          footprint_area_sq_m, nominal_capacity, capacity_source, ingested_at
                   FROM shelters WHERE zone_id = ?""",
                (zone_id,),
            ).fetchall()
        return [
            ShelterRecord(
                shelter_id=r[0], zone_id=r[1], name=r[2], lat=r[3], lon=r[4],
                osm_tag=r[5], footprint_area_sq_m=r[6], nominal_capacity=r[7],
                capacity_source=r[8], ingested_at=datetime.fromisoformat(r[9]),
            )
            for r in rows
        ]

    def get_all(self) -> list[ShelterRecord]:
        with closing(sqlite3.connect(self.db_path)) as conn:
            rows = conn.execute(
                """SELECT shelter_id, zone_id, name, lat, lon, osm_tag,
                          footprint_area_sq_m, nominal_capacity, capacity_source, ingested_at
                   FROM shelters"""
            ).fetchall()
        return [
            ShelterRecord(
                shelter_id=r[0], zone_id=r[1], name=r[2], lat=r[3], lon=r[4],
                osm_tag=r[5], footprint_area_sq_m=r[6], nominal_capacity=r[7],
                capacity_source=r[8], ingested_at=datetime.fromisoformat(r[9]),
            )
            for r in rows
        ]