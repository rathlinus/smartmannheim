"""Coordinators: official climate sensors + dashboard extras."""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import SensorNotFoundError, SmartMannheimClient, SmartMannheimError
from .const import (
    AQI_STATIONS,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    DWD_SERIES,
    POLLEN_SERIES,
)
from .official import climate_interval_minutes, latest_values

_LOGGER = logging.getLogger(__name__)

# Be a good citizen towards the shared backends: never fan out unboundedly.
_MAX_CONCURRENCY = 4


class ClimateCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Latest values of every selected official climate sensor.

    Data shape: ``{sensorId: {param: {"value", "timestamp"}} | None}``.

    Every update costs one request per sensor, so the interval stretches
    with the number of sensors to stay within 30 requests/hour.
    """

    def __init__(
        self,
        hass: HomeAssistant,
        client: SmartMannheimClient,
        sensors: list[dict[str, Any]],
    ) -> None:
        self.interval_minutes = climate_interval_minutes(len(sensors))
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_climate",
            update_interval=timedelta(minutes=self.interval_minutes),
        )
        self.client = client
        self.sensors = sensors
        self._failing: set[str] = set()

    @property
    def max_age(self) -> timedelta:
        """How long a kept value may be shown before it counts as stale."""
        return timedelta(minutes=max(60, 3 * self.interval_minutes))

    async def _async_update_data(self) -> dict[str, Any]:
        sem = asyncio.Semaphore(_MAX_CONCURRENCY)
        previous: dict[str, Any] = self.data or {}

        async def fetch(sensor: dict[str, Any]) -> tuple[str, Any]:
            sensor_id = sensor["sensorId"]
            async with sem:
                try:
                    rows = await self.client.get_measurements(sensor_id)
                except SensorNotFoundError:
                    self._log_failure(sensor, "no longer exists in the official API (HTTP 404)")
                    return sensor_id, None
                except SmartMannheimError as err:
                    return sensor_id, self._keep(sensor, previous, str(err))
            values = latest_values(rows)
            if not values:
                return sensor_id, self._keep(
                    sensor, previous, "no measurements in the last 60 minutes"
                )
            self._log_recovery(sensor)
            return sensor_id, values

        results = dict(await asyncio.gather(*(fetch(s) for s in self.sensors)))
        if self.sensors and not any(results.values()) and self._failing:
            # Nothing fetched and nothing to keep (e.g. the first refresh).
            raise UpdateFailed("No climate sensor could be fetched")
        return results

    def _keep(
        self, sensor: dict[str, Any], previous: dict[str, Any], reason: str
    ) -> dict[str, Any] | None:
        """Reuse the last good values of a sensor after a failed fetch.

        One failed request would otherwise blank the sensor for a whole
        (rate-limited) interval. Entities stop showing kept values once
        they exceed `max_age` (see KlimaSensor.available).
        """
        kept = previous.get(sensor["sensorId"])
        self._log_failure(
            sensor, f"{reason}; " + ("keeping last values" if kept else "no earlier values")
        )
        return kept

    def _log_failure(self, sensor: dict[str, Any], reason: str) -> None:
        # One warning per outage, not one per update.
        if sensor["sensorId"] not in self._failing:
            self._failing.add(sensor["sensorId"])
            _LOGGER.warning(
                "Climate sensor %s (%s): %s", sensor.get("name"), sensor["sensorId"], reason
            )

    def _log_recovery(self, sensor: dict[str, Any]) -> None:
        if sensor["sensorId"] in self._failing:
            self._failing.discard(sensor["sensorId"])
            _LOGGER.info("Climate sensor %s (%s) is delivering data again",
                         sensor.get("name"), sensor["sensorId"])


class ExtrasCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Pollen / AQI / DWD-station indicators from the dashboard backends.

    Data shape::

        {
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
        *,
        include_pollen: bool = True,
        include_aqi: bool = True,
        include_dwd: bool = True,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_extras",
            update_interval=DEFAULT_SCAN_INTERVAL,
        )
        self.client = client
        self.include_pollen = include_pollen
        self.include_aqi = include_aqi
        self.include_dwd = include_dwd

    async def _async_update_data(self) -> dict[str, Any]:
        sem = asyncio.Semaphore(_MAX_CONCURRENCY)

        async def guarded(coro):
            async with sem:
                return await coro

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
            pollen_results, aqi_results, dwd_results = await asyncio.gather(
                asyncio.gather(*pollen_tasks),
                asyncio.gather(*aqi_tasks),
                asyncio.gather(*dwd_tasks),
            )
        except SmartMannheimError as err:
            raise UpdateFailed(str(err)) from err

        pollen_out: dict[str, Any] = {key: data for key, data in pollen_results}

        aqi_out: dict[str, dict[str, Any]] = {
            s["key"]: {} for s in AQI_STATIONS
        }
        for station_key, meas_key, data in aqi_results:
            aqi_out[station_key][meas_key] = data

        dwd_out: dict[str, Any] = {key: data for key, data in dwd_results}

        return {
            "pollen": pollen_out,
            "aqi": aqi_out,
            "dwd": dwd_out,
        }


@dataclass
class RuntimeData:
    """Everything the platforms need for one config entry."""

    climate: ClimateCoordinator | None
    extras: ExtrasCoordinator | None
    sensors: list[dict[str, Any]] = field(default_factory=list)
    # location key → shared device for all selected sensors at that spot
    devices: dict[str, DeviceInfo] = field(default_factory=dict)
