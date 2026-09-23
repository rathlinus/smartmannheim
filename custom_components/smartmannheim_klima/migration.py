"""Config entry migration: dashboard stations (v1) → official sensors (v2).

Version 1 stored dashboard stations (``locationId``); version 2 stores
official API sensors (``sensorId``). Entities keep their ``entity_id`` —
only their ``unique_id`` is rewritten — so history and customisations
survive the switch.
"""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components import persistent_notification
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import SmartMannheimClient, SmartMannheimError
from .const import CONF_STATIONS, DOMAIN
from .helpers import async_get_sensors, async_get_snapshot
from .official import (
    KIND_CLIMATE,
    KIND_WIND,
    climate_interval_minutes,
    location_key,
    match_legacy_station,
    normalize_sensors,
)

_LOGGER = logging.getLogger(__name__)

# Old entity key → (role of the official sensor, official parameter)
_LEGACY_KEYS: dict[str, tuple[str, str]] = {
    "temperature": (KIND_CLIMATE, "temperature"),
    "humidity": (KIND_CLIMATE, "airHumidity"),
    "wind_speed": (KIND_WIND, "averageWindSpeed"),
}

CURRENT_VERSION = 2


def plan_migration(
    stations: list[dict[str, Any]],
    sensors: list[dict[str, Any]],
    legacy_map: dict[str, dict[str, str | None]],
    registered_unique_ids: set[str],
) -> tuple[dict[str, list[dict[str, Any]]], dict[str, str], list[str]]:
    """Work out the new selection and unique-id rewrites.

    Returns ``(new_sensors_by_location_id, unique_id_map, unmatched_names)``.
    Only roles that actually had entities are carried over, so a station
    whose wind sensor was never used doesn't start costing requests.
    """
    by_id = {s["sensorId"]: s for s in sensors}
    per_station: dict[str, list[dict[str, Any]]] = {}
    uid_map: dict[str, str] = {}
    unmatched: list[str] = []

    for station in stations:
        loc = station.get("locationId")
        if not loc or loc in per_station:
            continue
        roles = legacy_map.get(loc) or match_legacy_station(
            station.get("name"), station.get("coordinates"), sensors
        )
        role_sensor = {
            kind: by_id.get(sensor_id) if sensor_id else None
            for kind, sensor_id in roles.items()
        }
        old_uids = {key: f"{DOMAIN}_{loc}_{key}" for key in _LEGACY_KEYS}
        used_roles = {
            _LEGACY_KEYS[key][0]
            for key, uid in old_uids.items()
            if uid in registered_unique_ids
        } or {KIND_CLIMATE, KIND_WIND}

        chosen: list[dict[str, Any]] = []
        for kind in (KIND_CLIMATE, KIND_WIND):
            sensor = role_sensor.get(kind)
            if sensor and kind in used_roles:
                chosen.append(sensor)
                for key, (role, param) in _LEGACY_KEYS.items():
                    if role == kind:
                        uid_map[old_uids[key]] = f"{DOMAIN}_{sensor['sensorId']}_{param}"
        if not chosen:
            unmatched.append(station.get("name") or loc)
            continue
        per_station[loc] = chosen
        uid_map[f"{DOMAIN}_{loc}_location"] = f"{DOMAIN}_{location_key(chosen[0])}_location"

    return per_station, uid_map, unmatched


def _rewrite(
    stations: list[dict[str, Any]], per_station: dict[str, list[dict[str, Any]]]
) -> list[dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for station in stations:
        for sensor in per_station.get(station.get("locationId"), []):
            out.setdefault(sensor["sensorId"], sensor)
    return list(out.values())


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Migrate an old config entry (called by HA before setup)."""
    if entry.version > CURRENT_VERSION:
        return False
    if entry.version == CURRENT_VERSION:
        return True

    snapshot = await async_get_snapshot(hass)
    try:
        sensors = await async_get_sensors(
            hass, SmartMannheimClient(async_get_clientsession(hass))
        )
    except SmartMannheimError as err:
        # The bundled list is good enough to map old stations; ids that
        # no longer exist simply show up as unavailable afterwards.
        _LOGGER.warning("Sensor list unavailable (%s); migrating from snapshot", err)
        sensors = normalize_sensors(snapshot["api"])

    old_data = list(entry.data.get(CONF_STATIONS, []))
    old_options = entry.options.get(CONF_STATIONS)
    ent_reg = er.async_get(hass)
    registered = {
        e.unique_id for e in er.async_entries_for_config_entry(ent_reg, entry.entry_id)
    }
    per_station, uid_map, unmatched = plan_migration(
        old_data + list(old_options or []),
        sensors,
        snapshot.get("legacy") or {},
        registered,
    )

    @callback
    def _migrate(entity: er.RegistryEntry) -> dict[str, Any] | None:
        new_uid = uid_map.get(entity.unique_id)
        if new_uid is None:
            return None
        if ent_reg.async_get_entity_id(entity.domain, DOMAIN, new_uid):
            # Two old stations mapped to the same sensor; keep the first.
            return None
        # Detach from the old device, which setup removes afterwards; the
        # platform re-attaches the entity to its new location device.
        return {"new_unique_id": new_uid, "device_id": None}

    await er.async_migrate_entries(hass, entry.entry_id, _migrate)

    new_data = {**entry.data, CONF_STATIONS: _rewrite(old_data, per_station)}
    new_options = dict(entry.options)
    if old_options is not None:
        new_options[CONF_STATIONS] = _rewrite(list(old_options), per_station)
    hass.config_entries.async_update_entry(
        entry, data=new_data, options=new_options, version=CURRENT_VERSION
    )

    count = len(new_options.get(CONF_STATIONS, new_data[CONF_STATIONS]))
    _notify(hass, count, unmatched)
    _LOGGER.info(
        "Migrated %s to the official API: %d sensors, %d unmatched stations",
        entry.title, count, len(unmatched),
    )
    return True


def _notify(hass: HomeAssistant, count: int, unmatched: list[str]) -> None:
    interval = climate_interval_minutes(count)
    lines = [
        "Die Klimastationen nutzen jetzt die offizielle API "
        "(api.smartmannheim.de). Deine Entitäten und ihr Verlauf bleiben erhalten.",
        "",
        f"**{count} Sensoren** ausgewählt → Aktualisierung **alle {interval} Minuten**. "
        "Die API erlaubt 30 Anfragen pro Stunde, also 5 Sensoren im 10-Minuten-Takt; "
        "eine Station mit Temperatur und Wind zählt als 2 Sensoren.",
    ]
    if unmatched:
        lines += [
            "",
            "Nicht gefunden und entfernt: " + ", ".join(unmatched),
        ]
    lines += [
        "",
        f"_Climate stations now use the official API. {count} sensors → "
        f"updates every {interval} minutes (limit: 30 requests/hour)._",
    ]
    persistent_notification.async_create(
        hass,
        "\n".join(lines),
        title="Smart City Mannheim: offizielle API",
        notification_id=f"{DOMAIN}_migrated",
    )
