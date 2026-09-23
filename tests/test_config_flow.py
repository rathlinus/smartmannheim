"""Config and options flow."""
from __future__ import annotations

from unittest.mock import patch

import pytest
from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.smartmannheim_klima.const import (
    CONF_INCLUDE_AQI,
    CONF_INCLUDE_DWD,
    CONF_INCLUDE_POLLEN,
    CONF_STATIONS,
    DOMAIN,
)

API_STATIONS = [
    {
        "locationId": "loc-1",
        "name": "0101-001-21 | 0101-001-31",
        "displayName": "0101-001-21 | 0101-001-31",
        "address": "Feudenheim",
        "location": {"type": "Point", "coordinates": [8.475061, 49.496309]},
    },
    {
        "locationId": "loc-2",
        "name": "T-050 - SCM auf der Buga",
        "displayName": "T-050 - SCM auf der Buga",
        "address": "",
        "location": {"type": "Point", "coordinates": [8.5242, 49.5015]},
    },
]

LOAD = "custom_components.smartmannheim_klima.config_flow._load_stations"
SETUP = "custom_components.smartmannheim_klima.async_setup_entry"


@pytest.fixture
def mock_stations():
    with patch(LOAD, return_value=API_STATIONS) as mock:
        yield mock


async def test_search_pick_finish(hass: HomeAssistant, mock_stations) -> None:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.MENU

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": "search"}
    )
    assert result["step_id"] == "search"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"query": "feudenheim"}
    )
    assert result["step_id"] == "pick"
    assert result["description_placeholders"]["match_count"] == "1"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_STATIONS: ["loc-1"]}
    )
    assert result["type"] is FlowResultType.MENU
    assert "finish" in result["menu_options"]

    with patch(SETUP, return_value=True):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"next_step_id": "finish"}
        )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert [s["locationId"] for s in result["data"][CONF_STATIONS]] == ["loc-1"]
    assert result["data"][CONF_INCLUDE_POLLEN] is True


async def test_search_no_matches(hass: HomeAssistant, mock_stations) -> None:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": "search"}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"query": "nirgendwo"}
    )
    assert result["step_id"] == "search"
    assert result["errors"] == {"query": "no_matches"}


async def test_finish_hidden_without_picks(hass: HomeAssistant, mock_stations) -> None:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": "all_stations"}
    )
    assert result["step_id"] == "pick"
    assert result["description_placeholders"]["match_count"] == "2"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_STATIONS: []}
    )
    assert result["type"] is FlowResultType.MENU
    assert "finish" not in result["menu_options"]


def _entry(hass: HomeAssistant) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=DOMAIN,
        data={
            CONF_STATIONS: [
                {"locationId": "loc-1", "name": "A", "coordinates": [8.47, 49.49]}
            ],
            CONF_INCLUDE_POLLEN: True,
            CONF_INCLUDE_AQI: True,
            CONF_INCLUDE_DWD: True,
        },
    )
    entry.add_to_hass(hass)
    return entry


async def test_options_deselect_all(hass: HomeAssistant, mock_stations) -> None:
    entry = _entry(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.MENU

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "all_stations"}
    )
    assert result["step_id"] == "pick"
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_STATIONS: []}
    )
    assert "finish" in result["menu_options"]

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "finish"}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options[CONF_STATIONS] == []


async def test_options_extras_toggle(hass: HomeAssistant) -> None:
    entry = _entry(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "extras"}
    )
    assert result["step_id"] == "extras"
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {CONF_INCLUDE_POLLEN: False, CONF_INCLUDE_AQI: True, CONF_INCLUDE_DWD: True},
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options[CONF_INCLUDE_POLLEN] is False
    # Station selection is carried over unchanged.
    assert [s["locationId"] for s in entry.options[CONF_STATIONS]] == ["loc-1"]
