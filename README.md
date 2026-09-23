# Smart City Mannheim

A Home Assistant integration for the public [Smart City Mannheim](https://smartmannheim.de/) data platform — climate stations, pollen forecast, air quality and the official DWD weather station, all directly in your smart home.

---

## What's inside

- **Climate measurement network** — via the [official Smart City Mannheim API](https://api.smartmannheim.de/doc). Pick any of the ~830 climate and wind sensors at ~440 locations: temperature, humidity, air pressure, dew point, irradiance, wind speed, gusts and direction. Sensors at the same location share one HA device with a GPS pin on the map.
- **Pollenflug (DWD)** — 8 pollen species (alder, birch, hazel, ash, grasses, rye, mugwort, ragweed) with the official DWD danger index.
- **Luftqualitätsindex (UBA)** — air-quality monitoring station at Mannheim Friedrichsring: LQI, PM₁₀, PM₂,₅, NO₂.
- **Klimadaten DWD-Station Mannheim** — the official German Weather Service station: Temperature, Humidity, Wind speed, Precipitation.
- **Catalog-aware** — bundled snapshot of the 211-station metadata catalog enriches devices with altitude (m NN), Local Climate Zone, commissioning date and per-sensor measurement heights (where the sensor is in the catalog).

All three extra data sources (Pollen, AQI, DWD-Station) are **enabled by default** on a fresh install and can be toggled per-entry under *Configure → Zusätzliche Datenquellen*.

> **⚠️ Rate limit:** the official climate API allows **30 requests per hour**, and every selected sensor needs one request per update. Up to **5 sensors** update every 10 minutes; more sensors stretch the interval (see [Update interval](#update-interval)). A station with temperature *and* wind counts as **2 sensors**. Pollen, air quality and the DWD station are not affected.

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
2. Choose **Nach Sensorcode oder Straße suchen** and enter a sensor code or street (e.g. `0101-001`, `T-050`, `Dammstraße`) — or choose **Alle Sensoren anzeigen** to skip the search
3. Select sensor(s). The list is sorted by distance from your home, and each entry shows code, type (*Klima* / *Wind*), street (if known) and distance, e.g. `0101-001-21 · Klima · 2,3 km`. Climate and wind sensors of one station are listed next to each other; pick both to get all values of that station.
4. Add more sensors or finish. Every step shows how often your selection will update.

That's it — pollen, air quality and the DWD-Station turn on automatically.

### Changing the selection later

**Configure** on the integration tile shows a small menu:

| Option | What it does |
|---|---|
| *Sensoren suchen* / *Alle Sensoren anzeigen* | Search/select climate sensors exactly like first setup |
| *Zusätzliche Datenquellen* | Toggle Pollenflug, Luftqualitätsindex and DWD-Station on/off |

Deselected sensors and disabled data sources are removed together with their devices and entities. You can also deselect every sensor and keep only the extra data sources.

### Upgrading from 0.2.x

0.3.0 moves the climate stations from the dashboard backend to the official API. Existing installs are **migrated automatically** on the first start:

- every old station is mapped to its official sensors (by the sensor codes in the dashboard name, else by position) — 418 of the 419 dashboard stations map;
- only the roles you actually had entities for are carried over (a station without a wind entity doesn't start costing a wind request);
- entity IDs stay the same, so **history, dashboards and automations keep working**; only the internal unique IDs change;
- the mapping ships with the integration, so migration also works while the API is unreachable.

A notification summarises the result and your new update interval. Stations that couldn't be matched are listed there and removed. Back up your `config/.storage` folder before upgrading if you want to be able to roll back.

---

## Entities

### Per selected climate sensor

Entities are created from the parameters the API lists for the sensor type. Sensors at the same position (typically one climate + one wind sensor) share one device, named after the street (if known) or the sensor codes; the codes are shown as the device's serial number.

| Entity | Unit | Sensor type | Enabled by default |
|---|---|---|---|
| Temperatur | °C | Klima | ✅ |
| Luftfeuchtigkeit | % | Klima | ✅ |
| Luftdruck | hPa | Klima | ✅ |
| Globalstrahlung, Globalstrahlung (Maximum) | W/m² | Klima | — |
| Taupunkt, Temperatur (Minimum/Maximum) | °C | Klima | — |
| Windgeschwindigkeit | m/s | Wind | ✅ |
| Windrichtung | ° | Wind | ✅ |
| Windgeschwindigkeit (Minimum), Windböe (1 s / 3 s) | m/s | Wind | — |
| Böenrichtung | ° | Wind | — |
| Station location | GPS | — | ✅ (one `device_tracker` per location) |

Disabled entities can be enabled in the device page; they cost no extra requests (one request returns all values of a sensor). The API's `minIrradiation` (implausible values) and `precipitationTick` (undocumented) are not exposed.

Wind speeds are reported in m/s (they match the old dashboard values 1:1, and the city sensors' readings fit the DWD station's mast measurement). Home Assistant shows them in your unit system's default (km/h for metric) unless you change the entity's display unit.

Each sensor carries these attributes (catalog fields only when the sensor code is in the catalog):

```
sensor_id:              0004A30B00F72EED
sensor_name:            0101-001-21
update_interval_min:    10
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
| Windgeschwindigkeit | km/h | `wind_speed` |
| Niederschlag | mm | `precipitation` (latest 10-minute value) |
| Niederschlag heute | mm | `precipitation`, total since midnight, resets every night |

*Niederschlag heute* is summed by the backend from 00:00 (Mannheim time) until now, so Home Assistant's statistics also show daily and monthly totals. DWD data arrives about 45 minutes late, so rain shortly before midnight may only show up in the next day's total; right after midnight the value is 0 until the first data arrives.

---

## Requirements

- Home Assistant ≥ 2024.4.0
- Internet connection (`api.smartmannheim.de` for climate sensors; `apps.mvvsmartcities.com` and `dashboard.mvvsmartcities.com` for pollen, air quality and the DWD station)
- No credentials — all sources are publicly readable

---

## Update interval

**Climate sensors** follow the official API's limit of **30 requests per hour** (6 per sensor). Every update fetches each selected sensor once, so the interval is `max(10, 2 × sensors)` minutes:

| Selected sensors | Update interval |
|---|---|
| 1–5 | every 10 minutes |
| 6 | every 12 minutes |
| 8 | every 16 minutes |
| 10 | every 20 minutes |
| 15 | every 30 minutes |
| 20 | every 40 minutes |

The config and options flows show the interval for your current selection, each climate sensor exposes it as the `update_interval_min` attribute, and with more than 5 sensors a notice under **Settings → Repairs** explains the longer interval. The sensor list itself (limited to 4 calls per hour) is only fetched while you configure the integration and is cached for 15 minutes. Each Home Assistant restart or integration reload triggers one immediate update, so frequent restarts use up the hourly budget faster.

**Pollen, air quality and the DWD station** come from the dashboard backends and update every **10 minutes** (`DEFAULT_SCAN_INTERVAL` in `const.py`), independent of the climate sensors. The backends only refresh every 10 minutes themselves. Turning Pollen off cuts 8 requests per cycle, AQI cuts 4, DWD cuts 5. Fan-out is capped at 4 concurrent requests.

---

## API usage

| Source | Host | Endpoint | Auth |
|---|---|---|---|
| Climate sensors | `api.smartmannheim.de` ([docs](https://api.smartmannheim.de/doc)) | `GET /climate/sensors`, `GET /climate/measurements/{id}` | none (rate-limited) |
| Pollenflug | `dashboard.mvvsmartcities.com` | `POST /api/timeseriesanalyticsindicator` | public dashboard token, accountId `62f26d3370b56edf0044eaf2` |
| Luftqualitätsindex | `apps.mvvsmartcities.com` | `POST /api/dashboarddata` | public dashboard token, accountId `5f6c5c377f1cff0011096a73` |
| DWD-Station Mannheim | `dashboard.mvvsmartcities.com` | `POST /api/timeseriesanalyticsindicator` | public dashboard token, accountId `6233165a7faac33eade2c539` |

The climate API is official and documented. Pollen, air quality and the DWD station aren't part of it, so they still use the dashboard backends: each dashboard's public token (the same the public web app uses) is passed as the `id` query parameter and hardcoded in `const.py`. Those backends are **not officially documented** — the provider can change shape or revoke access at any time.

---

## Station metadata catalog

`custom_components/smartmannheim_klima/station_metadata.json` is a snapshot of the official Mannheim climate-network metadata catalog (211 stations × 80+ attributes per station). It enriches devices and entities with altitude, Local Climate Zone, commissioning date and per-sensor measurement heights. It is matched by sensor code, so it covers the `0101-…` sensors but only a few of the newer `23xxLH/LW` ones.

The snapshot is static and was generated from the official [Metadatenkatalog Klimamessnetz](https://www.smartmannheim.de/wp-content/uploads/2024/03/20240314_Metadatenkatalog_MA_Klimamessnetz.pdf) (xlsx edition). It is not refreshed automatically; after upstream catalog changes it has to be regenerated from the latest xlsx and committed.

### Sensor snapshot

`custom_components/smartmannheim_klima/sensor_snapshot.json` is generated by `scripts/build_sensor_snapshot.py` (usage in the script) and contains:

- the official sensor list (fallback for the 0.2 → 0.3 migration when the API is unreachable),
- street addresses from the old dashboard, keyed by location — the official API has none; they power address search and device names,
- the mapping from old dashboard stations to official sensors used by the migration.

---

## License

MIT for the integration code.

Data © Stadt Mannheim / Smart City Mannheim GmbH, provided under the [Data License Germany – Attribution – Version 2.0](https://www.govdata.de/dl-de/by-2-0). Air-quality data is from the *Umweltbundesamt*; pollen data is from the *Deutscher Wetterdienst*.
