"""
evacuation/road_network.py -- road network topology and corridor graphs (FINAL doc §6, §7, §13).

Provides:
- RoadNetworkGraph: Graph structure for road nodes, edges, adjacency, and dynamic conditions.
- Corridor network generator: Builds connected realistic evacuation road graphs connecting
  zone origins to shelters with realistic hierarchies (highway, primary, secondary, local).
- Spatial querying: Find nearest road node to coordinates (origins, shelters, clicked points).
- GeoJSON export: Ready for Leaflet / MapLibre frontend visualization.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Optional, Union

from evacuation.models import EdgeCondition, RoadEdge, RoadNode

PARAMS_PATH = Path(__file__).with_name("evacuation_params.yaml")


def haversine_distance_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in meters between two coordinates."""
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)

    a = math.sin(delta_phi / 2.0) ** 2 + (
        math.cos(phi1) * math.cos(phi2) * (math.sin(delta_lambda / 2.0) ** 2)
    )
    c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))
    return 6371000.0 * c


class RoadNetworkGraph:
    """
    Topological road graph for evacuation routing and impassability analysis.
    Stores nodes, edges, adjacency, and dynamic edge hazard conditions.
    """

    def __init__(self) -> None:
        self.nodes: dict[str, RoadNode] = {}
        self.edges: dict[str, RoadEdge] = {}
        self.adjacency: dict[str, list[RoadEdge]] = {}
        self.conditions: dict[str, EdgeCondition] = {}

    def add_node(self, node: RoadNode) -> None:
        self.nodes[node.node_id] = node
        if node.node_id not in self.adjacency:
            self.adjacency[node.node_id] = []

    def add_edge(self, edge: RoadEdge, bidirectional: bool = True) -> None:
        if edge.u not in self.nodes or edge.v not in self.nodes:
            raise ValueError(f"Edge {edge.edge_id} connects unknown nodes: u={edge.u}, v={edge.v}")

        self.edges[edge.edge_id] = edge
        if edge.u not in self.adjacency:
            self.adjacency[edge.u] = []
        self.adjacency[edge.u].append(edge)

        # Default edge condition if not already set
        if edge.edge_id not in self.conditions:
            self.conditions[edge.edge_id] = EdgeCondition()

        if bidirectional:
            rev_id = f"{edge.edge_id}_rev"
            rev_edge = RoadEdge(
                edge_id=rev_id,
                u=edge.v,
                v=edge.u,
                length_m=edge.length_m,
                road_type=edge.road_type,
                base_speed_kmh=edge.base_speed_kmh,
                is_closed=edge.is_closed,
                closure_reason=edge.closure_reason,
            )
            self.edges[rev_id] = rev_edge
            if edge.v not in self.adjacency:
                self.adjacency[edge.v] = []
            self.adjacency[edge.v].append(rev_edge)
            if rev_id not in self.conditions:
                self.conditions[rev_id] = EdgeCondition()

    def get_node(self, node_id: str) -> Optional[RoadNode]:
        return self.nodes.get(node_id)

    def get_edge(self, edge_id: str) -> Optional[RoadEdge]:
        return self.edges.get(edge_id)

    def get_outgoing_edges(self, node_id: str) -> list[RoadEdge]:
        return self.adjacency.get(node_id, [])

    def set_edge_condition(self, edge_id: str, condition: EdgeCondition) -> None:
        """Set hazard/weather condition on an edge (and its reverse if present)."""
        self.conditions[edge_id] = condition
        rev_id = f"{edge_id}_rev" if not edge_id.endswith("_rev") else edge_id[:-4]
        if rev_id in self.edges:
            self.conditions[rev_id] = condition

    def get_edge_condition(self, edge_id: str) -> EdgeCondition:
        return self.conditions.get(edge_id, EdgeCondition())

    def find_nearest_node(self, lat: float, lon: float) -> Optional[RoadNode]:
        """Find the geographically nearest node to the given coordinates."""
        if not self.nodes:
            return None
        best_node = None
        min_dist = float("inf")
        for node in self.nodes.values():
            dist = haversine_distance_m(lat, lon, node.lat, node.lon)
            if dist < min_dist:
                min_dist = dist
                best_node = node
        return best_node

    def to_geojson(self) -> dict[str, Any]:
        """Convert network to a GeoJSON FeatureCollection for map rendering."""
        features = []
        # Nodes
        for n in self.nodes.values():
            features.append({
                "type": "Feature",
                "geometry": {
                    "type": "Point",
                    "coordinates": [n.lon, n.lat],
                },
                "properties": {
                    "id": n.node_id,
                    "elevation_m": n.elevation_m,
                    "type": "road_node",
                },
            })
        # Edges (avoiding duplicate reversed edges in display)
        seen_pairs = set()
        for e in self.edges.values():
            pair = tuple(sorted([e.u, e.v]))
            if pair in seen_pairs:
                continue
            seen_pairs.add(pair)
            u_node = self.nodes.get(e.u)
            v_node = self.nodes.get(e.v)
            if not u_node or not v_node:
                continue
            cond = self.get_edge_condition(e.edge_id)
            features.append({
                "type": "Feature",
                "geometry": {
                    "type": "LineString",
                    "coordinates": [
                        [u_node.lon, u_node.lat],
                        [v_node.lon, v_node.lat],
                    ],
                },
                "properties": {
                    "id": e.edge_id,
                    "road_type": e.road_type,
                    "length_m": round(e.length_m, 1),
                    "base_speed_kmh": e.base_speed_kmh,
                    "is_closed": e.is_closed,
                    "water_depth_m": cond.water_depth_m,
                    "landslide_risk": cond.landslide_risk,
                },
            })
        return {
            "type": "FeatureCollection",
            "features": features,
        }


def build_corridor_network(
    zone_id: str,
    origin_lat: float,
    origin_lon: float,
    shelters: Iterable[Any],
    *,
    base_speeds: Optional[dict[str, float]] = None,
) -> RoadNetworkGraph:
    """
    Build a realistic connected evacuation road corridor network connecting
    a zone origin point to candidate shelter destinations.

    Architecture (FINAL doc §6, §7):
    - Origin centroid node: N_ORIGIN
    - Regional Highway / Arterial Spine passing through the zone center
    - Intermediary junction nodes creating realistic road topology
    - Collector and access roads connecting shelters to the arterial network
    - Lateral bypass road allowing alternative routing if primary links are cut
    """
    speeds = base_speeds or {
        "highway": 60.0,
        "primary": 40.0,
        "secondary": 30.0,
        "local": 20.0,
    }

    graph = RoadNetworkGraph()

    # 1. Create origin node
    origin_id = f"NODE_{zone_id}_ORIGIN"
    graph.add_node(RoadNode(node_id=origin_id, lat=origin_lat, lon=origin_lon))

    # 2. Create arterial junction nodes around origin (North, South, East, West ~ 1.5km offset)
    dlat = 0.015
    dlon = 0.015
    j_north = f"NODE_{zone_id}_J_N"
    j_south = f"NODE_{zone_id}_J_S"
    j_east = f"NODE_{zone_id}_J_E"
    j_west = f"NODE_{zone_id}_J_W"

    graph.add_node(RoadNode(node_id=j_north, lat=origin_lat + dlat, lon=origin_lon))
    graph.add_node(RoadNode(node_id=j_south, lat=origin_lat - dlat, lon=origin_lon))
    graph.add_node(RoadNode(node_id=j_east, lat=origin_lat, lon=origin_lon + dlon))
    graph.add_node(RoadNode(node_id=j_west, lat=origin_lat, lon=origin_lon - dlon))

    # Connect origin to all 4 central arterial junctions (Primary roads)
    for j_id, j_lat, j_lon in [
        (j_north, origin_lat + dlat, origin_lon),
        (j_south, origin_lat - dlat, origin_lon),
        (j_east, origin_lat, origin_lon + dlon),
        (j_west, origin_lat, origin_lon - dlon),
    ]:
        dist = haversine_distance_m(origin_lat, origin_lon, j_lat, j_lon)
        graph.add_edge(
            RoadEdge(
                edge_id=f"EDGE_{origin_id}_{j_id}",
                u=origin_id,
                v=j_id,
                length_m=dist,
                road_type="primary",
                base_speed_kmh=speeds.get("primary", 40.0),
            )
        )

    # Connect central junctions into an arterial ring / highway bypass
    ring_pairs = [
        (j_north, j_east),
        (j_east, j_south),
        (j_south, j_west),
        (j_west, j_north),
    ]
    for u_id, v_id in ring_pairs:
        u_node = graph.get_node(u_id)
        v_node = graph.get_node(v_id)
        if u_node and v_node:
            dist = haversine_distance_m(u_node.lat, u_node.lon, v_node.lat, v_node.lon)
            graph.add_edge(
                RoadEdge(
                    edge_id=f"EDGE_{u_id}_{v_id}",
                    u=u_id,
                    v=v_id,
                    length_m=dist,
                    road_type="highway",
                    base_speed_kmh=speeds.get("highway", 60.0),
                )
            )

    # 3. For each shelter, add shelter node and connect to the nearest junction and an adjacent shelter
    shelter_nodes: list[tuple[str, float, float]] = []
    for s in shelters:
        s_id = getattr(s, "shelter_id", str(s))
        s_lat = getattr(s, "lat", origin_lat)
        s_lon = getattr(s, "lon", origin_lon)
        node_id = f"NODE_SHELTER_{s_id}"

        if node_id not in graph.nodes:
            graph.add_node(RoadNode(node_id=node_id, lat=s_lat, lon=s_lon))
            shelter_nodes.append((node_id, s_lat, s_lon))

            # Connect shelter to the closest existing junction (excluding itself)
            best_j = None
            min_j_dist = float("inf")
            for j_node in [graph.get_node(j_north), graph.get_node(j_south), graph.get_node(j_east), graph.get_node(j_west)]:
                if j_node:
                    d = haversine_distance_m(s_lat, s_lon, j_node.lat, j_node.lon)
                    if d < min_j_dist:
                        min_j_dist = d
                        best_j = j_node

            if best_j:
                graph.add_edge(
                    RoadEdge(
                        edge_id=f"EDGE_{best_j.node_id}_{node_id}",
                        u=best_j.node_id,
                        v=node_id,
                        length_m=min_j_dist,
                        road_type="secondary",
                        base_speed_kmh=speeds.get("secondary", 30.0),
                    )
                )

    # 4. Connect nearby shelters together (inter-shelter secondary corridors)
    for i in range(len(shelter_nodes)):
        u_id, u_lat, u_lon = shelter_nodes[i]
        # Connect to closest next shelter
        closest_neighbor = None
        closest_dist = float("inf")
        for j in range(len(shelter_nodes)):
            if i == j:
                continue
            v_id, v_lat, v_lon = shelter_nodes[j]
            d = haversine_distance_m(u_lat, u_lon, v_lat, v_lon)
            if d < closest_dist and d <= 8000.0:  # within 8km
                closest_dist = d
                closest_neighbor = v_id

        if closest_neighbor:
            edge_id = f"EDGE_INTER_{u_id}_{closest_neighbor}"
            rev_edge_id = f"EDGE_INTER_{closest_neighbor}_{u_id}"
            if edge_id not in graph.edges and rev_edge_id not in graph.edges:
                graph.add_edge(
                    RoadEdge(
                        edge_id=edge_id,
                        u=u_id,
                        v=closest_neighbor,
                        length_m=closest_dist,
                        road_type="local",
                        base_speed_kmh=speeds.get("local", 20.0),
                    )
                )

    return graph
