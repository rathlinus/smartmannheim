"""Config & options flow: search → pick → (search more | finish)."""
from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable

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


class _AccumulatingFlow:
    """Shared search/pick/menu behaviour used by both config and options flows.

    Subclass stores selections in ``self._accumulated`` (``locationId -> payload``)
    across multiple search iterations; final ``finish`` commits all of them.
    """

    hass: Any

    def _init_state(
        self, initial: list[dict[str, Any]] | None = None
    ) -> None:
        self._accumulated: dict[str, dict[str, Any]] = {
            s["locationId"]: s for s in (initial or [])
        }
        self._all_stations: list[dict[str, Any]] = []
        self._candidates: list[dict[str, Any]] = []
        self._query: str = ""

    def _show_form(self, **kwargs):  # overridden by Flow subclasses
        raise NotImplementedError

    async def _do_search(
        self,
        step_id: str,
        user_input: dict[str, Any] | None,
        on_matches: Callable[[], Awaitable[ConfigFlowResult]],
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            self._query = (user_input.get(CONF_QUERY) or "").strip()
            try:
                if not self._all_stations:
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
                    return await on_matches()

        return self._show_form(
            step_id=step_id,
            data_schema=vol.Schema(
                {vol.Optional(CONF_QUERY, default=""): str}
            ),
            description_placeholders={
                "selected_count": str(len(self._accumulated)),
            },
            errors=errors,
        )

    async def _do_pick(
        self,
        step_id: str,
        user_input: dict[str, Any] | None,
        on_done: Callable[[], Awaitable[ConfigFlowResult]],
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
            return await on_done()

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
        return self._show_form(
            step_id=step_id,
            data_schema=schema,
            description_placeholders={
                "query": self._query or "—",
                "match_count": str(len(self._candidates)),
                "selected_count": str(len(self._accumulated)),
            },
        )


class SmartMannheimConfigFlow(ConfigFlow, _AccumulatingFlow, domain=DOMAIN):
    """Search → pick → menu → [search more | finish]."""

    VERSION = 1

    def __init__(self) -> None:
        self._init_state()

    def _show_form(self, **kwargs):
        return self.async_show_form(**kwargs)

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if self.unique_id is None:
            await self.async_set_unique_id(DOMAIN)
            self._abort_if_unique_id_configured()
        return await self._do_search("user", user_input, self.async_step_pick)

    async def async_step_pick(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        return await self._do_pick("pick", user_input, self.async_step_menu)

    async def async_step_menu(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        return self.async_show_menu(
            step_id="menu",
            menu_options=["search_more", "finish"],
            description_placeholders={
                "selected_count": str(len(self._accumulated)),
            },
        )

    async def async_step_search_more(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        # Land back on the same search form as step `user`.
        return await self._do_search("user", None, self.async_step_pick)

    async def async_step_finish(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if not self._accumulated:
            # User walked to "finish" with zero picks — bounce back to search.
            return await self._do_search("user", None, self.async_step_pick)
        return self.async_create_entry(
            title="Smart Mannheim Klimamessnetz",
            data={CONF_STATIONS: list(self._accumulated.values())},
        )

    @staticmethod
    @callback
    def async_get_options_flow(entry: ConfigEntry) -> OptionsFlow:
        return SmartMannheimOptionsFlow(entry)


class SmartMannheimOptionsFlow(OptionsFlow, _AccumulatingFlow):
    """Same search → pick → menu pattern, seeded with existing selection."""

    def __init__(self, entry: ConfigEntry) -> None:
        self._entry = entry
        existing = entry.options.get(CONF_STATIONS) or entry.data.get(
            CONF_STATIONS, []
        )
        self._init_state(initial=existing)

    def _show_form(self, **kwargs):
        return self.async_show_form(**kwargs)

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        return await self._do_search("init", user_input, self.async_step_pick)

    async def async_step_pick(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        return await self._do_pick("pick", user_input, self.async_step_menu)

    async def async_step_menu(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        return self.async_show_menu(
            step_id="menu",
            menu_options=["search_more", "finish"],
            description_placeholders={
                "selected_count": str(len(self._accumulated)),
            },
        )

    async def async_step_search_more(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        return await self._do_search("init", None, self.async_step_pick)

    async def async_step_finish(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        return self.async_create_entry(
            title="",
            data={CONF_STATIONS: list(self._accumulated.values())},
        )
