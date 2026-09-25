"""capacity.py -- Shelter effective capacity calculation and safety derating.

Mathematical formulation (Section 5 of Evacuation & Shelter Architecture):
    Usable_j    = Nominal_j - Occupancy_j - Reserved_j
    Effective_j = Usable_j x OperationalFactor_j x SafetyFactor_j

Key Engineering Safeguards:
1. NO artificial floor: The PDF's buggy max(100, ...) floor is eliminated. Usable and
   Effective capacities can reach 0 or negative numbers (flagged as over-capacity alerts).
2. Assignable Capacity: assignable = max(0, effective), 0 if unknown.
3. Safety Check: Shelters physically located inside RED zones are flagged UNSAFE with a
   SafetyFactor of 0.0. Shelters in YELLOW zones receive 0.5 (CAUTION), and GREEN receive 1.0 (SAFE).
4. Strict Provenance: Unknown nominal capacity is NEVER guessed or fabricated.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Union

from .models import ShelterCapacity

CONFIG_PATH = Path(__file__).with_name("config.yaml")

_STATUS_BY_COLOR = {
    "GREEN": "SAFE",
    "YELLOW": "CAUTION",
    "RED": "UNSAFE",
}


def _default_safety_factors() -> dict:
    return {"SAFE": 1.0, "CAUTION": 0.5, "UNSAFE": 0.0, "UNVERIFIED": 0.0}


@dataclass(frozen=True)
class CapacityParams:
    operational_factor: float = 1.0
    sq_m_per_person: float = 3.5
    safety_factors: dict = field(default_factory=_default_safety_factors)


def load_params(path: Union[str, Path, None] = None) -> CapacityParams:
    """Load capacity parameters from YAML or fallback to defaults."""
    cfg_file = Path(path) if path else CONFIG_PATH
    if not cfg_file.exists():
        return CapacityParams()
    try:
        import yaml
        data = (yaml.safe_load(cfg_file.read_text(encoding="utf-8")) or {}).get("capacity", {})
        factors = _default_safety_factors()
        factors.update(data.get("safety_factors", {}))
        return CapacityParams(
            operational_factor=float(data.get("operational_factor", 1.0)),
            sq_m_per_person=float(data.get("sq_m_per_person", 3.5)),
            safety_factors=factors,
        )
    except Exception:
        return CapacityParams()


def safety_status(zone_color: Any) -> str:
    """Determine shelter safety status (SAFE / CAUTION / UNSAFE / UNVERIFIED)
    based on the zone classification color.
    """
    if zone_color is None:
        return "UNVERIFIED"
    val = getattr(zone_color, "value", zone_color)
    return _STATUS_BY_COLOR.get(str(val).upper(), "UNVERIFIED")


def compute_shelter_capacity(
    shelter: Any,
    zone_color: Any,
    *,
    occupancy: float = 0.0,
    reserved: float = 0.0,
    operational_factor: Optional[float] = None,
    params: Optional[CapacityParams] = None,
) -> ShelterCapacity:
    """Compute effective assignable capacity for a single shelter.
    `shelter` can be any object or dict with: shelter_id, zone_id, name, lat, lon, nominal_capacity.
    """
    p = params or CapacityParams()
    op = p.operational_factor if operational_factor is None else operational_factor
    status = safety_status(zone_color)
    sf = p.safety_factors.get(status, 0.0)

    # Extract attributes safely from dict or object
    sid = getattr(shelter, "shelter_id", None) or (shelter.get("shelter_id") if isinstance(shelter, dict) else str(shelter))
    zid = getattr(shelter, "zone_id", "UNKNOWN") if not isinstance(shelter, dict) else shelter.get("zone_id", "UNKNOWN")
    name = getattr(shelter, "name", None) if not isinstance(shelter, dict) else shelter.get("name")
    lat = float(getattr(shelter, "lat", 0.0) if not isinstance(shelter, dict) else shelter.get("lat", 0.0))
    lon = float(getattr(shelter, "lon", 0.0) if not isinstance(shelter, dict) else shelter.get("lon", 0.0))
    nominal = getattr(shelter, "nominal_capacity", None) if not isinstance(shelter, dict) else shelter.get("nominal_capacity")
    tag = getattr(shelter, "osm_tag", None) if not isinstance(shelter, dict) else shelter.get("osm_tag")
    source = getattr(shelter, "capacity_source", "unknown") if not isinstance(shelter, dict) else shelter.get("capacity_source", "unknown")

    # If nominal is None but area is present, calculate using Sphere standard
    footprint = getattr(shelter, "footprint_m2", None) if not isinstance(shelter, dict) else shelter.get("footprint_m2")
    if nominal is None and footprint is not None and footprint > 0:
        nominal = int(footprint // p.sq_m_per_person)
        source = "footprint_estimate"

    base_args = dict(
        shelter_id=sid,
        zone_id=zid,
        name=name,
        lat=lat,
        lon=lon,
        osm_tag=tag,
        capacity_source=source,
        safety_status=status,
        safety_factor=sf,
        occupancy=occupancy,
        reserved=reserved,
    )

    if nominal is None:
        return ShelterCapacity(
            **base_args,
            capacity_known=False,
            nominal=None,
            usable=None,
            effective=None,
            assignable=0.0,
            over_capacity=False,
        )

    nominal = float(nominal)
    usable = nominal - occupancy - reserved
    effective = usable * op * sf
    assignable = max(0.0, effective)
    over_capacity = usable < 0

    return ShelterCapacity(
        **base_args,
        capacity_known=True,
        nominal=nominal,
        usable=usable,
        effective=effective,
        assignable=assignable,
        over_capacity=over_capacity,
    )


def compute_zone_capacities(
    shelters: Iterable[Any],
    zone_color: Any,
    *,
    occupancy_by_id: Optional[Dict[str, float]] = None,
    reserved_by_id: Optional[Dict[str, float]] = None,
    params: Optional[CapacityParams] = None,
) -> List[ShelterCapacity]:
    """Compute capacity metrics for a collection of shelters located in or around a zone."""
    occ = occupancy_by_id or {}
    res = reserved_by_id or {}
    results = []
    for s in shelters:
        sid = getattr(s, "shelter_id", None) or (s.get("shelter_id") if isinstance(s, dict) else str(s))
        cap = compute_shelter_capacity(
            s,
            zone_color,
            occupancy=occ.get(sid, 0.0),
            reserved=res.get(sid, 0.0),
            params=params,
        )
        results.append(cap)
    return results


def zone_capacity_summary(caps: List[ShelterCapacity]) -> dict:
    """Aggregate statistics for all evaluated shelters in a zone."""
    return {
        "shelters_total": len(caps),
        "shelters_safe": sum(c.safety_status == "SAFE" for c in caps),
        "shelters_caution": sum(c.safety_status == "CAUTION" for c in caps),
        "shelters_unsafe": sum(c.safety_status == "UNSAFE" for c in caps),
        "shelters_capacity_unknown": sum(not c.capacity_known for c in caps),
        "shelters_over_capacity": sum(c.over_capacity for c in caps),
        "total_nominal": sum(c.nominal or 0.0 for c in caps if c.capacity_known),
        "total_effective": sum(c.effective or 0.0 for c in caps if c.effective is not None),
        "total_assignable": sum(c.assignable for c in caps),
    }


def capacity_gap(demand: Optional[int], caps: List[ShelterCapacity]) -> dict:
    """Evaluate aggregate deficit between evacuation demand and available assignable capacity."""
    summary = zone_capacity_summary(caps)
    total_assignable = summary["total_assignable"]

    if demand is None:
        return {
            "demand": None,
            "total_assignable": total_assignable,
            "unserved": None,
            "surplus": None,
            "coverage": None,
            "has_deficit": False,
        }

    deficit = max(0.0, float(demand) - total_assignable)
    surplus = max(0.0, total_assignable - float(demand))
    coverage = (total_assignable / demand) if demand > 0 else 1.0

    return {
        "demand": demand,
        "total_assignable": total_assignable,
        "unserved": int(round(deficit)),
        "surplus": int(round(surplus)),
        "coverage": min(1.0, coverage),
        "has_deficit": deficit > 0,
    }


def map_safe_shelters(caps: List[ShelterCapacity]) -> List[dict]:
    """Sanitized public shelter list: returns location and facility details for SAFE and CAUTION
    shelters only, intentionally hiding operational capacity numbers to prevent panic.
    """
    safe_list = []
    for c in caps:
        if c.safety_status in ("SAFE", "CAUTION"):
            safe_list.append({
                "shelter_id": c.shelter_id,
                "name": c.name or f"Shelter {c.shelter_id}",
                "lat": c.lat,
                "lon": c.lon,
                "osm_tag": c.osm_tag,
                "safety_status": c.safety_status,
            })
    return safe_list
