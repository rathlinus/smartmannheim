"""Entry helpers."""
from __future__ import annotations

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.smartmannheim_klima.const import (
    CONF_INCLUDE_POLLEN,
    CONF_STATIONS,
    DOMAIN,
)
from custom_components.smartmannheim_klima.helpers import (
    get_stations,
    option_flag,
)

STATION = {"locationId": "a", "name": "A", "coordinates": [8.4, 49.4]}


def test_get_stations_falls_back_to_data():
    entry = MockConfigEntry(domain=DOMAIN, data={CONF_STATIONS: [STATION]})
    assert get_stations(entry) == [STATION]


def test_get_stations_keeps_empty_options():
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_STATIONS: [STATION]},
        options={CONF_STATIONS: []},
    )
    assert get_stations(entry) == []


def test_option_flag_prefers_options():
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_INCLUDE_POLLEN: True},
        options={CONF_INCLUDE_POLLEN: False},
    )
    assert option_flag(entry, CONF_INCLUDE_POLLEN) is False
    assert option_flag(MockConfigEntry(domain=DOMAIN, data={}), CONF_INCLUDE_POLLEN)
