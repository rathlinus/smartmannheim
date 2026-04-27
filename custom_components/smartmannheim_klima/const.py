"""Constants for the Smart City Mannheim integration."""
from __future__ import annotations

from datetime import timedelta
from typing import Final

DOMAIN: Final = "smartmannheim_klima"

API_BASE: Final = "https://apps.mvvsmartcities.com/api"
DASHBOARD_TOKEN: Final = "268b1470-a99b-4244-942e-d8fbdba033ab"
ACCOUNT_ID: Final = "6233165a7faac33eade2c539"
APP_ID: Final = DASHBOARD_TOKEN
MAP_TILE_ID: Final = "3a1e9ee5-9d72-4727-8832-9d46fc8c0395"

CONF_STATIONS: Final = "stations"
CONF_QUERY: Final = "query"

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
        "num_digits": 1,
    },
    {
        "key": MEAS_HUMIDITY,
        "timeseries_id": "de1bedd9-1b2c-40ea-8434-ca7895362ef3",
        "tile_id": "930d05a5-cefe-4dda-9190-db40cf82abbc",
        "display_name": "Klimasensor, Luftfeuchtigkeit",
        "num_digits": 0,
    },
    {
        "key": MEAS_WIND,
        "timeseries_id": "af7132bc-38e7-425f-8695-a8a94701a4b6",
        "tile_id": "13c34302-b5e3-433c-8602-aed08d7cf390",
        "display_name": "Durchschn. Windgeschwindigkeit",
        "num_digits": 1,
    },
)
