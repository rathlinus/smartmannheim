"""Pure helpers for the official climate API (api.smartmannheim.de).

Kept free of Home Assistant and package-relative imports so it can be
unit-tested directly and reused by ``scripts/build_sensor_snapshot.py``.
"""
from __future__ import annotations

import math
import re
from typing import Any

# Documented limits: 30 requests/hour in total, 6/hour per sensor. One
# update fetches every selected sensor once, so n sensors need n requests.
RATE_LIMIT_PER_HOUR = 30
MIN_INTERVAL_MINUTES = 10
SENSORS_AT_MIN_INTERVAL = RATE_LIMIT_PER_HOUR * MIN_INTERVAL_MINUTES // 60  # 5

KIND_CLIMATE = "climate"
KIND_WIND = "wind"

# Same tokeniser as metadata.py: keeps hyphenated IDs like 0101-001-21 intact.
_TOKEN_RE = re.compile(r"[0-9A-Za-z]+(?:-[0-9A-Za-z]+){0,3}")
# Newer sensor names start with YYMM, e.g. 2507LW195 (installed 2025-07).
_DATED_NAME_RE = re.compile(r"^\d{4}L[HW]\d+$")

# ~50 m in degrees latitude; longitude is scaled by cos(lat).
_MAX_MATCH_DISTANCE_M = 50.0


def climate_interval_minutes(sensor_count: int) -> int:
    """Poll interval that keeps ``sensor_count`` sensors within the limit."""
    return max(MIN_INTERVAL_MINUTES, math.ceil(60 * sensor_count / RATE_LIMIT_PER_HOUR))


def sensor_kind(params: list[str]) -> str:
    return KIND_WIND if "averageWindSpeed" in params else KIND_CLIMATE


def short_name(name: str) -> str:
    """``T-050 - SCM auf der Buga`` → ``T-050``."""
    return name.split(" - ", 1)[0].strip()


def location_key(sensor: dict[str, Any]) -> str:
    """Stable key grouping sensors mounted at the same spot.

    Sensors at one station share their exact position; sensors without a
    position get a location of their own.
    """
    coords = sensor.get("coordinates")
    if coords and len(coords) == 2:
        return f"loc_{coords[0]}_{coords[1]}"
    return f"sensor_{sensor['sensorId']}"


def normalize_sensors(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Turn a ``/climate/sensors`` response into stored sensor payloads."""
    param_sets: list[list[str]] = payload.get("paramSets") or []
    out: list[dict[str, Any]] = []
    for raw in payload.get("sensors") or []:
        idx = raw.get("paramSet")
        params = list(param_sets[idx]) if isinstance(idx, int) and idx < len(param_sets) else []
        position = raw.get("position")
        out.append(
            {
                "sensorId": raw["id"],
                "name": (raw.get("name") or raw["id"]).strip(),
                "coordinates": list(position) if position and len(position) == 2 else None,
                "params": params,
            }
        )
    return out


def latest_values(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Newest non-null value per parameter from a measurements response.

    Rows arrive newest first today, but don't rely on it. Parameters are
    looked up individually because not every row carries every field.
    """
    out: dict[str, dict[str, Any]] = {}
    for row in sorted(rows, key=lambda r: r.get("timestamp") or "", reverse=True):
        ts = row.get("timestamp")
        for key, value in row.items():
            if key == "timestamp" or value is None or key in out:
                continue
            out[key] = {"value": value, "timestamp": ts}
    return out


def distance_m(a: list[float], b: list[float]) -> float:
    lat = math.radians((a[1] + b[1]) / 2)
    dx = (a[0] - b[0]) * 111_320 * math.cos(lat)
    dy = (a[1] - b[1]) * 110_540
    return math.hypot(dx, dy)


def _newest(candidates: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Pick one sensor, preferring the most recently installed one."""
    if not candidates:
        return None
    return max(
        candidates,
        key=lambda s: (bool(_DATED_NAME_RE.match(s["name"])), s["name"]),
    )


def match_legacy_station(
    name: str | None,
    coordinates: list[float] | None,
    sensors: list[dict[str, Any]],
) -> dict[str, str | None]:
    """Map an old dashboard station to official sensors by role.

    Returns ``{"climate": sensorId | None, "wind": sensorId | None}``.
    Sensor codes in the dashboard name win (they name exactly the sensors
    the dashboard served); roles still missing are filled from sensors at
    the same position (within ~50 m).

    Dashboard names mark replaced sensors, e.g.
    ``T-002 | 2306LW027 ARCHIV_22.05.2026``: archived segments are skipped,
    and so is any named sensor that has since moved away from the station
    (2306LW027 now reports from ~2 km away).
    """
    has_coords = bool(coordinates and len(coordinates) == 2)
    by_name = {short_name(s["name"]).upper(): s for s in sensors}
    roles: dict[str, dict[str, Any] | None] = {KIND_CLIMATE: None, KIND_WIND: None}

    for segment in (name or "").split("|"):
        if "ARCHIV" in segment.upper():
            continue
        for token in _TOKEN_RE.findall(segment):
            hit = by_name.get(token.upper())
            if not hit:
                continue
            if (
                has_coords
                and hit.get("coordinates")
                and distance_m(hit["coordinates"], coordinates) > _MAX_MATCH_DISTANCE_M
            ):
                continue
            kind = sensor_kind(hit["params"])
            if roles[kind] is None:
                roles[kind] = hit

    if has_coords and None in roles.values():
        placed = [s for s in sensors if s.get("coordinates")]
        exact = [s for s in placed if s["coordinates"] == list(coordinates)]
        nearby = exact or [
            s for s in placed
            if distance_m(s["coordinates"], coordinates) <= _MAX_MATCH_DISTANCE_M
        ]
        for kind in roles:
            if roles[kind] is None:
                roles[kind] = _newest(
                    [s for s in nearby if sensor_kind(s["params"]) == kind]
                )

    return {kind: (s["sensorId"] if s else None) for kind, s in roles.items()}
