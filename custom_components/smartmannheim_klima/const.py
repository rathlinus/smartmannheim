"""Constants for the Smart City Mannheim integration."""
from __future__ import annotations

from datetime import timedelta
from typing import Final

DOMAIN: Final = "smartmannheim_klima"

# --- Existing climate-network dashboard ---------------------------------
API_BASE: Final = "https://apps.mvvsmartcities.com/api"
DASHBOARD_TOKEN: Final = "268b1470-a99b-4244-942e-d8fbdba033ab"
ACCOUNT_ID: Final = "6233165a7faac33eade2c539"
APP_ID: Final = DASHBOARD_TOKEN
MAP_TILE_ID: Final = "3a1e9ee5-9d72-4727-8832-9d46fc8c0395"

CONF_STATIONS: Final = "stations"
CONF_QUERY: Final = "query"

# Toggles for the three "extra" data sources discovered via the dashboard SPA.
# All default to True so a fresh install gets pollen / AQI / DWD out of the box.
CONF_INCLUDE_POLLEN: Final = "include_pollen"
CONF_INCLUDE_AQI: Final = "include_aqi"
CONF_INCLUDE_DWD: Final = "include_dwd"

DEFAULT_SCAN_INTERVAL: Final = timedelta(minutes=10)
REQUEST_TIMEOUT: Final = 30

MEAS_TEMPERATURE: Final = "temperature"
MEAS_HUMIDITY: Final = "humidity"
MEAS_WIND: Final = "wind_speed"

MEASUREMENTS: Final = (
    {
        "key": MEAS_TEMPERATURE,
        "timeseries_id": "536a8e89-34c6-4a23-8bac-dec7ae840ee0",
        "tile_id": "b56d6160-6cf4-48fa-be5a-51581216d1a2",
        "display_name": "Klimasensor, Temperatur",
        "digits": 1,
        "digits_field": "numDigits",
    },
    {
        "key": MEAS_HUMIDITY,
        "timeseries_id": "de1bedd9-1b2c-40ea-8434-ca7895362ef3",
        "tile_id": "930d05a5-cefe-4dda-9190-db40cf82abbc",
        "display_name": "Klimasensor, Luftfeuchtigkeit",
        "digits": 0,
        "digits_field": "numDigits",
    },
    {
        "key": MEAS_WIND,
        "timeseries_id": "af7132bc-38e7-425f-8695-a8a94701a4b6",
        "tile_id": "13c34302-b5e3-433c-8602-aed08d7cf390",
        "display_name": "Durchschn. Windgeschwindigkeit",
        "digits": 1,
        "digits_field": "displayDigits",
    },
)


# --- Pollen forecast (DWD via Smart Mannheim) ---------------------------
# Different backend host + account, simpler POST shape (no tile / entity).
POLLEN_API_BASE: Final = "https://dashboard.mvvsmartcities.com/api"
POLLEN_ACCOUNT_ID: Final = "62f26d3370b56edf0044eaf2"
POLLEN_TOKEN: Final = "26784a43-7be8-446c-a4a5-b960025f5939"
POLLEN_DEVICE_ID: Final = "pollen_mannheim"

# (key, timeseries_id, display_name)
# `display_name` mirrors what the SPA sends — the backend keys responses on it.
POLLEN_SERIES: Final = (
    {"key": "alder",    "timeseries_id": "e35d2aa3-9fe4-4fbc-9f2e-53711c155623", "display_name": "Pollenflug Gefahrenindex (DWD), Erle"},
    {"key": "birch",    "timeseries_id": "63b2802c-6ced-47b1-a759-c03efcdd8d5f", "display_name": "Pollenflug Gefahrenindex (DWD), Birke"},
    {"key": "hazel",    "timeseries_id": "3d8af28f-5896-4305-b908-c981f2892d9b", "display_name": "Pollenflug Gefahrenindex (DWD), Hasel"},
    {"key": "ash",      "timeseries_id": "396ecf7f-cf24-4773-8952-e8eb4d1290fe", "display_name": "Pollenflug Gefahrenindex (DWD), Esche"},
    {"key": "grasses",  "timeseries_id": "d6227427-43b6-45c4-9a24-1ff501e5537c", "display_name": "Pollenflug Gefahrenindex (DWD), Graeser"},
    {"key": "rye",      "timeseries_id": "8f55eedd-f019-4fe5-9108-96f0826a18a2", "display_name": "Pollenflug Gefahrenindex (DWD), Roggen"},
    {"key": "mugwort",  "timeseries_id": "13454090-b60e-47d0-8a49-935552cb1649", "display_name": "Pollenflug Gefahrenindex (DWD), Beifuss"},
    {"key": "ragweed",  "timeseries_id": "ea8911d6-05f4-423e-b656-e7ee78385518", "display_name": "Pollenflug Gefahrenindex (DWD), Ambrosia"},
)


# --- Luftqualitätsindex (UBA air quality) -------------------------------
AQI_API_BASE: Final = "https://apps.mvvsmartcities.com/api"
AQI_ACCOUNT_ID: Final = "5f6c5c377f1cff0011096a73"
AQI_TOKEN: Final = "luftqualitaetsindex_mannheim"

# One AQI device per measurement station. Each station entry holds the
# entityId expected by the dashboarddata endpoint plus all four indicators
# (LQI, PM10, PM2.5, NO2) with their tile pairings.
AQI_STATIONS: Final = (
    {
        "key": "friedrichsring",
        "name": "Mannheim Friedrichsring",
        "entity_id": "33df4c51-c02e-4cb4-8372-36340e36329c",
        "measurements": (
            {"key": "lqi",  "timeseries_id": "ba078a34-c4ea-4413-a095-b6e528a7bfce", "tile_id": "cedcb9bd-43f8-412d-9065-a35e1039de48", "display_name": "UBA - Mannheim Friedrichsring, Luftqualitätsindex",     "digits": 2, "digits_field": "numDigits"},
            {"key": "pm10", "timeseries_id": "6b578132-4720-43de-b6f7-815fede345d5", "tile_id": "9b5a71a3-1f5e-474b-9679-e512b183b715", "display_name": "UBA - Mannheim Nord, Feinstaub PM₁₀",                 "digits": 0, "digits_field": "numDigits"},
            {"key": "pm25", "timeseries_id": "dae5ff37-89b3-4055-b170-441b20957fe9", "tile_id": "af753dcf-f714-4db1-aeb9-5f8026d9be25", "display_name": "UBA - Mannheim Friedrichsring, Feinstaub PM₂,₅",      "digits": 0, "digits_field": "numDigits"},
            {"key": "no2",  "timeseries_id": "de25fb29-a688-4e02-9439-3fe047a717e2", "tile_id": "486286c3-5a13-489b-8657-39e735d43929", "display_name": "UBA - Mannheim Friedrichsring, Stickstoffdioxid NO₂", "digits": 0, "digits_field": "numDigits"},
        ),
    },
)


# --- Klimadaten DWD-Station Mannheim -----------------------------------
DWD_API_BASE: Final = "https://dashboard.mvvsmartcities.com/api"
DWD_ACCOUNT_ID: Final = "6233165a7faac33eade2c539"
DWD_TOKEN: Final = "fcea867d-8c40-4507-bb88-43ced0dbcbf5"
DWD_DEVICE_ID: Final = "dwd_station_mannheim"

# Four metrics from the official DWD station 0301-001-11. Wind speed is
# a derived ("computeddata") series; the rest are raw timeseries.
DWD_SERIES: Final = (
    {"key": "temperature",   "timeseries_id": "80decc91-8945-4fea-8e47-2c40afa8a1b4", "display_name": "0301-001-11, mittl. Temperatur"},
    {"key": "humidity",      "timeseries_id": "354e7ba2-4adc-4d2e-ad61-c76e935809e1", "display_name": "0301-001-11, mittl. rel. Feuchtigkeit"},
    {"key": "wind_speed",    "timeseries_id": "5c93debd-0f12-43a7-9f9c-aa6622fb4129", "display_name": "mittl. Windgeschwindigkeit DWD"},
    {"key": "precipitation", "timeseries_id": "5c9f6eff-d6cd-4132-a9fd-0bc96c16ac28", "display_name": "0301-001-11, mittl. Niederschlag"},
)
