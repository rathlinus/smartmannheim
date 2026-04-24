"""Config & options flow: search stations, then multi-select."""
from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
)

from .api import SmartMannheimClient, SmartMannheimError
from .const import CONF_QUERY, CONF_STATIONS, DOMAIN

_LOGGER = logging.getLogger(__name__)


def _station_label(station: dict[str, Any]) -> str:
    name = (station.get("displayName") or station.get("name") or "").strip()
    address = (station.get("address") or "").strip().strip(",").strip()
    if address and address not in name:
        return f"{name} — {address}" if name else address
    return name or station.get("locationId", "?")


def _matches(station: dict[str, Any], query: str) -> bool:
    if not query:
        return True
    q = query.lower().strip()
    for field in ("name", "displayName", "address"):
        val = station.get(field)
        if val and q in str(val).lower():
            return True
    return False


class SmartMannheimConfigFlow(ConfigFlow, domain=DOMAIN):
    """Two-step add flow: search → pick."""

    VERSION = 1

    def __init__(self) -> None:
        self._all_stations: list[dict[str, Any]] = []
        self._candidates: list[dict[str, Any]] = []
        self._query: str = ""

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Step 1 — free-text search (empty = show all)."""
        await self.async_set_unique_id(DOMAIN)
        self._abort_if_unique_id_configured()

        errors: dict[str, str] = {}

        if user_input is not None:
            self._query = (user_input.get(CONF_QUERY) or "").strip()
            try:
                self._all_stations = await _load_stations(self.hass)
            except SmartMannheimError as err:
                _LOGGER.error("Could not load station list: %s", err)
                errors["base"] = "cannot_connect"
            else:
                self._candidates = [
                    s for s in self._all_stations if _matches(s, self._query)
                ]
                if not self._candidates:
                    errors[CONF_QUERY] = "no_matches"
                else:
                    return await self.async_step_pick()

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({vol.Optional(CONF_QUERY, default=""): str}),
            errors=errors,
        )

    async def async_step_pick(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Step 2 — multi-select from the filtered matches."""
        if user_input is not None:
            selected_ids: list[str] = user_input[CONF_STATIONS]
            by_id = {s["locationId"]: s for s in self._candidates}
            chosen = [
                {
                    "locationId": sid,
                    "name": _station_label(by_id[sid]),
                    "coordinates": (by_id[sid].get("location") or {}).get(
                        "coordinates"
                    ),
                }
                for sid in selected_ids
                if sid in by_id
            ]
            return self.async_create_entry(
                title="Smart Mannheim Klimamessnetz",
                data={CONF_STATIONS: chosen},
            )

        options = [
            SelectOptionDict(value=s["locationId"], label=_station_label(s))
            for s in sorted(self._candidates, key=_station_label)
        ]
        schema = vol.Schema(
            {
                vol.Required(CONF_STATIONS, default=[]): SelectSelector(
                    SelectSelectorConfig(
                        options=options,
                        multiple=True,
                        mode=SelectSelectorMode.LIST,
                        custom_value=False,
                    )
                )
            }
        )
        return self.async_show_form(
            step_id="pick",
            data_schema=schema,
            description_placeholders={
                "query": self._query or "—",
                "count": str(len(self._candidates)),
            },
        )

    @staticmethod
    @callback
    def async_get_options_flow(entry: ConfigEntry) -> OptionsFlow:
        return SmartMannheimOptionsFlow(entry)


class SmartMannheimOptionsFlow(OptionsFlow):
    """Same two-step pattern for editing the station list later."""

    def __init__(self, entry: ConfigEntry) -> None:
        self._entry = entry
        self._all_stations: list[dict[str, Any]] = []
        self._candidates: list[dict[str, Any]] = []
        self._query: str = ""

    def _current_ids(self) -> set[str]:
        stations = self._entry.options.get(CONF_STATIONS) or self._entry.data.get(
            CONF_STATIONS, []
        )
        return {s["locationId"] for s in stations}

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            self._query = (user_input.get(CONF_QUERY) or "").strip()
            try:
                self._all_stations = await _load_stations(self.hass)
            except SmartMannheimError as err:
                _LOGGER.error("Could not load station list: %s", err)
                errors["base"] = "cannot_connect"
            else:
                self._candidates = [
                    s for s in self._all_stations if _matches(s, self._query)
                ]
                # Always include already-selected stations so they can be
                # unchecked even if they don't match the current query.
                current_ids = self._current_ids()
                existing_by_id = {s["locationId"]: s for s in self._all_stations}
                for sid in current_ids:
                    if sid in existing_by_id and all(
                        c["locationId"] != sid for c in self._candidates
                    ):
                        self._candidates.append(existing_by_id[sid])
                if not self._candidates:
                    errors[CONF_QUERY] = "no_matches"
                else:
                    return await self.async_step_pick()

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema({vol.Optional(CONF_QUERY, default=""): str}),
            errors=errors,
        )

    async def async_step_pick(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        current_ids = self._current_ids()

        if user_input is not None:
            selected_ids: list[str] = user_input[CONF_STATIONS]
            by_id = {s["locationId"]: s for s in self._candidates}
            chosen = [
                {
                    "locationId": sid,
                    "name": _station_label(by_id[sid]),
                    "coordinates": (by_id[sid].get("location") or {}).get(
                        "coordinates"
                    ),
                }
                for sid in selected_ids
                if sid in by_id
            ]
            return self.async_create_entry(title="", data={CONF_STATIONS: chosen})

        options = [
            SelectOptionDict(value=s["locationId"], label=_station_label(s))
            for s in sorted(self._candidates, key=_station_label)
        ]
        default_selected = [
            s["locationId"] for s in self._candidates if s["locationId"] in current_ids
        ]
        schema = vol.Schema(
            {
                vol.Required(
                    CONF_STATIONS, default=default_selected
                ): SelectSelector(
                    SelectSelectorConfig(
                        options=options,
                        multiple=True,
                        mode=SelectSelectorMode.LIST,
                        custom_value=False,
                    )
                )
            }
        )
        return self.async_show_form(
            step_id="pick",
            data_schema=schema,
            description_placeholders={
                "query": self._query or "—",
                "count": str(len(self._candidates)),
            },
        )


async def _load_stations(hass) -> list[dict[str, Any]]:
    session = async_get_clientsession(hass)
    client = SmartMannheimClient(session)
    return await client.list_stations()
