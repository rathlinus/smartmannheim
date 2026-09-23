"""Config and options flow."""
from __future__ import annotations

from unittest.mock import patch

import pytest
from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.smartmannheim_klima.api import SmartMannheimError
from custom_components.smartmannheim_klima.const import (
    CONF_INCLUDE_AQI,
    CONF_INCLUDE_DWD,
    CONF_INCLUDE_POLLEN,
    CONF_STATIONS,
    DOMAIN,
)

from .common import sensor, sensors

LOAD = "custom_components.smartmannheim_klima.config_flow._load_stations"
SETUP = "custom_components.smartmannheim_klima.async_setup_entry"


@pytest.fixture
def mock_sensors():
    with patch(LOAD, return_value=sensors()) as mock:
        yield mock


async def _start(hass: HomeAssistant):
    return await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )


async def test_search_pick_finish(hass: HomeAssistant, mock_sensors) -> None:
    result = await _start(hass)
    assert result["type"] is FlowResultType.MENU

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": "search"}
    )
    assert result["step_id"] == "search"
    assert result["description_placeholders"]["interval"] == "10"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"query": "0101-001"}
    )
    assert result["step_id"] == "pick"
    assert result["description_placeholders"]["match_count"] == "2"
    labels = [o["label"] for o in result["data_schema"].schema[CONF_STATIONS].config["options"]]
    # Climate before wind for the same station.
    assert labels[0].startswith("0101-001-21 · Klima")
    assert labels[1].startswith("0101-001-31 · Wind")

    thermo, wind = sensor("0101-001-21"), sensor("0101-001-31")
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_STATIONS: [thermo["sensorId"], wind["sensorId"]]}
    )
    assert result["type"] is FlowResultType.MENU
    assert "finish" in result["menu_options"]
    assert result["description_placeholders"]["selected_count"] == "2"

    with patch(SETUP, return_value=True):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"next_step_id": "finish"}
        )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_STATIONS] == [thermo, wind]
    assert result["data"][CONF_INCLUDE_POLLEN] is True
    assert result["result"].version == 2


async def test_search_by_address(hass: HomeAssistant, mock_sensors) -> None:
    result = await _start(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": "search"}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"query": "aubuckel"}
    )
    assert result["step_id"] == "pick"
    # T-002 and its replacement wind sensor share the address.
    assert result["description_placeholders"]["match_count"] == "2"


async def test_search_no_matches(hass: HomeAssistant, mock_sensors) -> None:
    result = await _start(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": "search"}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"query": "nirgendwo"}
    )
    assert result["step_id"] == "search"
    assert result["errors"] == {"query": "no_matches"}


async def test_cannot_connect(hass: HomeAssistant) -> None:
    with patch(LOAD, side_effect=SmartMannheimError("down")):
        result = await _start(hass)
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"next_step_id": "all_stations"}
        )
    assert result["step_id"] == "search"
    assert result["errors"] == {"base": "cannot_connect"}


async def test_finish_hidden_without_picks(hass: HomeAssistant, mock_sensors) -> None:
    result = await _start(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": "all_stations"}
    )
    assert result["step_id"] == "pick"
    assert result["description_placeholders"]["match_count"] == str(len(sensors()))

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_STATIONS: []}
    )
    assert result["type"] is FlowResultType.MENU
    assert "finish" not in result["menu_options"]


async def test_interval_grows_with_selection(hass: HomeAssistant, mock_sensors) -> None:
    result = await _start(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": "all_stations"}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_STATIONS: [s["sensorId"] for s in sensors()]}
    )
    assert result["description_placeholders"]["selected_count"] == "8"
    assert result["description_placeholders"]["interval"] == "16"


def _entry(hass: HomeAssistant) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=DOMAIN,
        version=2,
        data={
            CONF_STATIONS: [sensor("0101-001-21")],
            CONF_INCLUDE_POLLEN: True,
            CONF_INCLUDE_AQI: True,
            CONF_INCLUDE_DWD: True,
        },
    )
    entry.add_to_hass(hass)
    return entry


async def test_options_deselect_all(hass: HomeAssistant, mock_sensors) -> None:
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
    # Sensor selection is carried over unchanged.
    assert entry.options[CONF_STATIONS] == [sensor("0101-001-21")]
