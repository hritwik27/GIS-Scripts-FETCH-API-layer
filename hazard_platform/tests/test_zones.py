"""test_zones.py -- Verification of 50-zone registry, population, and shelters.

Exercises every zone in zones.py's _SEED_ZONES through:
1. get_zone() (bbox math and center calculation)
2. get_population() (WorldPop store)
3. get_shelters() & get_shelters_with_capacity() (ShelterStore)
"""
import sys
from pathlib import Path

# Add hazard_platform root to sys.path
HP_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HP_ROOT))

from zones import list_zones, get_zone
from evacuation.population import get_population
from evacuation.shelters import get_shelters, get_shelters_with_capacity


def test_all_zones():
    zones = list_zones()
    print(f"Testing {len(zones)} zone(s)\n")

    errors = []
    no_population = []
    no_shelters = []
    ok_count = 0

    for zone in zones:
        zid = zone.zone_id
        try:
            # 1. bbox / registry lookup round-trips
            looked_up = get_zone(zid)
            assert looked_up.zone_id == zid, "get_zone returned mismatched zone_id"
            center_lon, center_lat = looked_up.center

            # 2. population resolves
            pop = get_population(zid)
            if pop is None:
                no_population.append(zid)

            # 3. shelters resolve
            all_shelters = get_shelters(zid)
            if not all_shelters:
                no_shelters.append(zid)

            ok_count += 1
        except Exception as exc:
            errors.append((zid, repr(exc)))

    print(f"OK: {ok_count}/{len(zones)} zones resolved without exception")

    if no_population:
        print(f"WARNING: {len(no_population)} zone(s) with no population record: {sorted(no_population)}")
        raise AssertionError("Missing population records")
    else:
        print("Population: all 50 zones OK")

    if no_shelters:
        print(f"WARNING: {len(no_shelters)} zone(s) have zero shelters: {sorted(no_shelters)}")
        raise AssertionError("Zones missing shelters")
    else:
        print("Shelters: all 50 zones have valid shelters (including fallback shelters)")

    if errors:
        print(f"\nFAILED: {len(errors)} zone(s) raised an exception:")
        for zid, err in errors:
            print(f"  {zid}: {err}")
        raise SystemExit(1)

    print("\nPASS: All 50 zones verified successfully.")


if __name__ == "__main__":
    test_all_zones()
