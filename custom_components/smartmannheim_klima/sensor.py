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
    DEGREE,
    PERCENTAGE,
    UnitOfIrradiance,
    UnitOfLength,
    UnitOfPressure,
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
    DOMAIN,
    DWD_DEVICE_ID,
    POLLEN_DEVICE_ID,
    POLLEN_SERIES,
)
from .coordinator import ClimateCoordinator, ExtrasCoordinator, RuntimeData
from .official import location_key

# µg/m³ has no first-class HA constant; use the literal the AQI cards expect.
UG_PER_M3 = "µg/m³"


# --- Official climate sensors -------------------------------------------
# Keyed by the official API parameter name. The API declares no units;
# they were checked against live data on 2026-09-23. Wind speed matches
# the old dashboard values 1:1 (m/s: ~1 m/s at city sensors while the
# DWD station read 3.2 m/s; km/h would mean near-total calm).
# `minIrradiation` (bogus values around -1900) and `precipitationTick`
# (undocumented, always 0) are deliberately not exposed.
def _temperature(key: str, translation_key: str, enabled: bool = True) -> SensorEntityDescription:
    return SensorEntityDescription(
        key=key,
        translation_key=translation_key,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        suggested_display_precision=1,
        entity_registry_enabled_default=enabled,
    )


def _wind_speed(key: str, translation_key: str, enabled: bool = True) -> SensorEntityDescription:
    return SensorEntityDescription(
        key=key,
        translation_key=translation_key,
        device_class=SensorDeviceClass.WIND_SPEED,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfSpeed.METERS_PER_SECOND,
        suggested_display_precision=1,
        entity_registry_enabled_default=enabled,
    )


def _irradiance(key: str, translation_key: str, enabled: bool = False) -> SensorEntityDescription:
    return SensorEntityDescription(
        key=key,
        translation_key=translation_key,
        device_class=SensorDeviceClass.IRRADIANCE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfIrradiance.WATTS_PER_SQUARE_METER,
        suggested_display_precision=0,
        entity_registry_enabled_default=enabled,
    )


def _direction(key: str, translation_key: str, enabled: bool = True) -> SensorEntityDescription:
    # No device/state class: WIND_DIRECTION needs a newer HA than we
    # support, and long-term mean statistics of angles are meaningless.
    return SensorEntityDescription(
        key=key,
        translation_key=translation_key,
        icon="mdi:compass-outline",
        native_unit_of_measurement=DEGREE,
        suggested_display_precision=0,
        entity_registry_enabled_default=enabled,
    )


CLIMATE_SENSOR_TYPES: dict[str, SensorEntityDescription] = {
    d.key: d
    for d in (
        _temperature("temperature", "temperature"),
        SensorEntityDescription(
            key="airHumidity",
            translation_key="humidity",
            device_class=SensorDeviceClass.HUMIDITY,
            state_class=SensorStateClass.MEASUREMENT,
            native_unit_of_measurement=PERCENTAGE,
            suggested_display_precision=0,
        ),
        SensorEntityDescription(
            key="atmosphericPressure",
            translation_key="pressure",
            device_class=SensorDeviceClass.ATMOSPHERIC_PRESSURE,
            state_class=SensorStateClass.MEASUREMENT,
            native_unit_of_measurement=UnitOfPressure.HPA,
            suggested_display_precision=1,
        ),
        _temperature("dewPoint", "dew_point", enabled=False),
        _temperature("minTemperature", "min_temperature", enabled=False),
        _temperature("maxTemperature", "max_temperature", enabled=False),
        _irradiance("irradiation", "irradiation"),
        _irradiance("maxIrradiation", "max_irradiation"),
        _wind_speed("averageWindSpeed", "wind_speed"),
        _wind_speed("minWindSpeed", "min_wind_speed", enabled=False),
        _wind_speed("windGust1s", "wind_gust_1s", enabled=False),
        _wind_speed("windGust3s", "wind_gust_3s", enabled=False),
        _direction("averageWindDirection", "wind_direction"),
        _direction("windGustDirection", "wind_gust_direction", enabled=False),
    )
}


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


def _lqi_label(value: float | None) -> str | None:
    """German label for an LQI value; bands clamp to 1..5."""
    if value is None:
        return None
    return LQI_LEVEL_LABELS.get(max(1, min(5, int(value))))


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



async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    runtime: RuntimeData = hass.data[DOMAIN][entry.entry_id]
    entities: list[SensorEntity] = []

    if runtime.climate is not None:
        for sensor in runtime.sensors:
            meta = metadata.lookup(sensor["name"])
            device_info = runtime.devices[location_key(sensor)]
            for param in sensor["params"]:
                description = CLIMATE_SENSOR_TYPES.get(param)
                if description is not None:
                    entities.append(
                        KlimaSensor(runtime.climate, sensor, description, device_info, meta)
                    )

    extras = runtime.extras
    if extras is not None:
        if extras.include_pollen:
            for description in POLLEN_SENSOR_TYPES:
                entities.append(PollenSensor(extras, description))
        if extras.include_aqi:
            for station in AQI_STATIONS:
                for description in AQI_SENSOR_TYPES:
                    entities.append(AqiSensor(extras, station, description))
        if extras.include_dwd:
            for description in DWD_SENSOR_TYPES:
                entities.append(DwdSensor(extras, description))

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


def _timestamp_only(reading: dict[str, Any] | None) -> dict[str, Any]:
    if not reading or not reading.get("timestamp"):
        return {}
    parsed = dt_util.parse_datetime(reading["timestamp"])
    return {"measured_at": parsed.isoformat()} if parsed else {}


class KlimaSensor(CoordinatorEntity[ClimateCoordinator], SensorEntity):
    """One parameter of one official climate sensor."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: ClimateCoordinator,
        sensor: dict[str, Any],
        description: SensorEntityDescription,
        device_info: DeviceInfo,
        meta: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._sensor_id: str = sensor["sensorId"]
        self._sensor_name: str = sensor["name"]
        self._meta = meta
        coords = sensor.get("coordinates") or []
        # The API uses GeoJSON order [lon, lat].
        self._position = (float(coords[1]), float(coords[0])) if len(coords) == 2 else None
        self._attr_unique_id = f"{DOMAIN}_{self._sensor_id}_{description.key}"
        self._attr_device_info = device_info

    def _reading(self) -> dict[str, Any] | None:
        values = (self.coordinator.data or {}).get(self._sensor_id) or {}
        return values.get(self.entity_description.key)

    @property
    def available(self) -> bool:
        reading = self._reading()
        if not super().available or reading is None:
            return False
        # Values kept across failed fetches expire instead of freezing.
        measured = dt_util.parse_datetime(reading.get("timestamp") or "")
        return measured is None or dt_util.utcnow() - measured <= self.coordinator.max_age

    @property
    def native_value(self) -> float | None:
        reading = self._reading()
        return _float_or_none(reading["value"]) if reading else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        attrs: dict[str, Any] = {
            "sensor_id": self._sensor_id,
            "sensor_name": self._sensor_name,
            # Shown so the stretched poll interval (API rate limit) is visible.
            "update_interval_min": self.coordinator.interval_minutes,
        }
        if self._position:
            attrs["latitude"], attrs["longitude"] = self._position
        attrs.update(_timestamp_only(self._reading()))
        # Surface catalog-level context per sensor: measurement height &
        # the static station attrs (altitude, LCZ, commissioning date…).
        info = metadata.sensor_info(self._meta, self.entity_description.key)
        if info:
            if "height_m" in info:
                attrs["measurement_height_m"] = info["height_m"]
            if "type_accuracy" in info:
                attrs["sensor_type_accuracy"] = info["type_accuracy"]
        attrs.update(metadata.device_attrs(self._meta))
        return attrs


class PollenSensor(CoordinatorEntity[ExtrasCoordinator], SensorEntity):
    """One pollen species (DWD Pollenflug Mannheim)."""

    _attr_has_entity_name = True
    entity_description: PollenSensorDescription

    def __init__(
        self,
        coordinator: ExtrasCoordinator,
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


class AqiSensor(CoordinatorEntity[ExtrasCoordinator], SensorEntity):
    """One UBA air-quality metric at one station."""

    _attr_has_entity_name = True
    entity_description: AqiSensorDescription

    def __init__(
        self,
        coordinator: ExtrasCoordinator,
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
            label = _lqi_label(self.native_value)
            if label:
                attrs["level"] = label
        return attrs


class DwdSensor(CoordinatorEntity[ExtrasCoordinator], SensorEntity):
    """One DWD-station metric (Mannheim)."""

    _attr_has_entity_name = True
    entity_description: DwdSensorDescription

    def __init__(
        self,
        coordinator: ExtrasCoordinator,
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
