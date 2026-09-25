"""Capacity & Evacuation Demand Engine
=======================================
A standalone, zero-dependency mathematical engine for:
1. Vulnerability-adjusted evacuation demand estimation.
2. Effective shelter capacity calculation with Sphere standards & safety derating.
3. Capacity-constrained shelter assignment with corridor travel-time optimization.
4. Automatic detection of CAPACITY_DEFICIT and TRAPPED population states.

Designed for easy integration with Hazard ML models and geospatial data pipelines.
"""

from .models import (
    AssignmentStatus,
    EscalationLevel,
    ShelterCapacity,
    DemandResult,
    ShelterAssignment,
    ZoneAssignmentResult,
)
from .capacity import (
    CapacityParams,
    compute_shelter_capacity,
    compute_zone_capacities,
    zone_capacity_summary,
    capacity_gap,
    map_safe_shelters,
    safety_status,
)
from .demand import (
    DemandParams,
    compute_demand,
    calculate_vulnerability,
)
from .assignment import (
    AssignmentParams,
    assign_zone,
    haversine_distance_km,
    route_cost,
)

__all__ = [
    "AssignmentStatus",
    "EscalationLevel",
    "ShelterCapacity",
    "DemandResult",
    "ShelterAssignment",
    "ZoneAssignmentResult",
    "CapacityParams",
    "compute_shelter_capacity",
    "compute_zone_capacities",
    "zone_capacity_summary",
    "capacity_gap",
    "map_safe_shelters",
    "safety_status",
    "DemandParams",
    "compute_demand",
    "calculate_vulnerability",
    "AssignmentParams",
    "assign_zone",
    "haversine_distance_km",
    "route_cost",
]
