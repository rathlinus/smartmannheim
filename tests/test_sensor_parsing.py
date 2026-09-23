"""Value parsing helpers in the sensor platform."""
from __future__ import annotations

import pytest

from custom_components.smartmannheim_klima.sensor import (
    _lqi_label,
    _parse_pollen_indicator,
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("0", (0.0, "0")),
        ("0-1", (0.5, "0-1")),
        ("2-3", (2.5, "2-3")),
        (3, (3.0, "3")),
        ("", (None, None)),
        (None, (None, None)),
        ("x", (None, "x")),
        ("a-b", (None, "a-b")),
    ],
)
def test_parse_pollen_indicator(raw, expected):
    assert _parse_pollen_indicator(raw) == expected


@pytest.mark.parametrize(
    ("value", "label"),
    [
        (None, None),
        (0.4, "sehr gut"),
        (1.0, "sehr gut"),
        (2, "gut"),
        (3.99, "mäßig"),
        (4.5, "schlecht"),
        (5, "sehr schlecht"),
        (7, "sehr schlecht"),
    ],
)
def test_lqi_label(value, label):
    assert _lqi_label(value) == label
