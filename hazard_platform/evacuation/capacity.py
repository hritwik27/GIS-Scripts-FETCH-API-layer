"""
evacuation/capacity.py -- shelter effective capacity + safety check (FINAL doc section 5).

    Usable_j    = Nominal_j - Occupancy_j - Reserved_j
    Effective_j = Usable_j x OperationalFactor_j x SafetyFactor_j

- NO max(100, ...) floor (the PDF bug). Usable/Effective may reach 0 or go
  NEGATIVE (over-capacity, kept for alerting). `assignable` = max(0, effective)
  is what an assignment step may actually use.
- Safety check: a shelter inside a hazardous zone is not usable, regardless of
  free space. Status comes from the zone colour the shelter sits in.
- Unknown nominal capacity -> effective is None and assignable is 0. Never guessed.

Pure functions, no I/O, no network -- safe for a background job; never touches
the ingestion path. `shelter` is duck-typed: anything with shelter_id, zone_id,
name, lat, lon, nominal_capacity, capacity_source (a ShelterRecord works).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Iterable, Optional, Union

PARAMS_PATH = Path(__file__).with_name("evacuation_params.yaml")

_STATUS_BY_COLOR = {"GREEN": "SAFE", "YELLOW": "CAUTION", "RED": "UNSAFE"}


def _default_safety_factors() -> dict:
    return {"SAFE": 1.0, "CAUTION": 0.5, "UNSAFE": 0.0, "UNVERIFIED": 0.0}


@dataclass(frozen=True)
class CapacityParams:
    operational_factor: float = 1.0
    safety_factors: dict = field(default_factory=_default_safety_factors)


@dataclass
class ShelterCapacity:
    shelter_id: str
    zone_id: str
    name: Optional[str]
    lat: float
    lon: float
    osm_tag: Optional[str]
    capacity_source: str
    safety_status: str             # SAFE | CAUTION | UNSAFE | UNVERIFIED
    safety_factor: float
    capacity_known: bool
    nominal: Optional[float]
    occupancy: float
    reserved: float
    usable: Optional[float]        # may be negative
    effective: Optional[float]     # may be negative (over-capacity alert)
    assignable: float              # max(0, effective); 0 if unknown
    over_capacity: bool

    def to_dict(self) -> dict:
        return asdict(self)


def load_params(path: Union[str, Path, None] = None) -> CapacityParams:
    path = Path(path) if path else PARAMS_PATH
    if not path.exists():
        return CapacityParams()
    import yaml

    data = (yaml.safe_load(path.read_text(encoding="utf-8")) or {}).get("capacity", {})
    unknown = set(data) - {"operational_factor", "safety_factors"}
    if unknown:
        raise ValueError(f"Unknown capacity param(s) in {path}: {sorted(unknown)}")
    factors = _default_safety_factors()
    factors.update(data.get("safety_factors", {}))
    return CapacityParams(float(data.get("operational_factor", 1.0)), factors)


def safety_status(zone_color) -> str:
    """Zone colour (ZoneColor, str or None) -> SAFE/CAUTION/UNSAFE/UNVERIFIED."""
    if zone_color is None:
        return "UNVERIFIED"
    return _STATUS_BY_COLOR.get(str(getattr(zone_color, "value", zone_color)).upper(), "UNVERIFIED")


def compute_shelter_capacity(
    shelter,
    zone_color,
    *,
    occupancy: float = 0.0,
    reserved: float = 0.0,
    operational_factor: Optional[float] = None,
    params: Optional[CapacityParams] = None,
) -> ShelterCapacity:
    p = params or CapacityParams()
    op = p.operational_factor if operational_factor is None else operational_factor
    status = safety_status(zone_color)
    sf = p.safety_factors.get(status, 0.0)
    nominal = shelter.nominal_capacity

    base = dict(
        shelter_id=shelter.shelter_id, zone_id=shelter.zone_id, name=shelter.name,
        lat=shelter.lat, lon=shelter.lon, osm_tag=getattr(shelter, "osm_tag", None),
        capacity_source=shelter.capacity_source, safety_status=status, safety_factor=sf,
        occupancy=occupancy, reserved=reserved,
    )
    if nominal is None:
        return ShelterCapacity(**base, capacity_known=False, nominal=None, usable=None,
                               effective=None, assignable=0.0, over_capacity=False)

    usable = nominal - occupancy - reserved
    effective = usable * op * sf
    return ShelterCapacity(**base, capacity_known=True, nominal=nominal, usable=usable,
                           effective=effective, assignable=max(0.0, effective),
                           over_capacity=usable < 0)


def compute_zone_capacities(
    shelters: Iterable,
    zone_color,
    *,
    occupancy_by_id: Optional[dict] = None,
    reserved_by_id: Optional[dict] = None,
    params: Optional[CapacityParams] = None,
) -> list[ShelterCapacity]:
    occ, res = occupancy_by_id or {}, reserved_by_id or {}
    return [
        compute_shelter_capacity(s, zone_color, occupancy=occ.get(s.shelter_id, 0.0),
                                 reserved=res.get(s.shelter_id, 0.0), params=params)
        for s in shelters
    ]


def zone_capacity_summary(caps: list[ShelterCapacity]) -> dict:
    return {
        "shelters_total": len(caps),
        "shelters_safe": sum(c.safety_status == "SAFE" for c in caps),
        "shelters_capacity_unknown": sum(not c.capacity_known for c in caps),
        "shelters_over_capacity": sum(c.over_capacity for c in caps),
        "total_assignable": sum(c.assignable for c in caps),
    }


def capacity_gap(demand: Optional[int], caps: list[ShelterCapacity]) -> dict:
    """AGGREGATE check only (no distances, no per-shelter assignment)."""
    assignable = sum(c.assignable for c in caps)
    if demand is None:
        return {"demand": None, "assignable": assignable, "unserved": None, "coverage": None}
    unserved = max(0.0, demand - assignable)
    coverage = 1.0 if demand == 0 else min(1.0, assignable / demand)
    return {"demand": demand, "assignable": assignable, "unserved": unserved, "coverage": coverage}


def map_safe_shelters(caps: list[ShelterCapacity]) -> list[dict]:
    """What the PUBLIC MAP gets: SAFE shelters only, location + type, NO numbers.
    Population, demand and capacity figures belong to the authority dashboard."""
    return [
        {"shelter_id": c.shelter_id, "name": c.name, "lat": c.lat, "lon": c.lon, "osm_tag": c.osm_tag}
        for c in caps if c.safety_status == "SAFE"
    ]