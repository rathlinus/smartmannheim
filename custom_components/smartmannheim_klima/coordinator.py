"""DataUpdateCoordinator that polls every selected station."""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import SmartMannheimClient, SmartMannheimError
from .const import DEFAULT_SCAN_INTERVAL, DOMAIN, MEASUREMENTS

_LOGGER = logging.getLogger(__name__)

# Be a good citizen — the backend is a shared dashboard, not a rate-limited
# API. Still, don't fan out unboundedly if the user selects many stations.
_MAX_CONCURRENCY = 4


class SmartMannheimCoordinator(DataUpdateCoordinator[dict[str, dict[str, Any]]]):
    """Fetch the latest indicator for every (station, measurement) pair."""

    def __init__(
        self,
        hass: HomeAssistant,
        client: SmartMannheimClient,
        stations: list[dict[str, Any]],
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=DEFAULT_SCAN_INTERVAL,
        )
        self.client = client
        self.stations = stations

    async def _async_update_data(self) -> dict[str, dict[str, Any]]:
        sem = asyncio.Semaphore(_MAX_CONCURRENCY)

        async def fetch_one(
            station: dict[str, Any], meas: dict[str, Any]
        ) -> tuple[str, str, dict[str, Any] | None]:
            async with sem:
                try:
                    data = await self.client.get_indicator(
                        station["locationId"], meas
                    )
                except SmartMannheimError as err:
                    _LOGGER.debug(
                        "Fetch failed %s/%s: %s",
                        station.get("name"),
                        meas["key"],
                        err,
                    )
                    data = None
                return station["locationId"], meas["key"], data

        tasks = [
            fetch_one(s, m)
            for s in self.stations
            for m in MEASUREMENTS
        ]
        if not tasks:
            return {}

        try:
            results = await asyncio.gather(*tasks)
        except SmartMannheimError as err:
            raise UpdateFailed(str(err)) from err

        out: dict[str, dict[str, Any]] = {
            s["locationId"]: {} for s in self.stations
        }
        for location_id, key, data in results:
            out[location_id][key] = data
        return out
