"""Small helpers shared by setup, platforms and the config flow."""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo

from . import metadata
from .api import SmartMannheimClient
from .const import CONF_STATIONS, DOMAIN, SENSOR_LIST_CACHE_TTL
from .official import KIND_CLIMATE, location_key, normalize_sensors, sensor_kind, short_name

_SNAPSHOT_FILE = Path(__file__).parent / "sensor_snapshot.json"
_SENSOR_CACHE_KEY = f"{DOMAIN}_sensor_cache"
_SNAPSHOT_KEY = f"{DOMAIN}_snapshot"


def get_stations(entry: ConfigEntry) -> list[dict[str, Any]]:
    """Return the selected sensors, preferring options over data.

    An empty list stored in options is a deliberate "no stations" choice
    and must not fall back to the stations picked during initial setup.
    """
    if CONF_STATIONS in entry.options:
        return list(entry.options[CONF_STATIONS] or [])
    return list(entry.data.get(CONF_STATIONS, []))


def option_flag(entry: ConfigEntry, key: str, default: bool = True) -> bool:
    """Read a boolean toggle, preferring options over data."""
    val = entry.options.get(key)
    if val is None:
        val = entry.data.get(key, default)
    return bool(val)


def _read_snapshot() -> dict[str, Any]:
    return json.loads(_SNAPSHOT_FILE.read_text(encoding="utf-8"))


async def async_get_snapshot(hass: HomeAssistant) -> dict[str, Any]:
    """Bundled snapshot (addresses, legacy mapping, offline sensor list)."""
    if _SNAPSHOT_KEY not in hass.data:
        hass.data[_SNAPSHOT_KEY] = await hass.async_add_executor_job(_read_snapshot)
    return hass.data[_SNAPSHOT_KEY]


async def async_get_sensors(
    hass: HomeAssistant, client: SmartMannheimClient
) -> list[dict[str, Any]]:
    """Official sensor list, cached so flows stay within 4 calls/hour."""
    cached = hass.data.get(_SENSOR_CACHE_KEY)
    if cached and time.monotonic() - cached[0] < SENSOR_LIST_CACHE_TTL.total_seconds():
        return cached[1]
    sensors = normalize_sensors(await client.list_sensors())
    hass.data[_SENSOR_CACHE_KEY] = (time.monotonic(), sensors)
    return sensors


def address_for(sensor: dict[str, Any], snapshot: dict[str, Any]) -> str | None:
    return (snapshot.get("addresses") or {}).get(location_key(sensor))


def location_devices(
    sensors: list[dict[str, Any]], snapshot: dict[str, Any]
) -> dict[str, DeviceInfo]:
    """One device per location, shared by all selected sensors there.

    Named after the street address when the snapshot knows it, else after
    the sensor codes (``0101-001-21 | 0101-001-31``), like the dashboard.
    The catalog's commissioning date is used as `hw_version` so it shows
    up in the HA device card without needing a custom field.
    """
    groups: dict[str, list[dict[str, Any]]] = {}
    for sensor in sensors:
        groups.setdefault(location_key(sensor), []).append(sensor)

    devices: dict[str, DeviceInfo] = {}
    for key, members in groups.items():
        # Climate sensor first: it carries the catalog row with altitude.
        members = sorted(members, key=lambda s: (sensor_kind(s["params"]) != KIND_CLIMATE, s["name"]))
        codes = " | ".join(short_name(s["name"]) for s in members)
        device_info = DeviceInfo(
            identifiers={(DOMAIN, key)},
            name=address_for(members[0], snapshot) or codes,
            manufacturer="Stadt Mannheim",
            model="Klimamessstation",
            serial_number=codes,
            configuration_url="https://smartmannheim.de/datenartikel/klimamessnetz-mannheim/",
        )
        meta = next(filter(None, (metadata.lookup(s["name"]) for s in members)), None)
        if meta:
            if meta.get("commissioned_at"):
                device_info["hw_version"] = meta["commissioned_at"]
            if meta.get("altitude_m") is not None:
                device_info["model"] = f"Klimamessstation (Höhe {meta['altitude_m']} m NN)"
        devices[key] = device_info
    return devices
