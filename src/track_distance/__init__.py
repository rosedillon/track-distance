"""Distance between rail stations along the track.

Build the calculator once, then query it::

    from track_distance import TrackDistanceCalculator

    calc = TrackDistanceCalculator("tracks.shp", "stations.csv")
    calc.calculate_distance("MAN", "LDS", "miles")  # 42.34
"""

from __future__ import annotations

from track_distance.calculator import (
    DEFAULT_INPUT_CRS,
    DEFAULT_WORKING_CRS,
    NoRouteError,
    StationNotFoundError,
    TrackDistanceCalculator,
)
from track_distance.stations import StationSource
from track_distance.units import convert_metres

__all__ = [
    "DEFAULT_INPUT_CRS",
    "DEFAULT_WORKING_CRS",
    "NoRouteError",
    "StationNotFoundError",
    "StationSource",
    "TrackDistanceCalculator",
    "convert_metres",
]

__version__ = "0.1.0"
