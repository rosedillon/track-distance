"""A synthetic track network and station list.

The real Network Rail track model is a licensed 60 MB shapefile, so
these fixtures build a tiny one instead. It uses British National Grid
coordinates in round metres, so the expected distances are exact::

      D (1000, 1000)
      |
    1000 m
      |
      A ----1000 m---- B ----1000 m---- C
  (0, 0)         (1000, 0)        (2000, 0)

    S (5000, 5000) --200 m-- (5200, 5000)      <- disconnected stub

Station coordinates are made by projecting those grid points back to
latitude and longitude, so the tests go through the real projection
code.

Stations:

* ``AAA``, ``BBB``, ``CCC``, ``DDD`` sit exactly on the network nodes.
* ``NEA`` sits 30 m from B, to check snapping tolerates an offset.
* ``STR`` sits beside the disconnected stub. Snapping has to move it
  onto the main network, or it has no routes at all.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import geopandas as gpd
import pytest
from shapely.geometry import LineString

if TYPE_CHECKING:
    import pathlib

BRITISH_NATIONAL_GRID = "EPSG:27700"
WGS84 = "EPSG:4326"

NODE_A = (0.0, 0.0)
NODE_B = (1000.0, 0.0)
NODE_C = (2000.0, 0.0)
NODE_D = (1000.0, 1000.0)
STUB_START = (5000.0, 5000.0)
STUB_END = (5200.0, 5000.0)

# Station code -> British National Grid position.
STATION_GRID_POSITIONS: dict[str, tuple[float, float]] = {
    "AAA": NODE_A,
    "BBB": NODE_B,
    "CCC": NODE_C,
    "DDD": NODE_D,
    "NEA": (1000.0, 30.0),
    "STR": (5010.0, 5010.0),
}


@pytest.fixture
def track_shapefile(tmp_path: pathlib.Path) -> pathlib.Path:
    """A shapefile of the toy network, including a disconnected stub."""
    lines = [
        LineString([NODE_A, NODE_B]),
        LineString([NODE_B, NODE_C]),
        LineString([NODE_B, NODE_D]),
        # A longer duplicate of A-B: the shorter one must win.
        LineString([NODE_A, (500.0, 400.0), NODE_B]),
        # Not connected to anything else.
        LineString([STUB_START, STUB_END]),
    ]
    frame = gpd.GeoDataFrame(geometry=lines, crs=BRITISH_NATIONAL_GRID)
    path = tmp_path / "tracks.shp"
    frame.to_file(path)
    return path


@pytest.fixture
def stations_csv(tmp_path: pathlib.Path) -> pathlib.Path:
    """Station latitudes and longitudes, projected from the grid."""
    codes = list(STATION_GRID_POSITIONS)
    grid = gpd.GeoSeries(
        gpd.points_from_xy(
            [position[0] for position in STATION_GRID_POSITIONS.values()],
            [position[1] for position in STATION_GRID_POSITIONS.values()],
        ),
        crs=BRITISH_NATIONAL_GRID,
    ).to_crs(WGS84)

    path = tmp_path / "stations.csv"
    rows = ["crsCode,lat,long"]
    rows += [
        f"{code},{point.y:.8f},{point.x:.8f}" for code, point in zip(codes, grid, strict=True)
    ]
    path.write_text("\n".join(rows) + "\n")
    return path


@pytest.fixture
def calculator(track_shapefile: pathlib.Path, stations_csv: pathlib.Path):
    from track_distance import TrackDistanceCalculator

    return TrackDistanceCalculator(track_shapefile, stations_csv)
