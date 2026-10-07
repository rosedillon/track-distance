from __future__ import annotations

import pytest

from track_distance import convert_metres
from track_distance.units import METRES_PER_MILE


def test_metres_are_unchanged() -> None:
    assert convert_metres(1234.5, "metres") == pytest.approx(1234.5)


def test_kilometres() -> None:
    assert convert_metres(2500, "km") == pytest.approx(2.5)


def test_miles_use_the_international_mile() -> None:
    assert convert_metres(METRES_PER_MILE, "miles") == pytest.approx(1.0)
    assert convert_metres(1609.344, "miles") == pytest.approx(1.0)


def test_default_is_kilometres() -> None:
    assert convert_metres(1000) == pytest.approx(1.0)


def test_unknown_unit_lists_the_valid_ones() -> None:
    with pytest.raises(ValueError, match="miles"):
        convert_metres(1000, "furlongs")
