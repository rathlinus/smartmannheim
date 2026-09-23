"""0.2 (dashboard stations) → 0.3 (official sensors) migration."""
from __future__ import annotations

from unittest.mock import patch

from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.smartmannheim_klima.api import SmartMannheimError
from custom_components.smartmannheim_klima.const import (
    CONF_INCLUDE_AQI,
    CONF_INCLUDE_DWD,
    CONF_INCLUDE_POLLEN,
    CONF_STATIONS,
    DOMAIN,
)
from custom_components.smartmannheim_klima.official import location_key

from .common import sensor

GET_SENSORS = "custom_components.smartmannheim_klima.migration.async_get_sensors"
CLIMATE_UPDATE = (
    "custom_components.smartmannheim_klima.coordinator."
    "ClimateCoordinator._async_update_data"
)
EXTRAS_UPDATE = (
    "custom_components.smartmannheim_klima.coordinator."
    "ExtrasCoordinator._async_update_data"
)

# As stored by 0.2.x: label from the dashboard (codes or street address).
PAIR = {
    "locationId": "efa477a6-97b1-44a9-8002-488761a2efa9",
    "name": "0101-001-21 | 0101-001-31",
    "coordinates": [8.475061, 49.496309],
}
ADDRESS_ONLY = {
    "locationId": "e64131a0-2def-e7fb-57eb-8310476d47a2",
    "name": "Am Aubuckel ,",
    "coordinates": [8.521318, 49.493182],
}
GONE = {"locationId": "gone", "name": "Abgebaut", "coordinates": [8.0, 49.0]}


def _old_entities(hass, entry, station, keys):
    dev_reg, ent_reg = dr.async_get(hass), er.async_get(hass)
    device = dev_reg.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, station["locationId"])},
        name=station["name"],
    )
    ids = {}
    for key in keys:
        domain = "device_tracker" if key == "location" else "sensor"
        ids[key] = ent_reg.async_get_or_create(
            domain,
            DOMAIN,
            f"{DOMAIN}_{station['locationId']}_{key}",
            config_entry=entry,
            device_id=device.id,
            suggested_object_id=f"{station['locationId'][:4]}_{key}",
        ).entity_id
    return ids


async def test_migrates_entries_and_keeps_entity_ids(hass: HomeAssistant) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=DOMAIN,
        version=1,
        data={
            CONF_STATIONS: [PAIR, ADDRESS_ONLY, GONE],
            CONF_INCLUDE_POLLEN: True,
            CONF_INCLUDE_AQI: False,
            CONF_INCLUDE_DWD: False,
        },
    )
    entry.add_to_hass(hass)
    pair_ids = _old_entities(
        hass, entry, PAIR, ["temperature", "humidity", "wind_speed", "location"]
    )
    # This station never had a wind entity: its wind sensor must not be
    # added (it would cost requests for nothing).
    addr_ids = _old_entities(hass, entry, ADDRESS_ONLY, ["temperature", "humidity"])
    gone_ids = _old_entities(hass, entry, GONE, ["temperature"])

    with (
        # No network: fall back to the bundled snapshot.
        patch(GET_SENSORS, side_effect=SmartMannheimError("offline")),
        patch(CLIMATE_UPDATE, return_value={}),
        patch(EXTRAS_UPDATE, return_value={"pollen": {}, "aqi": {}, "dwd": {}}),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    assert entry.version == 2
    thermo, wind, t002 = sensor("0101-001-21"), sensor("0101-001-31"), sensor("T-002")
    assert [s["sensorId"] for s in entry.data[CONF_STATIONS]] == [
        thermo["sensorId"],
        wind["sensorId"],
        t002["sensorId"],
    ]

    ent_reg = er.async_get(hass)
    expected = {
        pair_ids["temperature"]: f"{DOMAIN}_{thermo['sensorId']}_temperature",
        pair_ids["humidity"]: f"{DOMAIN}_{thermo['sensorId']}_airHumidity",
        pair_ids["wind_speed"]: f"{DOMAIN}_{wind['sensorId']}_averageWindSpeed",
        pair_ids["location"]: f"{DOMAIN}_{location_key(thermo)}_location",
        addr_ids["temperature"]: f"{DOMAIN}_{t002['sensorId']}_temperature",
    }
    for entity_id, unique_id in expected.items():
        assert ent_reg.async_get(entity_id).unique_id == unique_id

    dev_reg = dr.async_get(hass)
    new_device = dev_reg.async_get_device(identifiers={(DOMAIN, location_key(thermo))})
    assert ent_reg.async_get(pair_ids["temperature"]).device_id == new_device.id
    for station in (PAIR, ADDRESS_ONLY, GONE):
        assert dev_reg.async_get_device(identifiers={(DOMAIN, station["locationId"])}) is None
    # Unmatched station's entities went with their device.
    assert ent_reg.async_get(gone_ids["temperature"]) is None
