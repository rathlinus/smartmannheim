"""Fixture loading shared by the tests."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from custom_components.smartmannheim_klima.official import normalize_sensors

FIXTURES = Path(__file__).parent / "fixtures"


def load_fixture(name: str) -> Any:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def sensors() -> list[dict[str, Any]]:
    """Normalised sensors from a trimmed real /climate/sensors response."""
    return normalize_sensors(load_fixture("sensors.json"))


def sensor(name: str) -> dict[str, Any]:
    return next(s for s in sensors() if s["name"] == name)
