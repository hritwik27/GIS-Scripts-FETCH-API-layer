"""test_capacity_demand.py -- Verification of evacuation demand and capacity calculations.
Pure-function tests: no database, no network.
"""
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

HP_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HP_ROOT))

from evacuation.capacity import (
    CapacityParams, capacity_gap, compute_zone_capacities, load_params as load_cap,
    map_safe_shelters, zone_capacity_summary,
)
from evacuation.demand import DemandParams, compute_demand, load_params as load_dem


@dataclass
class FakeShelter:
    shelter_id: str
    nominal_capacity: Optional[float]
    zone_id: str = "Z-TEST"
    name: str = "S"
    lat: float = 1.0
    lon: float = 2.0
    capacity_source: str = "footprint_estimate"
    osm_tag: str = "amenity=school"


def check(label, ok):
    print(("PASS " if ok else "FAIL ") + label)
    if not ok:
        raise SystemExit(1)


def test_capacity_demand():
    # ---- demand -------------------------------------------------------------
    d = compute_demand("Z", 10000, "GREEN", 0.9)
    check("demand: GREEN -> 0, no_evacuation", d.demand == 0 and d.status == "no_evacuation")

    d = compute_demand("Z", 10000, "RED", 0.9)
    check(f"demand: RED 0.9 -> 9855 (got {d.demand}), placeholder flagged",
          d.demand == 9855 and d.vulnerability_is_placeholder)

    d = compute_demand("Z", 10000, "YELLOW", 0.5, phi_kutcha=0.0, phi_dependent=0.0)
    check(f"demand: YELLOW 0.5, V=1 -> 5000 (got {d.demand}), not placeholder",
          d.demand == 5000 and not d.vulnerability_is_placeholder)

    d = compute_demand("Z", 10000, "RED", 1.0, phi_kutcha=1.0, phi_dependent=1.0)
    check("demand: cap -> never more than exposed population", d.demand == 10000 and d.capped)

    d = compute_demand("Z-UNSEEDED", None, "RED", 0.9)
    check("demand: unknown population -> None, no crash", d.demand is None and d.status == "no_population_data")

    check("demand: yaml loads", isinstance(load_dem(), DemandParams))

    # ---- capacity -----------------------------------------------------------
    caps = compute_zone_capacities([FakeShelter("a", 300)], "GREEN", occupancy_by_id={"a": 100}, reserved_by_id={"a": 50})
    check("capacity: 300-100-50 = 150 effective", caps[0].effective == 150 and caps[0].assignable == 150)

    caps = compute_zone_capacities([FakeShelter("a", 100)], "GREEN", occupancy_by_id={"a": 130})
    check("capacity: full/over shelter is NOT floored at 100",
          caps[0].effective == -30 and caps[0].assignable == 0 and caps[0].over_capacity)

    caps = compute_zone_capacities([FakeShelter("a", 200)], "RED")
    check("capacity: shelter in RED zone -> effective 0, UNSAFE", caps[0].effective == 0 and caps[0].safety_status == "UNSAFE")

    caps = compute_zone_capacities([FakeShelter("a", 200)], "YELLOW")
    check("capacity: YELLOW -> 50% (CAUTION)", caps[0].effective == 100 and caps[0].safety_status == "CAUTION")

    caps = compute_zone_capacities([FakeShelter("a", 200)], None)
    check("capacity: no classification -> UNVERIFIED, zero assignable", caps[0].safety_status == "UNVERIFIED" and caps[0].assignable == 0)

    caps = compute_zone_capacities([FakeShelter("a", None), FakeShelter("b", 400)], "GREEN")
    s = zone_capacity_summary(caps)
    check("capacity: unknown capacity excluded, never guessed",
          caps[0].capacity_known is False and caps[0].assignable == 0 and s["total_assignable"] == 400
          and s["shelters_capacity_unknown"] == 1)

    check("capacity: map gets SAFE shelters only, no numbers",
          len(map_safe_shelters(caps)) == 2 and "nominal" not in map_safe_shelters(caps)[0]
          and map_safe_shelters(compute_zone_capacities([FakeShelter("a", 9)], "RED")) == [])

    g = capacity_gap(500, caps)
    check("gap: demand 500 vs assignable 400 -> unserved 100", g["unserved"] == 100 and abs(g["coverage"] - 0.8) < 1e-9)
    check("gap: unknown demand -> None, no crash", capacity_gap(None, caps)["unserved"] is None)
    check("capacity: yaml loads", isinstance(load_cap(), CapacityParams))

    print("\nPASS: All capacity & demand tests passed.")


if __name__ == "__main__":
    test_capacity_demand()
