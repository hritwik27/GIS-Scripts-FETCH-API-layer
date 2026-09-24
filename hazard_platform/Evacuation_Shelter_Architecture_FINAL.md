# Evacuation, Shelter Capacity & Accessibility Engine — FINAL Reconciled Design

SIH 2026 · Problem Statement 26191 · hazard_platform

This document supersedes both the Master Design doc and the PDF workflow guide. It merges the two
per the reconciliation decisions below and is the version to build against for Phase 2 onward.

---

## 1. Core idea

**Hazard ML predicts danger. GIS represents population/roads/shelters. The evacuation engine
converts those into a constrained, explainable evacuation plan.**

The PDF's "school fire drill" analogy (count → assess → capacity → route → move) is kept as the
judge-facing explanation layer — it costs nothing and makes the pipeline legible in 30 seconds.
The underlying math is Master's, not the PDF's simplified version.

---

## 2. Frozen architecture

```
                     ┌─────────────────────┐
                     │ PUBLIC / AUTHORITY   │
                     │ DATA SOURCES         │
                     └──────────┬───────────┘
                                ↓
                ┌───────────────────────────┐
                │ GIS INGESTION              │
                │ Cleaning + Normalization   │
                │ Provenance + Freshness     │
                └─────────────┬─────────────┘
                                ↓
                ┌───────────────────────────┐
                │ HAZARD / GIS DATA STORE    │
                └─────────────┬─────────────┘
                                ↓
                ┌───────────────────────────┐
                │ HAZARD ML / PREDICTOR      │
                │ score / probability / extent│
                │ uncertainty + confidence   │
                └─────────────┬─────────────┘
                                ↓
              ┌─────────────────┴─────────────────┐
              ↓                                    ↓
       ZONE CLASSIFICATION                  EVACUATION ENGINE
       RED / YELLOW / GREEN                        │
                                                     │
                ┌────────────────────────────────────┼────────────────────┐
                ↓                                    ↓                    ↓
         POPULATION DEMAND                     ROAD NETWORK           SHELTERS
                │                                    │                    │
                ↓                                    ↓                    ↓
     Exposure + vulnerability                  Impassability        Safety check
     + mobility + warning                      + passability         + capacity
                │                                    │                    │
                └────────────────┬───────────────────┴────────────────────┘
                                  ↓
                            ROUTE ENGINE
                           Dijkstra / A*
                                  ↓
                       Route accessibility
                       + bottleneck analysis
                                  ↓
                      CAPACITY-AWARE ASSIGNMENT
                     Minimum-cost flow / CP-SAT
                                  ↓
                  ┌───────────────┴────────────────┐
                  ↓                                 ↓
           EVACUATION PLAN                   UNRESERVED /
                                              TRAPPED DEMAND
                  │                                 │
                  └───────────────┬─────────────────┘
                                  ↓
                        SCENARIO / RE-PLANNING
                     t0 → +1h → +3h → +6h
                                  ↓
                              FASTAPI
                                  ↓
                             DASHBOARD
```

RED/YELLOW/GREEN is retained as an **operational label layer** on top of the zone, computed from
Master's ML score, using PDF-derived default thresholds (see §4). It is not the primary math —
it is what the dashboard and field officers see.

---

## 3. Evacuation demand

Master's multi-factor model is the source of truth for the actual number of people to move:

```
E_i = P_i × X_i × H_i × V_i × M_i
```

- `P_i` — population (Census 2011 ward / WorldPop raster)
- `X_i` — exposed fraction
- `H_i` — hazard-response factor
- `V_i` — vulnerability (see below — kept group-specific, not PDF's single multiplier)
- `M_i` — mobility / evacuation participation factor

**PDF's contribution:** the piecewise `E_hazard` classification (risk ≥ 0.70 → full evacuation,
0.40–0.70 → partial, < 0.70 → none) is kept, but *only* as the rule that assigns RED/YELLOW/GREEN.
It does not replace `H_i` in the demand formula — using it as a hard gate on `X_i`/`H_i` would
throw away the continuous ML score for no benefit.

If the ML model outputs a calibrated probability, treat it as a probability. If it outputs an
uncalibrated score, label it a score and do not present it as a probability to the dashboard or
judges.

### Vulnerability (kept group-specific, per Master)

PDF's single multiplier:

```
V_vuln = 1 + 0.25·φ_kutcha + 0.20·φ_dependent
```

is retained as a **documented, literature-backed default weighting**, but implemented as a
group-specific model (separate kutcha-housing and dependent-population terms are tracked
individually, not only combined), so it can be extended per hazard type or region without
redefining the formula.

---

## 4. Zone classification (RED / YELLOW / GREEN)

Retained from the PDF as the operational layer, with thresholds moved into config
(`zone_thresholds.yaml` or similar) rather than hardcoded:

```
RED    = any hazard score >= red_threshold      (default 0.70)
YELLOW = any hazard score >= yellow_threshold    (default 0.40)
GREEN  = all hazard scores < yellow_threshold
```

Defaults come from the PDF but are per-hazard-type overridable, since flood/landslide/erosion/
cloudburst do not share a natural scale.

---

## 5. Shelter capacity

**Primary method (Master):**

```
UsableCapacity_j   = NominalCapacity_j - CurrentOccupancy_j - Reserved_j
EffectiveCapacity_j = UsableCapacity_j × OperationalFactor_j × SafetyFactor_j
```

Capacity source priority:

1. Authority-verified capacity (District Collector / Patwari register, when available)
2. Verified floor area × occupancy standard (fallback)
3. GIS-estimated usable area × occupancy standard (last-resort fallback, from PDF's
   `A_usable = π(500m)² × μ_slope` method)

**Changes from the PDF, both required:**

- **The 45 m²/person Sphere standard is not hardcoded.** It is a configurable default
  (`sq_m_per_person`, authority/standard-dependent), because different jurisdictions and shelter
  types may use different occupancy standards.
- **`C_spare = max(100, C_raw - P_existing)` is removed entirely.** This is a bug in the PDF, not
  a design choice — it forces every shelter to report at least 100 spare slots even when it is
  genuinely full or over capacity. `EffectiveCapacity_j` must be allowed to reach zero (or, if
  occupancy exceeds nominal capacity, to be treated as negative/over-capacity for alerting
  purposes).

Shelter eligibility also requires a **safety check** (Master): a shelter physically having space
does not make it usable if it sits inside a currently-hazardous zone. This is checked before
assignment, not assumed from GREEN classification alone.

---

## 6. Road impassability & route accessibility

**Primary model (Master, continuous and configurable):**

```
I_e = wR·R_e + wF·F_e + wS·S_e + wH·H_e + wC·C_e         (Σw = 1)
Passability_e = 1 - I_e
```

Hard closures override the weighted score unconditionally.

```
I_route = Σ(L_e · I_e) / ΣL_e
A_route = 1 - I_route
A_final = A_route × min(Passability_e)
```

**PDF's contribution:** concrete, literature-referenced threshold values are kept as the
**default configuration** for the flood/landslide components of `I_e`, rather than as separate
hardcoded cut rules:

- Flood: `water_depth ≥ 0.30m` OR `depth × velocity ≥ 0.6` → treated as hard closure
  (`I_e → 1`, not weighted); `0 < depth < 0.30m` → `K_flood = 1 − 1.8·depth`, feeding into `F_e`
- Landslide: `landslide_risk ≥ 0.75 AND 72hr_rainfall ≥ 150mm` → hard closure; otherwise no
  penalty by default, feeding into `S_e`

Keeping these as config means the same continuous model can be recalibrated per region without
code changes, while still shipping with the PDF's defensible, literature-backed starting values.

---

## 7. Routing

```
T_e = length_e / effective_speed_e
cost_e = α·T_e + β·I_e + γ·Risk_e
```

- **MVP:** Dijkstra/A* (both PDF and Master agree here) — hide or infinite-weight any edge with a
  hard closure.
- **Upgrade path:** minimum-cost flow / CP-SAT once capacity constraints across many
  origin-shelter pairs become significant (Master). Do not start this before Dijkstra + simple
  capacity-aware assignment is working end-to-end.

**Trapped state (added from PDF, not present in Master):**

If no path exists from a RED/YELLOW zone to any shelter with remaining effective capacity, the
zone is flagged **TRAPPED / INACCESSIBLE**. This is a first-class state on the zone/demand record,
not a UI-only concept — it must be queryable and it must escalate (analogous to PDF's "NDRF aerial
rescue" flag) rather than silently dropping that population from the plan.

---

## 8. Capacity-constrained assignment

**MVP heuristic (both docs agree, PDF's greedy nearest-shelter-with-space and Master's weighted
heuristic converge here):**

```
W_ij = (A_ij × S_j) / max(T_ij, ε)
P_ij = W_ij / Σ_k W_ik
x_ij = E_i × P_ij
```

**Formal model (Master, for later):**

```
min Σ_i Σ_j cost_ij · x_ij
subject to:
  Σ_j x_ij ≤ E_i
  Σ_i x_ij ≤ C_j
  x_ij ≥ 0
  x_ij = 0 for infeasible pairs

Unserved_i = E_i - Σ_j x_ij
```

Unserved/trapped demand must be surfaced explicitly with a high penalty rather than forced into an
infeasible assignment or silently discarded.

---

## 9. Provenance, fallback, uncertainty

Kept as Master (PDF has essentially none of this):

- Every reading carries `source`, `recorded_at` (freshness), `data_quality`/confidence, and
  `fallback_used`.
- Provider fallback chain (retry → cache → alternate provider → stale flag) per Master's risk
  table.
- Hazard ML outputs uncertainty/confidence alongside score — never presented as a bare number
  without a confidence indicator.

---

## 10. Scenario / re-planning

Kept as Master: `t0 → +1h → +3h → +6h` re-planning loop, re-running classification, demand,
routing, and assignment as conditions change. This is the first component to cut under time
pressure — a static plan is still a complete, demoable system without it.

---

## 11. Dashboard

Combined, per reconciliation:

- **Default view (from PDF):** simple operational map — RED/YELLOW/GREEN zones, evacuation counts,
  shelter capacity, routes, TRAPPED flags. This is what a field officer or judge sees first.
- **Secondary view (from Master):** analytical layer — provenance/freshness per reading,
  uncertainty bands, bottleneck analysis, scenario comparison.

---

## 12. Innovation claim

Master's framing is used, not the PDF's. Do **not** claim "no existing system combines all of
these" — it's an easy claim for judges to challenge (NDMIS, CWC/WRIS, GSI LEWS, SATARK, FEMA
Hazus-MH, HEC-LifeSim, UN OCHA/CCCM, UNHCR ProGres v4 all do *pieces* of this).

Defensible framing: the integrated pipeline is the contribution —

1. hazard-aware evacuation demand
2. dynamic road impassability
3. accessibility-weighted reachability
4. shelter safety + effective capacity
5. capacity-constrained assignment
6. explainable bottlenecks
7. provider fallbacks + freshness/provenance
8. scenario-based re-planning

The PDF's list of what existing Indian/global systems are missing (routing, automated capacity,
population integration) is still useful as *supporting evidence* for this framing — just not as a
"nobody has ever done this" claim.

---

## 13. Module layout

```
evacuation/
├── models.py
├── population.py
├── shelters.py
├── road_network.py
├── impassability.py
├── accessibility.py
├── routing.py
├── assignment.py
├── capacity.py
├── scenarios.py
└── provenance.py
```

---

## 14. Future roadmap (Master, extensive — kept over PDF's shorter list)

Time-dependent traffic/congestion · pedestrian/vehicle/assisted evacuation modes · road capacity
and queueing · multi-shelter staging · live road closures · live shelter occupancy · uncertainty
bands · ensemble hazard forecasts · agent-based evacuation simulation · dynamic re-routing ·
multilingual public guidance · SMS/app integration · offline mode · authority override/audit logs
· automated weight calibration · reinforcement learning only after a validated deterministic
baseline.

---

## 15. Engineering risks

| Problem | Solution |
|---|---|
| API outage | retry + cache + alternate provider + stale flag |
| OSM incompleteness | local authority data + confidence |
| Unknown shelter capacity | verified registry + conservative estimate |
| Shelter becomes unsafe | hazard re-check before assignment |
| Double counting | conservation constraints |
| Shelter overflow | optimization + reallocation |
| One bad road hidden by average | bottleneck metric |
| ML score misinterpreted | calibration / clear semantics |
| Mixed data vintages | source / vintage / timestamp |
| Slow optimization | candidate filtering + caching + min-cost flow |
| Connectivity failure | local graph + cached shelter/hazard snapshot |
| Shelter always reports ≥100 spare slots regardless of true occupancy (PDF bug) | removed — `max(100, ...)` floor dropped from capacity calc |

---

## 16. Testing / validation

Kept as Master (extensive) over PDF (limited): unit tests per module (capacity, impassability,
routing, assignment), integration tests across the full 12-state dataset, and validation of
AHP/weighted-formula scorer weights (CR < 0.10, per existing `WEIGHT_JUSTIFICATION.md`).
