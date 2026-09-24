"""
evacuation/scenarios.py -- dynamic scenario projection and re-planning (FINAL doc §10, §13).

Evaluates progressive evacuation timelines:
    t0 -> +1h -> +3h -> +6h

Features:
- Live Open-Meteo Hourly Forecast: Queries live precipitation predictions to dynamically drive
  future hazard score evolution and road water accumulation.
- Calibrated Stress Test Mode: Supports standard simulated profiles (monsoon surge, cyclone, cloudburst).
- Re-evaluates zone color classification, evacuation demand E_i(t), road link impassability,
  and emerging TRAPPED states over time.
"""

from __future__ import annotations

import json
import urllib.request
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from backend.zone_classifier import ZoneColor
from evacuation.capacity import compute_zone_capacities
from evacuation.demand import compute_demand
from evacuation.models import AssignmentStatus, EdgeCondition
from evacuation.road_network import build_corridor_network
from evacuation.shelters import get_shelters
from zones import get_zone


@dataclass
class TimestepProjection:
    step_id: str             # "t0", "+1h", "+3h", "+6h"
    offset_hours: int
    projected_time: datetime
    projected_hazard_score: float
    zone_color: str
    demand: int
    assigned: int
    unserved: int
    trapped: bool
    status: str
    closed_roads_count: int
    active_shelters_count: int
    rain_rate_mm_hr: float = 0.0
    cumulative_rain_mm: float = 0.0


@dataclass
class ZoneScenarioResult:
    zone_id: str
    base_time: datetime
    scenario_type: str      # "live_forecast", "monsoon_surge", "cyclone_landfall"
    forecast_source: str    # "open_meteo_live_forecast" or "calibrated_simulation"
    timeline: list[TimestepProjection]
    plans: dict[str, dict[str, Any]] = field(default_factory=dict)
    weather_summary: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "zone_id": self.zone_id,
            "base_time": self.base_time.isoformat(),
            "scenario_type": self.scenario_type,
            "forecast_source": self.forecast_source,
            "weather_summary": self.weather_summary,
            "timeline": [asdict(t) for t in self.timeline],
            "plans": self.plans,
        }


def fetch_live_hourly_forecast(
    lat: float, lon: float
) -> tuple[dict[str, float], dict[str, float], dict[str, float], dict[str, float], str]:
    """
    Query real live hourly precipitation forecast from Open-Meteo public API.
    Derives dynamic hazard deltas and road water depth accumulation.

    Returns:
        (rain_rates_mm_hr, cumulative_rain_mm, hazard_deltas, flood_depth_deltas, source_tag)
    """
    url = f"https://api.open-meteo.com/v1/forecast?latitude={lat:.4f}&longitude={lon:.4f}&hourly=precipitation&forecast_days=1"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "hazard-platform-evac/1.0"})
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode("utf-8"))

        precip = data.get("hourly", {}).get("precipitation", [])
        if not precip or len(precip) < 7:
            raise ValueError("Incomplete precipitation forecast series")

        p0 = float(precip[0])
        p1 = float(precip[1])
        p3 = float(precip[3])
        p6 = float(precip[6])

        rain_rates = {"t0": round(p0, 2), "+1h": round(p1, 2), "+3h": round(p3, 2), "+6h": round(p6, 2)}
        cum_rain = {
            "t0": 0.0,
            "+1h": round(sum(precip[:2]), 2),
            "+3h": round(sum(precip[:4]), 2),
            "+6h": round(sum(precip[:7]), 2),
        }

        # Dynamic hazard delta: rain rate scaling
        # p=0 -> negative delta (receding risk); p=20mm/hr -> ~+0.25 risk escalation
        haz_deltas = {
            "t0": 0.0,
            "+1h": round(min(0.40, max(-0.15, (p1 - 1.0) / 25.0 * 0.30)), 3),
            "+3h": round(min(0.50, max(-0.20, (cum_rain["+3h"] / 3.0 - 1.0) / 25.0 * 0.35)), 3),
            "+6h": round(min(0.60, max(-0.25, (cum_rain["+6h"] / 6.0 - 1.0) / 25.0 * 0.40)), 3),
        }

        # Dynamic road water depth from cumulative rainfall runoff
        # 40mm cumulative rain accumulates ~0.33m water on low-lying arterial corridors (triggering 0.30m closure)
        flood_depths = {
            "t0": 0.0,
            "+1h": round(min(0.80, max(0.0, (cum_rain["+1h"] / 50.0) * 0.40)), 2),
            "+3h": round(min(0.90, max(0.0, (cum_rain["+3h"] / 50.0) * 0.45)), 2),
            "+6h": round(min(1.00, max(0.0, (cum_rain["+6h"] / 50.0) * 0.50)), 2),
        }

        return rain_rates, cum_rain, haz_deltas, flood_depths, "open_meteo_live_forecast"

    except Exception:
        # Graceful fallback to calibrated storm surge model if offline / network error
        rain_rates = {"t0": 0.0, "+1h": 6.0, "+3h": 18.0, "+6h": 32.0}
        cum_rain = {"t0": 0.0, "+1h": 6.0, "+3h": 25.0, "+6h": 55.0}
        haz_deltas = {"t0": 0.0, "+1h": 0.08, "+3h": 0.20, "+6h": 0.35}
        flood_depths = {"t0": 0.0, "+1h": 0.10, "+3h": 0.25, "+6h": 0.45}
        return rain_rates, cum_rain, haz_deltas, flood_depths, "calibrated_simulation_fallback"


def run_zone_scenario(
    zone_id: str,
    base_hazard_score: float,
    population: Optional[float] = None,
    scenario_type: str = "live_forecast",
    use_live_forecast: bool = True,
    hazard_deltas: Optional[dict[str, float]] = None,
    flood_depth_deltas: Optional[dict[str, float]] = None,
) -> ZoneScenarioResult:
    """
    Project evacuation requirements forward across t0, +1h, +3h, and +6h.
    Uses real Open-Meteo hourly weather forecast by default.
    """
    zone = get_zone(zone_id)
    origin_lat, origin_lon = zone.center[1], zone.center[0]
    now = datetime.now(timezone.utc)

    # 1. Obtain Forecast Profiles (Live API or Calibrated Profile)
    rain_rates: dict[str, float] = {}
    cum_rain: dict[str, float] = {}

    if use_live_forecast and hazard_deltas is None and scenario_type in ("live_forecast", "default"):
        rain_rates, cum_rain, haz_deltas, flood_depths, forecast_source = fetch_live_hourly_forecast(
            origin_lat, origin_lon
        )
        hazard_deltas = haz_deltas
        flood_depth_deltas = flood_depths
    else:
        forecast_source = f"calibrated_{scenario_type}"
        if hazard_deltas is None:
            if scenario_type == "cyclone_landfall":
                hazard_deltas = {"t0": 0.0, "+1h": 0.15, "+3h": 0.35, "+6h": 0.50}
            else:  # monsoon_surge
                hazard_deltas = {"t0": 0.0, "+1h": 0.08, "+3h": 0.20, "+6h": 0.35}

        if flood_depth_deltas is None:
            flood_depth_deltas = {"t0": 0.0, "+1h": 0.10, "+3h": 0.25, "+6h": 0.45}

        rain_rates = {"t0": 0.0, "+1h": 8.0, "+3h": 22.0, "+6h": 40.0}
        cum_rain = {"t0": 0.0, "+1h": 8.0, "+3h": 30.0, "+6h": 65.0}

    steps = [
        ("t0", 0),
        ("+1h", 1),
        ("+3h", 3),
        ("+6h", 6),
    ]

    timeline: list[TimestepProjection] = []
    plans_by_step: dict[str, dict[str, Any]] = {}
    local_shelters = get_shelters(zone_id)

    for step_id, offset in steps:
        proj_time = now + timedelta(hours=offset)
        h_score = min(1.0, max(0.0, base_hazard_score + hazard_deltas.get(step_id, 0.0)))

        # Determine zone color
        if h_score >= 0.70:
            color = ZoneColor.RED
        elif h_score >= 0.40:
            color = ZoneColor.YELLOW
        else:
            color = ZoneColor.GREEN

        # 1. Demand at this timestep
        demand_res = compute_demand(zone_id, population, color, h_score)
        demand_val = demand_res.demand or 0

        # 2. Shelters & Safety check at this timestep
        caps = compute_zone_capacities(local_shelters, color)
        active_shelters = [c for c in caps if c.assignable > 0 and c.safety_factor > 0]

        # 3. Road network conditions at this timestep
        corridor = build_corridor_network(zone_id, origin_lat, origin_lon, caps)
        water_depth = flood_depth_deltas.get(step_id, 0.0)

        # Apply progressive water depth to arterial links
        closed_roads = 0
        if water_depth > 0.0:
            for edge in corridor.edges.values():
                if "ORIGIN" in edge.u or "ORIGIN" in edge.v:
                    # Low-lying origin arterial links accumulate runoff
                    corridor.set_edge_condition(
                        edge.edge_id,
                        EdgeCondition(
                            water_depth_m=water_depth,
                            rainfall_72h_mm=cum_rain.get(step_id, 0.0),
                        ),
                    )
                    if water_depth >= 0.30:
                        closed_roads += 1

        # 4. Assign evacuees
        from evacuation.assignment import assign_zone
        assign_res = assign_zone(
            zone_id,
            origin_lat,
            origin_lon,
            demand_val,
            caps,
            graph=corridor,
            hazard_score=h_score,
        )

        timeline.append(
            TimestepProjection(
                step_id=step_id,
                offset_hours=offset,
                projected_time=proj_time,
                projected_hazard_score=round(h_score, 3),
                zone_color=color.value,
                demand=demand_val,
                assigned=assign_res.total_assigned,
                unserved=assign_res.unserved,
                trapped=assign_res.trapped,
                status=assign_res.status.value,
                closed_roads_count=closed_roads,
                active_shelters_count=len(active_shelters),
                rain_rate_mm_hr=rain_rates.get(step_id, 0.0),
                cumulative_rain_mm=cum_rain.get(step_id, 0.0),
            )
        )

        plans_by_step[step_id] = {
            "demand": demand_val,
            "status": assign_res.status.value,
            "escalation": assign_res.escalation.value,
            "assigned": assign_res.total_assigned,
            "unserved": assign_res.unserved,
            "trapped": assign_res.trapped,
            "rain_rate_mm_hr": rain_rates.get(step_id, 0.0),
            "assignments": [a.to_dict() for a in assign_res.assignments],
        }

    return ZoneScenarioResult(
        zone_id=zone_id,
        base_time=now,
        scenario_type=scenario_type,
        forecast_source=forecast_source,
        weather_summary={
            "hourly_rain_mm_hr": rain_rates,
            "cumulative_rain_mm": cum_rain,
        },
        timeline=timeline,
        plans=plans_by_step,
    )
