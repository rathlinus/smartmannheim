# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/)
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.3.0] - Unreleased
### Changed — official climate API
- Climate stations now use the official Smart City Mannheim API
  (`api.smartmannheim.de`) instead of the dashboard backend. You pick
  individual sensors (climate or wind); sensors at the same location
  share one device.
- **Rate limit:** the API allows 30 requests per hour, so climate
  sensors update every `max(10, 2 × sensors)` minutes — 5 sensors every
  10 minutes, 10 every 20. The setup screens show the interval, each
  sensor has an `update_interval_min` attribute, and a Repairs notice
  appears with more than 5 sensors.
- Pollen, air quality and the DWD station stay on the dashboard backends,
  with their own 10-minute coordinator.
- Search by sensor code or street; the list is sorted by distance from
  home. Street addresses come from a bundled snapshot because the API has
  none.
- Existing 0.2.x installs migrate automatically (config entry version 2):
  old stations are mapped to their official sensors and entities keep
  their entity IDs and history. A notification lists the new interval and
  any stations that couldn't be matched.
- A failed or empty fetch for one climate sensor keeps its last values
  (instead of blanking it for a whole interval) and logs the reason once
  as a warning. Values older than `max(60, 3 × interval)` minutes turn
  unavailable.

### Added
- New climate entities: air pressure, wind direction (enabled), dew
  point, min/max temperature, irradiance, gusts and gust direction
  (disabled by default).
- `sensor_snapshot.json` and `scripts/build_sensor_snapshot.py`.
- Test suite (pytest-homeassistant-custom-component) and a GitHub
  Actions workflow running pytest, ruff, hassfest and HACS validation.

### Fixed
- DWD-Station wind speed was always unavailable: the series is now
  requested as `computeddata` instead of `timeseries`.
- Deselecting every station in the options flow no longer brings the
  original stations back.
- Choosing "Fertig" without any selected station no longer drops the
  user back into a broken menu; the option is hidden until something is
  picked.

### Changed
- Deselected stations and disabled data sources are removed together
  with their devices and entities.
- Shared config/options flow steps, device info and option helpers are
  no longer duplicated.
- README: updated setup steps and metadata-catalog notes.

## [0.2.1] - 2026-05-28
### Added
- "Alle Stationen anzeigen" / "Show all stations" button on the first
  setup screen and on the follow-up "Weitere Stationen hinzufügen?"
  menu, so the search step can be skipped entirely.
- Same option exposed at the top of the options flow.

### Changed
- First config-flow step is now a menu (Suchen / Alle anzeigen) instead
  of a search form, and the search-form copy no longer mentions
  "leave empty to list all stations".

## [0.2.0] - 2026-05-28
### Added
- Three new toggleable data sources, enabled by default for fresh installs:
  Pollenflug (DWD), Luftqualitätsindex Mannheim Friedrichsring (UBA) and
  Klimadaten DWD-Station Mannheim.
- Bundled 211-station metadata catalog snapshot
  (`station_metadata.json`).
- Station catalog is used to skip Temperature/Humidity/Wind sensors at
  stations that physically don't have them.
- Device cards and entity attributes now expose altitude, Local Climate
  Zone, commissioning date and per-sensor measurement heights when
  metadata is available.
- Options flow now has a top-level menu: "Stationen verwalten" vs
  "Zusätzliche Datenquellen" for toggling the new extras.
- `.gitignore` for Python build artefacts and macOS detritus.

### Changed
- `SmartMannheimCoordinator` data shape: top-level keys now are
  `stations`, `pollen`, `aqi`, `dwd` (was a bare locationId → readings
  map). Existing options/data on disk are unchanged.

## [0.1.2] - 2026-04-27
### Added
- Added documentation and issue tracker to manifest.

### Changed
- Renamed brands folder to brand for Home Assistant compatibility.

## [0.1.1] - 2026-04-27
### Added
- Initial changelog structure.
- Added section about API polling interval to README.
- Added details about API usage and authentication to README.
- Added icon for the integration in the brands folder.

### Changed
- Switched German translation from formal "Sie" to informal "du" for a friendlier tone.
- Fixed license reference in README to "Data License Germany – Attribution – Version 2.0".
- Unified update interval for all sensors to 10 minutes in the README entities table.
- Renamed integration from "Smart Mannheim Klimamessnetz" to "Smart City Mannheim".

## [0.1.0] - 2026-04-24
### Added
- First public release.