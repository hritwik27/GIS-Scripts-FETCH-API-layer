"""models.py -- Core domain data structures for the Capacity & Evacuation Engine.
Strictly decoupled, pure dataclasses with serialization support.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, List, Optional


class AssignmentStatus(str, Enum):
    NO_EVACUATION_NEEDED = "NO_EVACUATION_NEEDED"
    FULLY_SERVED = "FULLY_SERVED"
    CAPACITY_DEFICIT = "CAPACITY_DEFICIT"
    TRAPPED = "TRAPPED"
    UNASSIGNED = "UNASSIGNED"


class EscalationLevel(str, Enum):
    NONE = "NONE"
    EXTERNAL_STAGING_REQUIRED = "EXTERNAL_STAGING_REQUIRED"
    NDRF_AERIAL_RESCUE_REQUIRED = "NDRF_AERIAL_RESCUE_REQUIRED"


@dataclass
class ShelterCapacity:
    """Represents a shelter's calculated effective and assignable capacity.
    Reflects Sphere standard floor areas, current occupancies, reservations,
    and hazard safety derating.
    """
    shelter_id: str
    zone_id: str
    name: Optional[str]
    lat: float
    lon: float
    osm_tag: Optional[str] = None
    capacity_source: str = "footprint_estimate"  # osm_tag | footprint_estimate | authority_fallback | manual
    safety_status: str = "SAFE"                 # SAFE (1.0) | CAUTION (0.5) | UNSAFE (0.0) | UNVERIFIED (0.0)
    safety_factor: float = 1.0
    capacity_known: bool = True
    nominal: Optional[float] = None
    occupancy: float = 0.0
    reserved: float = 0.0
    usable: Optional[float] = None              # nominal - occupancy - reserved (can be negative)
    effective: Optional[float] = None           # usable * operational_factor * safety_factor
    assignable: float = 0.0                     # max(0, effective); 0 if unknown
    over_capacity: bool = False                 # True if usable < 0

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class DemandResult:
    """Calculated evacuation demand for a geographic zone based on population,
    hazard intensity, and socioeconomic vulnerability.
    """
    zone_id: str
    status: str                                 # "ok" | "no_evacuation" | "no_population_data"
    population: Optional[float]
    exposed_fraction: float
    hazard_factor: float
    vulnerability: float
    mobility: float
    demand: Optional[int]                       # integer evacuees required to move
    capped: bool                                # True if H*V*M was clamped to 1.0 (never move > population)
    vulnerability_is_placeholder: bool

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class ShelterAssignment:
    """Specific assignment of evacuees to an identified target shelter."""
    shelter_id: str
    shelter_name: str
    assigned_evacuees: int
    shelter_lat: float
    shelter_lon: float
    distance_km: float
    transit_time_hours: float
    route_cost: float
    safety_status: str
    effective_capacity: float
    remaining_capacity: float
    accessibility_score: float = 1.0
    route_nodes: List[str] = field(default_factory=list)
    bottleneck_edge_id: Optional[str] = None

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class ZoneAssignmentResult:
    """Comprehensive assignment summary for an evacuation zone."""
    zone_id: str
    demand: int
    total_assigned: int
    unserved: int
    status: AssignmentStatus
    assignments: List[ShelterAssignment] = field(default_factory=list)
    trapped: bool = False
    escalation: EscalationLevel = EscalationLevel.NONE

    def to_dict(self) -> dict:
        return {
            "zone_id": self.zone_id,
            "demand": self.demand,
            "total_assigned": self.total_assigned,
            "unserved": self.unserved,
            "status": self.status.value,
            "assignments": [a.to_dict() for a in self.assignments],
            "trapped": self.trapped,
            "escalation": self.escalation.value,
        }
