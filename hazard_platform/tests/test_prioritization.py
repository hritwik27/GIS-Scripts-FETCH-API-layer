"""test_prioritization.py -- Verification of multi-criteria zone prioritization (AHP + Vulnerability).
"""
import sys
from pathlib import Path

HP_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HP_ROOT))

from backend.prioritization import VulnerabilityInputs, prioritize
from backend.zone_classifier import ZoneClassification, ZoneColor
from data_pipeline.models import HazardType


def test_prioritization():
    # Test 1: RED zone, high vulnerability -> should be IMMEDIATE
    classification_red = ZoneClassification(
        zone_id="test-zone-1",
        color=ZoneColor.RED,
        worst_hazard=HazardType.FLOOD,
        worst_score=0.85,
        scores={HazardType.FLOOD: 0.85, HazardType.LANDSLIDE: 0.10, HazardType.EROSION: 0.10, HazardType.CLOUDBURST: 0.10},
    )
    vuln_high = VulnerabilityInputs(
        population_density_score=0.8,
        socioeconomic_vulnerability_score=0.7,
        disaster_history_score=0.6,
    )
    result1 = prioritize(classification_red, vuln_high)
    print("Test 1 (RED, high vuln):", result1.priority, "score:", round(result1.priority_score, 3))
    assert result1.priority.name == "IMMEDIATE", f"Expected IMMEDIATE, got {result1.priority}"

    # Test 2: GREEN zone -> should be NONE regardless of vulnerability
    classification_green = ZoneClassification(
        zone_id="test-zone-2",
        color=ZoneColor.GREEN,
        worst_hazard=HazardType.FLOOD,
        worst_score=0.15,
        scores={HazardType.FLOOD: 0.15, HazardType.LANDSLIDE: 0.10, HazardType.EROSION: 0.10, HazardType.CLOUDBURST: 0.10},
    )
    result2 = prioritize(classification_green, vuln_high)
    print("Test 2 (GREEN, high vuln):", result2.priority, "score:", result2.priority_score)
    assert result2.priority.name == "NONE", f"Expected NONE, got {result2.priority}"

    # Test 3: YELLOW zone, low vulnerability -> should be MEDIUM_TERM or SHORT_TERM, not IMMEDIATE
    classification_yellow = ZoneClassification(
        zone_id="test-zone-3",
        color=ZoneColor.YELLOW,
        worst_hazard=HazardType.LANDSLIDE,
        worst_score=0.5,
        scores={HazardType.FLOOD: 0.1, HazardType.LANDSLIDE: 0.5, HazardType.EROSION: 0.1, HazardType.CLOUDBURST: 0.1},
    )
    vuln_low = VulnerabilityInputs(
        population_density_score=0.2,
        socioeconomic_vulnerability_score=0.1,
        disaster_history_score=0.1,
    )
    result3 = prioritize(classification_yellow, vuln_low)
    print("Test 3 (YELLOW, low vuln):", result3.priority, "score:", round(result3.priority_score, 3))
    assert result3.priority.name in ("MEDIUM_TERM", "SHORT_TERM"), f"Unexpected priority {result3.priority}"

    print("\nPASS: All prioritization tests passed.")


if __name__ == "__main__":
    test_prioritization()
