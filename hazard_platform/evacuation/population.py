"""population.py — thin read wrapper around StaticDatasetStore for the
`population` field (evacuation demand base input P_i, see FINAL doc §13).

Population is ingested once (see data_pipeline/static_datasets/load_population.py)
via WorldPop's 2017 1km UN-adjusted raster, keyed to the 12 seeded zone_ids in
zones.py. This module does no computation and no live lookup -- it's a
read-only accessor other evacuation modules call to get P_i.

A zone_id outside the 12 seeded zones (e.g. a dynamically map-clicked point,
see zone_from_point() in zones.py) will have no row in StaticDatasetStore.
get_population() returns None in that case -- callers MUST handle None,
not assume every zone has population data. This is a deliberate limitation
of the static-CSV approach (see overview.md "Current state" / §10 of the
session log), not a bug.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from data_pipeline.static_datasets.store import StaticDatasetStore

FIELD_NAME = "population"


@dataclass
class PopulationRecord:
    zone_id: str
    population: float
    source: str
    ingested_at: datetime


def get_population(zone_id: str, store: StaticDatasetStore | None = None) -> PopulationRecord | None:
    """Look up population for a zone_id. Returns None if this zone was
    never ingested (dynamically-clicked point outside the 12 seeded
    zones, or population ingestion just hasn't been run yet) -- callers
    building evacuation demand must treat that as "no data", not crash
    or silently default to 0.

    `store` is injectable for testing; defaults to a fresh
    StaticDatasetStore() against the default db_path, matching every
    other reader in this pipeline (pipeline_runner.py, auto_refresh.py).
    """
    store = store or StaticDatasetStore()
    field = store.get(zone_id, FIELD_NAME)
    if field is None or field.value is None:
        return None
    return PopulationRecord(
        zone_id=field.zone_id,
        population=field.value,
        source=field.source,
        ingested_at=field.ingested_at,
    )