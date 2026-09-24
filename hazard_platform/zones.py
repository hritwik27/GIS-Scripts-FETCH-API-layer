"""zones.py — the zone_id -> bbox registry pipeline_runner.py needs.

Nothing else in this repo defines what a "zone" is in lon/lat terms
(HazardReading just stores a zone_id string). This started as a minimal,
hand-seeded registry of a few named towns -- it now also supports
registering a zone *dynamically* from any arbitrary lat/lon (e.g. a map
click), which is what makes "click anywhere and fetch that place" work
without pre-listing every place someone might click.

Each bbox is a small box (radius configurable, ~5km by default) around a
center point -- small enough that bbox.center (what every provider
actually queries) stays representative of the clicked/named place.

Two ways a Zone ends up in the registry:
  1. Hand-seeded at import time (`_SEED_ZONES` below) -- a few named
     towns kept around for the CLI/demo/tests.
  2. Registered at runtime via `zone_from_point(lat, lon)` -- this is
     what backend/api.py's /api/analyze-point calls for a map click. It
     derives a deterministic zone_id from the (rounded) coordinates,
     builds the bbox, and registers it so every existing zone_id-keyed
     piece of code (get_zone, ingest_zone, HazardReadingStore, the
     static-dataset fetchers) works on it exactly like a seeded zone --
     nothing downstream needs to know the difference.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class Zone:
    zone_id: str
    name: str
    min_lon: float
    min_lat: float
    max_lon: float
    max_lat: float

    @property
    def center(self) -> tuple[float, float]:
        return ((self.min_lon + self.max_lon) / 2, (self.min_lat + self.max_lat) / 2)


# lon/lat centers taken from public sources for each town; box is
# center +/- 0.025 degrees (~2.5km) in each direction.
_HALF_WIDTH_DEG = 0.025

_SEED_ZONES = [
    # --- original 12 ---
    ("Z-BIHAR-PATNA-01", "Patna, Bihar", 85.1376, 25.5941),
    ("Z-KERALA-WAYANAD-01", "Wayanad, Kerala", 76.1319, 11.6854),
    ("Z-ASSAM-GUWAHATI-01", "Guwahati, Assam", 91.7362, 26.1445),
    ("Z-ODISHA-PURI-01", "Puri, Odisha", 85.8312, 19.8135),
    ("Z-UTTARAKHAND-JOSHIMATH-01", "Joshimath, Uttarakhand", 79.5641, 30.5551),
    ("Z-HIMACHAL-KULLU-01", "Kullu, Himachal Pradesh", 77.1092, 31.9578),
    ("Z-JAMMUKASHMIR-KISHTWAR-01", "Kishtwar, Jammu & Kashmir", 75.7700, 33.3200),
    ("Z-SIKKIM-CHUNGTHANG-01", "Chungthang, Sikkim", 88.6456, 27.6045),
    ("Z-MAHARASHTRA-CHIPLUN-01", "Chiplun, Maharashtra", 73.5200, 17.5300),
    ("Z-TAMILNADU-CUDDALORE-01", "Cuddalore, Tamil Nadu", 79.7500, 11.7500),
    ("Z-WESTBENGAL-GOSABA-01", "Gosaba, West Bengal", 88.8079, 22.1652),
    ("Z-GUJARAT-MANDVI-01", "Mandvi, Gujarat", 69.3556, 22.8333),

    # --- flood (10 new) ---
    ("Z-UTTARPRADESH-GORAKHPUR-01", "Gorakhpur, Uttar Pradesh", 83.4039, 26.7638),
    ("Z-UTTARPRADESH-VARANASI-01", "Varanasi, Uttar Pradesh", 83.0128, 25.3189),
    ("Z-BIHAR-MUZAFFARPUR-01", "Muzaffarpur, Bihar", 85.3906, 26.1225),
    ("Z-WESTBENGAL-COOCHBEHAR-01", "Cooch Behar, West Bengal", 89.4510, 26.3242),
    ("Z-ASSAM-DHEMAJI-01", "Dhemaji, Assam", 94.5800, 27.4800),
    ("Z-ASSAM-BARPETA-01", "Barpeta, Assam", 91.0000, 26.3200),
    ("Z-ODISHA-BALASORE-01", "Balasore, Odisha", 86.9317, 21.4942),
    ("Z-ANDHRAPRADESH-KURNOOL-01", "Kurnool, Andhra Pradesh", 78.0373, 15.8281),
    ("Z-MADHYAPRADESH-NARMADAPURAM-01", "Narmadapuram (Hoshangabad), Madhya Pradesh", 77.7300, 22.7500),
    ("Z-HARYANA-YAMUNANAGAR-01", "Yamunanagar, Haryana", 77.2674, 30.1290),

    # --- landslide (8 new) ---
    ("Z-KERALA-MUNNAR-01", "Munnar, Kerala", 77.0595, 10.0889),
    ("Z-KARNATAKA-MADIKERI-01", "Madikeri (Coorg), Karnataka", 75.7382, 12.4244),
    ("Z-WESTBENGAL-DARJEELING-01", "Darjeeling, West Bengal", 88.2663, 27.0410),
    ("Z-UTTARAKHAND-MUSSOORIE-01", "Mussoorie, Uttarakhand", 78.0664, 30.4598),
    ("Z-KERALA-IDUKKI-01", "Idukki, Kerala", 76.9700, 9.8500),
    ("Z-TAMILNADU-OOTY-01", "Ooty (Nilgiris), Tamil Nadu", 76.6932, 11.4064),
    ("Z-MIZORAM-AIZAWL-01", "Aizawl, Mizoram", 92.7176, 23.7271),
    ("Z-MEGHALAYA-SHILLONG-01", "Shillong, Meghalaya", 91.8933, 25.5788),

    # --- cloudburst / flash flood (7 new) ---
    ("Z-LADAKH-LEH-01", "Leh, Ladakh", 77.5771, 34.1526),
    ("Z-HIMACHAL-DHARAMSHALA-01", "Dharamshala, Himachal Pradesh", 76.3234, 32.2190),
    ("Z-UTTARAKHAND-UTTARKASHI-01", "Uttarkashi, Uttarakhand", 78.4354, 30.7268),
    ("Z-UTTARAKHAND-CHAMOLI-01", "Chamoli, Uttarakhand", 79.3200, 30.4000),
    ("Z-UTTARAKHAND-RUDRAPRAYAG-01", "Rudraprayag, Uttarakhand", 78.9810, 30.2844),
    ("Z-ARUNACHALPRADESH-ITANAGAR-01", "Itanagar, Arunachal Pradesh", 93.6053, 27.0844),
    ("Z-HIMACHAL-SOLAN-01", "Solan, Himachal Pradesh", 77.0967, 30.9045),

    # --- coastal erosion / cyclone (10 new) ---
    ("Z-WESTBENGAL-DIGHA-01", "Digha, West Bengal", 87.5089, 21.6269),
    ("Z-ODISHA-PARADIP-01", "Paradip, Odisha", 86.6167, 20.3167),
    ("Z-ANDHRAPRADESH-VISAKHAPATNAM-01", "Visakhapatnam, Andhra Pradesh", 83.2185, 17.6868),
    ("Z-KARNATAKA-KARWAR-01", "Karwar, Karnataka", 74.1291, 14.8137),
    ("Z-MAHARASHTRA-RATNAGIRI-01", "Ratnagiri, Maharashtra", 73.3120, 16.9902),
    ("Z-KERALA-ALAPPUZHA-01", "Alappuzha, Kerala", 76.3388, 9.4981),
    ("Z-TAMILNADU-NAGAPATTINAM-01", "Nagapattinam, Tamil Nadu", 79.8449, 10.7672),
    ("Z-ANDAMANNICOBAR-PORTBLAIR-01", "Port Blair, Andaman & Nicobar Islands", 92.7265, 11.6234),
    ("Z-DAMANDIU-DIU-01", "Diu, Daman & Diu", 70.9874, 20.7144),
    ("Z-GUJARAT-VERAVAL-01", "Veraval, Gujarat", 70.3629, 20.9159),

    # --- mixed / additional state coverage (3 new) ---
    ("Z-ASSAM-JORHAT-01", "Jorhat, Assam", 94.2037, 26.7509),
    ("Z-MANIPUR-IMPHAL-01", "Imphal, Manipur", 93.9368, 24.8170),
    ("Z-CHHATTISGARH-RAIGARH-01", "Raigarh, Chhattisgarh", 83.3950, 21.8974),
]

# Mutable at runtime -- zone_from_point() adds to this dict, which is
# exactly what makes dynamic/clicked zones visible to every other
# zone_id-keyed lookup in the codebase (get_zone, list_zones, and the
# static-dataset fetchers' `_load_zones` helpers, which all import
# `list_zones`/`get_zone` fresh rather than caching a copy at import time).
_ZONES: dict[str, Zone] = {
    zone_id: Zone(
        zone_id=zone_id,
        name=name,
        min_lon=round(lon - _HALF_WIDTH_DEG, 4),
        min_lat=round(lat - _HALF_WIDTH_DEG, 4),
        max_lon=round(lon + _HALF_WIDTH_DEG, 4),
        max_lat=round(lat + _HALF_WIDTH_DEG, 4),
    )
    for zone_id, name, lon, lat in _SEED_ZONES
}


def get_zone(zone_id: str) -> Zone:
    try:
        return _ZONES[zone_id]
    except KeyError as exc:
        raise ValueError(
            f"Unknown zone_id '{zone_id}'. Known zones: {sorted(_ZONES)}. "
            "If this was meant to be a map-click point rather than a "
            "pre-seeded zone, call zone_from_point(lat, lon) first -- "
            "that registers it under a derived zone_id."
        ) from exc


def list_zones() -> list[Zone]:
    return list(_ZONES.values())


def register_zone(zone: Zone) -> Zone:
    """Add (or overwrite) a zone in the registry. Idempotent: registering
    the same zone_id twice just replaces it, which is what we want when
    the same point is clicked again later -- callers don't need to check
    "does this already exist" first."""
    _ZONES[zone.zone_id] = zone
    return zone


def _point_zone_id(lat: float, lon: float, precision: int = 3) -> str:
    """Deterministic zone_id for a raw lat/lon, e.g. 'Z-PT-25.594N-85.138E'.
    Rounding to `precision` decimal places (~110m at 3dp) means two clicks
    on essentially the same spot reuse one zone_id -- so HazardReadingStore
    history, ZoneHistory imputation fallback, and the static-dataset
    freshness cache all actually accumulate for that point instead of
    minting a fresh, historyless zone on every click.
    """
    lat_r, lon_r = round(lat, precision), round(lon, precision)
    ns = "N" if lat_r >= 0 else "S"
    ew = "E" if lon_r >= 0 else "W"
    return f"Z-PT-{abs(lat_r):.{precision}f}{ns}-{abs(lon_r):.{precision}f}{ew}"


def zone_from_point(
    lat: float,
    lon: float,
    radius_km: float = 5.0,
    name: Optional[str] = None,
) -> Zone:
    """Build a Zone bbox around an arbitrary clicked point and register it,
    so it's immediately usable by zone_id everywhere else in the codebase.
    This is the "no hardcoded regions" entry point: the frontend sends
    whatever lat/lon the user clicked, and this turns it into a real zone
    on the fly -- no prior entry in `_SEED_ZONES` required.

    `radius_km` controls the bbox half-width in km (converted to degrees
    the same way backend/api.py's `_bbox_from_point` already does for
    /api/place-data, so the two stay consistent). Latitude degrees are a
    constant ~111km; longitude degrees shrink with cos(latitude), which
    matters more the further a click is from the equator.
    """
    dlat = radius_km / 111.0
    dlon = radius_km / (111.0 * max(0.1, abs(math.cos(math.radians(lat)))))
    zone_id = _point_zone_id(lat, lon)
    zone = Zone(
        zone_id=zone_id,
        name=name or f"Point ({lat:.4f}, {lon:.4f})",
        min_lon=round(lon - dlon, 6),
        min_lat=round(lat - dlat, 6),
        max_lon=round(lon + dlon, 6),
        max_lat=round(lat + dlat, 6),
    )
    return register_zone(zone)
