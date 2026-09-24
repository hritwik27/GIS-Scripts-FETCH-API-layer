"""
evacuation/provenance.py -- data provenance, freshness, confidence, and fallback tracking (FINAL doc §9, §13).

Every reading and plan carries:
- source (provider / register)
- recorded_at (observation timestamp)
- freshness_hours (data vintage)
- data_quality (HIGH, MEDIUM, LOW, FALLBACK)
- confidence_score ([0.0, 1.0])
- fallback_used (bool)
- fallback_chain (list of provider attempts)
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional


class DataQualityLevel(str, Enum):
    HIGH = "HIGH"          # Fresh telemetry / verified source (< 3h)
    MEDIUM = "MEDIUM"      # Telemetry within 24h or verified GIS layer
    LOW = "LOW"            # Stale reading (> 24h) or spatial approximation
    FALLBACK = "FALLBACK"  # Synthetic fallback or emergency proxy used


@dataclass
class ReadingProvenance:
    source: str
    recorded_at: datetime
    freshness_hours: float
    data_quality: DataQualityLevel
    confidence_score: float
    fallback_used: bool = False
    fallback_chain: list[str] = field(default_factory=list)
    notes: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["recorded_at"] = self.recorded_at.isoformat()
        d["data_quality"] = self.data_quality.value
        return d


@dataclass
class PlanProvenance:
    zone_id: str
    computed_at: datetime
    overall_confidence: float
    hazard_provenance: ReadingProvenance
    population_provenance: ReadingProvenance
    shelter_source_breakdown: dict[str, int]
    fallback_summary: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "zone_id": self.zone_id,
            "computed_at": self.computed_at.isoformat(),
            "overall_confidence": round(self.overall_confidence, 3),
            "hazard_provenance": self.hazard_provenance.to_dict(),
            "population_provenance": self.population_provenance.to_dict(),
            "shelter_source_breakdown": self.shelter_source_breakdown,
            "fallback_summary": self.fallback_summary,
        }


def assess_reading_provenance(
    source: str,
    recorded_at: Optional[datetime] = None,
    *,
    fallback_used: bool = False,
    custom_confidence: Optional[float] = None,
    notes: Optional[str] = None,
) -> ReadingProvenance:
    """
    Assess data freshness and quality grade according to Master risk table (FINAL doc §9).
    """
    now = datetime.now(timezone.utc)
    rec_at = recorded_at or now
    if rec_at.tzinfo is None:
        rec_at = rec_at.replace(tzinfo=timezone.utc)

    age_hours = max(0.0, (now - rec_at).total_seconds() / 3600.0)

    if fallback_used:
        quality = DataQualityLevel.FALLBACK
        conf = custom_confidence if custom_confidence is not None else 0.55
    elif age_hours <= 3.0:
        quality = DataQualityLevel.HIGH
        conf = custom_confidence if custom_confidence is not None else 0.95
    elif age_hours <= 24.0:
        quality = DataQualityLevel.MEDIUM
        conf = custom_confidence if custom_confidence is not None else 0.80
    else:
        quality = DataQualityLevel.LOW
        conf = custom_confidence if custom_confidence is not None else 0.60

    return ReadingProvenance(
        source=source,
        recorded_at=rec_at,
        freshness_hours=round(age_hours, 2),
        data_quality=quality,
        confidence_score=round(conf, 3),
        fallback_used=fallback_used,
        fallback_chain=[source] if not fallback_used else [source, "fallback_proxy"],
        notes=notes,
    )


def build_plan_provenance(
    zone_id: str,
    hazard_reading_ts: Optional[datetime],
    hazard_source: str = "open-meteo/cwc",
    population_source: str = "worldpop_2020",
    shelters: Optional[list[Any]] = None,
    hazard_confidence: float = 0.90,
) -> PlanProvenance:
    """
    Construct multi-source provenance metadata for a computed ZonePlan.
    """
    now = datetime.now(timezone.utc)

    haz_prov = assess_reading_provenance(
        source=hazard_source,
        recorded_at=hazard_reading_ts,
        custom_confidence=hazard_confidence,
    )

    pop_prov = assess_reading_provenance(
        source=population_source,
        recorded_at=now,
        custom_confidence=0.85,
        notes="WorldPop 1km raster aggregated over zone bounding box",
    )

    # Breakdown shelter sources
    shelter_sources: dict[str, int] = {}
    fallback_notes = []
    if shelters:
        for s in shelters:
            src = getattr(s, "capacity_source", "unknown")
            shelter_sources[src] = shelter_sources.get(src, 0) + 1

        if "authority_fallback" in shelter_sources:
            count = shelter_sources["authority_fallback"]
            fallback_notes.append(f"{count} shelter(s) using emergency authority fallback registry")

    # Harmonic/weighted compound confidence
    overall_conf = (haz_prov.confidence_score * 0.5) + (pop_prov.confidence_score * 0.3) + 0.2

    return PlanProvenance(
        zone_id=zone_id,
        computed_at=now,
        overall_confidence=overall_conf,
        hazard_provenance=haz_prov,
        population_provenance=pop_prov,
        shelter_source_breakdown=shelter_sources,
        fallback_summary=fallback_notes,
    )
