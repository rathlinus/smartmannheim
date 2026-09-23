"""Smart City Mannheim integration."""
from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from . import metadata
from .api import SmartMannheimClient
from .const import (
    AQI_STATIONS,
    CONF_INCLUDE_AQI,
    CONF_INCLUDE_DWD,
    CONF_INCLUDE_POLLEN,
    DOMAIN,
    DWD_DEVICE_ID,
    ISSUE_TOO_MANY_SENSORS,
    POLLEN_DEVICE_ID,
)
from .coordinator import ClimateCoordinator, ExtrasCoordinator, RuntimeData
from .helpers import async_get_snapshot, get_stations, location_devices, option_flag
from .migration import async_migrate_entry  # noqa: F401  (HA looks it up here)
from .official import SENSORS_AT_MIN_INTERVAL, climate_interval_minutes

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.DEVICE_TRACKER, Platform.SENSOR]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up from a config entry."""
    session = async_get_clientsession(hass)
    client = SmartMannheimClient(session)
    await hass.async_add_executor_job(metadata.load)
    snapshot = await async_get_snapshot(hass)

    sensors = get_stations(entry)
    climate: ClimateCoordinator | None = None
    if sensors:
        climate = ClimateCoordinator(hass, client, sensors)
        await climate.async_config_entry_first_refresh()
    else:
        # Allowed: pollen / AQI / DWD still work without climate stations.
        _LOGGER.debug("No climate stations selected for %s", entry.title)

    extras: ExtrasCoordinator | None = None
    flags = {key: option_flag(entry, key) for key in (CONF_INCLUDE_POLLEN, CONF_INCLUDE_AQI, CONF_INCLUDE_DWD)}
    if any(flags.values()):
        extras = ExtrasCoordinator(
            hass,
            client,
            include_pollen=flags[CONF_INCLUDE_POLLEN],
            include_aqi=flags[CONF_INCLUDE_AQI],
            include_dwd=flags[CONF_INCLUDE_DWD],
        )
        await extras.async_config_entry_first_refresh()

    runtime = RuntimeData(
        climate=climate,
        extras=extras,
        sensors=sensors,
        devices=location_devices(sensors, snapshot),
    )
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = runtime
    _update_rate_limit_issue(hass, len(sensors))

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    # Only after the platforms re-attached migrated entities to their new
    # devices; removing a device also removes the entities still on it.
    _remove_stale_devices(hass, entry, runtime, flags)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


def _update_rate_limit_issue(hass: HomeAssistant, sensor_count: int) -> None:
    """Tell the user when the API limit stretches the update interval."""
    if sensor_count > SENSORS_AT_MIN_INTERVAL:
        ir.async_create_issue(
            hass,
            DOMAIN,
            ISSUE_TOO_MANY_SENSORS,
            is_fixable=False,
            severity=ir.IssueSeverity.WARNING,
            translation_key=ISSUE_TOO_MANY_SENSORS,
            translation_placeholders={
                "count": str(sensor_count),
                "interval": str(climate_interval_minutes(sensor_count)),
                "max_sensors": str(SENSORS_AT_MIN_INTERVAL),
            },
        )
    else:
        ir.async_delete_issue(hass, DOMAIN, ISSUE_TOO_MANY_SENSORS)


def _remove_stale_devices(
    hass: HomeAssistant,
    entry: ConfigEntry,
    runtime: RuntimeData,
    flags: dict[str, bool],
) -> None:
    """Drop devices of deselected stations and disabled extras.

    Removing a device also removes its entities from the entity registry,
    so nothing lingers as "no longer provided".
    """
    wanted = set(runtime.devices)
    if flags[CONF_INCLUDE_POLLEN]:
        wanted.add(POLLEN_DEVICE_ID)
    if flags[CONF_INCLUDE_AQI]:
        wanted.update(f"aqi_{s['key']}" for s in AQI_STATIONS)
    if flags[CONF_INCLUDE_DWD]:
        wanted.add(DWD_DEVICE_ID)

    dev_reg = dr.async_get(hass)
    for device in dr.async_entries_for_config_entry(dev_reg, entry.entry_id):
        ids = {ident for domain, ident in device.identifiers if domain == DOMAIN}
        if ids and not ids & wanted:
            dev_reg.async_remove_device(device.id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        hass.data[DOMAIN].pop(entry.entry_id, None)
    return unloaded


async def async_remove_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Clean up the rate-limit notice when the integration is removed."""
    ir.async_delete_issue(hass, DOMAIN, ISSUE_TOO_MANY_SENSORS)


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload when station selection or extras toggles change in options."""
    await hass.config_entries.async_reload(entry.entry_id)
