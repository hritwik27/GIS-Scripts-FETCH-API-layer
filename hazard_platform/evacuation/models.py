"""
evacuation/models.py -- core data models for the evacuation engine.

Per FINAL doc §13 module layout. Centralizes dataclasses for:
- Demand, Capacity, Routing, Assignment, and Zone Plans
- TRAPPED / INACCESSIBLE first-class evacuation state (FINAL doc §7)
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional


class AssignmentStatus(str, Enum):
    NO_EVACUATION_NEEDED = "NO_EVACUATION_NEEDED"
    FULLY_SERVED = "FULLY_SERVED"
    CAPACITY_DEFICIT = "CAPACITY_DEFICIT"
    TRAPPED = "TRAPPED"  # First-class state per FINAL doc §7


class EscalationLevel(str, Enum):
    NONE = "NONE"
    EXTERNAL_STAGING_REQUIRED = "EXTERNAL_STAGING_REQUIRED"
    NDRF_AERIAL_RESCUE_REQUIRED = "NDRF_AERIAL_RESCUE_REQUIRED"  # Triggered when TRAPPED


@dataclass
class ShelterAssignment:
    shelter_id: str
    shelter_name: Optional[str]
    lat: float
    lon: float
    assigned_evacuees: int
    distance_km: float
    travel_time_hours: float
    route_cost: float
    safety_status: str
    capacity_nominal: Optional[float]
    capacity_assignable: float
    capacity_remaining: float
    route_accessibility: float = 1.0
    bottleneck_edge: Optional[str] = None
    bottleneck_reason: Optional[str] = None
    route_nodes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)



@dataclass
class ZoneAssignmentResult:
    zone_id: str
    demand: Optional[int]
    total_assigned: int
    unserved: int
    trapped: bool
    status: AssignmentStatus
    escalation: EscalationLevel
    coverage_ratio: float
    assignments: list[ShelterAssignment] = field(default_factory=list)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["status"] = self.status.value
        d["escalation"] = self.escalation.value
        d["assignments"] = [a.to_dict() if hasattr(a, "to_dict") else a for a in self.assignments]
        return d


@dataclass
class RoadNode:
    node_id: str
    lat: float
    lon: float
    elevation_m: Optional[float] = None

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class RoadEdge:
    edge_id: str
    u: str
    v: str
    length_m: float
    road_type: str = "primary"
    base_speed_kmh: float = 40.0
    is_closed: bool = False
    closure_reason: Optional[str] = None

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class EdgeCondition:
    water_depth_m: float = 0.0
    water_velocity_mps: float = 0.0
    landslide_risk: float = 0.0
    rainfall_72h_mm: float = 0.0
    road_quality: float = 1.0
    debris_factor: float = 0.0

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class ImpassabilityResult:
    edge_id: str
    impassability: float         # I_e in [0, 1]
    passability: float           # 1 - I_e in [0, 1]
    effective_speed_kmh: float
    is_closed: bool
    closure_reason: Optional[str] = None

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class RouteAccessibilityResult:
    route_impassability: float   # I_route = Σ(L_e · I_e) / ΣL_e
    route_accessibility: float   # A_route = 1 - I_route
    min_passability: float       # min(Passability_e)
    final_accessibility: float   # A_final = A_route × min(Passability_e)
    bottleneck_edge_id: Optional[str] = None
    bottleneck_reason: Optional[str] = None

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class RouteResult:
    found: bool
    path_nodes: list[str] = field(default_factory=list)
    edge_ids: list[str] = field(default_factory=list)
    total_distance_km: float = 0.0
    total_time_hours: float = 0.0
    total_cost: float = float("inf")
    accessibility: float = 0.0
    bottleneck_edge_id: Optional[str] = None
    bottleneck_reason: Optional[str] = None

    def to_dict(self) -> dict:
        return asdict(self)

