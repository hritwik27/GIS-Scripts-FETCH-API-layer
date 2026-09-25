"""assignment.py -- Capacity-constrained evacuation shelter assignment and deficit escalation.

Mathematical formulation (Section 8 of Evacuation & Shelter Architecture):
    W_ij = (A_ij x S_j) / max(T_ij, eps)
    P_ij = W_ij / sum_k W_ik
    x_ij = min(C_j, round(E_i x P_ij))

Where:
    A_ij = Accessibility score of the evacuation corridor (0.0 to 1.0)
    S_j  = Safety factor of the shelter (1.0 for SAFE, 0.5 for CAUTION)
    T_ij = Transit travel time in hours (distance x detour / speed)
    C_j  = Remaining assignable capacity of shelter j
    E_i  = Total evacuation demand of zone i

First-Class Trapped & Deficit Escalations:
- If demand > 0 but sum(C_j) == 0 (no safe shelters within max_distance_km or all full):
  Zone is flagged TRAPPED, escalating to EscalationLevel.NDRF_AERIAL_RESCUE_REQUIRED.
- If demand > sum(C_j):
  Zone status is CAPACITY_DEFICIT, escalating to EscalationLevel.EXTERNAL_STAGING_REQUIRED.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, fields
from pathlib import Path
from typing import Any, Iterable, List, Optional, Tuple, Union

from .models import (
    AssignmentStatus,
    EscalationLevel,
    ShelterAssignment,
    ShelterCapacity,
    ZoneAssignmentResult,
)

CONFIG_PATH = Path(__file__).with_name("config.yaml")


@dataclass(frozen=True)
class AssignmentParams:
    detour_factor: float = 1.4         # Winding road multiplier over great-circle line
    speed_kmh: float = 25.0            # Average evacuation convoy speed in km/h
    max_distance_km: float = 50.0      # Maximum viable relocation radius
    alpha: float = 1.0                 # Cost weight: travel time
    beta: float = 0.5                  # Cost weight: road impassability
    gamma: float = 0.5                 # Cost weight: hazard risk
    epsilon_hours: float = 0.05        # 3 minutes minimum time threshold


def load_params(path: Union[str, Path, None] = None) -> AssignmentParams:
    """Load assignment parameters from YAML or fallback to defaults."""
    cfg_file = Path(path) if path else CONFIG_PATH
    if not cfg_file.exists():
        return AssignmentParams()
    try:
        import yaml
        data = (yaml.safe_load(cfg_file.read_text(encoding="utf-8")) or {}).get("assignment", {})
        valid = {f.name for f in fields(AssignmentParams)}
        filtered = {k: float(v) for k, v in data.items() if k in valid}
        return AssignmentParams(**filtered)
    except Exception:
        return AssignmentParams()


def haversine_distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance between two geographic coordinates in kilometers."""
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
) -> Tuple[float, float, float]:
    """Calculate (total_cost, distance_km, transit_time_hours) for an evacuation route."""
    p = params or AssignmentParams()
    straight_line_km = haversine_distance_km(origin_lat, origin_lon, shelter_lat, shelter_lon)
    dist_km = straight_line_km * p.detour_factor
    time_hrs = dist_km / max(1.0, p.speed_kmh)

    cost = p.alpha * time_hrs + p.beta * impassability + p.gamma * risk
    return cost, dist_km, time_hrs


def assign_zone(
    zone_id: str,
    origin_lat: float,
    origin_lon: float,
    demand: int,
    candidate_shelters: Iterable[ShelterCapacity],
    *,
    params: Optional[AssignmentParams] = None,
    hazard_score: float = 0.0,
) -> ZoneAssignmentResult:
    """Assign zone evacuees to safe candidate shelters respecting capacity limits."""
    p = params or AssignmentParams()

    if demand <= 0:
        return ZoneAssignmentResult(
            zone_id=zone_id,
            demand=0,
            total_assigned=0,
            unserved=0,
            status=AssignmentStatus.NO_EVACUATION_NEEDED,
            assignments=[],
            trapped=False,
            escalation=EscalationLevel.NONE,
        )

    # Filter candidate shelters: must have assignable capacity > 0 and be SAFE or CAUTION
    eligible = []
    for s in candidate_shelters:
        if s.assignable <= 0:
            continue
        if s.safety_status not in ("SAFE", "CAUTION"):
            continue

        cost, dist_km, time_hrs = route_cost(
            origin_lat, origin_lon, s.lat, s.lon,
            params=p, risk=hazard_score
        )
        if dist_km > p.max_distance_km:
            continue

        # Effective attractiveness weight: W_ij = (A_ij * S_j) / max(T_ij, eps)
        accessibility = 1.0  # Default corridor passability in standalone engine
        weight = (accessibility * s.safety_factor) / max(time_hrs, p.epsilon_hours)

        eligible.append({
            "shelter": s,
            "dist_km": dist_km,
            "time_hrs": time_hrs,
            "cost": cost,
            "weight": weight,
            "accessibility": accessibility,
        })

    # If no eligible shelters exist, population is TRAPPED
    if not eligible:
        return ZoneAssignmentResult(
            zone_id=zone_id,
            demand=demand,
            total_assigned=0,
            unserved=demand,
            status=AssignmentStatus.TRAPPED,
            assignments=[],
            trapped=True,
            escalation=EscalationLevel.NDRF_AERIAL_RESCUE_REQUIRED,
        )

    # Sort candidates by weight descending (most attractive first)
    eligible.sort(key=lambda item: item["weight"], reverse=True)

    total_weight = sum(item["weight"] for item in eligible)
    remaining_demand = demand
    assignments: List[ShelterAssignment] = []
    assigned_total = 0

    # Pass 1: Proportional gravity assignment
    provisional_allocations = []
    for item in eligible:
        s = item["shelter"]
        p_ij = item["weight"] / total_weight if total_weight > 0 else (1.0 / len(eligible))
        target_allocation = int(round(demand * p_ij))
        allocated = min(int(s.assignable), target_allocation)
        provisional_allocations.append(allocated)

    # Pass 2: Greedy fill to satisfy remaining demand up to capacity limits
    sum_prov = sum(provisional_allocations)
    diff = demand - sum_prov

    for idx, item in enumerate(eligible):
        s = item["shelter"]
        cap_int = int(s.assignable)
        current = provisional_allocations[idx]
        if diff > 0 and current < cap_int:
            add_amount = min(diff, cap_int - current)
            provisional_allocations[idx] += add_amount
            diff -= add_amount
        elif diff < 0 and current > 0:
            sub_amount = min(abs(diff), current)
            provisional_allocations[idx] -= sub_amount
            diff += sub_amount

    # Build assignment objects
    for idx, item in enumerate(eligible):
        allocated = provisional_allocations[idx]
        if allocated <= 0:
            continue

        s = item["shelter"]
        assigned_total += allocated
        rem_cap = max(0.0, s.assignable - allocated)

        assignments.append(
            ShelterAssignment(
                shelter_id=s.shelter_id,
                shelter_name=s.name or f"Shelter {s.shelter_id}",
                assigned_evacuees=allocated,
                shelter_lat=s.lat,
                shelter_lon=s.lon,
                distance_km=round(item["dist_km"], 2),
                transit_time_hours=round(item["time_hrs"], 2),
                route_cost=round(item["cost"], 2),
                safety_status=s.safety_status,
                effective_capacity=s.effective or 0.0,
                remaining_capacity=rem_cap,
                accessibility_score=item["accessibility"],
            )
        )

    unserved = max(0, demand - assigned_total)

    if unserved > 0:
        status = AssignmentStatus.CAPACITY_DEFICIT
        escalation = EscalationLevel.EXTERNAL_STAGING_REQUIRED
    else:
        status = AssignmentStatus.FULLY_SERVED
        escalation = EscalationLevel.NONE

    return ZoneAssignmentResult(
        zone_id=zone_id,
        demand=demand,
        total_assigned=assigned_total,
        unserved=unserved,
        status=status,
        assignments=assignments,
        trapped=False,
        escalation=escalation,
    )
