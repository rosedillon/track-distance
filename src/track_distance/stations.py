"""Where the station coordinates come from."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import pathlib


@dataclass(frozen=True, slots=True)
class StationSource:
    """A CSV of station locations, and which columns to read from it.

    The defaults match the column names in the widely shared National
    Rail station list (``crsCode``, ``lat``, ``long``). Any CSV with a
    station code, latitude and longitude will do.
    """

    path: pathlib.Path
    code_column: str = "crsCode"
    latitude_column: str = "lat"
    longitude_column: str = "long"

    @property
    def columns(self) -> list[str]:
        return [self.code_column, self.latitude_column, self.longitude_column]
