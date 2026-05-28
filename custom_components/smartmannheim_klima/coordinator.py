"""DataUpdateCoordinator that polls every selected station."""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import SmartMannheimClient, SmartMannheimError
from .const import (
    AQI_STATIONS,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    DWD_SERIES,
    MEASUREMENTS,
    POLLEN_SERIES,
)

_LOGGER = logging.getLogger(__name__)

# Be a good citizen — the backend is a shared dashboard, not a rate-limited
# API. Still, don't fan out unboundedly if the user selects many stations.
_MAX_CONCURRENCY = 4


class SmartMannheimCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Fetch the latest indicator for every (station, measurement) pair.

    Data shape::

        {
            "stations": { locationId: { meas_key: {...indicator...} | None } },
            "pollen":   { pollen_key: {...indicator...} | None },
            "aqi":      { station_key: { meas_key: {...} | None } },
            "dwd":      { meas_key: {...} | None },
        }

    Sub-trees are only populated when their corresponding toggle is on.
    """

    def __init__(
        self,
        hass: HomeAssistant,
        client: SmartMannheimClient,
        stations: list[dict[str, Any]],
        *,
        include_pollen: bool = True,
        include_aqi: bool = True,
        include_dwd: bool = True,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=DEFAULT_SCAN_INTERVAL,
        )
        self.client = client
        self.stations = stations
        self.include_pollen = include_pollen
        self.include_aqi = include_aqi
        self.include_dwd = include_dwd

    async def _async_update_data(self) -> dict[str, Any]:
        sem = asyncio.Semaphore(_MAX_CONCURRENCY)

        async def guarded(coro):
            async with sem:
                return await coro

        async def fetch_station(
            station: dict[str, Any], meas: dict[str, Any]
        ) -> tuple[str, str, dict[str, Any] | None]:
            try:
                data = await self.client.get_indicator(station["locationId"], meas)
            except SmartMannheimError as err:
                _LOGGER.debug(
                    "Fetch failed %s/%s: %s",
                    station.get("name"), meas["key"], err,
                )
                data = None
            return station["locationId"], meas["key"], data

        async def fetch_pollen(
            series: dict[str, Any],
        ) -> tuple[str, dict[str, Any] | None]:
            try:
                data = await self.client.get_pollen_indicator(series)
            except SmartMannheimError as err:
                _LOGGER.debug("Pollen fetch failed %s: %s", series["key"], err)
                data = None
            return series["key"], data

        async def fetch_aqi(
            station: dict[str, Any], meas: dict[str, Any]
        ) -> tuple[str, str, dict[str, Any] | None]:
            try:
                data = await self.client.get_aqi_indicator(station["entity_id"], meas)
            except SmartMannheimError as err:
                _LOGGER.debug(
                    "AQI fetch failed %s/%s: %s",
                    station["key"], meas["key"], err,
                )
                data = None
            return station["key"], meas["key"], data

        async def fetch_dwd(
            series: dict[str, Any],
        ) -> tuple[str, dict[str, Any] | None]:
            try:
                data = await self.client.get_dwd_indicator(series)
            except SmartMannheimError as err:
                _LOGGER.debug("DWD fetch failed %s: %s", series["key"], err)
                data = None
            return series["key"], data

        station_tasks = [
            guarded(fetch_station(s, m))
            for s in self.stations
            for m in MEASUREMENTS
        ]
        pollen_tasks = (
            [guarded(fetch_pollen(s)) for s in POLLEN_SERIES]
            if self.include_pollen else []
        )
        aqi_tasks = (
            [
                guarded(fetch_aqi(st, m))
                for st in AQI_STATIONS
                for m in st["measurements"]
            ]
            if self.include_aqi else []
        )
        dwd_tasks = (
            [guarded(fetch_dwd(s)) for s in DWD_SERIES]
            if self.include_dwd else []
        )

        try:
            station_results, pollen_results, aqi_results, dwd_results = await asyncio.gather(
                asyncio.gather(*station_tasks),
                asyncio.gather(*pollen_tasks),
                asyncio.gather(*aqi_tasks),
                asyncio.gather(*dwd_tasks),
            )
        except SmartMannheimError as err:
            raise UpdateFailed(str(err)) from err

        stations_out: dict[str, dict[str, Any]] = {
            s["locationId"]: {} for s in self.stations
        }
        for location_id, key, data in station_results:
            stations_out[location_id][key] = data

        pollen_out: dict[str, Any] = {key: data for key, data in pollen_results}

        aqi_out: dict[str, dict[str, Any]] = {
            s["key"]: {} for s in AQI_STATIONS
        }
        for station_key, meas_key, data in aqi_results:
            aqi_out[station_key][meas_key] = data

        dwd_out: dict[str, Any] = {key: data for key, data in dwd_results}

        return {
            "stations": stations_out,
            "pollen": pollen_out,
            "aqi": aqi_out,
            "dwd": dwd_out,
        }
