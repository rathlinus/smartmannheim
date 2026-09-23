"""Setup and device cleanup."""
from __future__ import annotations

from unittest.mock import patch

from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.smartmannheim_klima.const import (
    CONF_INCLUDE_AQI,
    CONF_INCLUDE_DWD,
    CONF_INCLUDE_POLLEN,
    CONF_STATIONS,
    DOMAIN,
    DWD_DEVICE_ID,
    POLLEN_DEVICE_ID,
)

UPDATE = (
    "custom_components.smartmannheim_klima.coordinator."
    "SmartMannheimCoordinator._async_update_data"
)
EMPTY = {"stations": {}, "pollen": {}, "aqi": {}, "dwd": {}}


async def test_setup_removes_stale_devices(hass: HomeAssistant) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=DOMAIN,
        data={
            CONF_STATIONS: [
                {"locationId": "loc-1", "name": "A", "coordinates": [8.47, 49.49]}
            ],
            CONF_INCLUDE_POLLEN: True,
            CONF_INCLUDE_AQI: True,
            CONF_INCLUDE_DWD: True,
        },
        options={
            CONF_STATIONS: [
                {"locationId": "loc-1", "name": "A", "coordinates": [8.47, 49.49]}
            ],
            CONF_INCLUDE_POLLEN: True,
            CONF_INCLUDE_AQI: True,
            CONF_INCLUDE_DWD: False,
        },
    )
    entry.add_to_hass(hass)
    dev_reg = dr.async_get(hass)
    for ident in ("loc-old", DWD_DEVICE_ID, POLLEN_DEVICE_ID):
        dev_reg.async_get_or_create(
            config_entry_id=entry.entry_id, identifiers={(DOMAIN, ident)}
        )

    with patch(UPDATE, return_value=EMPTY):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    assert dev_reg.async_get_device(identifiers={(DOMAIN, "loc-old")}) is None
    assert dev_reg.async_get_device(identifiers={(DOMAIN, DWD_DEVICE_ID)}) is None
    assert dev_reg.async_get_device(identifiers={(DOMAIN, POLLEN_DEVICE_ID)})
    assert dev_reg.async_get_device(identifiers={(DOMAIN, "loc-1")})
    # Station sensors exist but are unavailable without data.
    assert hass.states.get("sensor.a_temperature").state == "unavailable"
