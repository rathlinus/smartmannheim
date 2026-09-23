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
from homeassistant.core import HomeAssistant, callback
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
from .helpers import address_for, async_get_sensors, async_get_snapshot, get_stations
from .official import (
    KIND_CLIMATE,
    KIND_WIND,
    SENSORS_AT_MIN_INTERVAL,
    climate_interval_minutes,
    distance_m,
    location_key,
    sensor_kind,
)

_LOGGER = logging.getLogger(__name__)

# All three extra data sources default to ON for a fresh install.
_EXTRAS_DEFAULTS: dict[str, bool] = {
    CONF_INCLUDE_POLLEN: True,
    CONF_INCLUDE_AQI: True,
    CONF_INCLUDE_DWD: True,
}


_KIND_LABELS = {KIND_CLIMATE: "Klima", KIND_WIND: "Wind"}


class _Catalog:
    """Official sensor list plus labels, addresses and home distance."""

    def __init__(
        self,
        sensors: list[dict[str, Any]],
        snapshot: dict[str, Any],
        home: list[float] | None,
    ) -> None:
        self.sensors = sensors
        self._snapshot = snapshot
        self._home = home

    def address(self, sensor: dict[str, Any]) -> str | None:
        return address_for(sensor, self._snapshot)

    def distance_km(self, sensor: dict[str, Any]) -> float | None:
        if not self._home or not sensor.get("coordinates"):
            return None
        return distance_m(sensor["coordinates"], self._home) / 1000

    def label(self, sensor: dict[str, Any]) -> str:
        parts = [sensor["name"], _KIND_LABELS[sensor_kind(sensor["params"])]]
        if address := self.address(sensor):
            parts.append(address)
        if (km := self.distance_km(sensor)) is not None:
            parts.append(f"{km:.1f} km".replace(".", ","))
        return " · ".join(parts)

    def sort_key(self, sensor: dict[str, Any]) -> tuple:
        # Nearest first; sensors of one station stay together, climate
        # before wind.
        km = self.distance_km(sensor)
        return (
            km if km is not None else float("inf"),
            location_key(sensor),
            sensor_kind(sensor["params"]) != KIND_CLIMATE,
            sensor["name"],
        )

    def matches(self, sensor: dict[str, Any], query: str) -> bool:
        if not query:
            return True
        q = query.lower().strip()
        return any(
            q in text.lower()
            for text in (sensor["name"], sensor["sensorId"], self.address(sensor) or "")
        )


async def _load_stations(hass: HomeAssistant) -> list[dict[str, Any]]:
    client = SmartMannheimClient(async_get_clientsession(hass))
    return await async_get_sensors(hass, client)


async def _load_catalog(hass: HomeAssistant) -> _Catalog:
    sensors = await _load_stations(hass)
    snapshot = await async_get_snapshot(hass)
    home = [hass.config.longitude, hass.config.latitude] if hass.config.latitude else None
    return _Catalog(sensors, snapshot, home)


def _rate_placeholders(count: int) -> dict[str, str]:
    return {
        "selected_count": str(count),
        "interval": str(climate_interval_minutes(count)),
        "max_sensors": str(SENSORS_AT_MIN_INTERVAL),
    }


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

    Selections live in ``self._accumulated`` (``sensorId -> payload``)
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
            s["sensorId"]: s for s in (initial or [])
        }
        self._catalog: _Catalog | None = None
        self._candidates: list[dict[str, Any]] = []
        self._query: str = ""

    def _search_form(self, errors: dict[str, str] | None = None) -> ConfigFlowResult:
        return self.async_show_form(
            step_id="search",
            data_schema=vol.Schema({vol.Optional(CONF_QUERY, default=""): str}),
            description_placeholders=_rate_placeholders(len(self._accumulated)),
            errors=errors or {},
        )

    async def _get_catalog(self) -> _Catalog:
        if self._catalog is None:
            self._catalog = await _load_catalog(self.hass)
        return self._catalog

    async def async_step_search(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is None:
            return self._search_form()
        self._query = (user_input.get(CONF_QUERY) or "").strip()
        try:
            catalog = await self._get_catalog()
        except SmartMannheimError as err:
            _LOGGER.error("Could not load station list: %s", err)
            return self._search_form({"base": "cannot_connect"})
        self._candidates = [
            s for s in catalog.sensors if catalog.matches(s, self._query)
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
            catalog = await self._get_catalog()
        except SmartMannheimError as err:
            _LOGGER.error("Could not load station list: %s", err)
            return self._search_form({"base": "cannot_connect"})
        self._query = ""
        self._candidates = list(catalog.sensors)
        return await self.async_step_pick()

    async def async_step_pick(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        candidate_ids = {s["sensorId"] for s in self._candidates}

        if user_input is not None:
            selected_ids: list[str] = user_input[CONF_STATIONS]
            by_id = {s["sensorId"]: s for s in self._candidates}
            # Items inside the current match-set that were unchecked are
            # removed; items outside the current match-set stay as they are.
            for sid in list(self._accumulated.keys()):
                if sid in candidate_ids and sid not in selected_ids:
                    del self._accumulated[sid]
            for sid in selected_ids:
                if sid in by_id:
                    self._accumulated[sid] = by_id[sid]
            return await self.async_step_menu()

        catalog = await self._get_catalog()
        default = [sid for sid in self._accumulated if sid in candidate_ids]
        options = [
            SelectOptionDict(value=s["sensorId"], label=catalog.label(s))
            for s in sorted(self._candidates, key=catalog.sort_key)
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
                **_rate_placeholders(len(self._accumulated)),
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
            description_placeholders=_rate_placeholders(len(self._accumulated)),
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

    # v2: stations are official API sensors (see migration.py).
    VERSION = 2

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
            description_placeholders=_rate_placeholders(len(self._accumulated)),
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
