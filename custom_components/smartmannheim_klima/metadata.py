"""Loader + matcher for the Smart Mannheim station metadata catalog.

The integration ships ``station_metadata.json``, a snapshot of the public
Excel metadata catalog. The official API only gives us id, name and
position per sensor; this module matches the sensor name (e.g.
``0101-001-21``) back to a catalog row so we can enrich the HA device and
entities with altitude, LCZ, commissioning date and measurement heights.

Call :func:`load` from an executor before the first :func:`lookup`; it
reads the file once and caches it.
"""
from __future__ import annotations

import json
import logging
import os
import re
from functools import lru_cache
from typing import Any

_LOGGER = logging.getLogger(__name__)

_HERE = os.path.dirname(__file__)
_FILE = os.path.join(_HERE, "station_metadata.json")

# Used to tokenise an API station name like ``T-016 - SCM auf der Buga``
# or ``0101-001-21 | 0101-001-31``. Hyphenated IDs must stay intact.
_TOKEN_RE = re.compile(r"[0-9A-Za-z]+(?:-[0-9A-Za-z]+){0,3}")

# Official API parameter → metadata catalog flag (column in the xlsx).
SENSOR_TO_META_KEY: dict[str, str] = {
    "temperature": "TT",
    "airHumidity": "RF",
    "averageWindSpeed": "FF",
    "averageWindDirection": "DD",
    "atmosphericPressure": "PP",
    "irradiation": "GS",
}


def load() -> None:
    """Warm the cache (blocking file I/O — run in an executor)."""
    _index_by_id()


@lru_cache(maxsize=1)
def _load_snapshot() -> dict[str, Any]:
    try:
        with open(_FILE, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        _LOGGER.warning("station_metadata.json missing — skipping enrichment")
        return {"stations": [], "station_count": 0}
    except (OSError, ValueError) as err:
        _LOGGER.warning("Could not load station metadata: %s", err)
        return {"stations": [], "station_count": 0}


@lru_cache(maxsize=1)
def _index_by_id() -> dict[str, dict[str, Any]]:
    """Keyed by every plausible identifier the catalog row carries.

    Both ``station_name`` (e.g. ``T-016``, ``2303LH068``) and the
    ``code_string_prefix`` (``0101-001-21``) become lookup keys.
    """
    idx: dict[str, dict[str, Any]] = {}
    for st in _load_snapshot()["stations"]:
        for key in (st.get("station_name"), st.get("code_string_prefix")):
            if key:
                idx[str(key).strip().upper()] = st
    return idx


def lookup(api_station_name: str | None) -> dict[str, Any] | None:
    """Find metadata for an API station by scanning tokens in its name.

    Returns ``None`` if no token in the name appears in the catalog.
    """
    if not api_station_name:
        return None
    idx = _index_by_id()
    for token in _TOKEN_RE.findall(api_station_name):
        hit = idx.get(token.upper())
        if hit:
            return hit
    return None


def sensor_info(meta: dict[str, Any] | None, sensor_key: str) -> dict[str, Any] | None:
    """Per-sensor catalog details (measurement height, type/accuracy) if any."""
    if not meta:
        return None
    meta_key = SENSOR_TO_META_KEY.get(sensor_key)
    if not meta_key:
        return None
    info = (meta.get("sensors") or {}).get(meta_key)
    if not info or not info.get("installed"):
        return None
    out: dict[str, Any] = {}
    if "height_m" in info:
        out["height_m"] = info["height_m"]
    if "type_accuracy" in info:
        out["type_accuracy"] = info["type_accuracy"]
    return out or None


def device_attrs(meta: dict[str, Any] | None) -> dict[str, Any]:
    """Static catalog attributes worth attaching to the HA device."""
    if not meta:
        return {}
    out: dict[str, Any] = {}
    for src, dst in (
        ("station_name", "catalog_id"),
        ("station_id", "station_id"),
        ("code_string_prefix", "code_string"),
        ("altitude_m", "altitude_m"),
        ("commissioned_at", "commissioned_at"),
        ("lcz", "local_climate_zone"),
        ("station_type", "station_type_code"),
        ("station_quality", "station_quality_code"),
    ):
        v = meta.get(src)
        if v not in (None, ""):
            out[dst] = v
    return out
