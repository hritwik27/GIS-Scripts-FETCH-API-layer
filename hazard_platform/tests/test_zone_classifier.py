"""test_zone_classifier.py -- Unit tests for zone color classification logic.
Tests all hazard types across Red / Yellow / Green threshold boundaries.
"""
import sys
from pathlib import Path

HP_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HP_ROOT))

from backend.zone_classifier import classify_zone
from data_pipeline.models import HazardType
from ml_service.inference.predictor import ScoreResult

OTHER_HAZARDS_BASELINE = 0.10

THRESHOLDS = [
    (HazardType.FLOOD, 0.70, 0.40),
    (HazardType.LANDSLIDE, 0.75, 0.40),
    (HazardType.EROSION, 0.70, 0.40),
    (HazardType.CLOUDBURST, 0.70, 0.40),
]

CASES = [
    ("green (below yellow)", lambda red, yellow: yellow - 0.05, "GREEN"),
    ("at yellow boundary", lambda red, yellow: yellow, "YELLOW"),
    ("yellow (between yellow and red)", lambda red, yellow: (yellow + red) / 2, "YELLOW"),
    ("just below red", lambda red, yellow: red - 0.01, "YELLOW"),
    ("at red boundary", lambda red, yellow: red, "RED"),
    ("above red", lambda red, yellow: min(red + 0.05, 1.0), "RED"),
]


def make_scores(hazard_under_test, score):
    return {
        h: ScoreResult(
            score=score if h == hazard_under_test else OTHER_HAZARDS_BASELINE,
            missing_fields=[],
        )
        for h, _, _ in THRESHOLDS
    }


def test_zone_classifier():
    total = 0
    failed = 0
    for hazard, red, yellow in THRESHOLDS:
        for label, score_fn, expected in CASES:
            score = round(score_fn(red, yellow), 4)
            result = classify_zone(
                zone_id=f"test-{hazard.name.lower()}-{label.replace(' ', '-')}",
                scores=make_scores(hazard, score),
            )
            total += 1
            ok = result.color.name == expected
            if not ok:
                failed += 1
            status = "OK" if ok else "FAIL"
            print(f"[{status}] {hazard.name} {label} (score={score}): "
                  f"got {result.color.name}, expected {expected}")

    print(f"\n{total - failed}/{total} passed" + (f", {failed} FAILED" if failed else ""))
    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    test_zone_classifier()
