"""test_assignment.py -- Verification of capacity-constrained evacuation assignment.
Pure-function tests: no DB, no network.
"""
import sys
from pathlib import Path

HP_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HP_ROOT))

from evacuation.assignment import (
    AssignmentParams,
    assign_zone,
    haversine_distance_km,
    load_params,
    route_cost,
)
from evacuation.capacity import ShelterCapacity
from evacuation.models import AssignmentStatus, EscalationLevel


def check(label, ok):
    print(("PASS " if ok else "FAIL ") + label)
    if not ok:
        raise SystemExit(1)


def make_shelter(
    shelter_id: str,
    lat: float,
    lon: float,
    assignable: float,
    safety_status: str = "SAFE",
    safety_factor: float = 1.0,
    name: str = "Shelter",
) -> ShelterCapacity:
    return ShelterCapacity(
        shelter_id=shelter_id,
        zone_id="Z-TEST",
        name=name,
        lat=lat,
        lon=lon,
        osm_tag="amenity=school",
        capacity_source="footprint_estimate",
        safety_status=safety_status,
        safety_factor=safety_factor,
        capacity_known=True,
        nominal=assignable,
        occupancy=0.0,
        reserved=0.0,
        usable=assignable,
        effective=assignable,
        assignable=assignable,
        over_capacity=False,
    )


def test_assignment():
    # 1. Distance & route cost checks
    d = haversine_distance_km(28.6139, 77.2090, 28.7041, 77.1025)
    check(f"haversine: ~14.3km (got {d:.2f}km)", 12.0 < d < 16.0)

    cost, dist_km, time_hrs = route_cost(28.6139, 77.2090, 28.7041, 77.1025)
    check(f"route_cost: detour applied {dist_km:.2f}km > {d:.2f}km", dist_km > d and time_hrs > 0)

    # 2. Demand = 0 -> NO_EVACUATION_NEEDED
    res = assign_zone("Z-1", 28.0, 77.0, 0, [make_shelter("s1", 28.01, 77.01, 500)])
    check("assignment: demand 0 -> NO_EVACUATION_NEEDED", res.status == AssignmentStatus.NO_EVACUATION_NEEDED and res.unserved == 0)

    # 3. Sufficient capacity -> FULLY_SERVED
    s1 = make_shelter("s1", 28.01, 77.01, 400)
    s2 = make_shelter("s2", 28.02, 77.02, 300)
    res = assign_zone("Z-1", 28.0, 77.0, 500, [s1, s2])
    check("assignment: demand 500 across 400+300 -> FULLY_SERVED",
          res.status == AssignmentStatus.FULLY_SERVED and res.total_assigned == 500 and res.unserved == 0)
    check("assignment: capacity limits respected",
          res.assignments[0].assigned_evacuees <= 400 and res.assignments[1].assigned_evacuees <= 300)

    # 4. Partial capacity -> CAPACITY_DEFICIT
    s1 = make_shelter("s1", 28.01, 77.01, 200)
    res = assign_zone("Z-1", 28.0, 77.0, 500, [s1])
    check(f"assignment: demand 500 vs 200 cap -> CAPACITY_DEFICIT, unserved 300 (got {res.unserved})",
          res.status == AssignmentStatus.CAPACITY_DEFICIT and res.unserved == 300 and res.total_assigned == 200)
    check("assignment: escalation flag set for deficit",
          res.escalation == EscalationLevel.EXTERNAL_STAGING_REQUIRED and not res.trapped)

    # 5. No safe shelters (all UNSAFE due to RED zone) -> TRAPPED
    unsafe_s = make_shelter("s_unsafe", 28.01, 77.01, 0.0, safety_status="UNSAFE", safety_factor=0.0)
    res = assign_zone("Z-RED", 28.0, 77.0, 1000, [unsafe_s])
    check("assignment: all shelters UNSAFE -> TRAPPED",
          res.trapped and res.status == AssignmentStatus.TRAPPED and res.unserved == 1000)
    check("assignment: TRAPPED triggers NDRF aerial rescue escalation",
          res.escalation == EscalationLevel.NDRF_AERIAL_RESCUE_REQUIRED)

    # 6. Shelter beyond max_distance_km -> unreachable -> TRAPPED
    far_s = make_shelter("s_far", 29.5, 79.5, 500)
    res = assign_zone("Z-ISOLATED", 28.0, 77.0, 300, [far_s])
    check("assignment: out-of-range shelter excluded -> TRAPPED",
          res.trapped and res.status == AssignmentStatus.TRAPPED and len(res.assignments) == 0)

    # 7. YAML params load
    p = load_params()
    check("assignment: yaml loads cleanly", isinstance(p, AssignmentParams) and p.detour_factor == 1.4)

    print("\nPASS: All assignment tests passed.")


if __name__ == "__main__":
    test_assignment()
