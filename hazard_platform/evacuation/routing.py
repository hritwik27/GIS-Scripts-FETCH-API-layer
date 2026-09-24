"""
evacuation/routing.py -- Dijkstra/A* evacuation pathfinder with hazard-aware edge weighting (FINAL doc §7).

Mathematical Model:
    T_e = length_e / effective_speed_e        (travel time in hours)
    cost_e = alpha * T_e + beta * I_e + gamma * Risk_e

Constraints:
- Closed edges (is_closed == True or I_e >= 1.0) are completely impenetrable (cost = inf).
- Evaluates route accessibility via evacuation/accessibility.py:
    A_final = A_route * min(Passability_e)
- Detects bottlenecks along the optimal route.
"""

from __future__ import annotations

import heapq
from dataclasses import dataclass, fields
from pathlib import Path
from typing import Optional, Union

from evacuation.accessibility import calculate_route_accessibility
from evacuation.impassability import calculate_edge_impassability, load_params as load_impassability_params
from evacuation.models import EdgeCondition, ImpassabilityResult, RoadEdge, RouteResult
from evacuation.road_network import RoadNetworkGraph

PARAMS_PATH = Path(__file__).with_name("evacuation_params.yaml")


@dataclass(frozen=True)
class RoutingParams:
    alpha: float = 1.0   # Weight for travel time (hours)
    beta: float = 0.5    # Weight for edge impassability I_e
    gamma: float = 0.5   # Weight for hazard risk along edge


def load_params(path: Union[str, Path, None] = None) -> RoutingParams:
    """Read `routing:` section from YAML, returning defaults if absent."""
    path = Path(path) if path else PARAMS_PATH
    if not path.exists():
        return RoutingParams()
    import yaml

    data = (yaml.safe_load(path.read_text(encoding="utf-8")) or {}).get("routing", {})
    valid_fields = {f.name for f in fields(RoutingParams)}
    filtered = {k: v for k, v in data.items() if k in valid_fields}
    return RoutingParams(**filtered)


def find_shortest_route(
    graph: RoadNetworkGraph,
    origin_node_id: str,
    destination_node_id: str,
    *,
    hazard_score: float = 0.0,
    params: Optional[RoutingParams] = None,
) -> RouteResult:
    """
    Find the optimal evacuation route between two nodes using Dijkstra's algorithm
    weighted by travel time, road impassability, and hazard risk.
    """
    p = params or load_params()

    if origin_node_id not in graph.nodes or destination_node_id not in graph.nodes:
        return RouteResult(found=False, total_cost=float("inf"), accessibility=0.0)

    if origin_node_id == destination_node_id:
        return RouteResult(
            found=True,
            path_nodes=[origin_node_id],
            edge_ids=[],
            total_distance_km=0.0,
            total_time_hours=0.0,
            total_cost=0.0,
            accessibility=1.0,
            bottleneck_edge_id=None,
            bottleneck_reason=None,
        )

    # Priority queue: (cost, node_id)
    pq: list[tuple[float, str]] = [(0.0, origin_node_id)]
    
    # Track lowest cost and route traversal:
    # best[node_id] = (cost, distance_m, time_hours, prev_node, prev_edge_id, edge_impass_res)
    best: dict[str, tuple[float, float, float, Optional[str], Optional[str], Optional[ImpassabilityResult]]] = {
        origin_node_id: (0.0, 0.0, 0.0, None, None, None)
    }

    visited = set()

    while pq:
        current_cost, u = heapq.heappop(pq)

        if u in visited:
            continue
        visited.add(u)

        if u == destination_node_id:
            break

        for edge in graph.get_outgoing_edges(u):
            v = edge.v
            if v in visited:
                continue

            # Calculate dynamic edge impassability
            cond = graph.get_edge_condition(edge.edge_id)
            imp_res = calculate_edge_impassability(edge, cond, hazard_score=hazard_score)

            # Impassable / closed edges cannot be traversed
            if imp_res.is_closed or imp_res.impassability >= 1.0:
                continue

            # Travel time: length (km) / effective speed (km/h)
            dist_km = edge.length_m / 1000.0
            speed = max(1.0, imp_res.effective_speed_kmh)
            time_hours = dist_km / speed

            # Edge cost = alpha*T_e + beta*I_e + gamma*Risk_e (FINAL doc §7)
            edge_cost = (p.alpha * time_hours) + (p.beta * imp_res.impassability) + (p.gamma * hazard_score)
            new_cost = current_cost + edge_cost

            if v not in best or new_cost < best[v][0]:
                u_dist = best[u][1]
                u_time = best[u][2]
                best[v] = (
                    new_cost,
                    u_dist + edge.length_m,
                    u_time + time_hours,
                    u,
                    edge.edge_id,
                    imp_res,
                )
                heapq.heappush(pq, (new_cost, v))

    if destination_node_id not in visited:
        return RouteResult(found=False, total_cost=float("inf"), accessibility=0.0)

    # Reconstruct path
    curr = destination_node_id
    path_nodes = []
    edge_ids = []
    edge_impass_results = []

    while curr is not None:
        path_nodes.append(curr)
        prev_node = best[curr][3]
        edge_id = best[curr][4]
        imp_res = best[curr][5]
        if edge_id:
            edge_ids.append(edge_id)
            edge_obj = graph.get_edge(edge_id)
            length_m = edge_obj.length_m if edge_obj else 0.0
            if imp_res:
                edge_impass_results.append((length_m, imp_res))
        curr = prev_node

    path_nodes.reverse()
    edge_ids.reverse()
    edge_impass_results.reverse()

    total_cost, total_dist_m, total_time_hours, _, _, _ = best[destination_node_id]

    # Calculate compound route accessibility and bottleneck analysis
    acc_res = calculate_route_accessibility(edge_impass_results)

    return RouteResult(
        found=True,
        path_nodes=path_nodes,
        edge_ids=edge_ids,
        total_distance_km=round(total_dist_m / 1000.0, 3),
        total_time_hours=round(total_time_hours, 4),
        total_cost=round(total_cost, 4),
        accessibility=acc_res.final_accessibility,
        bottleneck_edge_id=acc_res.bottleneck_edge_id,
        bottleneck_reason=acc_res.bottleneck_reason,
    )


def route_between_points(
    graph: RoadNetworkGraph,
    origin_lat: float,
    origin_lon: float,
    dest_lat: float,
    dest_lon: float,
    *,
    hazard_score: float = 0.0,
    params: Optional[RoutingParams] = None,
) -> RouteResult:
    """
    Find optimal route between two arbitrary lat/lon coordinates
    by mapping to nearest nodes on the road graph.
    """
    start_node = graph.find_nearest_node(origin_lat, origin_lon)
    end_node = graph.find_nearest_node(dest_lat, dest_lon)

    if not start_node or not end_node:
        return RouteResult(found=False, total_cost=float("inf"), accessibility=0.0)

    return find_shortest_route(
        graph,
        start_node.node_id,
        end_node.node_id,
        hazard_score=hazard_score,
        params=params,
    )
