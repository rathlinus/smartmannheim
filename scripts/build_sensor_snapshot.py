"""Build custom_components/smartmannheim_klima/sensor_snapshot.json.

Usage::

    curl -o sensors.json https://api.smartmannheim.de/climate/sensors
    curl -o dashboard_stations.json -X POST -H 'Content-Type: application/json' \\
      'https://apps.mvvsmartcities.com/api/dashboarddata?accountId=6233165a7faac33eade2c539&id=268b1470-a99b-4244-942e-d8fbdba033ab' \\
      -d '{"appId":"268b1470-a99b-4244-942e-d8fbdba033ab","dashboardTemplateTileId":"3a1e9ee5-9d72-4727-8832-9d46fc8c0395"}'
    python scripts/build_sensor_snapshot.py sensors.json dashboard_stations.json

The snapshot holds:
  * the official sensor list (offline fallback for the 0.2 → 0.3 migration),
  * street addresses from the legacy dashboard, keyed by location (the
    official API has none; they keep address search working),
  * ``legacy``: old dashboard ``locationId`` → official sensor per role.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PKG = ROOT / "custom_components" / "smartmannheim_klima"

spec = importlib.util.spec_from_file_location("official", PKG / "official.py")
official = importlib.util.module_from_spec(spec)
spec.loader.exec_module(official)


def _address(station: dict) -> str | None:
    text = " ".join((station.get("address") or "").split()).strip(" ,")
    return text or None


def main(sensors_path: str, dashboard_path: str) -> None:
    raw = json.loads(Path(sensors_path).read_text(encoding="utf-8"))
    dashboard = json.loads(Path(dashboard_path).read_text(encoding="utf-8"))
    sensors = official.normalize_sensors(raw)

    addresses: dict[str, str] = {}
    legacy: dict[str, dict[str, str | None]] = {}
    for st in dashboard:
        coords = (st.get("location") or {}).get("coordinates")
        addr = _address(st)
        if addr and coords:
            key = official.location_key({"sensorId": "", "coordinates": coords})
            addresses.setdefault(key, addr)
        roles = official.match_legacy_station(st.get("name"), coords, sensors)
        if any(roles.values()):
            legacy[st["locationId"]] = roles

    out = {
        "generated_at": date.today().isoformat(),
        "sources": [
            "https://api.smartmannheim.de/climate/sensors",
            "https://apps.mvvsmartcities.com/api/dashboarddata (map tile)",
        ],
        # Raw /climate/sensors shape; normalised on load (much smaller than
        # repeating every parameter list per sensor).
        "api": {
            "sensorCount": raw.get("sensorCount"),
            "sensors": [
                {k: s[k] for k in ("id", "name", "position", "paramSet") if k in s}
                for s in raw.get("sensors") or []
            ],
            "paramSets": raw.get("paramSets") or [],
        },
        "addresses": addresses,
        "legacy": legacy,
    }
    target = PKG / "sensor_snapshot.json"
    target.write_text(
        json.dumps(out, ensure_ascii=False, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    unmatched = [st.get("name") for st in dashboard if st["locationId"] not in legacy]
    print(f"{len(sensors)} sensors, {len(addresses)} addresses, "
          f"{len(legacy)}/{len(dashboard)} legacy stations mapped -> {target}")
    if unmatched:
        print("unmatched:", ", ".join(map(str, unmatched)))


if __name__ == "__main__":
    main(*sys.argv[1:3])
