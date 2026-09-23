"""Smart Mannheim Klimamessnetz integration."""
from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import SmartMannheimClient
from .const import (
    AQI_STATIONS,
    CONF_INCLUDE_AQI,
    CONF_INCLUDE_DWD,
    CONF_INCLUDE_POLLEN,
    DOMAIN,
    DWD_DEVICE_ID,
    POLLEN_DEVICE_ID,
)
from .coordinator import SmartMannheimCoordinator
from .helpers import get_stations, option_flag

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.DEVICE_TRACKER, Platform.SENSOR]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up from a config entry."""
    session = async_get_clientsession(hass)
    client = SmartMannheimClient(session)

    stations = get_stations(entry)
    if not stations:
        # Allowed: pollen / AQI / DWD still work without climate stations.
        _LOGGER.debug("No climate stations selected for %s", entry.title)

    coordinator = SmartMannheimCoordinator(
        hass,
        client,
        stations,
        include_pollen=option_flag(entry, CONF_INCLUDE_POLLEN),
        include_aqi=option_flag(entry, CONF_INCLUDE_AQI),
        include_dwd=option_flag(entry, CONF_INCLUDE_DWD),
    )
    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator
    _remove_stale_devices(hass, entry, coordinator)

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


def _remove_stale_devices(
    hass: HomeAssistant, entry: ConfigEntry, coordinator: SmartMannheimCoordinator
) -> None:
    """Drop devices of deselected stations and disabled extras.

    Removing a device also removes its entities from the entity registry,
    so nothing lingers as "no longer provided".
    """
    wanted = {s["locationId"] for s in coordinator.stations}
    if coordinator.include_pollen:
        wanted.add(POLLEN_DEVICE_ID)
    if coordinator.include_aqi:
        wanted.update(f"aqi_{s['key']}" for s in AQI_STATIONS)
    if coordinator.include_dwd:
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


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload when station selection or extras toggles change in options."""
    await hass.config_entries.async_reload(entry.entry_id)
