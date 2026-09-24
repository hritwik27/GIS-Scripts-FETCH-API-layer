"""test_routing.py -- Verification of evacuation routing, impassability, accessibility, and corridor networks.
"""
import math
import sys
from pathlib import Path

HP_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HP_ROOT))

from evacuation.accessibility import calculate_route_accessibility
from evacuation.assignment import assign_zone
from evacuation.capacity import ShelterCapacity
from evacuation.impassability import (
    ImpassabilityParams,
    calculate_edge_impassability,
    load_params as load_imp_params,
)
from evacuation.models import (
    AssignmentStatus,
    EdgeCondition,
    EscalationLevel,
    ImpassabilityResult,
    RoadEdge,
    RoadNode,
)
from evacuation.road_network import (
    RoadNetworkGraph,
    build_corridor_network,
    haversine_distance_m,
)
from evacuation.routing import (
    RoutingParams,
    find_shortest_route,
    route_between_points,
)


def check(label: str, ok: bool) -> None:
    print(("PASS " if ok else "FAIL ") + label)
    if not ok:
        raise SystemExit(1)


def test_routing():
    print("--- 1. Impassability & Hard Closures (FINAL doc §6) ---")
    p_imp = ImpassabilityParams()
    e_test = RoadEdge(edge_id="E1", u="N1", v="N2", length_m=1000.0, road_type="primary", base_speed_kmh=40.0)

    # 1a. Normal dry road
    res_dry = calculate_edge_impassability(e_test, EdgeCondition(), params=p_imp)
    check("dry road: open, impassability 0, speed 40", not res_dry.is_closed and res_dry.impassability == 0.0 and res_dry.effective_speed_kmh == 40.0)

    # 1b. Flood below critical threshold: 0.20m depth
    cond_flood_low = EdgeCondition(water_depth_m=0.20)
    res_flood_low = calculate_edge_impassability(e_test, cond_flood_low, params=p_imp)
    check("shallow flood: open, speed reduced", not res_flood_low.is_closed and 0.10 < res_flood_low.impassability < 0.20 and res_flood_low.effective_speed_kmh < 40.0)

    # 1c. Flood hard closure: depth >= 0.30m
    cond_flood_deep = EdgeCondition(water_depth_m=0.35)
    res_flood_deep = calculate_edge_impassability(e_test, cond_flood_deep, params=p_imp)
    check("flood >= 0.30m: hard closure triggered", res_flood_deep.is_closed and res_flood_deep.impassability == 1.0 and "CRITICAL_FLOOD_DEPTH_VELOCITY" in res_flood_deep.closure_reason)

    # 1d. Flood h*v hard closure: depth 0.25m * velocity 2.5m/s = 0.625 >= 0.60
    cond_flood_hv = EdgeCondition(water_depth_m=0.25, water_velocity_mps=2.5)
    res_flood_hv = calculate_edge_impassability(e_test, cond_flood_hv, params=p_imp)
    check("flood hv >= 0.60: hard closure triggered", res_flood_hv.is_closed and res_flood_hv.impassability == 1.0)

    # 1e. Landslide hard closure: risk >= 0.75 AND rain >= 150mm
    cond_landslide = EdgeCondition(landslide_risk=0.85, rainfall_72h_mm=180.0)
    res_landslide = calculate_edge_impassability(e_test, cond_landslide, params=p_imp)
    check("landslide risk + heavy rain: hard closure triggered", res_landslide.is_closed and "CRITICAL_LANDSLIDE" in res_landslide.closure_reason)

    print("\n--- 2. Route Accessibility & Bottleneck Analysis (FINAL doc §6) ---")
    edge_res_1 = ImpassabilityResult("E1", 0.10, 0.90, 36.0, False)
    edge_res_2 = ImpassabilityResult("E2", 0.40, 0.60, 24.0, False)
    acc = calculate_route_accessibility([(1000.0, edge_res_1), (2000.0, edge_res_2)])
    check("route accessibility math: A_final == 0.42", abs(acc.final_accessibility - 0.42) < 0.001)
    check("bottleneck identification: E2 identified", acc.bottleneck_edge_id == "E2")

    edge_res_closed = ImpassabilityResult("E3", 1.0, 0.0, 0.0, True, "CRITICAL_FLOOD")
    acc_closed = calculate_route_accessibility([(1000.0, edge_res_1), (500.0, edge_res_closed)])
    check("route with closed link: A_final == 0.0 and bottleneck is E3", acc_closed.final_accessibility == 0.0 and acc_closed.bottleneck_edge_id == "E3")

    print("\n--- 3. Dijkstra Routing & Dynamic Rerouting (FINAL doc §7) ---")
    g = RoadNetworkGraph()
    g.add_node(RoadNode("N_ORIGIN", 25.594, 85.137))
    g.add_node(RoadNode("N_A", 25.600, 85.140))
    g.add_node(RoadNode("N_B", 25.610, 85.150))
    g.add_node(RoadNode("N_DETOUR", 25.605, 85.130))

    g.add_edge(RoadEdge("E_OA", "N_ORIGIN", "N_A", 1000.0, "primary", 40.0))
    g.add_edge(RoadEdge("E_AB", "N_A", "N_B", 1500.0, "primary", 40.0))
    g.add_edge(RoadEdge("E_OD", "N_ORIGIN", "N_DETOUR", 1200.0, "secondary", 30.0))
    g.add_edge(RoadEdge("E_DB", "N_DETOUR", "N_B", 1800.0, "secondary", 30.0))

    route1 = find_shortest_route(g, "N_ORIGIN", "N_B")
    check("direct route found: ORIGIN -> A -> B", route1.found and route1.path_nodes == ["N_ORIGIN", "N_A", "N_B"])

    g.set_edge_condition("E_AB", EdgeCondition(water_depth_m=0.50))
    route2 = find_shortest_route(g, "N_ORIGIN", "N_B")
    check("automatic rerouting around flooded link: ORIGIN -> DETOUR -> B", route2.found and route2.path_nodes == ["N_ORIGIN", "N_DETOUR", "N_B"])

    g.set_edge_condition("E_DB", EdgeCondition(water_depth_m=0.50))
    route3 = find_shortest_route(g, "N_ORIGIN", "N_B")
    check("all paths cut off: route not found", not route3.found and math.isinf(route3.total_cost))

    print("\n--- 4. Corridor Network Generator & GeoJSON ---")
    class MockShelter:
        def __init__(self, sid, lat, lon):
            self.shelter_id = sid
            self.lat = lat
            self.lon = lon

    shelters = [
        MockShelter("S1", 25.620, 85.160),
        MockShelter("S2", 25.580, 85.120),
        MockShelter("S3", 25.605, 85.180),
    ]
    corridor_net = build_corridor_network("Z-TEST", 25.594, 85.137, shelters)
    check("corridor network nodes created", len(corridor_net.nodes) >= 8)
    check("corridor network edges created", len(corridor_net.edges) >= 10)

    geojson = corridor_net.to_geojson()
    check("GeoJSON FeatureCollection valid", geojson["type"] == "FeatureCollection" and len(geojson["features"]) > 0)

    print("\n--- 5. Capacity Assignment With Road Network & TRAPPED State ---")
    def make_shelter_cap(sid, lat, lon, cap):
        return ShelterCapacity(
            shelter_id=sid,
            zone_id="Z-TEST",
            name=f"Shelter {sid}",
            lat=lat,
            lon=lon,
            osm_tag="amenity=school",
            capacity_source="gis_estimated",
            safety_status="SAFE",
            safety_factor=1.0,
            capacity_known=True,
            nominal=cap,
            occupancy=0.0,
            reserved=0.0,
            usable=cap,
            effective=cap,
            assignable=cap,
            over_capacity=False,
        )

    shelter_caps = [
        make_shelter_cap("S1", 25.620, 85.160, 500.0),
        make_shelter_cap("S2", 25.580, 85.120, 500.0),
    ]
    corridor_for_assign = build_corridor_network("Z-TEST", 25.594, 85.137, shelter_caps)

    res_assign = assign_zone(
        "Z-TEST", 25.594, 85.137, 400, shelter_caps,
        graph=corridor_for_assign, hazard_score=0.2
    )
    check("graph assignment: FULLY_SERVED", res_assign.status == AssignmentStatus.FULLY_SERVED and res_assign.total_assigned == 400)
    check("graph assignment: route details attached", len(res_assign.assignments) > 0 and len(res_assign.assignments[0].route_nodes) > 0)

    for edge in corridor_for_assign.edges.values():
        if "ORIGIN" in edge.u or "ORIGIN" in edge.v:
            corridor_for_assign.set_edge_condition(edge.edge_id, EdgeCondition(water_depth_m=0.80))

    res_trapped = assign_zone(
        "Z-TEST", 25.594, 85.137, 400, shelter_caps,
        graph=corridor_for_assign, hazard_score=0.8
    )
    check("flooded corridors trigger TRAPPED state", res_trapped.status == AssignmentStatus.TRAPPED and res_trapped.trapped)
    check("flooded corridors trigger NDRF aerial escalation", res_trapped.escalation == EscalationLevel.NDRF_AERIAL_RESCUE_REQUIRED)

    print("\nPASS: All routing & impassability tests passed.")


if __name__ == "__main__":
    test_routing()
