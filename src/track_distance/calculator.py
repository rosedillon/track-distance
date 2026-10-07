"""Distance between stations along the track.

Straight-line distance between two stations is easy to work out and
usually wrong, because railways do not run in straight lines. This
measures along the rails.

A track model (a shapefile of every stretch of line) becomes a graph.
Each stretch of track is an edge weighted by its real length, and the
points where stretches meet are nodes. The distance between two points
is then an ordinary shortest-path search: networkx for a single route,
scipy for every station at once.

Stations are not points in the track model, so each station's latitude
and longitude is projected into the track model's coordinate system and
snapped to a nearby graph node, found through a KD-tree. That node
stands in for the station when routing. :meth:`_snap_stations` explains
which node is chosen.
"""

from __future__ import annotations

import itertools
import logging
import pathlib
from typing import TYPE_CHECKING, Any

import geopandas as gpd
import networkx as nx
import numpy as np
import pandas as pd
from scipy.sparse import csr_matrix
from scipy.sparse.csgraph import dijkstra
from scipy.spatial import KDTree
from shapely.geometry import MultiLineString, Point

from track_distance.stations import StationSource
from track_distance.units import Unit, convert_metres

if TYPE_CHECKING:
    from shapely.geometry.base import BaseGeometry

logger = logging.getLogger(__name__)

# How many nearby nodes to consider when snapping a station before
# giving up and taking the nearest regardless of whether it is
# connected to anything.
DEFAULT_SNAP_CANDIDATES = 12

DEFAULT_INPUT_CRS = "EPSG:4326"
DEFAULT_WORKING_CRS = "EPSG:27700"

# An edge key: the two node coordinates, sorted so it is
# direction-independent.
EdgeKey = tuple[tuple[float, float], tuple[float, float]]


class StationNotFoundError(KeyError):
    """A station code is not in the loaded station list."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(
            f"Station {code!r} is not in the station list. Check the code and that "
            "the CSV covers it."
        )


class NoRouteError(ValueError):
    """No path exists on the track network between two stations."""

    def __init__(self, origin: str, destination: str) -> None:
        super().__init__(
            f"No route on the track network between {origin} and {destination}. "
            "They are probably on separate, unconnected parts of the track model."
        )


class TrackDistanceCalculator:
    """Shortest distances along the track between stations.

    Building one reads the shapefile and builds the graph, which is
    where nearly all the time goes, so build it once and reuse it.
    Routes are cached in both directions, since track distance is
    symmetric.

    Parameters
    ----------
    track_shapefile
        A shapefile of track centre lines.
    stations
        Where station coordinates come from. A bare path is accepted and
        wrapped in a :class:`~track_distance.stations.StationSource`
        with default column names.
    input_crs
        The coordinate system the station latitudes/longitudes are in.
    working_crs
        The coordinate system to route in. Must be metre-based, since
        edge weights are geometry lengths. The default is the British
        National Grid.
    snap_candidates
        How many nearby nodes to consider when snapping a station.
    """

    def __init__(
        self,
        track_shapefile: pathlib.Path | str,
        stations: StationSource | pathlib.Path | str,
        *,
        input_crs: str = DEFAULT_INPUT_CRS,
        working_crs: str = DEFAULT_WORKING_CRS,
        snap_candidates: int = DEFAULT_SNAP_CANDIDATES,
    ) -> None:
        self.input_crs = input_crs
        self.working_crs = working_crs
        self._snap_candidates = snap_candidates
        self._cache: dict[tuple[str, str], tuple[float, list[Any], list[EdgeKey]]] = {}

        if not isinstance(stations, StationSource):
            stations = StationSource(path=pathlib.Path(stations))

        logger.info("Reading track model from %s", track_shapefile)
        self.tracks = gpd.read_file(track_shapefile)

        self._build_graph()
        self._load_stations(stations)

    def _build_graph(self) -> None:
        self.graph: nx.Graph[tuple[float, float]] = nx.Graph()

        for geometry in self.tracks.geometry:
            if geometry is None:
                continue
            for line in _as_linestrings(geometry):
                coordinates = list(line.coords)
                if len(coordinates) < 2:
                    continue

                # Only each line's two end points become nodes, joined
                # by one edge weighted by the line's real length. Track
                # segments meet end to end, so that is enough to route
                # across the network, and it keeps the graph far smaller
                # than one node per vertex.
                start, end = coordinates[0], coordinates[-1]
                weight = line.length

                existing = self.graph.get_edge_data(start, end)
                if existing is None:
                    self.graph.add_edge(start, end, weight=weight, geometry=line)
                elif weight < existing["weight"]:
                    # Two lines joining the same pair of points: keep
                    # the shorter.
                    existing["weight"] = weight
                    existing["geometry"] = line

        logger.info(
            "Built track graph: %d nodes, %d edges",
            self.graph.number_of_nodes(),
            self.graph.number_of_edges(),
        )

        self._nodes: list[tuple[float, float]] = list(self.graph.nodes())
        self._kdtree = KDTree(np.array(self._nodes)) if self._nodes else None

        # The same graph as a sparse matrix for distances_from, where
        # scipy's Dijkstra runs about 15 times faster than networkx's.
        self._node_index = {node: i for i, node in enumerate(self._nodes)}
        edges = np.array(
            [
                (self._node_index[a], self._node_index[b], data["weight"])
                for a, b, data in self.graph.edges(data=True)
            ]
        ).reshape(-1, 3)
        size = len(self._nodes)
        self._matrix = csr_matrix(
            (edges[:, 2], (edges[:, 0].astype(int), edges[:, 1].astype(int))),
            shape=(size, size),
        )

    def _load_stations(self, source: StationSource) -> None:
        """Read and project station coordinates, then snap them."""
        logger.info("Reading station coordinates from %s", source.path)
        frame = pd.read_csv(source.path, usecols=source.columns).dropna()

        points = gpd.points_from_xy(frame[source.longitude_column], frame[source.latitude_column])
        located = gpd.GeoDataFrame(frame, geometry=points, crs=self.input_crs)
        located = located.to_crs(self.working_crs)

        # .geometry holds Points here by construction; x/y live on
        # Point, not on the BaseGeometry the accessor is typed as.
        self.station_locations: dict[str, tuple[float, float]] = {
            str(code).strip().upper(): (float(x), float(y))
            for code, x, y in zip(
                located[source.code_column],
                located.geometry.x,
                located.geometry.y,
                strict=True,
            )
        }
        logger.info("Loaded %d station locations", len(self.station_locations))
        self._snap_stations()

    def _snap_stations(self) -> None:
        """Attach each station to the nearest *usable* node.

        A track model contains small disconnected fragments (sidings,
        stubs, digitising artefacts). A station beside one would snap
        onto it and become unreachable from everywhere else. Nothing
        raises an error when that happens; the station just has no
        routes, which looks downstream like a station nobody travels to.

        Candidates are therefore taken in order of distance and the
        first one on the largest connected component wins. Only if none
        of them is on it does the station take the nearest node
        regardless.
        """
        self._station_nodes: dict[str, tuple[float, float]] = {}
        if not self.station_locations or self._kdtree is None:
            return

        main_component: set[tuple[float, float]] = (
            max(nx.connected_components(self.graph), key=len) if self.graph else set()
        )
        neighbours = min(self._snap_candidates, len(self._nodes))
        coordinates = np.array(list(self.station_locations.values()))
        _, indices = self._kdtree.query(coordinates, k=neighbours)
        # query() drops the candidate axis entirely when k == 1,
        # returning shape (n_stations,) rather than (n_stations, 1).
        # atleast_2d would turn that into a single row of n, so reshape
        # explicitly.
        indices = np.asarray(indices).reshape(len(coordinates), -1)

        rerouted = []
        for code, candidate_indices in zip(self.station_locations, indices, strict=True):
            nearest = self._nodes[candidate_indices[0]]
            chosen = next(
                (
                    self._nodes[index]
                    for index in candidate_indices
                    if self._nodes[index] in main_component
                ),
                nearest,
            )
            if chosen != nearest:
                rerouted.append(code)
            self._station_nodes[code] = chosen

        if rerouted:
            logger.info(
                "Snapped %d station(s) past a disconnected track fragment onto the "
                "main network: %s",
                len(rerouted),
                ", ".join(sorted(rerouted)),
            )

    @property
    def stations(self) -> frozenset[str]:
        """Every station code that can be routed from or to."""
        return frozenset(self._station_nodes)

    def __contains__(self, code: str) -> bool:
        return str(code).strip().upper() in self._station_nodes

    def _node_for(self, code: str) -> tuple[float, float]:
        normalised = str(code).strip().upper()
        try:
            return self._station_nodes[normalised]
        except KeyError:
            raise StationNotFoundError(normalised) from None

    def _route(self, origin: str, destination: str) -> tuple[float, list[Any], list[EdgeKey]]:
        key = (origin, destination)
        if key in self._cache:
            return self._cache[key]

        start = self._node_for(origin)
        end = self._node_for(destination)
        try:
            path = nx.shortest_path(self.graph, source=start, target=end, weight="weight")
        except nx.NetworkXNoPath as error:
            raise NoRouteError(origin, destination) from error

        pairs = list(itertools.pairwise(path))
        edges = [self.graph[a][b] for a, b in pairs]
        # Sorting each pair makes the key direction-independent, so the
        # same physical stretch of track has one identity however it is
        # traversed.
        edge_keys: list[EdgeKey] = [tuple(sorted((a, b))) for a, b in pairs]  # type: ignore[misc]
        metres = sum(edge["weight"] for edge in edges)
        geometry = [edge["geometry"] for edge in edges]

        result = (metres, geometry, edge_keys)
        # Track distance is symmetric, so the reverse is known too.
        self._cache[key] = result
        self._cache.setdefault((destination, origin), result)
        return result

    def calculate_distance(self, origin: str, destination: str, unit: Unit | str = "km") -> float:
        """Distance along the track between two stations."""
        origin = str(origin).strip().upper()
        destination = str(destination).strip().upper()
        metres, _, _ = self._route(origin, destination)
        return convert_metres(metres, unit)

    def distances_from(self, origin: str, unit: Unit | str = "km") -> dict[str, float]:
        """Distance from one station to every station reachable from it.

        One shortest-path tree, which is far cheaper than calling
        :meth:`calculate_distance` once per destination. Unreachable
        stations are omitted rather than given an infinite distance.
        """
        start = self._node_index[self._node_for(origin)]
        lengths = dijkstra(self._matrix, directed=False, indices=start)
        distances = {}
        for code, node in self._station_nodes.items():
            metres = float(lengths[self._node_index[node]])
            if np.isfinite(metres):
                distances[code] = convert_metres(metres, unit)
        return distances

    def route_edges(self, origin: str, destination: str) -> list[EdgeKey]:
        """The physical track segments a route traverses.

        Each key identifies one stretch of track independent of
        direction, so a per-route metric can be aggregated onto the
        underlying track rather than drawn as one full route per
        corridor, which overdraws badly around hubs where many corridors
        share the same rails.
        """
        origin = str(origin).strip().upper()
        destination = str(destination).strip().upper()
        _, _, edge_keys = self._route(origin, destination)
        return edge_keys

    def route_geometry(self, origin: str, destination: str) -> list[BaseGeometry]:
        """The line geometries a route traverses, in the working CRS."""
        origin = str(origin).strip().upper()
        destination = str(destination).strip().upper()
        _, geometry, _ = self._route(origin, destination)
        return geometry

    def route_frame(self, origin: str, destination: str) -> gpd.GeoDataFrame:
        """The route as a GeoDataFrame, for GeoJSON or plotting."""
        geometry = self.route_geometry(origin, destination)
        return gpd.GeoDataFrame(geometry=geometry, crs=self.working_crs)

    def save_map(
        self,
        origin: str,
        destination: str,
        output_file: pathlib.Path | str,
        *,
        route_colour: str = "red",
        route_weight: int = 4,
        station_colour: str = "blue",
    ) -> None:
        """Write an interactive HTML map of the route.

        Needs the ``map`` extra, because this goes through geopandas
        ``.explore()``, which needs folium::

            pip install 'track-distance[map]'
        """
        origin = str(origin).strip().upper()
        destination = str(destination).strip().upper()
        route = self.route_frame(origin, destination).to_crs(self.input_crs)

        codes = [origin, destination]
        station_points = gpd.GeoDataFrame(
            {"station": codes},
            geometry=[Point(self.station_locations[code]) for code in codes],
            crs=self.working_crs,
        ).to_crs(self.input_crs)

        try:
            explored = route.explore(color=route_colour, weight=route_weight, name="Route")
            explored = station_points.explore(m=explored, color=station_colour, name="Stations")
        except ImportError as error:  # pragma: no cover - depends on the environment
            raise ImportError(
                "Interactive maps need folium: pip install 'track-distance[map]'"
            ) from error

        explored.save(str(output_file))
        logger.info("Wrote map to %s", output_file)


def _as_linestrings(geometry: BaseGeometry) -> list[Any]:
    """Flatten a geometry into LineStrings, ignoring anything else.

    A track model row is usually a LineString but can be a
    MultiLineString. The odd point or polygon turns up too, and cannot
    be routed along.
    """
    if geometry.geom_type == "LineString":
        return [geometry]
    if isinstance(geometry, MultiLineString):
        return list(geometry.geoms)
    return []
