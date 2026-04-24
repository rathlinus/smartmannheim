"""Device-tracker platform: one stationary GPS pin per station."""
from __future__ import annotations

from typing import Any

from homeassistant.components.device_tracker import SourceType
from homeassistant.components.device_tracker.config_entry import TrackerEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_STATIONS, DOMAIN
from .coordinator import SmartMannheimCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: SmartMannheimCoordinator = hass.data[DOMAIN][entry.entry_id]
    stations = entry.options.get(CONF_STATIONS) or entry.data.get(CONF_STATIONS, [])

    trackers: list[KlimaStationTracker] = []
    for station in stations:
        coords = station.get("coordinates") or []
        if len(coords) == 2:
            trackers.append(KlimaStationTracker(coordinator, station))
    async_add_entities(trackers)


class KlimaStationTracker(
    CoordinatorEntity[SmartMannheimCoordinator], TrackerEntity
):
    """Static GPS pin placed at the station's coordinates."""

    _attr_has_entity_name = True
    _attr_name = None  # entity carries the device name directly
    _attr_icon = "mdi:weather-partly-cloudy"

    def __init__(
        self,
        coordinator: SmartMannheimCoordinator,
        station: dict[str, Any],
    ) -> None:
        super().__init__(coordinator)
        self._location_id: str = station["locationId"]
        station_name = station.get("name") or self._location_id
        # Backend stores GeoJSON order [lon, lat].
        lon, lat = station["coordinates"]
        self._lat: float = float(lat)
        self._lon: float = float(lon)
        self._attr_unique_id = f"{DOMAIN}_{self._location_id}_location"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, self._location_id)},
            name=station_name,
            manufacturer="Stadt Mannheim",
            model="Klimamessstation",
            configuration_url="https://smartmannheim.de/datenartikel/klimamessnetz-mannheim/",
        )

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
    def available(self) -> bool:
        # Coordinates are static; tracker is always available independent
        # of the live-data coordinator status.
        return True

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {"location_id": self._location_id}
