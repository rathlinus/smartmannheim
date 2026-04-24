"""Sensor platform — 3 sensors per selected station."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    PERCENTAGE,
    UnitOfSpeed,
    UnitOfTemperature,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .const import (
    CONF_STATIONS,
    DOMAIN,
    MEAS_HUMIDITY,
    MEAS_TEMPERATURE,
    MEAS_WIND,
)
from .coordinator import SmartMannheimCoordinator


@dataclass(frozen=True, kw_only=True)
class KlimaSensorDescription(SensorEntityDescription):
    measurement_key: str


SENSOR_TYPES: tuple[KlimaSensorDescription, ...] = (
    KlimaSensorDescription(
        key=MEAS_TEMPERATURE,
        measurement_key=MEAS_TEMPERATURE,
        translation_key=MEAS_TEMPERATURE,
        name="Temperatur",
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        suggested_display_precision=1,
    ),
    KlimaSensorDescription(
        key=MEAS_HUMIDITY,
        measurement_key=MEAS_HUMIDITY,
        translation_key=MEAS_HUMIDITY,
        name="Luftfeuchtigkeit",
        device_class=SensorDeviceClass.HUMIDITY,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=PERCENTAGE,
        suggested_display_precision=0,
    ),
    # The backend doesn't declare a unit; m/s is the common IoT default for
    # wind speed. If your values look off by ~3.6x, it's actually km/h.
    KlimaSensorDescription(
        key=MEAS_WIND,
        measurement_key=MEAS_WIND,
        translation_key=MEAS_WIND,
        name="Windgeschwindigkeit",
        device_class=SensorDeviceClass.WIND_SPEED,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfSpeed.METERS_PER_SECOND,
        suggested_display_precision=1,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: SmartMannheimCoordinator = hass.data[DOMAIN][entry.entry_id]
    stations = entry.options.get(CONF_STATIONS) or entry.data.get(CONF_STATIONS, [])

    entities: list[KlimaSensor] = []
    for station in stations:
        for description in SENSOR_TYPES:
            entities.append(KlimaSensor(coordinator, station, description))
    async_add_entities(entities)


class KlimaSensor(CoordinatorEntity[SmartMannheimCoordinator], SensorEntity):
    """One measurement for one station."""

    _attr_has_entity_name = True
    entity_description: KlimaSensorDescription

    def __init__(
        self,
        coordinator: SmartMannheimCoordinator,
        station: dict[str, Any],
        description: KlimaSensorDescription,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._location_id: str = station["locationId"]
        self._station_name: str = station.get("name") or station["locationId"]
        coords = station.get("coordinates") or []
        if len(coords) == 2:
            # Backend stores GeoJSON order [lon, lat].
            self._longitude: float | None = float(coords[0])
            self._latitude: float | None = float(coords[1])
        else:
            self._longitude = self._latitude = None
        self._attr_unique_id = f"{DOMAIN}_{self._location_id}_{description.key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, self._location_id)},
            name=self._station_name,
            manufacturer="Stadt Mannheim",
            model="Klimamessstation",
            configuration_url="https://smartmannheim.de/datenartikel/klimamessnetz-mannheim/",
        )

    def _reading(self) -> dict[str, Any] | None:
        data = self.coordinator.data or {}
        return (data.get(self._location_id) or {}).get(
            self.entity_description.measurement_key
        )

    @property
    def available(self) -> bool:
        if not super().available:
            return False
        reading = self._reading()
        return reading is not None and reading.get("indicator") is not None

    @property
    def native_value(self) -> float | None:
        reading = self._reading()
        if reading is None:
            return None
        return reading.get("indicator")

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        attrs: dict[str, Any] = {"location_id": self._location_id}
        if self._latitude is not None and self._longitude is not None:
            # Exposing these makes the sensor usable as a pin on a Map card.
            attrs["latitude"] = self._latitude
            attrs["longitude"] = self._longitude
        reading = self._reading()
        if not reading:
            return attrs
        ts = reading.get("timestamp")
        if ts:
            parsed = dt_util.parse_datetime(ts)
            if parsed:
                attrs["measured_at"] = parsed.isoformat()
        warning = reading.get("warning")
        if warning:
            attrs["warning"] = warning
        return attrs
