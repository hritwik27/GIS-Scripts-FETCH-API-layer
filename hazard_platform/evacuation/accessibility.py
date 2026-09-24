"""
evacuation/accessibility.py -- route-level accessibility and bottleneck analysis (FINAL doc §6).

Mathematical Model:
    I_route = sum(L_e * I_e) / sum(L_e)
    A_route = 1.0 - I_route
    A_final = A_route * min(Passability_e)

Bottleneck Analysis:
    Identifies the single critical bottleneck edge along the evacuation route
    (lowest passability / highest impassability), ensuring that a single failing
    bridge or flooded underpass cannot be masked by a long highway average.
"""

from __future__ import annotations

from typing import Iterable, Optional

from evacuation.models import ImpassabilityResult, RouteAccessibilityResult


def calculate_route_accessibility(
    edge_results: Iterable[tuple[float, ImpassabilityResult]],
) -> RouteAccessibilityResult:
    """
    Calculate route-level accessibility and bottleneck characteristics.

    Args:
        edge_results: Iterable of (length_m, ImpassabilityResult) for each edge along the path.

    Returns:
        RouteAccessibilityResult with route impassability, accessibility,
        min passability, final compound accessibility, and bottleneck identification.
    """
    edge_list = list(edge_results)

    if not edge_list:
        return RouteAccessibilityResult(
            route_impassability=0.0,
            route_accessibility=1.0,
            min_passability=1.0,
            final_accessibility=1.0,
            bottleneck_edge_id=None,
            bottleneck_reason=None,
        )

    total_length = sum(length for length, _ in edge_list)
    if total_length <= 0:
        total_length = 1.0

    weighted_impassability = sum(length * res.impassability for length, res in edge_list)
    route_impassability = min(1.0, max(0.0, weighted_impassability / total_length))
    route_accessibility = 1.0 - route_impassability

    # Find the bottleneck edge (lowest passability)
    bottleneck_edge_id: Optional[str] = None
    bottleneck_reason: Optional[str] = None
    min_passability = 1.0

    for _, res in edge_list:
        if res.is_closed:
            min_passability = 0.0
            bottleneck_edge_id = res.edge_id
            bottleneck_reason = res.closure_reason or "HARD_ROAD_CLOSURE"
            break  # Hard closure immediately dominates

        if res.passability < min_passability:
            min_passability = res.passability
            bottleneck_edge_id = res.edge_id
            bottleneck_reason = f"LOW_PASSABILITY (passability={res.passability:.2f}, impassability={res.impassability:.2f})"

    # A_final = A_route * min(Passability_e)
    final_accessibility = min(1.0, max(0.0, route_accessibility * min_passability))

    return RouteAccessibilityResult(
        route_impassability=round(route_impassability, 4),
        route_accessibility=round(route_accessibility, 4),
        min_passability=round(min_passability, 4),
        final_accessibility=round(final_accessibility, 4),
        bottleneck_edge_id=bottleneck_edge_id,
        bottleneck_reason=bottleneck_reason,
    )
