"""
evacuation/assignment.py -- capacity-constrained shelter assignment (FINAL doc §7, §8).

    W_ij = (A_ij x S_j) / max(T_ij, eps)
    P_ij = W_ij / sum_k W_ik
    x_ij = min(C_j, round(E_i x P_ij))

v1 implementation:
- Straight-line distance x detour_factor stub for route_cost() (swapped for real routing in step 4).
- Detects TRAPPED / INACCESSIBLE state as a first-class citizen:
  If a zone has demand E_i > 0, but no accessible safe shelter with capacity exists
  (e.g., all local shelters are inside a RED zone / UNSAFE, or beyond max_distance_km,
  or already full), the zone is flagged TRAPPED and escalates to NDRF_AERIAL_RESCUE_REQUIRED.
- Pure functions, deterministic, no I/O in assign_zone(): safe for background planner jobs.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, fields
from pathlib import Path
from typing import Iterable, Optional, Union

from evacuation.capacity import ShelterCapacity
from evacuation.models import (
    AssignmentStatus,
    EscalationLevel,
    ShelterAssignment,
    ZoneAssignmentResult,
)

PARAMS_PATH = Path(__file__).with_name("evacuation_params.yaml")


@dataclass(frozen=True)
class AssignmentParams:
    detour_factor: float = 1.4         # Road detour multiplier over straight line
    speed_kmh: float = 25.0            # Evacuation transit speed in km/h
    max_distance_km: float = 50.0      # Maximum viable relocation radius
    alpha: float = 1.0                 # Cost weight: travel time
    beta: float = 0.5                  # Cost weight: road impassability
    gamma: float = 0.5                 # Cost weight: hazard risk
    epsilon_hours: float = 0.05        # 3 minutes min time to avoid division by zero


def load_params(path: Union[str, Path, None] = None) -> AssignmentParams:
    """Read the `assignment:` section from YAML, returning defaults if absent."""
    path = Path(path) if path else PARAMS_PATH
    if not path.exists():
        return AssignmentParams()
    import yaml

    data = (yaml.safe_load(path.read_text(encoding="utf-8")) or {}).get("assignment", {})
    valid_fields = {f.name for f in fields(AssignmentParams)}
    unknown = set(data) - valid_fields
    if unknown:
        raise ValueError(f"Unknown assignment param(s) in {path}: {sorted(unknown)}")
    return AssignmentParams(**data)


def haversine_distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance between two points in kilometers."""
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)

    a = math.sin(delta_phi / 2.0) ** 2 + (
        math.cos(phi1) * math.cos(phi2) * (math.sin(delta_lambda / 2.0) ** 2)
    )
    c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))
    return 6371.0 * c


def route_cost(
    origin_lat: float,
    origin_lon: float,
    shelter_lat: float,
    shelter_lon: float,
    *,
    params: Optional[AssignmentParams] = None,
    impassability: float = 0.0,
    risk: float = 0.0,
    graph: Optional[Any] = None,
) -> tuple[float, float, float]:
    """
    Computes evacuation route cost.
    If a RoadNetworkGraph is supplied, uses Dijkstra routing across the graph
    taking edge closures and impassabilities into account (FINAL doc §7).
    Otherwise, uses the straight-line x detour factor fallback stub.

    Returns:
        (route_cost, estimated_road_distance_km, travel_time_hours)
    """
    p = params or AssignmentParams()

    if graph is not None:
        from evacuation.routing import RoutingParams, route_between_points
        r_params = RoutingParams(alpha=p.alpha, beta=p.beta, gamma=p.gamma)
        route_res = route_between_points(
            graph, origin_lat, origin_lon, shelter_lat, shelter_lon,
            hazard_score=risk, params=r_params
        )
        if route_res.found:
            return route_res.total_cost, route_res.total_distance_km, route_res.total_time_hours
        else:
            return float("inf"), float("inf"), float("inf")

    straight_line_km = haversine_distance_km(origin_lat, origin_lon, shelter_lat, shelter_lon)
    distance_km = straight_line_km * p.detour_factor
    speed = max(1.0, p.speed_kmh)
    travel_time_hours = distance_km / speed

    cost = (p.alpha * travel_time_hours) + (p.beta * impassability) + (p.gamma * risk)
    return cost, distance_km, travel_time_hours


def assign_zone(
    zone_id: str,
    origin_lat: float,
    origin_lon: float,
    demand: Optional[int],
    shelters: Iterable[ShelterCapacity],
    *,
    params: Optional[AssignmentParams] = None,
    graph: Optional[Any] = None,
    hazard_score: float = 0.0,
) -> ZoneAssignmentResult:
    """
    Assign evacuees from a zone to shelters based on capacity, accessibility, and distance.
    Enforces capacity constraints and surfaces TRAPPED state (FINAL doc §7, §8).
    """
    p = params or AssignmentParams()

    if demand is None or demand <= 0:
        return ZoneAssignmentResult(
            zone_id=zone_id,
            demand=demand,
            total_assigned=0,
            unserved=0,
            trapped=False,
            status=AssignmentStatus.NO_EVACUATION_NEEDED,
            escalation=EscalationLevel.NONE,
            coverage_ratio=1.0,
            assignments=[],
        )

    # 1. Filter candidate shelters & calculate route accessibility + attraction weight W_ij
    candidates: list[dict] = []
    for s in shelters:
        # Check safety: UNSAFE or UNVERIFIED shelters are unusable (FINAL doc §5)
        if s.safety_factor <= 0.0 or s.assignable <= 0.0:
            continue

        route_acc = 1.0
        bottleneck_edge = None
        bottleneck_reason = None
        route_nodes = []

        if graph is not None:
            from evacuation.routing import RoutingParams, route_between_points
            r_params = RoutingParams(alpha=p.alpha, beta=p.beta, gamma=p.gamma)
            route_res = route_between_points(
                graph, origin_lat, origin_lon, s.lat, s.lon,
                hazard_score=hazard_score, params=r_params
            )
            if not route_res.found or math.isinf(route_res.total_cost):
                continue  # Shelter is unreachable due to closed/flooded roads
            cost = route_res.total_cost
            dist_km = route_res.total_distance_km
            time_hrs = route_res.total_time_hours
            route_acc = route_res.accessibility
            bottleneck_edge = route_res.bottleneck_edge_id
            bottleneck_reason = route_res.bottleneck_reason
            route_nodes = route_res.path_nodes
        else:
            cost, dist_km, time_hrs = route_cost(
                origin_lat, origin_lon, s.lat, s.lon, params=p, risk=hazard_score
            )

        # Distance reachability check
        if dist_km > p.max_distance_km:
            continue

        # Accessibility A_ij = route_accessibility * shelter.safety_factor
        a_ij = route_acc * s.safety_factor
        eff_time = max(time_hrs, p.epsilon_hours)
        weight = (a_ij * s.safety_factor) / eff_time

        if weight > 0.0:
            candidates.append({
                "shelter": s,
                "weight": weight,
                "cost": cost,
                "distance_km": dist_km,
                "travel_time_hours": time_hrs,
                "assignable": s.assignable,
                "route_accessibility": route_acc,
                "bottleneck_edge": bottleneck_edge,
                "bottleneck_reason": bottleneck_reason,
                "route_nodes": route_nodes,
            })


    # 2. If no reachable safe shelters with assignable capacity exist -> TRAPPED
    if not candidates:
        return ZoneAssignmentResult(
            zone_id=zone_id,
            demand=demand,
            total_assigned=0,
            unserved=demand,
            trapped=True,
            status=AssignmentStatus.TRAPPED,
            escalation=EscalationLevel.NDRF_AERIAL_RESCUE_REQUIRED,
            coverage_ratio=0.0,
            assignments=[],
        )

    # 3. Capacity-aware allocation heuristic (FINAL doc §8)
    total_weight = sum(c["weight"] for c in candidates)
    remaining_demand = demand
    assignments_list: list[ShelterAssignment] = []

    # Proportional initial assignment
    allocated_by_id: dict[str, int] = {}
    for c in candidates:
        s: ShelterCapacity = c["shelter"]
        p_ij = c["weight"] / total_weight
        target = min(int(c["assignable"]), int(round(demand * p_ij)))
        allocated_by_id[s.shelter_id] = target
        remaining_demand -= target

    # Greedy reallocation of any remaining unallocated demand to shelters with spare capacity
    if remaining_demand > 0:
        candidates_sorted = sorted(candidates, key=lambda c: c["weight"], reverse=True)
        for c in candidates_sorted:
            s = c["shelter"]
            spare = int(c["assignable"]) - allocated_by_id[s.shelter_id]
            if spare > 0:
                add = min(spare, remaining_demand)
                allocated_by_id[s.shelter_id] += add
                remaining_demand -= add
                if remaining_demand <= 0:
                    break

    # Build ShelterAssignment records
    total_assigned = 0
    for c in candidates:
        s = c["shelter"]
        num_assigned = allocated_by_id[s.shelter_id]
        if num_assigned > 0:
            total_assigned += num_assigned
            assignments_list.append(
                ShelterAssignment(
                    shelter_id=s.shelter_id,
                    shelter_name=s.name,
                    lat=s.lat,
                    lon=s.lon,
                    assigned_evacuees=num_assigned,
                    distance_km=round(c["distance_km"], 2),
                    travel_time_hours=round(c["travel_time_hours"], 3),
                    route_cost=round(c["cost"], 3),
                    safety_status=s.safety_status,
                    capacity_nominal=s.nominal,
                    capacity_assignable=s.assignable,
                    capacity_remaining=max(0.0, s.assignable - num_assigned),
                    route_accessibility=round(c.get("route_accessibility", 1.0), 3),
                    bottleneck_edge=c.get("bottleneck_edge"),
                    bottleneck_reason=c.get("bottleneck_reason"),
                    route_nodes=c.get("route_nodes", []),
                )
            )

    unserved = max(0, demand - total_assigned)
    coverage = min(1.0, total_assigned / demand) if demand > 0 else 1.0

    if total_assigned == 0:
        status = AssignmentStatus.TRAPPED
        escalation = EscalationLevel.NDRF_AERIAL_RESCUE_REQUIRED
        trapped = True
    elif unserved > 0:
        status = AssignmentStatus.CAPACITY_DEFICIT
        escalation = EscalationLevel.EXTERNAL_STAGING_REQUIRED
        trapped = False
    else:
        status = AssignmentStatus.FULLY_SERVED
        escalation = EscalationLevel.NONE
        trapped = False

    return ZoneAssignmentResult(
        zone_id=zone_id,
        demand=demand,
        total_assigned=total_assigned,
        unserved=unserved,
        trapped=trapped,
        status=status,
        escalation=escalation,
        coverage_ratio=coverage,
        assignments=assignments_list,
    )
