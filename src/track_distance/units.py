"""Distance unit conversion."""

from __future__ import annotations

from typing import Literal

Unit = Literal["metres", "km", "miles"]

# The international mile, as used for UK rail mileages.
METRES_PER_MILE = 1609.344

_DIVISORS: dict[str, float] = {
    "metres": 1.0,
    "km": 1000.0,
    "miles": METRES_PER_MILE,
}


def convert_metres(distance_metres: float, unit: Unit | str = "km") -> float:
    """Convert *distance_metres* into *unit*.

    >>> convert_metres(1609.344, "miles")
    1.0
    >>> convert_metres(2500, "km")
    2.5
    """
    try:
        return distance_metres / _DIVISORS[unit]
    except KeyError:
        raise ValueError(f"unit must be one of {sorted(_DIVISORS)}, got {unit!r}") from None
