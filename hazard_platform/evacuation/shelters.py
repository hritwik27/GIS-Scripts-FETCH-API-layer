"""
evacuation/shelters.py -- thin read wrapper over ShelterStore.

Save as: hazard_platform/evacuation/shelters.py
Mirrors evacuation/population.py: store is injectable for tests and
defaults to ShelterStore() like every other reader in the pipeline.
"""

from typing import Optional

from data_pipeline.static_datasets.shelters_store import ShelterRecord, ShelterStore


def get_shelters(zone_id: str, store: Optional[ShelterStore] = None) -> list[ShelterRecord]:
    """All shelter candidates for a zone (may be empty)."""
    store = store or ShelterStore()
    return store.get_all_for_zone(zone_id)


def get_shelters_with_capacity(
    zone_id: str, store: Optional[ShelterStore] = None
) -> list[ShelterRecord]:
    """Shelters usable for assignment: nominal_capacity known and > 0.

    Shelters with unknown capacity are excluded here, not guessed at.
    Use get_shelters() if you need to list or flag them.
    """
    return [
        s
        for s in get_shelters(zone_id, store)
        if s.nominal_capacity is not None and s.nominal_capacity > 0
    ]


def get_all_shelters(store: Optional[ShelterStore] = None) -> list[ShelterRecord]:
    """All registered shelters across all zones."""
    store = store or ShelterStore()
    return store.get_all()