"""Smart Mannheim Klimamessnetz integration."""
from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import SmartMannheimClient
from .const import (
    CONF_INCLUDE_AQI,
    CONF_INCLUDE_DWD,
    CONF_INCLUDE_POLLEN,
    CONF_STATIONS,
    DOMAIN,
)
from .coordinator import SmartMannheimCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.DEVICE_TRACKER, Platform.SENSOR]


def _flag(entry: ConfigEntry, key: str, default: bool = True) -> bool:
    """Read a boolean toggle, preferring options over data, defaulting True."""
    val = entry.options.get(key)
    if val is None:
        val = entry.data.get(key, default)
    return bool(val)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up from a config entry."""
    session = async_get_clientsession(hass)
    client = SmartMannheimClient(session)

    stations = entry.options.get(CONF_STATIONS) or entry.data.get(CONF_STATIONS, [])
    if not stations:
        _LOGGER.warning("No stations selected for %s", entry.title)

    coordinator = SmartMannheimCoordinator(
        hass,
        client,
        stations,
        include_pollen=_flag(entry, CONF_INCLUDE_POLLEN),
        include_aqi=_flag(entry, CONF_INCLUDE_AQI),
        include_dwd=_flag(entry, CONF_INCLUDE_DWD),
    )
    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        hass.data[DOMAIN].pop(entry.entry_id, None)
    return unloaded


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload when station selection or extras toggles change in options."""
    await hass.config_entries.async_reload(entry.entry_id)
