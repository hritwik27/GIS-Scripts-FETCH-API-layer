from __future__ import annotations

import functools
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

import yaml

from data_pipeline.models import HazardType
from ml_service.inference.predictor import ScoreResult

_DEFAULT_CONFIG_PATH = Path(__file__).parent / "zone_thresholds.yaml"


@functools.lru_cache(maxsize=1)
def _load_thresholds(config_path: Path = _DEFAULT_CONFIG_PATH) -> dict:
    with open(config_path) as f:
        return yaml.safe_load(f)


def _thresholds_for(hazard: HazardType, config: dict) -> tuple[float, float]:
    overrides = config.get("overrides", {})
    entry = overrides.get(hazard.value, config["default"])
    return entry["red"], entry["yellow"]


class ZoneColor(str, Enum):
    RED = "RED"
    YELLOW = "YELLOW"
    GREEN = "GREEN"


@dataclass
class ZoneClassification:
    zone_id: str
    color: ZoneColor
    worst_hazard: HazardType
    worst_score: float
    scores: dict[HazardType, float]


def classify_zone(
    zone_id: str,
    scores: dict[HazardType, ScoreResult],
    config_path: Path = _DEFAULT_CONFIG_PATH,
) -> ZoneClassification:
    config = _load_thresholds(config_path)
    worst_hazard, worst_result = max(scores.items(), key=lambda kv: kv[1].score)
    worst_score = worst_result.score

    red_threshold, yellow_threshold = _thresholds_for(worst_hazard, config)

    if worst_score >= red_threshold:
        color = ZoneColor.RED
    elif worst_score >= yellow_threshold:
        color = ZoneColor.YELLOW
    else:
        color = ZoneColor.GREEN

    return ZoneClassification(
        zone_id=zone_id,
        color=color,
        worst_hazard=worst_hazard,
        worst_score=worst_score,
        scores={h: r.score for h, r in scores.items()},
    )
