"""
evacuation/impassability.py -- dynamic road impassability computation (FINAL doc §6).

Mathematical Model:
    I_e = w_R * R_e + w_F * F_e + w_S * S_e + w_H * H_e + w_C * C_e    (sum(w) = 1.0)
    Passability_e = 1.0 - I_e

Hard Closure Rules (override weighted score unconditionally per FINAL doc §6):
1. Flood:
   water_depth >= 0.30m OR (water_depth * water_velocity) >= 0.60 m^2/s
   -> I_e = 1.0, is_closed = True, closure_reason = "CRITICAL_FLOOD_DEPTH_VELOCITY"
   When 0 < water_depth < 0.30m:
   K_flood = 1 - 1.8 * water_depth  =>  F_e = 1.8 * water_depth

2. Landslide:
   landslide_risk >= 0.75 AND rainfall_72h >= 150mm
   -> I_e = 1.0, is_closed = True, closure_reason = "CRITICAL_LANDSLIDE_DEBRIS_FLOW"
   Otherwise:
   S_e = landslide_risk * min(1.0, rainfall_72h / 150.0)

Effective Speed:
    effective_speed_e = 0.0 if is_closed else max(1.0, base_speed_e * Passability_e)
"""

from __future__ import annotations

from dataclasses import dataclass, fields
from pathlib import Path
from typing import Optional, Union

from evacuation.models import EdgeCondition, ImpassabilityResult, RoadEdge

PARAMS_PATH = Path(__file__).with_name("evacuation_params.yaml")


@dataclass(frozen=True)
class ImpassabilityParams:
    w_rainfall: float = 0.15
    w_flood: float = 0.35
    w_slope_landslide: float = 0.25
    w_hazard: float = 0.15
    w_condition: float = 0.10
    flood_depth_critical: float = 0.30
    flood_hv_critical: float = 0.60
    flood_k_coeff: float = 1.8
    landslide_risk_critical: float = 0.75
    rainfall_72h_critical: float = 150.0


def load_params(path: Union[str, Path, None] = None) -> ImpassabilityParams:
    """Read the `impassability:` section from YAML, returning defaults if absent."""
    path = Path(path) if path else PARAMS_PATH
    if not path.exists():
        return ImpassabilityParams()
    import yaml

    data = (yaml.safe_load(path.read_text(encoding="utf-8")) or {}).get("impassability", {})
    valid_fields = {f.name for f in fields(ImpassabilityParams)}
    filtered = {k: v for k, v in data.items() if k in valid_fields}
    return ImpassabilityParams(**filtered)


def calculate_edge_impassability(
    edge: RoadEdge,
    condition: Optional[EdgeCondition] = None,
    hazard_score: float = 0.0,
    *,
    params: Optional[ImpassabilityParams] = None,
) -> ImpassabilityResult:
    """
    Compute impassability, passability, effective speed, and closure status for a road edge.
    Evaluates hard closures first (unconditional override), then multi-factor weighted score.
    """
    p = params or load_params()
    cond = condition or EdgeCondition()

    # 1. Existing manual closure on edge
    if edge.is_closed:
        return ImpassabilityResult(
            edge_id=edge.edge_id,
            impassability=1.0,
            passability=0.0,
            effective_speed_kmh=0.0,
            is_closed=True,
            closure_reason=edge.closure_reason or "MANUAL_CLOSURE",
        )

    # 2. Hard Closure Check: Flood Depth / Velocity (FINAL doc §6)
    hv_product = cond.water_depth_m * cond.water_velocity_mps
    if cond.water_depth_m >= p.flood_depth_critical or hv_product >= p.flood_hv_critical:
        reason = (
            f"CRITICAL_FLOOD_DEPTH_VELOCITY (depth={cond.water_depth_m:.2f}m >= {p.flood_depth_critical}m "
            f"or hv={hv_product:.2f} >= {p.flood_hv_critical})"
        )
        return ImpassabilityResult(
            edge_id=edge.edge_id,
            impassability=1.0,
            passability=0.0,
            effective_speed_kmh=0.0,
            is_closed=True,
            closure_reason=reason,
        )

    # 3. Hard Closure Check: Landslide Risk & 72h Rainfall (FINAL doc §6)
    if cond.landslide_risk >= p.landslide_risk_critical and cond.rainfall_72h_mm >= p.rainfall_72h_critical:
        reason = (
            f"CRITICAL_LANDSLIDE_DEBRIS_FLOW (risk={cond.landslide_risk:.2f} >= {p.landslide_risk_critical} "
            f"and rain={cond.rainfall_72h_mm:.1f}mm >= {p.rainfall_72h_critical}mm)"
        )
        return ImpassabilityResult(
            edge_id=edge.edge_id,
            impassability=1.0,
            passability=0.0,
            effective_speed_kmh=0.0,
            is_closed=True,
            closure_reason=reason,
        )

    # 4. Continuous Factor Calculations (FINAL doc §6)
    # R_e: Rainfall factor (normalized to critical threshold)
    r_factor = min(1.0, max(0.0, cond.rainfall_72h_mm / max(1.0, p.rainfall_72h_critical)))

    # F_e: Partial flood penalty: K_flood = 1 - 1.8 * depth  =>  F_e = 1.8 * depth
    if cond.water_depth_m > 0.0:
        f_factor = min(1.0, max(0.0, p.flood_k_coeff * cond.water_depth_m))
    else:
        f_factor = 0.0

    # S_e: Landslide / slope factor
    s_factor = min(1.0, max(0.0, cond.landslide_risk * (cond.rainfall_72h_mm / max(1.0, p.rainfall_72h_critical))))

    # H_e: General hazard ML score along edge
    h_factor = min(1.0, max(0.0, hazard_score))

    # C_e: Road structural condition / debris factor
    c_factor = min(1.0, max(0.0, (1.0 - cond.road_quality) + cond.debris_factor))

    # 5. Weighted Impassability I_e
    impassability = (
        (p.w_rainfall * r_factor)
        + (p.w_flood * f_factor)
        + (p.w_slope_landslide * s_factor)
        + (p.w_hazard * h_factor)
        + (p.w_condition * c_factor)
    )
    impassability = min(1.0, max(0.0, impassability))
    passability = 1.0 - impassability

    # 6. Effective Speed
    effective_speed = max(1.0, edge.base_speed_kmh * passability)

    return ImpassabilityResult(
        edge_id=edge.edge_id,
        impassability=round(impassability, 4),
        passability=round(passability, 4),
        effective_speed_kmh=round(effective_speed, 2),
        is_closed=False,
        closure_reason=None,
    )
