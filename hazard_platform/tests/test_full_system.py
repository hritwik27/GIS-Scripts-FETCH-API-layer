"""test_full_system.py -- Comprehensive end-to-end verification of:
1. Road network and routing integration into ZonePlan
2. Provenance tracking (§9)
3. Dynamic scenario re-planning (§10)
4. Fallback shelter availability across all 50 zones (§5)
5. FastAPI authority endpoints & dashboard serving
"""
import sys
from pathlib import Path

HP_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HP_ROOT))

from fastapi.testclient import TestClient
from backend.api import app
from zones import list_zones
from evacuation.shelters import get_shelters

client = TestClient(app)


def check(label, ok):
    print(("PASS " if ok else "FAIL ") + label)
    if not ok:
        raise SystemExit(1)


def test_full_system():
    print("--- 1. Testing Fallback Shelters Across All 50 Zones ---")
    all_zones = list_zones()
    check(f"50 zones registered (got {len(all_zones)})", len(all_zones) == 50)

    zero_shelter_zones = [z.zone_id for z in all_zones if len(get_shelters(z.zone_id)) == 0]
    check(f"Zero shelter zones == 0 (got {len(zero_shelter_zones)})", len(zero_shelter_zones) == 0)

    # Check Joshimath fallback shelters
    jm_shelters = get_shelters("Z-UTTARAKHAND-JOSHIMATH-01")
    check(f"Joshimath has fallback shelters (got {len(jm_shelters)})", len(jm_shelters) >= 3)
    check("Joshimath shelter capacity source is authority_fallback", jm_shelters[0].capacity_source == "authority_fallback")

    print("\n--- 2. Testing Authority Plan with Road Network & Provenance ---")
    res = client.get("/api/authority/plan/Z-BIHAR-PATNA-01")
    check(f"GET /api/authority/plan/Z-BIHAR-PATNA-01 -> 200 (got {res.status_code})", res.status_code == 200)

    plan = res.json()
    check("plan has road_network GeoJSON", "road_network" in plan and plan["road_network"]["type"] == "FeatureCollection")
    check("plan road_network contains corridor features", len(plan["road_network"]["features"]) > 0)
    check("plan has provenance dictionary", "provenance" in plan and "overall_confidence" in plan["provenance"])
    check("plan has assignment details", "assignment" in plan and "status" in plan["assignment"])

    print("\n--- 3. Testing Dynamic Scenario Re-planning Endpoint (§10) ---")
    res_scen = client.get("/api/authority/scenario/Z-BIHAR-PATNA-01?scenario_type=monsoon_surge")
    check(f"GET /api/authority/scenario/Z-BIHAR-PATNA-01 -> 200 (got {res_scen.status_code})", res_scen.status_code == 200)

    scen_data = res_scen.json()
    check("scenario response has timeline with 4 steps", len(scen_data.get("timeline", [])) == 4)
    check("scenario timeline steps: t0, +1h, +3h, +6h", [s["step_id"] for s in scen_data["timeline"]] == ["t0", "+1h", "+3h", "+6h"])

    print("\n--- 4. Testing National Overview Endpoint ---")
    res_plans = client.get("/api/authority/plans")
    check(f"GET /api/authority/plans -> 200 (got {res_plans.status_code})", res_plans.status_code == 200)
    summary = res_plans.json().get("summary", {})
    check("summary reports total_zones == 50", summary.get("total_zones") == 50)
    check("summary reports total_registered_shelters > 200", summary.get("total_registered_shelters", 0) > 200)
    check("summary reports total_shelters in evaluated plans >= 18", summary.get("total_shelters", 0) >= 18)

    print("\n--- 5. Testing Static Dashboard Routes ---")
    res_auth = client.get("/authority")
    check(f"GET /authority -> 200 (got {res_auth.status_code})", res_auth.status_code == 200)

    res_dash = client.get("/dashboard")
    check(f"GET /dashboard -> 200 (got {res_dash.status_code})", res_dash.status_code == 200)

    print("\nPASS: All end-to-end full system checks passed.")


if __name__ == "__main__":
    test_full_system()
