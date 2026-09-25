"""run_tests.py -- Master test runner for the Hazard Platform.

Executes all verification and unit test suites across the backend, evacuation engine,
AHP weighting, and static data stores.

Run from hazard_platform/:
    python run_tests.py
"""
import sys
import time
from pathlib import Path

HP_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(HP_ROOT))

# Import individual test modules
from tests import test_zones
from tests import test_zone_classifier
from tests import test_prioritization
from tests import test_capacity_demand
from tests import test_assignment
from tests import test_routing
from tests import test_scenarios
from tests import test_full_system
from tests import test_vulnerability_wiring


def run_ahp_tests():
    import pytest
    ret = pytest.main(["-q", str(HP_ROOT / "tests" / "test_ahp_weighting.py")])
    if ret != 0:
        raise RuntimeError("AHP weighting tests failed")


TEST_SUITES = [
    ("Zone Registry & Population (50 Zones)", test_zones.test_all_zones),
    ("Census Vulnerability Inputs & Wiring", test_vulnerability_wiring.test_vulnerability_wiring),
    ("Zone Classifier & Hazard Thresholds", test_zone_classifier.test_zone_classifier),
    ("Multi-Criteria AHP Prioritization", test_prioritization.test_prioritization),
    ("Evacuation Capacity & Demand Engine", test_capacity_demand.test_capacity_demand),
    ("Capacity-Constrained Shelter Assignment", test_assignment.test_assignment),
    ("Road Corridors, Impassability & Routing", test_routing.test_routing),
    ("Dynamic Scenario Re-planning (t0 -> +6h)", test_scenarios.test_scenarios),
    ("End-to-End System & API Verification", test_full_system.test_full_system),
    ("AHP Consistency & Weights (Saaty CR < 0.10)", run_ahp_tests),
]



def main():
    print("=" * 70)
    print("           HAZARD PLATFORM - MASTER TEST SUITE RUNNER")
    print("=" * 70)
    print(f"Executing {len(TEST_SUITES)} test suite(s)...\n")

    results = []
    total_start = time.time()

    for name, test_fn in TEST_SUITES:
        print(f"\n>> Running: {name}")
        print("-" * 60)
        start = time.time()
        try:
            test_fn()
            duration = round(time.time() - start, 2)
            results.append((name, "PASSED", duration, None))
        except Exception as e:
            duration = round(time.time() - start, 2)
            results.append((name, "FAILED", duration, str(e)))

    total_duration = round(time.time() - total_start, 2)

    print("\n" + "=" * 70)
    print("                      TEST SUITE SUMMARY")
    print("=" * 70)
    passed_count = sum(1 for _, status, _, _ in results if status == "PASSED")
    for name, status, duration, error in results:
        status_str = f"[{status}]"
        print(f" {status_str:<10} {name:<45} ({duration}s)")
        if error:
            print(f"             Error: {error}")

    print("-" * 70)
    print(f"Total: {passed_count}/{len(results)} passed in {total_duration}s")
    print("=" * 70)

    if passed_count < len(results):
        sys.exit(1)
    else:
        print("ALL TESTS PASSED SUCCESSFULLY.")
        sys.exit(0)


if __name__ == "__main__":
    main()
