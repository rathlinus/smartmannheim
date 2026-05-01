"""Async client for the Smart Mannheim climate-network backend."""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

import aiohttp
from yarl import URL

from .const import (
    ACCOUNT_ID,
    API_BASE,
    APP_ID,
    DASHBOARD_TOKEN,
    MAP_TILE_ID,
    REQUEST_TIMEOUT,
)

_LOGGER = logging.getLogger(__name__)


class SmartMannheimError(Exception):
    """Base error."""


class SmartMannheimClient:
    """Thin async wrapper around the public dashboard backend.

    The public "dashboard token" acts as a shared read key: it is put into
    the `id` query parameter on every call. Per-station reads put the
    station id into the request body as `entityId`.
    """

    def __init__(self, session: aiohttp.ClientSession) -> None:
        self._session = session

    async def list_stations(self) -> list[dict[str, Any]]:
        """Return the list of all climate stations on the map."""
        url = URL(f"{API_BASE}/dashboarddata").with_query(
            {"accountId": ACCOUNT_ID, "id": DASHBOARD_TOKEN}
        )
        body = {"appId": APP_ID, "dashboardTemplateTileId": MAP_TILE_ID}
        data = await self._post(url, body)
        if not isinstance(data, list):
            raise SmartMannheimError(f"Unexpected station list payload: {data!r}")
        return data

    async def get_indicator(
        self, entity_id: str, measurement: dict[str, Any]
    ) -> dict[str, Any] | None:
        """Return latest value for one measurement at one station, or None."""
        now = datetime.now(timezone.utc)
        frm = (now - timedelta(hours=24)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
        to = now.strftime("%Y-%m-%dT%H:%M:%S.000Z")

        url = URL(f"{API_BASE}/dashboarddata").with_query(
            {"accountId": ACCOUNT_ID, "id": DASHBOARD_TOKEN}
        )
        # Per-measurement digits field name mirrors what the SPA sends:
        # wind uses `displayDigits`, the others use `numDigits`.
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
            "accountId": ACCOUNT_ID,
            "orient": "analytics",
            "timezone": "Europe/Berlin",
            "dashboardTemplateTileId": measurement["tile_id"],
            "appId": APP_ID,
            "entityId": entity_id,
        }
        data = await self._post(url, body)
        if not isinstance(data, list) or not data:
            return None
        return data[0]

    async def _post(self, url: URL, body: dict[str, Any]) -> Any:
        timeout = aiohttp.ClientTimeout(total=REQUEST_TIMEOUT)
        try:
            async with self._session.post(url, json=body, timeout=timeout) as resp:
                if resp.status >= 400:
                    text = await resp.text()
                    raise SmartMannheimError(
                        f"{resp.status} {resp.reason} for {url}: {text[:200]}"
                    )
                return await resp.json(content_type=None)
        except asyncio.TimeoutError as err:
            raise SmartMannheimError(f"Timeout talking to {url}") from err
        except aiohttp.ClientError as err:
            raise SmartMannheimError(f"Network error: {err}") from err
