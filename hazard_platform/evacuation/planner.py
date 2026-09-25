"""
evacuation/planner.py -- background evacuation-lane job (FINAL doc §1 / §11 flow).

    population -> demand -> shelters -> capacity

Cached per zone, read by the authority endpoint (api.py). Never runs in the
synchronous map-click path (/api/analyze-point -> ingest_point -> fetch ->
normalize -> clean -> save). This module reads readings that are ALREADY
in HazardReadingStore and recomputes a classification from them -- exactly
what api.py's own `_score_zone()` does for /api/zone-status -- it never
fetches, never touches gis_fetcher/ingest_point, and never blocks on network
I/O. Routing/assignment don't exist yet, so "unserved" below is the
aggregate zone-level number from capacity.capacity_gap(), not a per-shelter
assignment, and TRAPPED is not computed here -- that needs routing.py.

Confirmed against the real code (not guessed):
  - evacuation.population.get_population(zone_id) -> PopulationRecord | None
  - evacuation.shelters.get_shelters(zone_id) -> list[ShelterRecord]
  - HazardReadingStore.latest_for_zone(zone_id, hazard_type) -> HazardReading | None
  - HazardReading.recorded_at -> datetime  (used as the cache key)
  - build_feature_dict(hazard, reading.parameters), predict(features_by_hazard),
    classify_zone(zone_id, scores) -> ZoneClassification(.color, .worst_hazard, .scores)
This mirrors backend/api.py's _score_zone() line for line on the read side.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Callable, Optional

from backend.zone_classifier import ZoneClassification, classify_zone
from data_pipeline.hazard_reading_store import HazardReadingStore
from data_pipeline.models import HazardType
from evacuation import population as population_mod
from evacuation import shelters as shelters_mod
from evacuation import vulnerability as vulnerability_mod
from evacuation.assignment import (
    AssignmentParams,
    assign_zone,
    haversine_distance_km,
    load_params as load_assignment_params,
)
from evacuation.capacity import (
    CapacityParams,
    capacity_gap,
    compute_zone_capacities,
    load_params as load_capacity_params,
    map_safe_shelters,
    zone_capacity_summary,
)
from evacuation.demand import DemandParams, compute_demand, load_params as load_demand_params
from ml_service.features.feature_engineering import build_feature_dict
from ml_service.inference.predictor import predict
from zones import get_zone

# (zone_color, worst_score, reading_timestamp)
HazardReader = Callable[[str], "tuple[object, float, Optional[datetime]]"]


def make_hazard_reader(store: HazardReadingStore) -> HazardReader:
    """Same read path as backend/api.py's _score_zone(): latest reading per
    hazard type -> features -> predict -> classify. No fetch, no network.
    Raises ValueError if the zone has no stored readings yet (unseeded zone,
    or a seeded zone never ingested) -- callers decide how to handle that."""

    def _read(zone_id: str):
        features_by_hazard = {}
        latest_ts: Optional[datetime] = None
        for hazard in HazardType:
            reading = store.latest_for_zone(zone_id, hazard)
            if reading is None:
                continue
            features_by_hazard[hazard] = build_feature_dict(hazard, reading.parameters)
            if latest_ts is None or reading.recorded_at > latest_ts:
                latest_ts = reading.recorded_at

        if not features_by_hazard:
            raise ValueError(f"No readings stored for zone {zone_id}")

        scores = predict(features_by_hazard)
        classification: ZoneClassification = classify_zone(zone_id, scores)
        worst_score = max(classification.scores.values()) if classification.scores else 0.0
        return classification.color, worst_score, latest_ts

    return _read


@dataclass
class ZonePlan:
    zone_id: str
    computed_at: datetime
    reading_timestamp: Optional[datetime]
    zone_color: str
    worst_score: float
    demand: dict
    capacity_summary: dict
    capacity_gap: dict
    safe_shelters_public: list   # -> map response (§11: location+type, no numbers)
    shelters_full: list          # -> authority dashboard only
    trapped: bool = False        # First-class state per FINAL doc §7
    assignment: Optional[dict] = None
    road_network: Optional[dict] = None
    provenance: Optional[dict] = None



    def to_dict(self) -> dict:
        d = asdict(self)
        d["computed_at"] = self.computed_at.isoformat()
        if self.reading_timestamp is not None:
            d["reading_timestamp"] = self.reading_timestamp.isoformat()
        return d


class PlannerCache:
    """In-memory, keyed by (zone_id, reading_timestamp). A fresh ingest of
    even one hazard for a zone changes reading_timestamp (it's the max
    recorded_at across that zone's readings), which naturally invalidates
    the cached plan instead of it silently going stale."""

    def __init__(self):
        self._store: dict[str, ZonePlan] = {}

    def get(self, zone_id: str, reading_timestamp: Optional[datetime]) -> Optional[ZonePlan]:
        cached = self._store.get(zone_id)
        if cached is None or cached.reading_timestamp != reading_timestamp:
            return None
        return cached

    def set(self, zone_id: str, plan: ZonePlan) -> None:
        self._store[zone_id] = plan


def plan_zone(
    zone_id: str,
    hazard_reader: HazardReader,
    *,
    cache: Optional[PlannerCache] = None,
    demand_params: Optional[DemandParams] = None,
    capacity_params: Optional[CapacityParams] = None,
    assignment_params: Optional[AssignmentParams] = None,
) -> ZonePlan:
    """Compute (or return cached) plan for one zone. Raises ValueError
    (propagated from hazard_reader) if the zone has no stored readings."""
    color, worst_score, reading_ts = hazard_reader(zone_id)

    if cache is not None:
        hit = cache.get(zone_id, reading_ts)
        if hit is not None:
            return hit

    population_record = population_mod.get_population(zone_id)
    population = population_record.population if population_record is not None else None

    vuln_record = vulnerability_mod.get_vulnerability(zone_id)
    phi_k = vuln_record.phi_kutcha if vuln_record is not None else None
    phi_d = vuln_record.phi_dependent if vuln_record is not None else None

    dparams = demand_params or load_demand_params()
    demand_result = compute_demand(
        zone_id,
        population,
        color,
        worst_score,
        params=dparams,
        phi_kutcha=phi_k,
        phi_dependent=phi_d,
    )

    shelters = shelters_mod.get_shelters(zone_id)
    cparams = capacity_params or load_capacity_params()
    caps = compute_zone_capacities(shelters, color, params=cparams)

    aparams = assignment_params or load_assignment_params()
    zone = get_zone(zone_id)
    origin_lat, origin_lon = (zone.center[1], zone.center[0]) if zone else (0.0, 0.0)

    # Candidate shelters for assignment: local shelters + reachable safe shelters
    all_candidate_caps = list(caps)
    assignable_local = sum(c.assignable for c in caps)
    if demand_result.demand and demand_result.demand > assignable_local and zone:
        for s in shelters_mod.get_all_shelters():
            if s.zone_id == zone_id:
                continue
            dist = haversine_distance_km(origin_lat, origin_lon, s.lat, s.lon)
            if dist <= aparams.max_distance_km:
                if not any(c.shelter_id == s.shelter_id for c in all_candidate_caps):
                    s_cap = compute_zone_capacities([s], "GREEN", params=cparams)[0]
                    all_candidate_caps.append(s_cap)

    from evacuation.road_network import build_corridor_network

    corridor_graph = build_corridor_network(zone_id, origin_lat, origin_lon, all_candidate_caps)

    assignment_res = assign_zone(
        zone_id,
        origin_lat,
        origin_lon,
        demand_result.demand,
        all_candidate_caps,
        params=aparams,
        graph=corridor_graph,
        hazard_score=worst_score,
    )

    from evacuation.provenance import build_plan_provenance

    prov = build_plan_provenance(
        zone_id=zone_id,
        hazard_reading_ts=reading_ts,
        shelters=all_candidate_caps,
        hazard_confidence=0.92,
    )

    plan = ZonePlan(
        zone_id=zone_id,
        computed_at=datetime.now(timezone.utc),
        reading_timestamp=reading_ts,
        zone_color=str(getattr(color, "value", color)),
        worst_score=worst_score,
        demand=demand_result.to_dict(),
        capacity_summary=zone_capacity_summary(caps),
        capacity_gap=capacity_gap(demand_result.demand, caps),
        safe_shelters_public=map_safe_shelters(caps),
        shelters_full=[c.to_dict() for c in caps],
        trapped=assignment_res.trapped,
        assignment=assignment_res.to_dict(),
        road_network=corridor_graph.to_geojson(),
        provenance=prov.to_dict(),
    )

    if cache is not None:
        cache.set(zone_id, plan)
    return plan



def plan_all_zones(
    zone_ids: list,
    hazard_reader: HazardReader,
    *,
    cache: Optional[PlannerCache] = None,
    demand_params: Optional[DemandParams] = None,
    capacity_params: Optional[CapacityParams] = None,
    assignment_params: Optional[AssignmentParams] = None,
) -> dict:
    """Runs plan_zone() per zone. A zone with nothing ingested yet (or any
    other per-zone failure) is collected under 'errors', not raised -- one
    bad zone must not kill a 50-zone batch run."""
    results: dict = {}
    errors: dict = {}
    for zone_id in zone_ids:
        try:
            results[zone_id] = plan_zone(
                zone_id, hazard_reader, cache=cache,
                demand_params=demand_params, capacity_params=capacity_params,
                assignment_params=assignment_params,
            )
        except Exception as exc:  # noqa: BLE001
            errors[zone_id] = str(exc)
    return {"plans": results, "errors": errors}