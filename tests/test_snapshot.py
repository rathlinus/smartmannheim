"""The bundled snapshot must map (almost) every legacy dashboard station."""
from __future__ import annotations

import json
from pathlib import Path

from custom_components.smartmannheim_klima.official import normalize_sensors

from .common import load_fixture

SNAPSHOT = (
    Path(__file__).parent.parent
    / "custom_components/smartmannheim_klima/sensor_snapshot.json"
)


def test_snapshot_covers_dashboard_stations():
    snapshot = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    dashboard = load_fixture("dashboard_stations.json")
    legacy = snapshot["legacy"]
    mapped = [st for st in dashboard if st["locationId"] in legacy]
    assert len(mapped) >= 415, f"{len(mapped)}/{len(dashboard)} mapped"

    known = {s["sensorId"] for s in normalize_sensors(snapshot["api"])}
    for roles in legacy.values():
        assert {sid for sid in roles.values() if sid} <= known

    assert legacy["efa477a6-97b1-44a9-8002-488761a2efa9"] == {
        "climate": "0004A30B00F72EED",
        "wind": "0004A30B00F79967",
    }
