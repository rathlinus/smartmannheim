# Smart City Mannheim

A Home Assistant integration for the public [Smart City Mannheim](https://smartmannheim.de/) data platform — climate stations, pollen forecast, air quality and the official DWD weather station, all directly in your smart home.

---

## What's inside

- **Climate measurement network** — pick any of the ~130 city-wide stations; each becomes a HA device with Temperature, Humidity and Wind speed sensors plus a GPS pin on the map.
- **Pollenflug (DWD)** — 8 pollen species (alder, birch, hazel, ash, grasses, rye, mugwort, ragweed) with the official DWD danger index.
- **Luftqualitätsindex (UBA)** — air-quality monitoring station at Mannheim Friedrichsring: LQI, PM₁₀, PM₂,₅, NO₂.
- **Klimadaten DWD-Station Mannheim** — the official German Weather Service station: Temperature, Humidity, Wind speed, Precipitation.
- **Catalog-aware** — bundled snapshot of the 211-station metadata catalog. Stations only get sensors they actually have installed, and devices are enriched with altitude (m NN), Local Climate Zone, commissioning date and per-sensor measurement heights.

All three extra data sources (Pollen, AQI, DWD-Station) are **enabled by default** on a fresh install and can be toggled per-entry under *Configure → Zusätzliche Datenquellen*.

---

## Installation

### Via HACS (recommended)

1. Open HACS → **Integrations** → menu top right → **Custom repositories**
2. Enter URL `https://github.com/rathlinus/smartmannheim.git`, Category: **Integration**
3. Search for *Smart City Mannheim* and install
4. Restart Home Assistant

### Manually

1. Download this repository as a ZIP
2. Copy `custom_components/smartmannheim_klima` to your HA `config/custom_components/`
3. Restart Home Assistant

---

## Setup

1. **Settings → Integrations → Add Integration → Smart City Mannheim**
2. Enter a street, district or station code (e.g. `Feudenheim`, `Innenstadt`, `T-016`); leave empty to list all stations
3. Select matching station(s)
4. Add more stations or finish

That's it — pollen, air quality and the DWD-Station turn on automatically.

### Changing the selection later

**Configure** on the integration tile shows a small menu:

| Option | What it does |
|---|---|
| *Stationen verwalten* | Search/select climate stations exactly like first setup |
| *Zusätzliche Datenquellen* | Toggle Pollenflug, Luftqualitätsindex and DWD-Station on/off |

---

## Entities

### Per selected climate station

The integration only creates entities for sensors the catalog says are physically installed at that station. So a station with `TT/RF` but no `FF` gets two sensors instead of three.

| Entity | Type | Unit | Notes |
|---|---|---|---|
| Temperatur | `sensor` | °C | If TT installed |
| Luftfeuchtigkeit | `sensor` | % | If RF installed |
| Windgeschwindigkeit | `sensor` | m/s | If FF installed |
| Station location | `device_tracker` | GPS | Static pin, always present |

Each sensor carries the following attributes from the metadata catalog (when available):

```
measured_at:            2026-05-28T13:50:00+02:00
measurement_height_m:   3
sensor_type_accuracy:   2/1
catalog_id:             T-016
station_id:             001
code_string:            0101-001-21
altitude_m:             96
commissioned_at:        2022-04-01
local_climate_zone:     02/01
station_type_code:      10
station_quality_code:   2
latitude / longitude:   (geo)
```

The device card itself uses the catalog data too — model becomes e.g. `Klimamessstation (Höhe 96 m NN)` and the commissioning date appears as the hardware version.

### Pollenflug Mannheim (single device)

8 sensors, one per species — Erle, Birke, Hasel, Esche, Gräser, Roggen, Beifuß, Ambrosia. State is the DWD danger index (0 / 0–1 / 1 / 1–2 / 2 / 2–3 / 3), exposed as a number (range values become their midpoint, e.g. `"1-2"` → `1.5`). Attributes:

- `level` — German label (`keine`, `gering`, `mittel`, `hoch`…)
- `level_raw` — the original value as returned by the API (so ranges aren't lost)

### Luftqualität Mannheim Friedrichsring (single device)

| Entity | Unit | Device class |
|---|---|---|
| Luftqualitätsindex | (1–5) | — (`level` attr: `sehr gut`/`gut`/`mäßig`/`schlecht`/`sehr schlecht`) |
| Feinstaub PM₁₀ | µg/m³ | `pm10` |
| Feinstaub PM₂,₅ | µg/m³ | `pm25` |
| Stickstoffdioxid NO₂ | µg/m³ | `nitrogen_dioxide` |

### DWD-Station Mannheim (single device)

| Entity | Unit | Device class |
|---|---|---|
| Temperatur | °C | `temperature` |
| Luftfeuchtigkeit | % | `humidity` |
| Windgeschwindigkeit | m/s | `wind_speed` |
| Niederschlag | mm | `precipitation` |

---

## Requirements

- Home Assistant ≥ 2024.4.0
- Internet connection (the public APIs at `apps.mvvsmartcities.com` and `dashboard.mvvsmartcities.com`)
- No credentials — the dashboards are publicly readable

---

## Update interval

The integration polls every **10 minutes** (`DEFAULT_SCAN_INTERVAL` in `const.py`). The backends only refresh every 10 minutes themselves, so a faster poll wouldn't gain you new values.

When a station's extras are disabled, no requests are made for them — turning Pollen off cuts 8 requests per cycle, AQI cuts 4, DWD cuts 4. Fan-out is capped at 4 concurrent requests to be polite to the shared backend.

---

## API usage

The integration talks to four different public dashboards, each on its own tenant:

| Source | Host | Endpoint | accountId |
|---|---|---|---|
| Climate network | `apps.mvvsmartcities.com` | `POST /api/dashboarddata` | `6233165a7faac33eade2c539` |
| Pollenflug | `dashboard.mvvsmartcities.com` | `POST /api/timeseriesanalyticsindicator` | `62f26d3370b56edf0044eaf2` |
| Luftqualitätsindex | `apps.mvvsmartcities.com` | `POST /api/dashboarddata` | `5f6c5c377f1cff0011096a73` |
| DWD-Station Mannheim | `dashboard.mvvsmartcities.com` | `POST /api/timeseriesanalyticsindicator` | `6233165a7faac33eade2c539` |

Each dashboard's public token is passed as the `id` query parameter. No personal authentication; all tokens are hardcoded in `const.py` and are the same the public SPA uses.

Example climate request:

```http
POST https://apps.mvvsmartcities.com/api/dashboarddata?accountId=6233165a7faac33eade2c539&id=268b1470-a99b-4244-942e-d8fbdba033ab
Content-Type: application/json

{ ...request body... }
```

The APIs are publicly readable but **not officially documented** — the provider can change shape or revoke access at any time.

---

## Station metadata catalog

`custom_components/smartmannheim_klima/station_metadata.json` is a snapshot of the official Mannheim climate-network metadata catalog (211 stations × 80+ attributes per station). It powers two things:

1. **Sensor presence filtering** — the catalog's TT/RF/FF flags tell us which sensors are actually wired at each station, so the integration doesn't create permanently-unavailable entities.
2. **Device enrichment** — altitude, Local Climate Zone, commissioning date and per-sensor measurement heights are surfaced on the HA device & entity attributes.

The snapshot is static. To refresh it after the upstream catalog changes, re-run `build_station_metadata.py` in the repo root against the latest xlsx and commit the regenerated JSON.

---

## License

MIT for the integration code.

Data © Stadt Mannheim / Smart City Mannheim GmbH, provided under the [Data License Germany – Attribution – Version 2.0](https://www.govdata.de/dl-de/by-2-0). Air-quality data is from the *Umweltbundesamt*; pollen data is from the *Deutscher Wetterdienst*.
