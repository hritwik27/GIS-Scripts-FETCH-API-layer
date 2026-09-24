"""test_scenarios.py -- Verification of dynamic evacuation scenario replanning (t0 -> +1h -> +3h -> +6h).
Tests both calibrated stress test and live Open-Meteo forecast modes.
"""
import sys
from pathlib import Path

HP_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HP_ROOT))

from evacuation.scenarios import run_zone_scenario


def check(label: str, ok: bool) -> None:
    print(("PASS " if ok else "FAIL ") + label)
    if not ok:
        raise SystemExit(1)


def test_scenarios():
    # Test 1: Calibrated monsoon surge scenario with Patna
    res = run_zone_scenario("Z-BIHAR-PATNA-01", base_hazard_score=0.35, population=50000.0, scenario_type="monsoon_surge")

    check("scenario result has 4 timesteps", len(res.timeline) == 4)
    check("t0 step is present", res.timeline[0].step_id == "t0")
    check("t0 status is NO_EVACUATION_NEEDED (score 0.35 < 0.40)", res.timeline[0].status == "NO_EVACUATION_NEEDED")

    # By +3h, score is 0.35 + 0.20 = 0.55 (YELLOW) -> demand > 0
    check("+3h step escalates to YELLOW", res.timeline[2].zone_color == "YELLOW" and res.timeline[2].demand > 0)

    # By +6h, score is 0.35 + 0.35 = 0.70 (RED) and flood depth is 0.45m (>=0.30m closure) -> roads close, TRAPPED
    check("+6h step escalates to RED and triggers closed roads", res.timeline[3].zone_color == "RED" and res.timeline[3].closed_roads_count > 0)
    check("+6h triggers TRAPPED or CAPACITY_DEFICIT", res.timeline[3].trapped or res.timeline[3].unserved > 0)

    # Test 2: Live Open-Meteo Forecast Mode
    res_live = run_zone_scenario("Z-BIHAR-PATNA-01", base_hazard_score=0.35, population=50000.0, scenario_type="live_forecast")
    check("live forecast scenario runs", len(res_live.timeline) == 4)
    check("live forecast has forecast_source tag", "open_meteo" in res_live.forecast_source or "fallback" in res_live.forecast_source)
    check("live forecast contains rain rates", "hourly_rain_mm_hr" in res_live.weather_summary)

    print("\nPASS: All dynamic scenario replanning tests passed.")


if __name__ == "__main__":
    test_scenarios()
