"""Setup, entities, device grouping, cleanup and the rate-limit notice."""
from __future__ import annotations

from unittest.mock import patch

from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import issue_registry as ir
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.smartmannheim_klima.const import (
    CONF_INCLUDE_AQI,
    CONF_INCLUDE_DWD,
    CONF_INCLUDE_POLLEN,
    CONF_STATIONS,
    DOMAIN,
    DWD_DEVICE_ID,
    ISSUE_TOO_MANY_SENSORS,
    POLLEN_DEVICE_ID,
)
from custom_components.smartmannheim_klima.official import latest_values, location_key

from .common import load_fixture, sensor, sensors

CLIMATE_UPDATE = (
    "custom_components.smartmannheim_klima.coordinator."
    "ClimateCoordinator._async_update_data"
)
EXTRAS_UPDATE = (
    "custom_components.smartmannheim_klima.coordinator."
    "ExtrasCoordinator._async_update_data"
)
EXTRAS_EMPTY = {"pollen": {}, "aqi": {}, "dwd": {}}


def _climate_data() -> dict:
    return {
        sensor("0101-001-21")["sensorId"]: latest_values(
            load_fixture("measurements_climate.json")["data"]
        ),
        sensor("0101-001-31")["sensorId"]: latest_values(
            load_fixture("measurements_wind.json")["data"]
        ),
    }


async def _setup(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    with (
        patch(CLIMATE_UPDATE, return_value=_climate_data()),
        patch(EXTRAS_UPDATE, return_value=EXTRAS_EMPTY),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()


def _entry(stations, **flags) -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        unique_id=DOMAIN,
        version=2,
        data={
            CONF_STATIONS: stations,
            CONF_INCLUDE_POLLEN: flags.get("pollen", True),
            CONF_INCLUDE_AQI: flags.get("aqi", True),
            CONF_INCLUDE_DWD: flags.get("dwd", True),
        },
    )


async def test_pair_shares_one_device(hass: HomeAssistant, freezer) -> None:
    # Fixture readings are from 08:00 UTC; older values would count as stale.
    freezer.move_to("2026-09-23T08:05:00+00:00")
    thermo, wind = sensor("0101-001-21"), sensor("0101-001-31")
    entry = _entry([thermo, wind])
    entry.add_to_hass(hass)
    await _setup(hass, entry)

    ent_reg = er.async_get(hass)
    temp_id = ent_reg.async_get_entity_id(
        "sensor", DOMAIN, f"{DOMAIN}_{thermo['sensorId']}_temperature"
    )
    wind_id = ent_reg.async_get_entity_id(
        "sensor", DOMAIN, f"{DOMAIN}_{wind['sensorId']}_averageWindSpeed"
    )
    assert hass.states.get(temp_id).state == "13.4"
    # 1.2 m/s, shown in HA's metric default for wind (km/h).
    assert hass.states.get(wind_id).state == "4.32"
    attrs = hass.states.get(temp_id).attributes
    assert attrs["update_interval_min"] == 10
    assert attrs["measured_at"].startswith("2026-09-23T08:00:00")
    # Catalog enrichment for 0101-001-21 (T-016 in the catalog).
    assert attrs["catalog_id"] == "T-016"
    assert attrs["measurement_height_m"] == 3

    # Disabled by default: dew point.
    dew = ent_reg.async_get(
        ent_reg.async_get_entity_id("sensor", DOMAIN, f"{DOMAIN}_{thermo['sensorId']}_dewPoint")
    )
    assert dew.disabled_by is er.RegistryEntryDisabler.INTEGRATION
    # Skipped parameters.
    assert not ent_reg.async_get_entity_id(
        "sensor", DOMAIN, f"{DOMAIN}_{thermo['sensorId']}_precipitationTick"
    )

    dev_reg = dr.async_get(hass)
    device = dev_reg.async_get_device(identifiers={(DOMAIN, location_key(thermo))})
    assert device.serial_number == "0101-001-21 | 0101-001-31"
    assert ent_reg.async_get(temp_id).device_id == device.id
    assert ent_reg.async_get(wind_id).device_id == device.id
    # One map pin per location.
    assert len(hass.states.async_entity_ids("device_tracker")) == 1
    assert not ir.async_get(hass).async_get_issue(DOMAIN, ISSUE_TOO_MANY_SENSORS)


async def test_too_many_sensors_issue(hass: HomeAssistant) -> None:
    entry = _entry(sensors())
    entry.add_to_hass(hass)
    await _setup(hass, entry)

    issue = ir.async_get(hass).async_get_issue(DOMAIN, ISSUE_TOO_MANY_SENSORS)
    assert issue is not None
    assert issue.translation_placeholders == {
        "count": "8",
        "interval": "16",
        "max_sensors": "5",
    }


async def test_setup_removes_stale_devices(hass: HomeAssistant) -> None:
    thermo = sensor("0101-001-21")
    entry = _entry([thermo], dwd=False)
    entry.add_to_hass(hass)
    dev_reg = dr.async_get(hass)
    for ident in ("loc-old", DWD_DEVICE_ID, POLLEN_DEVICE_ID):
        dev_reg.async_get_or_create(
            config_entry_id=entry.entry_id, identifiers={(DOMAIN, ident)}
        )
    await _setup(hass, entry)

    assert dev_reg.async_get_device(identifiers={(DOMAIN, "loc-old")}) is None
    assert dev_reg.async_get_device(identifiers={(DOMAIN, DWD_DEVICE_ID)}) is None
    assert dev_reg.async_get_device(identifiers={(DOMAIN, POLLEN_DEVICE_ID)})
    assert dev_reg.async_get_device(identifiers={(DOMAIN, location_key(thermo))})


async def test_extras_only(hass: HomeAssistant) -> None:
    entry = _entry([])
    entry.add_to_hass(hass)
    await _setup(hass, entry)
    assert hass.states.async_entity_ids("device_tracker") == []
    assert any(e.startswith("sensor.pollenflug") for e in hass.states.async_entity_ids("sensor"))


async def test_dwd_precipitation_today(hass: HomeAssistant) -> None:
    entry = _entry([], pollen=False, aqi=False)
    entry.add_to_hass(hass)
    extras = {
        "pollen": {},
        "aqi": {},
        "dwd": {
            "precipitation_today": {
                "indicator": 2.44,
                "timestamp": "2026-09-23T10:05:00.000Z",
                "warning": None,
            },
            # Real value; the computed series is km/h (3.1 m/s).
            "wind_speed": {
                "indicator": 11.16,
                "timestamp": "2026-09-23T10:00:00.000Z",
                "warning": None,
            },
        },
    }
    with patch(EXTRAS_UPDATE, return_value=extras):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    entity_id = er.async_get(hass).async_get_entity_id(
        "sensor", DOMAIN, f"{DOMAIN}_dwd_precipitation_today"
    )
    state = hass.states.get(entity_id)
    assert float(state.state) == 2.44
    assert state.attributes["state_class"] == "total_increasing"
    assert state.attributes["unit_of_measurement"] == "mm"

    wind = hass.states.get(
        er.async_get(hass).async_get_entity_id("sensor", DOMAIN, f"{DOMAIN}_dwd_wind_speed")
    )
    assert float(wind.state) == 11.16
    assert wind.attributes["unit_of_measurement"] == "km/h"
