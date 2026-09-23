"""Pure helpers for the official API."""
from __future__ import annotations

import pytest

from custom_components.smartmannheim_klima.official import (
    KIND_CLIMATE,
    KIND_WIND,
    climate_interval_minutes,
    latest_values,
    location_key,
    match_legacy_station,
    sensor_kind,
)

from .common import load_fixture, sensor, sensors


@pytest.mark.parametrize(
    ("count", "minutes"), [(0, 10), (1, 10), (5, 10), (6, 12), (8, 16), (20, 40)]
)
def test_climate_interval(count, minutes):
    assert climate_interval_minutes(count) == minutes


def test_normalize_sensors():
    thermo = sensor("0101-001-21")
    assert thermo["sensorId"] == "0004A30B00F72EED"
    assert thermo["coordinates"] == [8.475061, 49.496309]
    assert "temperature" in thermo["params"]
    assert sensor_kind(thermo["params"]) == KIND_CLIMATE
    assert sensor_kind(sensor("0101-001-31")["params"]) == KIND_WIND
    assert sensor("2303LH085")["coordinates"] is None


def test_location_key_groups_pairs():
    assert location_key(sensor("0101-001-21")) == location_key(sensor("0101-001-31"))
    assert location_key(sensor("2303LH085")).startswith("sensor_")


def test_latest_values_real_response():
    values = latest_values(load_fixture("measurements_climate.json")["data"])
    assert values["temperature"] == {
        "value": 13.4,
        "timestamp": "2026-09-23T08:00:00.000Z",
    }
    assert values["atmosphericPressure"]["value"] == 1014.65


def test_latest_values_unordered_and_sparse():
    rows = [
        {"timestamp": "2026-09-23T07:50:00.000Z", "temperature": 1.0, "windGust1s": 4.0},
        {"timestamp": "2026-09-23T08:00:00.000Z", "temperature": 2.0, "windGust1s": None},
    ]
    values = latest_values(rows)
    assert values["temperature"]["value"] == 2.0
    # Missing in the newest row → falls back to the older one.
    assert values["windGust1s"] == {"value": 4.0, "timestamp": "2026-09-23T07:50:00.000Z"}


def test_match_by_name_tokens():
    roles = match_legacy_station(
        "0101-001-21 | 0101-001-31", [8.475061, 49.496309], sensors()
    )
    assert roles == {KIND_CLIMATE: "0004A30B00F72EED", KIND_WIND: "0004A30B00F79967"}


def test_match_skips_archived_and_moved_sensor():
    # 2306LW027 was archived at T-002 and now reports from ~2 km away; the
    # replacement 2507LW195 sits at the station's position.
    roles = match_legacy_station(
        "T-002 | 2306LW027 ARCHIV_22.05.2026", [8.521318, 49.493182], sensors()
    )
    assert roles[KIND_CLIMATE] == sensor("T-002")["sensorId"]
    assert roles[KIND_WIND] == sensor("2507LW195")["sensorId"]


def test_match_by_position_when_label_is_an_address():
    roles = match_legacy_station("Am Aubuckel ,", [8.52132, 49.49318], sensors())
    assert roles[KIND_CLIMATE] == sensor("T-002")["sensorId"]


def test_match_nothing():
    assert match_legacy_station("Nirgendwo", [8.0, 49.0], sensors()) == {
        KIND_CLIMATE: None,
        KIND_WIND: None,
    }
