"""Geospatial helpers — distance, bearing, and small local offsets."""
from __future__ import annotations
import math

_EARTH_R = 6_371_000.0  # metres
_COMPASS = ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
            "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"]


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance between two points in metres."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * _EARTH_R * math.asin(math.sqrt(a))


def bearing_deg(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Initial bearing from point 1 to point 2, degrees clockwise from north."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dl = math.radians(lon2 - lon1)
    y = math.sin(dl) * math.cos(p2)
    x = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl)
    return (math.degrees(math.atan2(y, x)) + 360.0) % 360.0


def compass(bearing: float) -> str:
    """Nearest 16-point compass label for a bearing in degrees."""
    return _COMPASS[round(bearing / 22.5) % 16]


def offset_m(lat: float, lon: float, dnorth: float, deast: float) -> tuple[float, float]:
    """Return (lat, lon) shifted by dnorth/deast metres — flat-earth ok for <10 km."""
    dlat = dnorth / 111_320.0
    dlon = deast / (111_320.0 * math.cos(math.radians(lat)))
    return lat + dlat, lon + dlon
