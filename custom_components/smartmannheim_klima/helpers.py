"""Small helpers shared by setup, platforms and the config flow."""
from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.device_registry import DeviceInfo

from .const import CONF_STATIONS, DOMAIN


def get_stations(entry: ConfigEntry) -> list[dict[str, Any]]:
    """Return the selected stations, preferring options over data.

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


def station_device_info(
    station: dict[str, Any], meta: dict[str, Any] | None
) -> DeviceInfo:
    """Device card for one climate station, enriched from the catalog.

    The catalog's commissioning date is used as `hw_version` so it shows
    up in the HA device card without needing a custom field.
    """
    location_id: str = station["locationId"]
    device_info = DeviceInfo(
        identifiers={(DOMAIN, location_id)},
        name=station.get("name") or location_id,
        manufacturer="Stadt Mannheim",
        model="Klimamessstation",
        configuration_url="https://smartmannheim.de/datenartikel/klimamessnetz-mannheim/",
    )
    if meta:
        if meta.get("commissioned_at"):
            device_info["hw_version"] = meta["commissioned_at"]
        if meta.get("altitude_m") is not None:
            device_info["model"] = f"Klimamessstation (Höhe {meta['altitude_m']} m NN)"
    return device_info
