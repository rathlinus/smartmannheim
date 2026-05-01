# Smart City Mannheim

A Home Assistant integration for the [Mannheim City Climate Network](https://smartmannheim.de/datenartikel/klimamessnetz-mannheim/) – over 100 measurement stations across the city, directly in your smart home.

---

## Features

- **3 sensors per station** – Temperature (°C), Humidity (%), Wind speed (m/s)
- **GPS pin on the map** – each station appears as a Device Tracker with its real coordinates
- **Multiple stations at once** – search and select as many stations as you like via the UI
- **Standard HA Device Classes** – works out of the box with Energy Dashboard, Automations, and History

---

## Installation

### Via HACS (recommended)

1. Open HACS → **Integrations** → Menu top right → **Custom repositories**
2. Enter URL `https://github.com/rathlinus/smartmannheim.git`, Category: **Integration**
3. Search for and install the integration
4. Restart Home Assistant

### Manually

1. Download this repository as a ZIP
2. Copy folder `custom_components/smartmannheim_klima` to your HA directory `config/custom_components/`
3. Restart Home Assistant

---

## Setup

1. **Settings → Integrations → Add Integration → Smart City Mannheim**
2. Enter a street name or district (e.g., `Feudenheim`, `Innenstadt`, `Käfertal`)
3. Select matching station(s) from the list
4. Add more stations or finish

You can always adjust stations under **Settings → Integrations → Smart City Mannheim → Configure**.

---

## Entities

For each selected station, the following entities are created:

| Entity | Type | Unit | Update |
|---|---|---|---|
| Temperature | `sensor` | °C | 10 min |
| Humidity | `sensor` | % | 10 min |
| Wind speed | `sensor` | m/s | 10 min |
| Station location | `device_tracker` | GPS | static |

All sensors have `measured_at` as an additional attribute (timestamp of the last measurement). The Device Tracker places a pin on the map with the actual station coordinates – ready to use with the Lovelace Map Card.

---

## Requirements

- Home Assistant ≥ 2024.4.0
- Internet connection (the API runs at `apps.mvvsmartcities.com`)
- No credentials required – the API is publicly readable

---

## Update Interval (Polling)

The integration polls the API every **10 minutes** by default (polling interval). This ensures new measurements are regularly fetched for all selected stations. The sensors in Home Assistant show the last available value.

- The interval is set in the source code as `DEFAULT_SCAN_INTERVAL` (10 minutes).
- Individual sensors (e.g., temperature, humidity) may update more frequently depending on the data source, but the backend delivers new values at most every 10 minutes.

---

## API Usage & Authentication

The integration fetches data from the MVV Smart Cities platform's internal Dashboard API:

- **Base URL:** `https://apps.mvvsmartcities.com/api/dashboarddata`
- **Authentication:** No personal login is required. Instead, a fixed, public "Dashboard Token" is passed as the query parameter `id`. This token is hardcoded in the source and serves as a shared read access.
- **Additional parameters:** `accountId` and `appId` are also set automatically.
- **Example request:**

	```http
	POST https://apps.mvvsmartcities.com/api/dashboarddata?accountId=<ACCOUNT_ID>&id=<DASHBOARD_TOKEN>
	Content-Type: application/json
	{ ...Request-Body... }
	```

**Note:** The API is publicly readable but not officially documented. Changes by the provider are possible at any time.

---

## License

MIT – Data © Stadt Mannheim / Smart City Mannheim GmbH, provided under the [Data License Germany – Attribution – Version 2.0](https://www.govdata.de/dl-de/by-2-0).