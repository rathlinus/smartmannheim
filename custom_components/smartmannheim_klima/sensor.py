"""Sensor platform — climate stations + pollen + AQI + DWD station."""
from __future__ import annotations

from dataclasses import dataclass
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
    UnitOfLength,
    UnitOfSpeed,
    UnitOfTemperature,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from . import metadata
from .const import (
    AQI_STATIONS,
    CONF_INCLUDE_AQI,
    CONF_INCLUDE_DWD,
    CONF_INCLUDE_POLLEN,
    CONF_STATIONS,
    DOMAIN,
    DWD_DEVICE_ID,
    DWD_SERIES,
    MEAS_HUMIDITY,
    MEAS_TEMPERATURE,
    MEAS_WIND,
    POLLEN_DEVICE_ID,
    POLLEN_SERIES,
)
from .coordinator import SmartMannheimCoordinator

# µg/m³ has no first-class HA constant; use the literal the AQI cards expect.
UG_PER_M3 = "µg/m³"


@dataclass(frozen=True, kw_only=True)
class KlimaSensorDescription(SensorEntityDescription):
    measurement_key: str


STATION_SENSOR_TYPES: tuple[KlimaSensorDescription, ...] = (
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


# --- Pollen ------------------------------------------------------------
# DWD Pollenflug index uses discrete steps 0..3 plus the interpolated
# half-steps "0-1", "1-2", "2-3" — exposed by the API as strings.
# We surface the midpoint as the numeric state and the raw string as
# the `level_raw` attribute, with a German label in `level`.
POLLEN_LEVEL_LABELS: dict[float, str] = {
    0.0: "keine",
    0.5: "keine bis gering",
    1.0: "gering",
    1.5: "gering bis mittel",
    2.0: "mittel",
    2.5: "mittel bis hoch",
    3.0: "hoch",
}


def _parse_pollen_indicator(raw: Any) -> tuple[float | None, str | None]:
    """Return (numeric_midpoint, raw_string) for a DWD pollen indicator."""
    if raw is None:
        return None, None
    text = str(raw).strip()
    if not text:
        return None, None
    if "-" in text:
        try:
            lo_s, hi_s = text.split("-", 1)
            return (float(lo_s) + float(hi_s)) / 2.0, text
        except ValueError:
            return None, text
    try:
        return float(text), text
    except ValueError:
        return None, text


@dataclass(frozen=True, kw_only=True)
class PollenSensorDescription(SensorEntityDescription):
    series_key: str


POLLEN_SENSOR_TYPES: tuple[PollenSensorDescription, ...] = tuple(
    PollenSensorDescription(
        key=f"pollen_{s['key']}",
        series_key=s["key"],
        translation_key=f"pollen_{s['key']}",
        name=s["display_name"].split(", ", 1)[-1],
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:flower-pollen",
        suggested_display_precision=0,
    )
    for s in POLLEN_SERIES
)


# --- AQI (UBA Luftqualität) -------------------------------------------
@dataclass(frozen=True, kw_only=True)
class AqiSensorDescription(SensorEntityDescription):
    measurement_key: str


AQI_SENSOR_TYPES: tuple[AqiSensorDescription, ...] = (
    AqiSensorDescription(
        key="lqi",
        measurement_key="lqi",
        translation_key="aqi_lqi",
        name="Luftqualitätsindex",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:weather-hazy",
        suggested_display_precision=1,
    ),
    AqiSensorDescription(
        key="pm10",
        measurement_key="pm10",
        translation_key="aqi_pm10",
        name="Feinstaub PM₁₀",
        device_class=SensorDeviceClass.PM10,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UG_PER_M3,
        suggested_display_precision=0,
    ),
    AqiSensorDescription(
        key="pm25",
        measurement_key="pm25",
        translation_key="aqi_pm25",
        name="Feinstaub PM₂,₅",
        device_class=SensorDeviceClass.PM25,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UG_PER_M3,
        suggested_display_precision=0,
    ),
    AqiSensorDescription(
        key="no2",
        measurement_key="no2",
        translation_key="aqi_no2",
        name="Stickstoffdioxid NO₂",
        device_class=SensorDeviceClass.NITROGEN_DIOXIDE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UG_PER_M3,
        suggested_display_precision=0,
    ),
)

# Maps LQI integer band → German label, mirroring the dashboard's color scheme.
LQI_LEVEL_LABELS = {
    1: "sehr gut",
    2: "gut",
    3: "mäßig",
    4: "schlecht",
    5: "sehr schlecht",
}


# --- DWD (Klimadaten DWD-Station Mannheim) ----------------------------
@dataclass(frozen=True, kw_only=True)
class DwdSensorDescription(SensorEntityDescription):
    series_key: str


DWD_SENSOR_TYPES: tuple[DwdSensorDescription, ...] = (
    DwdSensorDescription(
        key="temperature",
        series_key="temperature",
        translation_key="dwd_temperature",
        name="Temperatur",
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        suggested_display_precision=1,
    ),
    DwdSensorDescription(
        key="humidity",
        series_key="humidity",
        translation_key="dwd_humidity",
        name="Luftfeuchtigkeit",
        device_class=SensorDeviceClass.HUMIDITY,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=PERCENTAGE,
        suggested_display_precision=0,
    ),
    DwdSensorDescription(
        key="wind_speed",
        series_key="wind_speed",
        translation_key="dwd_wind_speed",
        name="Windgeschwindigkeit",
        device_class=SensorDeviceClass.WIND_SPEED,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfSpeed.METERS_PER_SECOND,
        suggested_display_precision=1,
    ),
    DwdSensorDescription(
        key="precipitation",
        series_key="precipitation",
        translation_key="dwd_precipitation",
        name="Niederschlag",
        device_class=SensorDeviceClass.PRECIPITATION,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfLength.MILLIMETERS,
        suggested_display_precision=1,
    ),
)


def _option_flag(entry: ConfigEntry, key: str, default: bool = True) -> bool:
    val = entry.options.get(key)
    if val is None:
        val = entry.data.get(key, default)
    return bool(val)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: SmartMannheimCoordinator = hass.data[DOMAIN][entry.entry_id]
    stations = entry.options.get(CONF_STATIONS) or entry.data.get(CONF_STATIONS, [])

    entities: list[SensorEntity] = []
    for station in stations:
        meta = metadata.lookup(station.get("name"))
        for description in STATION_SENSOR_TYPES:
            # Skip sensors the catalog says aren't installed at this station.
            # When metadata is unknown, helper returns True (permissive).
            if not metadata.has_sensor(meta, description.measurement_key):
                continue
            entities.append(KlimaSensor(coordinator, station, description, meta))

    if _option_flag(entry, CONF_INCLUDE_POLLEN):
        for description in POLLEN_SENSOR_TYPES:
            entities.append(PollenSensor(coordinator, description))

    if _option_flag(entry, CONF_INCLUDE_AQI):
        for station in AQI_STATIONS:
            for description in AQI_SENSOR_TYPES:
                entities.append(AqiSensor(coordinator, station, description))

    if _option_flag(entry, CONF_INCLUDE_DWD):
        for description in DWD_SENSOR_TYPES:
            entities.append(DwdSensor(coordinator, description))

    async_add_entities(entities)


def _float_or_none(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _timestamp_attr(reading: dict[str, Any] | None) -> dict[str, Any]:
    if not reading:
        return {}
    out: dict[str, Any] = {}
    ts = reading.get("timestamp")
    if ts:
        parsed = dt_util.parse_datetime(ts)
        if parsed:
            out["measured_at"] = parsed.isoformat()
    warning = reading.get("warning")
    if warning:
        out["warning"] = warning
    return out


class KlimaSensor(CoordinatorEntity[SmartMannheimCoordinator], SensorEntity):
    """One measurement for one climate station."""

    _attr_has_entity_name = True
    entity_description: KlimaSensorDescription

    def __init__(
        self,
        coordinator: SmartMannheimCoordinator,
        station: dict[str, Any],
        description: KlimaSensorDescription,
        meta: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._location_id: str = station["locationId"]
        self._station_name: str = station.get("name") or station["locationId"]
        self._meta = meta
        coords = station.get("coordinates") or []
        if len(coords) == 2:
            # Backend stores GeoJSON order [lon, lat].
            self._longitude: float | None = float(coords[0])
            self._latitude: float | None = float(coords[1])
        else:
            self._longitude = self._latitude = None
        self._attr_unique_id = f"{DOMAIN}_{self._location_id}_{description.key}"
        # Use the catalog's commissioning date as `hw_version` so it shows
        # up in the HA device card without needing a custom field.
        device_info = DeviceInfo(
            identifiers={(DOMAIN, self._location_id)},
            name=self._station_name,
            manufacturer="Stadt Mannheim",
            model="Klimamessstation",
            configuration_url="https://smartmannheim.de/datenartikel/klimamessnetz-mannheim/",
        )
        if meta:
            commissioned = meta.get("commissioned_at")
            if commissioned:
                device_info["hw_version"] = commissioned
            altitude = meta.get("altitude_m")
            if altitude is not None:
                device_info["model"] = f"Klimamessstation (Höhe {altitude} m NN)"
        self._attr_device_info = device_info

    def _reading(self) -> dict[str, Any] | None:
        data = self.coordinator.data or {}
        stations = data.get("stations") or {}
        return (stations.get(self._location_id) or {}).get(
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
        return _float_or_none(reading.get("indicator"))

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        attrs: dict[str, Any] = {"location_id": self._location_id}
        if self._latitude is not None and self._longitude is not None:
            attrs["latitude"] = self._latitude
            attrs["longitude"] = self._longitude
        attrs.update(_timestamp_attr(self._reading()))
        # Surface catalog-level context per sensor: measurement height &
        # the static station attrs (altitude, LCZ, commissioning date…).
        info = metadata.sensor_info(self._meta, self.entity_description.measurement_key)
        if info:
            if "height_m" in info:
                attrs["measurement_height_m"] = info["height_m"]
            if "type_accuracy" in info:
                attrs["sensor_type_accuracy"] = info["type_accuracy"]
        attrs.update(metadata.device_attrs(self._meta))
        return attrs


class PollenSensor(CoordinatorEntity[SmartMannheimCoordinator], SensorEntity):
    """One pollen species (DWD Pollenflug Mannheim)."""

    _attr_has_entity_name = True
    entity_description: PollenSensorDescription

    def __init__(
        self,
        coordinator: SmartMannheimCoordinator,
        description: PollenSensorDescription,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{DOMAIN}_pollen_{description.series_key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, POLLEN_DEVICE_ID)},
            name="Pollenflug Mannheim",
            manufacturer="Deutscher Wetterdienst",
            model="Pollenflug Gefahrenindex",
            configuration_url="https://dashboard.mvvsmartcities.com/#/26784a43-7be8-446c-a4a5-b960025f5939",
        )

    def _reading(self) -> dict[str, Any] | None:
        data = self.coordinator.data or {}
        return (data.get("pollen") or {}).get(self.entity_description.series_key)

    @property
    def available(self) -> bool:
        if not super().available:
            return False
        reading = self._reading()
        if reading is None:
            return False
        value, _ = _parse_pollen_indicator(reading.get("indicator"))
        return value is not None

    @property
    def native_value(self) -> float | None:
        reading = self._reading()
        if reading is None:
            return None
        value, _ = _parse_pollen_indicator(reading.get("indicator"))
        return value

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        reading = self._reading()
        attrs = _timestamp_attr(reading)
        if reading is not None:
            value, raw = _parse_pollen_indicator(reading.get("indicator"))
            if raw is not None:
                attrs["level_raw"] = raw
            if value is not None:
                label = POLLEN_LEVEL_LABELS.get(value)
                if label:
                    attrs["level"] = label
        return attrs


class AqiSensor(CoordinatorEntity[SmartMannheimCoordinator], SensorEntity):
    """One UBA air-quality metric at one station."""

    _attr_has_entity_name = True
    entity_description: AqiSensorDescription

    def __init__(
        self,
        coordinator: SmartMannheimCoordinator,
        station: dict[str, Any],
        description: AqiSensorDescription,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._station_key: str = station["key"]
        self._station_name: str = station["name"]
        self._attr_unique_id = (
            f"{DOMAIN}_aqi_{self._station_key}_{description.measurement_key}"
        )
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"aqi_{self._station_key}")},
            name=f"Luftqualität {self._station_name}",
            manufacturer="Umweltbundesamt",
            model="Luftqualitätsmessstation",
            configuration_url="https://apps.mvvsmartcities.com/#/luftqualitaetsindex_mannheim",
        )

    def _reading(self) -> dict[str, Any] | None:
        data = self.coordinator.data or {}
        return ((data.get("aqi") or {}).get(self._station_key) or {}).get(
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
        return _float_or_none(reading.get("indicator"))

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        attrs = _timestamp_attr(self._reading())
        if self.entity_description.measurement_key == "lqi":
            value = self.native_value
            if value is not None:
                # LQI bands are 1.0–4.99; clamp to int index 1..5.
                band = max(1, min(5, int(value))) if value >= 1 else 1
                label = LQI_LEVEL_LABELS.get(band)
                if label:
                    attrs["level"] = label
        return attrs


class DwdSensor(CoordinatorEntity[SmartMannheimCoordinator], SensorEntity):
    """One DWD-station metric (Mannheim)."""

    _attr_has_entity_name = True
    entity_description: DwdSensorDescription

    def __init__(
        self,
        coordinator: SmartMannheimCoordinator,
        description: DwdSensorDescription,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{DOMAIN}_dwd_{description.series_key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, DWD_DEVICE_ID)},
            name="DWD-Station Mannheim",
            manufacturer="Deutscher Wetterdienst",
            model="Klimastation 0301-001-11",
            configuration_url="https://dashboard.mvvsmartcities.com/#/fcea867d-8c40-4507-bb88-43ced0dbcbf5",
        )

    def _reading(self) -> dict[str, Any] | None:
        data = self.coordinator.data or {}
        return (data.get("dwd") or {}).get(self.entity_description.series_key)

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
        return _float_or_none(reading.get("indicator"))

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return _timestamp_attr(self._reading())
