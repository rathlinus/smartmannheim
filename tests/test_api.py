"""Official API client."""
from __future__ import annotations

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from custom_components.smartmannheim_klima.api import (
    SensorNotFoundError,
    SmartMannheimClient,
    SmartMannheimError,
)

from .common import load_fixture

BASE = "https://api.smartmannheim.de/climate"


async def test_list_sensors(hass: HomeAssistant, aioclient_mock) -> None:
    aioclient_mock.get(f"{BASE}/sensors", json=load_fixture("sensors.json"))
    client = SmartMannheimClient(async_get_clientsession(hass))
    data = await client.list_sensors()
    assert len(data["sensors"]) == 8


async def test_get_measurements(hass: HomeAssistant, aioclient_mock) -> None:
    aioclient_mock.get(
        f"{BASE}/measurements/0004A30B00F72EED",
        json=load_fixture("measurements_climate.json"),
    )
    client = SmartMannheimClient(async_get_clientsession(hass))
    rows = await client.get_measurements("0004A30B00F72EED")
    assert rows[0]["temperature"] == 13.4


async def test_unknown_sensor(hass: HomeAssistant, aioclient_mock) -> None:
    aioclient_mock.get(
        f"{BASE}/measurements/NOPE", status=404, json={"error": "Sensor not found"}
    )
    client = SmartMannheimClient(async_get_clientsession(hass))
    with pytest.raises(SensorNotFoundError):
        await client.get_measurements("NOPE")


async def test_server_error(hass: HomeAssistant, aioclient_mock) -> None:
    aioclient_mock.get(f"{BASE}/sensors", status=500, text="boom")
    client = SmartMannheimClient(async_get_clientsession(hass))
    with pytest.raises(SmartMannheimError):
        await client.list_sensors()
