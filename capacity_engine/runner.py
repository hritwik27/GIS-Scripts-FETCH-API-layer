"""runner.py -- Interactive demonstration runner for Capacity & Evacuation Demand Engine.
Simulates 4 distinct operational scenarios driven by ML hazard predictions:

1. Scenario 1: GREEN Zone (Normal Conditions / Routine Monitoring)
2. Scenario 2: YELLOW Zone (Approaching Cyclonic Storm / Moderate Hazard)
3. Scenario 3: RED Zone (Severe Cyclone Surge / Capacity Deficit & External Staging)
4. Scenario 4: RED Zone (Corridor Inundation / Trapped Population & NDRF Aerial Escalation)

Usage:
    python runner.py
"""
from __future__ import annotations

import json
import sys
from dataclasses import asdict
from pathlib import Path
from typing import List

# Support running from within capacity_engine folder or from project root
pkg_dir = Path(__file__).resolve().parent
if str(pkg_dir.parent) not in sys.path:
    sys.path.insert(0, str(pkg_dir.parent))
if str(pkg_dir) not in sys.path:
    sys.path.insert(0, str(pkg_dir))

try:
    from capacity_engine import (
        AssignmentParams,
        AssignmentStatus,
        CapacityParams,
        DemandParams,
        EscalationLevel,
        ShelterCapacity,
        assign_zone,
        compute_demand,
        compute_shelter_capacity,
    )
except ImportError:
    from models import AssignmentStatus, EscalationLevel, ShelterCapacity
    from capacity import CapacityParams, compute_shelter_capacity
    from demand import DemandParams, compute_demand
    from assignment import AssignmentParams, assign_zone



def print_header(title: str) -> None:
    line = "=" * 70
    print(f"\n{line}")
    print(f"  {title.upper()}")
    print(f"{line}")


def print_scenario(scenario_num: int, title: str, description: str) -> None:
    print(f"\n[{scenario_num}] {title}")
    print(f"    Context: {description}")
    print("-" * 70)


def run_scenario_1() -> None:
    """Scenario 1: GREEN Zone - Normal conditions."""
    print_scenario(
        1,
        "GREEN Zone: Routine Baseline",
        "ML Model detects normal weather (Hazard=0.05). No evacuation required.",
    )

    zone_id = "ZONE-PURI-01"
    population = 15000
    ml_hazard_score = 0.05
    zone_color = "GREEN"

    # 1. Compute Demand
    demand_res = compute_demand(
        zone_id=zone_id,
        population=population,
        zone_color=zone_color,
        worst_hazard_score=ml_hazard_score,
    )
    print(f"  Zone ID:             {demand_res.zone_id}")
    print(f"  Population:          {demand_res.population:,}")
    print(f"  ML Hazard Score:     {demand_res.hazard_factor:.2f} ({zone_color})")
    print(f"  Evacuation Demand:   {demand_res.demand} evacuees (Status: {demand_res.status})")

    # 2. Shelters in zone
    shelters = [
        {"shelter_id": "S1", "name": "Town Hall", "lat": 19.81, "lon": 85.83, "nominal_capacity": 500},
        {"shelter_id": "S2", "name": "Govt High School", "lat": 19.82, "lon": 85.84, "nominal_capacity": 400},
    ]
    capacities = [compute_shelter_capacity(s, zone_color="GREEN") for s in shelters]

    # 3. Assignment
    res = assign_zone(
        zone_id=zone_id,
        origin_lat=19.81,
        origin_lon=85.83,
        demand=demand_res.demand or 0,
        candidate_shelters=capacities,
    )
    print(f"  Assignment Status:   {res.status.value}")
    print(f"  Escalation Required: {res.escalation.value}")


def run_scenario_2() -> None:
    """Scenario 2: YELLOW Zone - Approaching storm with 50% shelter derating."""
    print_scenario(
        2,
        "YELLOW Zone: Approaching Cyclone (Moderate Threat)",
        "ML Model predicts Hazard=0.48. High kutcha housing vulnerability. Shelters derated by 50%.",
    )

    zone_id = "ZONE-BALASORE-04"
    population = 8000
    ml_hazard_score = 0.48
    zone_color = "YELLOW"
    phi_kutcha = 0.45       # 45% kutcha / mud thatch homes
    phi_dependent = 0.30    # 30% elderly and children

    # 1. Compute Demand
    demand_res = compute_demand(
        zone_id=zone_id,
        population=population,
        zone_color=zone_color,
        worst_hazard_score=ml_hazard_score,
        phi_kutcha=phi_kutcha,
        phi_dependent=phi_dependent,
    )
    print(f"  Zone ID:             {demand_res.zone_id}")
    print(f"  Population:          {demand_res.population:,}")
    print(f"  ML Hazard Score:     {demand_res.hazard_factor:.2f} ({zone_color})")
    print(f"  Vulnerability Multiplier: {demand_res.vulnerability:.3f} (kutcha: {phi_kutcha*100:.0f}%, dep: {phi_dependent*100:.0f}%)")
    print(f"  Evacuation Demand:   {demand_res.demand:,} evacuees")

    # 2. Shelters (1 inside yellow zone derated 50%, 2 in adjacent safe green zone)
    raw_shelters = [
        {"shelter_id": "SH-LOCAL", "name": "Block Cyclone Shelter (Local)", "lat": 21.50, "lon": 86.92, "nominal_capacity": 1200, "zone_color": "YELLOW"},
        {"shelter_id": "SH-INLAND-1", "name": "District Sports Complex", "lat": 21.53, "lon": 86.85, "nominal_capacity": 2500, "zone_color": "GREEN"},
        {"shelter_id": "SH-INLAND-2", "name": "ITI College Campus", "lat": 21.55, "lon": 86.82, "nominal_capacity": 2000, "zone_color": "GREEN"},
    ]
    capacities: List[ShelterCapacity] = [
        compute_shelter_capacity(s, zone_color=s["zone_color"]) for s in raw_shelters
    ]

    print("\n  Candidate Shelters Evaluation:")
    for sc in capacities:
        print(f"   * {sc.shelter_id} ({sc.name}): Nominal={sc.nominal}, Safety={sc.safety_status} ({sc.safety_factor*100:.0f}%), Assignable={sc.assignable:.0f}")

    # 3. Assignment
    res = assign_zone(
        zone_id=zone_id,
        origin_lat=21.49,
        origin_lon=86.93,
        demand=demand_res.demand or 0,
        candidate_shelters=capacities,
    )
    print(f"\n  Assignment Summary:")
    print(f"  Demand:              {res.demand:,}")
    print(f"  Total Assigned:      {res.total_assigned:,}")
    print(f"  Unserved Evacuees:   {res.unserved}")
    print(f"  Status:              {res.status.value}")
    print(f"  Escalation:          {res.escalation.value}")

    print("  Dispatched Allocations:")
    for a in res.assignments:
        print(f"   -> {a.shelter_name} ({a.shelter_id}): {a.assigned_evacuees:,} evacuees | Distance: {a.distance_km} km | ETA: {a.transit_time_hours*60:.0f} mins")


def run_scenario_3() -> None:
    """Scenario 3: RED Zone - Extreme surge with capacity deficit."""
    print_scenario(
        3,
        "RED Zone: Severe Surge with Capacity Deficit",
        "ML Model predicts Hazard=0.92. Demand exceeds all reachable inland shelter capacities.",
    )

    zone_id = "ZONE-PARADIP-02"
    population = 12000
    ml_hazard_score = 0.92
    zone_color = "RED"

    # 1. Compute Demand
    demand_res = compute_demand(
        zone_id=zone_id,
        population=population,
        zone_color=zone_color,
        worst_hazard_score=ml_hazard_score,
    )
    print(f"  Zone ID:             {demand_res.zone_id}")
    print(f"  ML Hazard Score:     {demand_res.hazard_factor:.2f} ({zone_color})")
    print(f"  Evacuation Demand:   {demand_res.demand:,} evacuees")

    # 2. Candidate shelters: Total inland capacity only 6,500 (deficit of ~5,000)
    raw_shelters = [
        {"shelter_id": "SH-COASTAL", "name": "Port Community Hall", "lat": 20.30, "lon": 86.60, "nominal_capacity": 1500, "zone_color": "RED"},
        {"shelter_id": "SH-SAFE-1", "name": "Kendriya Vidyalaya", "lat": 20.35, "lon": 86.45, "nominal_capacity": 3500, "zone_color": "GREEN"},
        {"shelter_id": "SH-SAFE-2", "name": "Polytechnic Hostel", "lat": 20.38, "lon": 86.42, "nominal_capacity": 3000, "zone_color": "GREEN"},
    ]
    capacities: List[ShelterCapacity] = [
        compute_shelter_capacity(s, zone_color=s["zone_color"]) for s in raw_shelters
    ]

    print("\n  Shelter Safety & Usability:")
    for sc in capacities:
        print(f"   * {sc.shelter_id} ({sc.name}): Status={sc.safety_status} (Safety Factor={sc.safety_factor}), Assignable={sc.assignable:.0f}")

    # 3. Assignment
    res = assign_zone(
        zone_id=zone_id,
        origin_lat=20.29,
        origin_lon=86.61,
        demand=demand_res.demand or 0,
        candidate_shelters=capacities,
    )
    print(f"\n  Assignment Summary:")
    print(f"  Demand:              {res.demand:,}")
    print(f"  Total Assigned:      {res.total_assigned:,}")
    print(f"  Unserved Evacuees:   {res.unserved:,}  <-- DEFICIT DETECTED")
    print(f"  Status:              {res.status.value}")
    print(f"  Escalation:          {res.escalation.value} (District Staging Triggered)")


def run_scenario_4() -> None:
    """Scenario 4: RED Zone - Cut off population trapped."""
    print_scenario(
        4,
        "RED Zone: Coastal Breach / TRAPPED Population",
        "ML Model flags severe surge. Coastal shelter is inside RED zone (UNSAFE), inland shelters unreachable (> 50 km).",
    )

    zone_id = "ZONE-ISLAND-DHAMRA"
    population = 3500
    ml_hazard_score = 0.95
    zone_color = "RED"

    # 1. Compute Demand
    demand_res = compute_demand(
        zone_id=zone_id,
        population=population,
        zone_color=zone_color,
        worst_hazard_score=ml_hazard_score,
    )
    print(f"  Zone ID:             {demand_res.zone_id}")
    print(f"  ML Hazard Score:     {demand_res.hazard_factor:.2f} ({zone_color})")
    print(f"  Evacuation Demand:   {demand_res.demand:,} evacuees")

    # 2. Candidate shelters: Local shelter is submerged/UNSAFE (RED zone), inland shelters are 65 km away
    raw_shelters = [
        {"shelter_id": "SH-LOCAL", "name": "Local Jetty Shelter", "lat": 20.80, "lon": 86.95, "nominal_capacity": 1000, "zone_color": "RED"},
        {"shelter_id": "SH-FAR", "name": "Highland Base Shelter", "lat": 21.35, "lon": 86.50, "nominal_capacity": 5000, "zone_color": "GREEN"},
    ]
    capacities: List[ShelterCapacity] = [
        compute_shelter_capacity(s, zone_color=s["zone_color"]) for s in raw_shelters
    ]

    # 3. Assignment
    res = assign_zone(
        zone_id=zone_id,
        origin_lat=20.80,
        origin_lon=86.95,
        demand=demand_res.demand or 0,
        candidate_shelters=capacities,
        params=AssignmentParams(max_distance_km=50.0),
    )
    print(f"\n  Assignment Summary:")
    print(f"  Demand:              {res.demand:,}")
    print(f"  Total Assigned:      {res.total_assigned:,}")
    print(f"  Unserved Evacuees:   {res.unserved:,}")
    print(f"  Status:              {res.status.value}")
    print(f"  Trapped Flag:        {res.trapped}")
    print(f"  Escalation:          {res.escalation.value} (NDRF Heli-Lift Dispatched)")


def main() -> None:
    print_header("Capacity & Evacuation Demand Engine: Multi-Scenario Simulation")
    run_scenario_1()
    run_scenario_2()
    run_scenario_3()
    run_scenario_4()
    print_header("Simulation Finished Successfully")


if __name__ == "__main__":
    main()
