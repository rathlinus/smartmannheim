"""Climate coordinator: keeping values across failed fetches."""
from __future__ import annotations

import logging
from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest
from freezegun.api import FrozenDateTimeFactory
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.update_coordinator import UpdateFailed
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.smartmannheim_klima.api import (
    SensorNotFoundError,
    SmartMannheimError,
)
from custom_components.smartmannheim_klima.const import (
    CONF_INCLUDE_AQI,
    CONF_INCLUDE_DWD,
    CONF_INCLUDE_POLLEN,
    CONF_STATIONS,
    DOMAIN,
)
from custom_components.smartmannheim_klima.coordinator import ClimateCoordinator

from .common import load_fixture, sensor

ROWS = load_fixture("measurements_climate.json")["data"]
THERMO = sensor("0101-001-21")
SID = THERMO["sensorId"]


def _coordinator(hass: HomeAssistant, get_measurements) -> ClimateCoordinator:
    client = MagicMock()
    client.get_measurements = AsyncMock(side_effect=get_measurements)
    return ClimateCoordinator(hass, client, [THERMO])


async def test_failed_fetch_keeps_last_values(hass: HomeAssistant, caplog) -> None:
    responses = [ROWS, SmartMannheimError("HTTP 429 for …"), SmartMannheimError("again"), ROWS]
    coordinator = _coordinator(hass, responses)

    first = await coordinator._async_update_data()
    coordinator.data = first
    caplog.set_level(logging.INFO)

    kept = await coordinator._async_update_data()
    assert kept[SID] == first[SID]
    coordinator.data = kept
    await coordinator._async_update_data()
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    # One warning per outage, naming the cause.
    assert len(warnings) == 1
    assert "HTTP 429" in warnings[0].getMessage()
    assert "keeping last values" in warnings[0].getMessage()

    await coordinator._async_update_data()
    assert any("delivering data again" in r.getMessage() for r in caplog.records)


async def test_empty_response_keeps_last_values(hass: HomeAssistant) -> None:
    coordinator = _coordinator(hass, [ROWS, []])
    coordinator.data = await coordinator._async_update_data()
    assert (await coordinator._async_update_data())[SID]["temperature"]["value"] == 13.4


async def test_not_found_gives_none(hass: HomeAssistant) -> None:
    coordinator = _coordinator(hass, [ROWS, SensorNotFoundError("gone")])
    coordinator.data = await coordinator._async_update_data()
    with pytest.raises(UpdateFailed):
        # The only sensor is gone and nothing else was fetched.
        await coordinator._async_update_data()


async def test_first_refresh_all_failed(hass: HomeAssistant) -> None:
    coordinator = _coordinator(hass, [SmartMannheimError("down")])
    with pytest.raises(UpdateFailed):
        await coordinator._async_update_data()


async def test_kept_values_expire(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    freezer.move_to("2026-09-23T08:05:00+00:00")
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=DOMAIN,
        version=2,
        data={
            CONF_STATIONS: [THERMO],
            CONF_INCLUDE_POLLEN: False,
            CONF_INCLUDE_AQI: False,
            CONF_INCLUDE_DWD: False,
        },
    )
    entry.add_to_hass(hass)
    get = AsyncMock(return_value=ROWS)
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(
            "custom_components.smartmannheim_klima.api.SmartMannheimClient.get_measurements",
            get,
        )
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        entity_id = er.async_get(hass).async_get_entity_id(
            "sensor", DOMAIN, f"{DOMAIN}_{SID}_temperature"
        )
        assert hass.states.get(entity_id).state == "13.4"

        # API fails from now on; values are kept …
        get.side_effect = SmartMannheimError("down")
        coordinator = hass.data[DOMAIN][entry.entry_id].climate
        freezer.tick(timedelta(minutes=30))
        await coordinator.async_refresh()
        await hass.async_block_till_done()
        assert hass.states.get(entity_id).state == "13.4"

        # … until they are older than max_age (60 min for 1 sensor).
        freezer.tick(timedelta(minutes=40))
        await coordinator.async_refresh()
        await hass.async_block_till_done()
        assert hass.states.get(entity_id).state == "unavailable"
