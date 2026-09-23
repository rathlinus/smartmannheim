"""Config & options flow: search → pick → (search more | finish)."""
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
    BooleanSelector,
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
)

from .api import SmartMannheimClient, SmartMannheimError
from .const import (
    CONF_INCLUDE_AQI,
    CONF_INCLUDE_DWD,
    CONF_INCLUDE_POLLEN,
    CONF_QUERY,
    CONF_STATIONS,
    DOMAIN,
)
from .helpers import get_stations

_LOGGER = logging.getLogger(__name__)

# All three extra data sources default to ON for a fresh install.
_EXTRAS_DEFAULTS: dict[str, bool] = {
    CONF_INCLUDE_POLLEN: True,
    CONF_INCLUDE_AQI: True,
    CONF_INCLUDE_DWD: True,
}


def _station_label(station: dict[str, Any]) -> str:
    name = (station.get("displayName") or station.get("name") or "").strip()
    address = (station.get("address") or "").strip().strip(",").strip()
    if address and address not in name:
        return f"{name} — {address}" if name else address
    return name or station.get("locationId", "?")


def _station_payload(station: dict[str, Any]) -> dict[str, Any]:
    return {
        "locationId": station["locationId"],
        "name": _station_label(station),
        "coordinates": (station.get("location") or {}).get("coordinates"),
    }


def _matches(station: dict[str, Any], query: str) -> bool:
    if not query:
        return True
    q = query.lower().strip()
    for field in ("name", "displayName", "address"):
        val = station.get(field)
        if val and q in str(val).lower():
            return True
    return False


async def _load_stations(hass) -> list[dict[str, Any]]:
    session = async_get_clientsession(hass)
    client = SmartMannheimClient(session)
    return await client.list_stations()


def _extras_schema(current: dict[str, Any]) -> vol.Schema:
    """Build the schema for the extras toggle step, seeding from `current`."""
    def _default(key: str) -> bool:
        val = current.get(key)
        return _EXTRAS_DEFAULTS[key] if val is None else bool(val)

    return vol.Schema(
        {
            vol.Required(
                CONF_INCLUDE_POLLEN, default=_default(CONF_INCLUDE_POLLEN)
            ): BooleanSelector(),
            vol.Required(
                CONF_INCLUDE_AQI, default=_default(CONF_INCLUDE_AQI)
            ): BooleanSelector(),
            vol.Required(
                CONF_INCLUDE_DWD, default=_default(CONF_INCLUDE_DWD)
            ): BooleanSelector(),
        }
    )


class _AccumulatingFlow:
    """Search/pick/menu steps shared by the config and options flows.

    Selections live in ``self._accumulated`` (``locationId -> payload``)
    across multiple search iterations; ``finish`` commits all of them.
    """

    hass: Any
    # The options flow may end with zero stations (extras still work);
    # the initial config flow needs at least one pick.
    _allow_empty_finish = False

    def _init_state(
        self, initial: list[dict[str, Any]] | None = None
    ) -> None:
        self._accumulated: dict[str, dict[str, Any]] = {
            s["locationId"]: s for s in (initial or [])
        }
        self._all_stations: list[dict[str, Any]] = []
        self._candidates: list[dict[str, Any]] = []
        self._query: str = ""

    def _search_form(self, errors: dict[str, str] | None = None) -> ConfigFlowResult:
        return self.async_show_form(
            step_id="search",
            data_schema=vol.Schema({vol.Optional(CONF_QUERY, default=""): str}),
            description_placeholders={
                "selected_count": str(len(self._accumulated)),
            },
            errors=errors or {},
        )

    async def async_step_search(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is None:
            return self._search_form()
        self._query = (user_input.get(CONF_QUERY) or "").strip()
        try:
            if not self._all_stations:
                self._all_stations = await _load_stations(self.hass)
        except SmartMannheimError as err:
            _LOGGER.error("Could not load station list: %s", err)
            return self._search_form({"base": "cannot_connect"})
        self._candidates = [
            s for s in self._all_stations if _matches(s, self._query)
        ]
        if not self._candidates:
            return self._search_form({CONF_QUERY: "no_matches"})
        return await self.async_step_pick()

    async def async_step_all_stations(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Skip the search input — load every station and jump to pick.

        On a backend error fall back to the regular search form so the
        user sees a meaningful "cannot_connect" message instead of a
        silent menu re-render.
        """
        try:
            if not self._all_stations:
                self._all_stations = await _load_stations(self.hass)
        except SmartMannheimError as err:
            _LOGGER.error("Could not load station list: %s", err)
            return self._search_form({"base": "cannot_connect"})
        self._query = ""
        self._candidates = list(self._all_stations)
        return await self.async_step_pick()

    async def async_step_pick(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        candidate_ids = {s["locationId"] for s in self._candidates}

        if user_input is not None:
            selected_ids: list[str] = user_input[CONF_STATIONS]
            by_id = {s["locationId"]: s for s in self._candidates}
            # Items inside the current match-set that were unchecked are
            # removed; items outside the current match-set stay as they are.
            for sid in list(self._accumulated.keys()):
                if sid in candidate_ids and sid not in selected_ids:
                    del self._accumulated[sid]
            for sid in selected_ids:
                if sid in by_id:
                    self._accumulated[sid] = _station_payload(by_id[sid])
            return await self.async_step_menu()

        default = [sid for sid in self._accumulated if sid in candidate_ids]
        options = [
            SelectOptionDict(value=s["locationId"], label=_station_label(s))
            for s in sorted(self._candidates, key=_station_label)
        ]
        schema = vol.Schema(
            {
                vol.Required(
                    CONF_STATIONS, default=default
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
                "match_count": str(len(self._candidates)),
                "selected_count": str(len(self._accumulated)),
            },
        )

    async def async_step_menu(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        menu_options = ["search_more", "show_all_more"]
        # Without any pick, "finish" would only bounce back; hide it.
        if self._accumulated or self._allow_empty_finish:
            menu_options.append("finish")
        return self.async_show_menu(
            step_id="menu",
            menu_options=menu_options,
            description_placeholders={
                "selected_count": str(len(self._accumulated)),
            },
        )

    async def async_step_search_more(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        return self._search_form()

    async def async_step_show_all_more(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        return await self.async_step_all_stations()


class SmartMannheimConfigFlow(_AccumulatingFlow, ConfigFlow, domain=DOMAIN):
    """Top-level menu → [search | all stations] → pick → [search more | finish]."""

    VERSION = 1

    def __init__(self) -> None:
        self._init_state()

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if self.unique_id is None:
            await self.async_set_unique_id(DOMAIN)
            self._abort_if_unique_id_configured()
        return self.async_show_menu(
            step_id="user",
            menu_options=["search", "all_stations"],
            description_placeholders={
                "selected_count": str(len(self._accumulated)),
            },
        )

    async def async_step_finish(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        return self.async_create_entry(
            title="Smart Mannheim Klimamessnetz",
            data={
                CONF_STATIONS: list(self._accumulated.values()),
                # Enable all three "extra" data sources by default for new
                # installs. Users can flip them off in Configure → Extras.
                **_EXTRAS_DEFAULTS,
            },
        )

    @staticmethod
    @callback
    def async_get_options_flow(entry: ConfigEntry) -> OptionsFlow:
        return SmartMannheimOptionsFlow(entry)


class SmartMannheimOptionsFlow(_AccumulatingFlow, OptionsFlow):
    """Stations search → pick → menu, plus an extras toggle step."""

    _allow_empty_finish = True

    def __init__(self, entry: ConfigEntry) -> None:
        self._init_state(initial=get_stations(entry))
        # Seed extras from existing options/data so the toggle step can
        # show the user's current choices on re-entry.
        self._extras: dict[str, bool] = {
            k: bool(entry.options.get(k, entry.data.get(k, default)))
            for k, default in _EXTRAS_DEFAULTS.items()
        }

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        # Top-level menu: manage stations (search or list-all) or toggle
        # the extra data sources.
        return self.async_show_menu(
            step_id="init",
            menu_options=["search", "all_stations", "extras"],
        )

    async def async_step_extras(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            self._extras = {k: bool(user_input.get(k, _EXTRAS_DEFAULTS[k]))
                            for k in _EXTRAS_DEFAULTS}
            return await self.async_step_finish()
        return self.async_show_form(
            step_id="extras",
            data_schema=_extras_schema(self._extras),
        )

    async def async_step_finish(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        return self.async_create_entry(
            title="",
            data={
                CONF_STATIONS: list(self._accumulated.values()),
                **self._extras,
            },
        )
