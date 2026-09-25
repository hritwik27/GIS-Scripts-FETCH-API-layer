"""test_engine.py -- Standalone verification test suite for capacity_engine.

Run with:
    python test_engine.py
"""
import sys
from pathlib import Path

# Ensure capacity_engine is importable
ENGINE_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ENGINE_ROOT))

from capacity_engine import (
    AssignmentStatus,
    CapacityParams,
    DemandParams,
    EscalationLevel,
    ShelterCapacity,
    assign_zone,
    capacity_gap,
    compute_demand,
    compute_zone_capacities,
    haversine_distance_km,
    map_safe_shelters,
    route_cost,
    zone_capacity_summary,
)


def check(label: str, ok: bool) -> None:
    status = "PASS" if ok else "FAIL"
    print(f"[{status}] {label}")
    if not ok:
        raise AssertionError(f"Test failed: {label}")


def make_shelter(
    sid: str,
    nominal: float,
    lat: float = 25.60,
    lon: float = 85.14,
    safety_status: str = "SAFE",
    safety_factor: float = 1.0,
    occupancy: float = 0.0,
    reserved: float = 0.0,
) -> ShelterCapacity:
    usable = nominal - occupancy - reserved
    effective = usable * safety_factor
    return ShelterCapacity(
        shelter_id=sid,
        zone_id="Z-TEST",
        name=f"Shelter {sid}",
        lat=lat,
        lon=lon,
        osm_tag="amenity=school",
        capacity_source="footprint_estimate",
        safety_status=safety_status,
        safety_factor=safety_factor,
        capacity_known=True,
        nominal=nominal,
        occupancy=occupancy,
        reserved=reserved,
        usable=usable,
        effective=effective,
        assignable=max(0.0, effective),
        over_capacity=usable < 0,
    )


def run_tests():
    print("=" * 65)
    print("      CAPACITY & EVACUATION DEMAND ENGINE TEST SUITE")
    print("=" * 65)

    print("\n--- 1. Evacuation Demand Formulation (Section 3) ---")
    # 1a. GREEN zone -> 0 demand regardless of score
    d_green = compute_demand("Z-1", 10000, "GREEN", 0.35)
    check("GREEN zone: demand is 0, status 'no_evacuation'", d_green.demand == 0 and d_green.status == "no_evacuation")

    # 1b. YELLOW zone: E_i = 10000 * 1.0 * 0.5 * (1 + 0.25*0 + 0.20*0) = 5000
    d_yellow = compute_demand("Z-1", 10000, "YELLOW", 0.50, phi_kutcha=0.0, phi_dependent=0.0)
    check("YELLOW zone 0.50 hazard, V=1: demand is 5000", d_yellow.demand == 5000)

    # 1c. RED zone with vulnerability: E_i = 10000 * 1.0 * 0.90 * (1 + 0.25*0.10 + 0.20*0.35)
    # V = 1 + 0.025 + 0.07 = 1.095; 10000 * 0.9 * 1.095 = 9855
    d_red = compute_demand("Z-1", 10000, "RED", 0.90)
    check("RED zone 0.90 hazard with default vulnerability: demand is 9855", d_red.demand == 9855)

    # 1d. Conservation constraint: demand never exceeds exposed population
    d_max = compute_demand("Z-1", 10000, "RED", 1.0, phi_kutcha=1.0, phi_dependent=1.0)
    check("Conservation constraint: demand clamped to exposed population", d_max.demand == 10000 and d_max.capped)

    # 1e. Unknown population gracefully handled
    d_unknown = compute_demand("Z-1", None, "RED", 0.8)
    check("Unknown population: demand is None, status 'no_population_data'", d_unknown.demand is None and d_unknown.status == "no_population_data")


    print("\n--- 2. Effective Shelter Capacity & Safety Derating (Section 5) ---")
    # 2a. Normal safe shelter: 500 nominal - 100 occ - 50 res = 350 effective
    s_raw = {"shelter_id": "S1", "nominal_capacity": 500, "lat": 25.6, "lon": 85.1}
    caps = compute_zone_capacities([s_raw], "GREEN", occupancy_by_id={"S1": 100}, reserved_by_id={"S1": 50})
    check("Effective capacity calculation: 500 - 100 - 50 = 350", caps[0].effective == 350 and caps[0].assignable == 350)

    # 2b. PDF Bug removal: over-capacity shelter is NOT floored at 100
    caps_over = compute_zone_capacities([s_raw], "GREEN", occupancy_by_id={"S1": 600})
    check("Over-capacity shelter reports negative effective, assignable 0 (bug removed)",
          caps_over[0].effective == -100 and caps_over[0].assignable == 0 and caps_over[0].over_capacity)

    # 2c. Safety derating: RED zone shelter is UNSAFE (0.0 effective)
    caps_red = compute_zone_capacities([s_raw], "RED")
    check("Shelter inside RED zone is UNSAFE (effective 0.0)", caps_red[0].effective == 0.0 and caps_red[0].safety_status == "UNSAFE")

    # 2d. Safety derating: YELLOW zone shelter gets 50% capacity (CAUTION)
    caps_yellow = compute_zone_capacities([s_raw], "YELLOW")
    check("Shelter inside YELLOW zone gets 50% derating (CAUTION)", caps_yellow[0].effective == 250 and caps_yellow[0].safety_status == "CAUTION")

    # 2e. Capacity gap evaluation
    gap_test = capacity_gap(400, caps)  # demand 400 vs assignable 350
    check("Capacity gap: demand 400 vs assignable 350 -> unserved 50", gap_test["unserved"] == 50 and gap_test["has_deficit"])


    print("\n--- 3. Capacity-Constrained Assignment & Escalation (Section 8) ---")
    # 3a. Demand = 0 -> NO_EVACUATION_NEEDED
    res_zero = assign_zone("Z-1", 25.60, 85.14, 0, [make_shelter("S1", 500)])
    check("Zero demand -> NO_EVACUATION_NEEDED", res_zero.status == AssignmentStatus.NO_EVACUATION_NEEDED)

    # 3b. Sufficient capacity across multiple shelters -> FULLY_SERVED
    s1 = make_shelter("S1", 300, lat=25.61, lon=85.14)
    s2 = make_shelter("S2", 300, lat=25.62, lon=85.15)
    res_full = assign_zone("Z-1", 25.60, 85.14, 450, [s1, s2])
    check("Sufficient capacity: FULLY_SERVED, total assigned 450",
          res_full.status == AssignmentStatus.FULLY_SERVED and res_full.total_assigned == 450 and res_full.unserved == 0)

    # 3c. Capacity deficit -> CAPACITY_DEFICIT & EXTERNAL_STAGING_REQUIRED
    res_deficit = assign_zone("Z-1", 25.60, 85.14, 700, [s1, s2])  # 700 demand vs 600 cap
    check("Capacity deficit: status CAPACITY_DEFICIT, unserved 100",
          res_deficit.status == AssignmentStatus.CAPACITY_DEFICIT and res_deficit.unserved == 100)
    check("Deficit triggers EXTERNAL_STAGING_REQUIRED escalation",
          res_deficit.escalation == EscalationLevel.EXTERNAL_STAGING_REQUIRED and not res_deficit.trapped)

    # 3d. No safe shelters (all UNSAFE or out of reach) -> TRAPPED & NDRF_AERIAL_RESCUE_REQUIRED
    unsafe_s = make_shelter("S_UNSAFE", 1000, safety_status="UNSAFE", safety_factor=0.0)
    res_trapped = assign_zone("Z-RED", 25.60, 85.14, 500, [unsafe_s])
    check("No safe shelters: status TRAPPED", res_trapped.status == AssignmentStatus.TRAPPED and res_trapped.trapped)
    check("TRAPPED state triggers NDRF_AERIAL_RESCUE_REQUIRED escalation",
          res_trapped.escalation == EscalationLevel.NDRF_AERIAL_RESCUE_REQUIRED)

    print("\n" + "=" * 65)
    print("       ALL CAPACITY ENGINE TESTS COMPLETED SUCCESSFULLY!")
    print("=" * 65)


if __name__ == "__main__":
    run_tests()
