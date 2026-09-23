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


DWD_URL = "https://dashboard.mvvsmartcities.com/api/timeseriesanalyticsindicator"


def _dwd_series(key: str) -> dict:
    from custom_components.smartmannheim_klima.const import DWD_SERIES

    return next(s for s in DWD_SERIES if s["key"] == key)


@pytest.mark.parametrize(
    ("now", "expected_from"),
    [
        # Summer (CEST, UTC+2) and winter (CET, UTC+1).
        ("2026-09-23T10:05:00+00:00", "2026-09-22T22:00:00.000Z"),
        ("2026-01-15T10:05:00+00:00", "2026-01-14T23:00:00.000Z"),
        # 23:30 UTC is already the next day in Berlin.
        ("2026-09-23T23:30:00+00:00", "2026-09-23T22:00:00.000Z"),
    ],
)
def test_window_today(freezer, now, expected_from) -> None:
    from custom_components.smartmannheim_klima.api import _window_today

    freezer.move_to(now)
    frm, to = _window_today()
    assert frm == expected_from
    assert to.startswith(now[:16])


async def test_dwd_precipitation_today_request(
    hass: HomeAssistant, aioclient_mock, freezer
) -> None:
    freezer.move_to("2026-09-23T10:05:00+00:00")
    aioclient_mock.post(
        DWD_URL,
        json=[{"indicator": 2.44, "timestamp": "2026-09-23T10:05:00.000Z", "warning": None}],
    )
    client = SmartMannheimClient(async_get_clientsession(hass))
    reading = await client.get_dwd_indicator(_dwd_series("precipitation_today"))
    assert reading["indicator"] == 2.44

    body = aioclient_mock.mock_calls[-1][2]
    assert body["timeseries"][0]["aggregationFunction"] == "sum"
    assert body["from"] == "2026-09-22T22:00:00.000Z"


async def test_dwd_precipitation_today_no_data_is_zero(
    hass: HomeAssistant, aioclient_mock
) -> None:
    aioclient_mock.post(
        DWD_URL,
        json=[{"indicator": None, "warning": {"code": "NO_DATA_FOUND", "data": {"name": ""}}}],
    )
    client = SmartMannheimClient(async_get_clientsession(hass))
    reading = await client.get_dwd_indicator(_dwd_series("precipitation_today"))
    assert reading["indicator"] == 0
    assert reading["warning"] is None


async def test_dwd_plain_series_unchanged(hass: HomeAssistant, aioclient_mock) -> None:
    aioclient_mock.post(
        DWD_URL,
        json=[{"indicator": None, "warning": {"code": "NO_DATA_FOUND", "data": {"name": ""}}}],
    )
    client = SmartMannheimClient(async_get_clientsession(hass))
    reading = await client.get_dwd_indicator(_dwd_series("precipitation"))
    # Only sums turn "no data" into 0; a missing measurement stays unknown.
    assert reading["indicator"] is None
    body = aioclient_mock.mock_calls[-1][2]
    assert body["timeseries"][0]["aggregationFunction"] == ""
