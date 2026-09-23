"""Async clients for the official climate API and the dashboard backends."""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

import aiohttp
from yarl import URL

from .const import (
    AQI_ACCOUNT_ID,
    AQI_API_BASE,
    AQI_TOKEN,
    DWD_ACCOUNT_ID,
    DWD_API_BASE,
    DWD_TOKEN,
    OFFICIAL_API_BASE,
    POLLEN_ACCOUNT_ID,
    POLLEN_API_BASE,
    POLLEN_TOKEN,
    REQUEST_TIMEOUT,
)

_LOGGER = logging.getLogger(__name__)


class SmartMannheimError(Exception):
    """Base error."""


class SensorNotFoundError(SmartMannheimError):
    """The official API doesn't know this sensor (HTTP 404)."""


def _window_24h() -> tuple[str, str]:
    """Return a (from, to) ISO pair covering the last 24h in UTC."""
    now = datetime.now(timezone.utc)
    frm = (now - timedelta(hours=24)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    to = now.strftime("%Y-%m-%dT%H:%M:%S.000Z")
    return frm, to


class SmartMannheimClient:
    """Thin async wrapper around the Smart Mannheim backends.

    Climate stations use the official API (plain GETs, no auth). Pollen,
    AQI and the DWD station still use the public dashboard backends, where
    the dashboard token goes into the ``id`` query parameter.
    """

    def __init__(self, session: aiohttp.ClientSession) -> None:
        self._session = session

    async def list_sensors(self) -> dict[str, Any]:
        """Raw ``/climate/sensors`` payload (limited to 4 calls/hour)."""
        data = await self._get(URL(f"{OFFICIAL_API_BASE}/climate/sensors"))
        if not isinstance(data, dict) or not isinstance(data.get("sensors"), list):
            raise SmartMannheimError(f"Unexpected sensor list payload: {data!r:.200}")
        return data

    async def get_measurements(self, sensor_id: str) -> list[dict[str, Any]]:
        """Rows of the last 60 minutes for one sensor (6 calls/hour/sensor)."""
        url = URL(f"{OFFICIAL_API_BASE}/climate/measurements") / sensor_id
        data = await self._get(url)
        if not isinstance(data, dict):
            raise SmartMannheimError(f"Unexpected measurements payload: {data!r:.200}")
        rows = data.get("data") or []
        return [r for r in rows if isinstance(r, dict)]

    async def get_pollen_indicator(
        self, series: dict[str, Any]
    ) -> dict[str, Any] | None:
        """Latest value for one pollen species (DWD Pollenflug dashboard).

        Pollen uses a different host + endpoint (no tile / entity needed):
            POST dashboard.mvvsmartcities.com/api/timeseriesanalyticsindicator
        Returns one element of the standard ``[{indicator, timestamp, ...}]``
        shape, or None on empty / failed responses.
        """
        frm, to = _window_24h()
        url = URL(f"{POLLEN_API_BASE}/timeseriesanalyticsindicator").with_query(
            {"accountId": POLLEN_ACCOUNT_ID, "id": POLLEN_TOKEN}
        )
        body = {
            "timeseries": [
                {
                    "timeSeriesId": series["timeseries_id"],
                    "aggregationFunction": "",
                    "gapFill": "None",
                    "displayName": series["display_name"],
                    "displayDigits": None,
                    "definitionType": "timeseries",
                }
            ],
            "from": frm,
            "to": to,
            "accountId": POLLEN_ACCOUNT_ID,
            "orient": "analytics",
            "timezone": "Europe/Berlin",
        }
        data = await self._post(url, body)
        if not isinstance(data, list) or not data:
            return None
        return data[0]

    async def get_aqi_indicator(
        self, entity_id: str, measurement: dict[str, Any]
    ) -> dict[str, Any] | None:
        """Latest value for one UBA air-quality metric at one station."""
        frm, to = _window_24h()
        url = URL(f"{AQI_API_BASE}/dashboarddata").with_query(
            {"accountId": AQI_ACCOUNT_ID, "id": AQI_TOKEN}
        )
        timeseries_entry = {
            "timeSeriesId": measurement["timeseries_id"],
            "aggregationFunction": "",
            "gapFill": "None",
            "displayName": measurement["display_name"],
            measurement["digits_field"]: measurement["digits"],
            "definitionType": "timeseries",
        }
        body = {
            "timeseries": [timeseries_entry],
            "from": frm,
            "to": to,
            "accountId": AQI_ACCOUNT_ID,
            "orient": "analytics",
            "timezone": "Europe/Berlin",
            "dashboardTemplateTileId": measurement["tile_id"],
            "appId": AQI_TOKEN,
            "entityId": entity_id,
        }
        data = await self._post(url, body)
        if not isinstance(data, list) or not data:
            return None
        return data[0]

    async def get_dwd_indicator(
        self, series: dict[str, Any]
    ) -> dict[str, Any] | None:
        """Latest value for one DWD-station metric (Klimadaten dashboard)."""
        frm, to = _window_24h()
        url = URL(f"{DWD_API_BASE}/timeseriesanalyticsindicator").with_query(
            {"accountId": DWD_ACCOUNT_ID, "id": DWD_TOKEN}
        )
        body = {
            "timeseries": [
                {
                    "timeSeriesId": series["timeseries_id"],
                    "aggregationFunction": "",
                    "gapFill": "None",
                    "displayName": series["display_name"],
                    "displayDigits": 1,
                    "definitionType": series.get("definition_type", "timeseries"),
                }
            ],
            "from": frm,
            "to": to,
            "accountId": DWD_ACCOUNT_ID,
            "orient": "analytics",
            "timezone": "Europe/Berlin",
        }
        data = await self._post(url, body)
        if not isinstance(data, list) or not data:
            return None
        return data[0]

    async def _get(self, url: URL) -> Any:
        return await self._request("GET", url)

    async def _post(self, url: URL, body: dict[str, Any]) -> Any:
        return await self._request("POST", url, body)

    async def _request(
        self, method: str, url: URL, body: dict[str, Any] | None = None
    ) -> Any:
        timeout = aiohttp.ClientTimeout(total=REQUEST_TIMEOUT)
        try:
            async with self._session.request(
                method, url, json=body, timeout=timeout
            ) as resp:
                if resp.status == 404 and url.host == URL(OFFICIAL_API_BASE).host:
                    raise SensorNotFoundError(f"Not found: {url}")
                if resp.status >= 400:
                    text = await resp.text()
                    raise SmartMannheimError(
                        f"HTTP {resp.status} for {url}: {text[:200]}"
                    )
                return await resp.json(content_type=None)
        except asyncio.TimeoutError as err:
            raise SmartMannheimError(f"Timeout talking to {url}") from err
        except aiohttp.ClientError as err:
            raise SmartMannheimError(f"Network error: {err}") from err
