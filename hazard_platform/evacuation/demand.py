"""
evacuation/demand.py -- evacuation demand (FINAL doc section 3).

    E_i = P_i x X_i x H_i x V_i x M_i

    P_i  population                  (evacuation/population.py)
    X_i  exposed fraction            (config, PLACEHOLDER 1.0)
    H_i  hazard-response factor      = the CONTINUOUS worst ML score, 0 if GREEN
    V_i  vulnerability               = 1 + 0.25*phi_kutcha + 0.20*phi_dependent
    M_i  mobility / participation    (config, PLACEHOLDER 1.0)

Pure function: no I/O, no network, safe to call from a background job.
Takes plain values (not store objects) so it never touches ingestion.

DESIGN NOTE: the literal product can exceed P_i x X_i (V_i > 1 and H_i near
1), which would mean moving more people than are exposed. The factor
H*V*M is capped at 1.0 and `capped=True` is recorded on the result.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from typing import Optional, Union

PARAMS_PATH = Path(__file__).with_name("evacuation_params.yaml")


@dataclass(frozen=True)
class DemandParams:
    exposed_fraction: float = 1.0
    mobility: float = 1.0
    kutcha_weight: float = 0.25
    dependent_weight: float = 0.20
    phi_kutcha: float = 0.10       # PLACEHOLDER, not sourced
    phi_dependent: float = 0.35    # PLACEHOLDER, not sourced


@dataclass
class DemandResult:
    zone_id: str
    status: str                    # "ok" | "no_evacuation" | "no_population_data"
    population: Optional[float]
    exposed_fraction: float
    hazard_factor: float
    vulnerability: float
    mobility: float
    demand: Optional[int]          # people to move; None if population unknown
    capped: bool                   # True if H*V*M exceeded 1.0 and was clamped
    vulnerability_is_placeholder: bool

    def to_dict(self) -> dict:
        return asdict(self)


def load_params(path: Union[str, Path, None] = None) -> DemandParams:
    """Read the `demand:` section of the YAML; defaults if the file is absent."""
    path = Path(path) if path else PARAMS_PATH
    if not path.exists():
        return DemandParams()
    import yaml

    data = (yaml.safe_load(path.read_text(encoding="utf-8")) or {}).get("demand", {})
    unknown = set(data) - {f.name for f in fields(DemandParams)}
    if unknown:
        raise ValueError(f"Unknown demand param(s) in {path}: {sorted(unknown)}")
    return DemandParams(**data)


def _color_str(color) -> str:
    return str(getattr(color, "value", color)).upper()


def compute_demand(
    zone_id: str,
    population: Optional[float],
    color,
    worst_score: float,
    *,
    params: Optional[DemandParams] = None,
    phi_kutcha: Optional[float] = None,
    phi_dependent: Optional[float] = None,
) -> DemandResult:
    """`color`: ZoneColor or "RED"/"YELLOW"/"GREEN". `phi_*`: real census
    fractions if you have them; otherwise the params' placeholders are used."""
    p = params or DemandParams()
    using_placeholder = phi_kutcha is None or phi_dependent is None
    pk = p.phi_kutcha if phi_kutcha is None else phi_kutcha
    pd = p.phi_dependent if phi_dependent is None else phi_dependent
    vulnerability = 1.0 + p.kutcha_weight * pk + p.dependent_weight * pd

    is_green = _color_str(color) == "GREEN"
    hazard_factor = 0.0 if is_green else min(1.0, max(0.0, float(worst_score)))

    if population is None or population <= 0:
        return DemandResult(zone_id, "no_population_data", population, p.exposed_fraction,
                            hazard_factor, vulnerability, p.mobility, None, False, using_placeholder)

    combined = hazard_factor * vulnerability * p.mobility
    capped = combined > 1.0
    exposed = population * p.exposed_fraction
    people = exposed * min(1.0, combined)
    demand = math.ceil(round(people, 6))  # round first: avoids 9855.000000000002 -> 9856

    status = "no_evacuation" if demand == 0 else "ok"
    return DemandResult(zone_id, status, population, p.exposed_fraction, hazard_factor,
                        vulnerability, p.mobility, demand, capped, using_placeholder)