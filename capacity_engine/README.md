# Capacity & Evacuation Demand Engine
### Standalone Modular Package for ML Disaster Pipelines

A self-contained, zero-dependency Python mathematical engine for computing **evacuation demand**, **shelter effective capacity with safety derating**, and **capacity-constrained corridor evacuation assignments**.

Designed to plug directly into Machine Learning hazard forecasting models (flood inundation, storm surge, cyclone wind grids).

---

## Key Features

1. **Pure Python Standard Library**: Runs anywhere (`math`, `dataclasses`, `typing`, `enum`) without requiring GDAL, GeoPandas, or external databases. Optional `PyYAML` support for `config.yaml` with automatic fallback to built-in constants.
2. **ML Interface Ready**: Accepts continuous hazard scores $H_i \in [0.0, 1.0]$ or zone classifications (`GREEN`, `YELLOW`, `RED`).
3. **Sphere Standards & Safeguards**:
   - $3.5\,\text{m}^2/\text{person}$ net floor area standard.
   - Eliminates the artificial $\max(100, \dots)$ capacity floor bug. Over-capacity shelters report true usable/effective values ($\le 0$) and 0 assignable slots.
   - Shelters in `RED` zones are flagged `UNSAFE` (0.0 safety factor) and never receive evacuees.
   - Shelters in `YELLOW` zones are derated by 50% (`CAUTION`, 0.5 safety factor).
4. **First-Class Escalation States**:
   - **`CAPACITY_DEFICIT`**: Demand exceeds safe regional capacity $\rightarrow$ `EXTERNAL_STAGING_REQUIRED`.
   - **`TRAPPED`**: All access severed or all local shelters inundated $\rightarrow$ `NDRF_AERIAL_RESCUE_REQUIRED`.

---

## Mathematical Formulations

### 1. Evacuation Demand ($E_i$)

$$E_i = P_i \times X_i \times \min\Big(1.0, H_i \times V_i \times M_i\Big)$$

- $P_i$: Total zone population.
- $X_i$: Fraction physically exposed to the hazard (default: `1.0`).
- $H_i$: Continuous hazard score from ML prediction:
  - If zone is `GREEN`: $H_i = 0.0 \implies E_i = 0$ (no mandatory evacuation).
  - If zone is `YELLOW` or `RED`: $H_i \in (0.0, 1.0]$.
- $V_i$: Socioeconomic vulnerability multiplier:
  $$V_i = 1.0 + 0.25\,\phi_{\text{kutcha}} + 0.20\,\phi_{\text{dependent}}$$
- $M_i$: Evacuation participation & mobility factor (default: `1.0`).
- **Conservation Law**: The combined factor $H_i \times V_i \times M_i$ is strictly clamped to $\le 1.0$, ensuring evacuation demand never exceeds exposed population ($P_i \times X_i$).

### 2. Effective Shelter Capacity ($Effective_j$)

$$Usable_j = Nominal_j - Occupancy_j - Reserved_j$$
$$Effective_j = Usable_j \times OperationalFactor \times SafetyFactor_j$$
$$Assignable_j = \max(0, Effective_j)$$

| Shelter Hazard Zone | Safety Status | Safety Factor ($S_j$) | Effective Multiplier |
| :--- | :--- | :--- | :--- |
| **GREEN** | `SAFE` | $1.0$ | $100\%$ usable capacity |
| **YELLOW** | `CAUTION` | $0.5$ | $50\%$ derating (hazard buffer) |
| **RED** | `UNSAFE` | $0.0$ | $0\%$ (shelter is in direct danger) |
| *Unknown / None* | `UNVERIFIED` | $0.0$ | $0\%$ (fail-safe zero assignment) |

### 3. Capacity-Constrained Assignment Heuristic

$$W_{ij} = \frac{A_{ij} \times S_j}{\max(T_{ij}, \epsilon)}$$
$$P_{ij} = \frac{W_{ij}}{\sum_k W_{ik}}$$
$$x_{ij} = \min\Big(C_j, \text{round}(E_i \times P_{ij})\Big)$$

- $W_{ij}$: Route attractiveness weight.
- $A_{ij}$: Corridor accessibility / passability score ($0.0 \le A_{ij} \le 1.0$).
- $S_j$: Shelter safety factor.
- $T_{ij}$: Estimated transit travel time in hours:
  $$T_{ij} = \frac{\text{HaversineDistance}(i, j) \times \text{DetourFactor}}{\text{ConvoySpeed}}$$
- $C_j$: Remaining assignable capacity of shelter $j$.
- $x_{ij}$: Evacuees dispatched from zone $i$ to shelter $j$. Followed by a greedy second-pass fill up to capacity bounds.

---

## Directory Structure

```text
capacity_engine/
├── __init__.py         # Package exports
├── models.py           # Pure dataclasses: ShelterCapacity, DemandResult, ZoneAssignmentResult
├── config.yaml         # Configurable parameters (Sphere area, speeds, weights)
├── capacity.py         # Effective capacity & safety derating algorithms
├── demand.py           # Vulnerability-adjusted demand computation
├── assignment.py       # Corridor travel time, gravity routing & escalation
├── runner.py           # 4-scenario simulation CLI demo
└── test_engine.py      # Standalone verification test suite
```

---

## Quickstart for ML Engineers

### Running the Included Scenarios & Tests

```bash
# 1. Run the interactive simulation (demonstrates Green, Yellow, Deficit, and Trapped)
python runner.py

# 2. Run the test suite (100% assertions passing)
python test_engine.py
```

### Minimal Python Integration

```python
from capacity_engine import (
    compute_demand,
    compute_shelter_capacity,
    assign_zone,
    AssignmentStatus,
    EscalationLevel,
)

# -------------------------------------------------------------
# 1. Output from your ML Model
# -------------------------------------------------------------
zone_id = "ZONE-COASTAL-42"
predicted_hazard = 0.88          # e.g., Flood depth / surge model output
zone_color = "RED" if predicted_hazard >= 0.70 else "YELLOW" if predicted_hazard >= 0.30 else "GREEN"
zone_population = 6500

# -------------------------------------------------------------
# 2. Compute Evacuation Demand
# -------------------------------------------------------------
demand_result = compute_demand(
    zone_id=zone_id,
    population=zone_population,
    zone_color=zone_color,
    worst_hazard_score=predicted_hazard,
    phi_kutcha=0.40,       # 40% kutcha / mud-thatch housing
    phi_dependent=0.30,    # 30% elderly and children
)

print(f"Demand: {demand_result.demand} evacuees (Status: {demand_result.status})")

# -------------------------------------------------------------
# 3. Assess Available Shelters
# -------------------------------------------------------------
raw_shelters = [
    {"shelter_id": "S-LOCAL", "name": "Beachside Hall", "lat": 19.80, "lon": 85.80, "nominal_capacity": 1000, "zone_color": "RED"},
    {"shelter_id": "S-INLAND", "name": "District Stadium", "lat": 19.86, "lon": 85.75, "nominal_capacity": 4000, "zone_color": "GREEN"},
]

evaluated_shelters = [
    compute_shelter_capacity(s, zone_color=s["zone_color"]) for s in raw_shelters
]

# S-LOCAL is automatically derated to 0 assignable because it is inside RED zone!

# -------------------------------------------------------------
# 4. Dispatch Assignments & Check Escalations
# -------------------------------------------------------------
assignment_result = assign_zone(
    zone_id=zone_id,
    origin_lat=19.80,
    origin_lon=85.81,
    demand=demand_result.demand,
    candidate_shelters=evaluated_shelters,
)

print(f"Status: {assignment_result.status.value}")
print(f"Assigned: {assignment_result.total_assigned} / Unserved: {assignment_result.unserved}")
print(f"Escalation: {assignment_result.escalation.value}")

for a in assignment_result.assignments:
    print(f" -> {a.shelter_name}: {a.assigned_evacuees} people | Travel Time: {a.transit_time_hours*60:.1f} mins")
```

---

## Configuration (`config.yaml`)

You can tune default operational parameters in `config.yaml` without changing code:

```yaml
capacity:
  operational_factor: 1.0     # Usability fraction (e.g. 0.9 if 10% lost to logistics)
  sq_m_per_person: 3.5        # Sphere standard area (m² per person)
  safety_factors:
    SAFE: 1.0                 # Green zone shelter
    CAUTION: 0.5              # Yellow zone shelter
    UNSAFE: 0.0               # Red zone shelter
    UNVERIFIED: 0.0

demand:
  exposed_fraction: 1.0       # Spatial exposure fraction
  mobility: 1.0               # Evacuation participation
  kutcha_weight: 0.25         # Sensitivity to mud/thatch housing
  dependent_weight: 0.20      # Sensitivity to elderly/child ratio

assignment:
  detour_factor: 1.4          # Road winding multiplier vs straight line
  speed_kmh: 25.0             # Evacuation convoy travel speed
  max_distance_km: 50.0       # Maximum feasible relocation distance
```
