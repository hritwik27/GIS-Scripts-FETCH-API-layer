"""demand.py -- Evacuation demand estimation with group-specific vulnerability.

Mathematical formulation (Section 3 of Evacuation & Shelter Architecture):
    E_i = P_i x X_i x H_i x V_i x M_i

Where:
    P_i = Total zone population (from Census or WorldPop raster)
    X_i = Exposed fraction within the hazard zone (default 1.0)
    H_i = Continuous worst hazard score (0.0 for GREEN zones, continuous score for YELLOW/RED)
    V_i = Group-specific vulnerability multiplier:
          V_vuln = 1 + 0.25·φ_kutcha + 0.20·φ_dependent
    M_i = Evacuation participation & mobility factor (default 1.0)

Conservation Constraint:
    The product H_i x V_i x M_i is clamped to 1.0 so that an evacuation demand can NEVER
    exceed the physically exposed population (P_i x X_i).
"""
from __future__ import annotations

import math
from dataclasses import dataclass, fields
from pathlib import Path
from typing import Any, Optional, Union

from .models import DemandResult

CONFIG_PATH = Path(__file__).with_name("config.yaml")


@dataclass(frozen=True)
class DemandParams:
    exposed_fraction: float = 1.0
    mobility: float = 1.0
    kutcha_weight: float = 0.25
    dependent_weight: float = 0.20
    phi_kutcha: float = 0.10
    phi_dependent: float = 0.35


def load_params(path: Union[str, Path, None] = None) -> DemandParams:
    """Load demand parameters from YAML or fallback to defaults."""
    cfg_file = Path(path) if path else CONFIG_PATH
    if not cfg_file.exists():
        return DemandParams()
    try:
        import yaml
        data = (yaml.safe_load(cfg_file.read_text(encoding="utf-8")) or {}).get("demand", {})
        valid = {f.name for f in fields(DemandParams)}
        filtered = {k: float(v) for k, v in data.items() if k in valid}
        return DemandParams(**filtered)
    except Exception:
        return DemandParams()


def calculate_vulnerability(
    phi_kutcha: Optional[float] = None,
    phi_dependent: Optional[float] = None,
    params: Optional[DemandParams] = None,
) -> tuple[float, bool]:
    """Calculate the vulnerability multiplier V_i.
    Returns (vulnerability_value, is_placeholder).
    """
    p = params or DemandParams()
    is_placeholder = (phi_kutcha is None or phi_dependent is None)
    pk = p.phi_kutcha if phi_kutcha is None else max(0.0, min(1.0, float(phi_kutcha)))
    pd = p.phi_dependent if phi_dependent is None else max(0.0, min(1.0, float(phi_dependent)))
    vuln = 1.0 + p.kutcha_weight * pk + p.dependent_weight * pd
    return vuln, is_placeholder


def compute_demand(
    zone_id: str,
    population: Optional[float],
    zone_color: Any,
    worst_hazard_score: float,
    *,
    params: Optional[DemandParams] = None,
    phi_kutcha: Optional[float] = None,
    phi_dependent: Optional[float] = None,
) -> DemandResult:
    """Compute evacuation demand E_i for a zone given its population and hazard intensity.
    `zone_color` can be ZoneColor enum or string ("GREEN", "YELLOW", "RED").
    """
    p = params or DemandParams()
    vulnerability, is_placeholder = calculate_vulnerability(phi_kutcha, phi_dependent, p)

    color_str = str(getattr(zone_color, "value", zone_color)).upper()
    is_green = (color_str == "GREEN")

    # GREEN zones require no evacuation; YELLOW and RED use continuous hazard score
    hazard_factor = 0.0 if is_green else min(1.0, max(0.0, float(worst_hazard_score)))

    if population is None or population <= 0:
        return DemandResult(
            zone_id=zone_id,
            status="no_population_data",
            population=population,
            exposed_fraction=p.exposed_fraction,
            hazard_factor=hazard_factor,
            vulnerability=vulnerability,
            mobility=p.mobility,
            demand=None,
            capped=False,
            vulnerability_is_placeholder=is_placeholder,
        )

    combined_factor = hazard_factor * vulnerability * p.mobility
    capped = combined_factor > 1.0
    effective_factor = min(1.0, combined_factor)

    raw_demand = population * p.exposed_fraction * effective_factor
    demand_int = int(math.ceil(raw_demand)) if raw_demand > 0 else 0
    status = "no_evacuation" if demand_int == 0 else "ok"

    return DemandResult(
        zone_id=zone_id,
        status=status,
        population=population,
        exposed_fraction=p.exposed_fraction,
        hazard_factor=hazard_factor,
        vulnerability=vulnerability,
        mobility=p.mobility,
        demand=demand_int,
        capped=capped,
        vulnerability_is_placeholder=is_placeholder,
    )
