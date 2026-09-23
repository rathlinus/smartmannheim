"""Device-tracker platform: one stationary GPS pin per station location."""
from __future__ import annotations

from typing import Any

from homeassistant.components.device_tracker import SourceType
from homeassistant.components.device_tracker.config_entry import TrackerEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import metadata
from .const import DOMAIN
from .coordinator import RuntimeData
from .official import location_key


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    runtime: RuntimeData = hass.data[DOMAIN][entry.entry_id]
    trackers: dict[str, KlimaStationTracker] = {}
    for sensor in runtime.sensors:
        key = location_key(sensor)
        coords = sensor.get("coordinates") or []
        if len(coords) == 2 and key not in trackers:
            trackers[key] = KlimaStationTracker(
                key, coords, runtime.devices[key], metadata.lookup(sensor["name"])
            )
    async_add_entities(trackers.values())


class KlimaStationTracker(TrackerEntity):
    """Static GPS pin placed at the station's coordinates.

    Coordinates are static, so the tracker doesn't follow the (rate-limited)
    climate coordinator and is always available.
    """

    _attr_has_entity_name = True
    _attr_name = None  # entity carries the device name directly
    _attr_icon = "mdi:weather-partly-cloudy"
    _attr_should_poll = False

    def __init__(
        self,
        key: str,
        coordinates: list[float],
        device_info: DeviceInfo,
        meta: dict[str, Any] | None = None,
    ) -> None:
        self._key = key
        self._meta = meta
        # The API uses GeoJSON order [lon, lat].
        lon, lat = coordinates
        self._lat: float = float(lat)
        self._lon: float = float(lon)
        self._attr_unique_id = f"{DOMAIN}_{key}_location"
        self._attr_device_info = device_info

    @property
    def source_type(self) -> SourceType:
        return SourceType.GPS

    @property
    def latitude(self) -> float | None:
        return self._lat

    @property
    def longitude(self) -> float | None:
        return self._lon

    @property
    def location_accuracy(self) -> int:
        return 0

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        attrs: dict[str, Any] = {"location_key": self._key}
        attrs.update(metadata.device_attrs(self._meta))
        return attrs
