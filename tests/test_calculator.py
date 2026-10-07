from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from track_distance import (
    NoRouteError,
    StationNotFoundError,
    StationSource,
    TrackDistanceCalculator,
)

from .conftest import NODE_A, NODE_B, NODE_C, NODE_D

if TYPE_CHECKING:
    import pathlib


class TestGraphBuilding:
    def test_nodes_are_the_line_endpoints(self, calculator: TrackDistanceCalculator) -> None:
        for node in (NODE_A, NODE_B, NODE_C, NODE_D):
            assert node in calculator.graph

    def test_duplicate_line_keeps_shorter(self, calculator: TrackDistanceCalculator) -> None:
        # A-B exists twice: straight (1000 m) and via a dogleg (~1140
        # m).
        assert calculator.graph[NODE_A][NODE_B]["weight"] == pytest.approx(1000.0)

    def test_stub_in_graph(self, calculator: TrackDistanceCalculator) -> None:
        # It is loaded but unreachable, which is what snapping guards
        # against.
        assert calculator.graph.number_of_nodes() > 4


class TestDistances:
    def test_adjacent_stations(self, calculator: TrackDistanceCalculator) -> None:
        assert calculator.calculate_distance("AAA", "BBB", "metres") == pytest.approx(1000.0)

    def test_distance_sums_along_the_route(self, calculator: TrackDistanceCalculator) -> None:
        # A to C goes through B: 1000 + 1000.
        assert calculator.calculate_distance("AAA", "CCC", "metres") == pytest.approx(2000.0)

    def test_route_not_straight_line(self, calculator: TrackDistanceCalculator) -> None:
        # A to D is 1414 m as the crow flies, but the rails go via B:
        # 2000 m.
        straight_line = (1000.0**2 + 1000.0**2) ** 0.5
        along_track = calculator.calculate_distance("AAA", "DDD", "metres")
        assert along_track == pytest.approx(2000.0)
        assert along_track > straight_line

    def test_units(self, calculator: TrackDistanceCalculator) -> None:
        assert calculator.calculate_distance("AAA", "BBB", "km") == pytest.approx(1.0)
        assert calculator.calculate_distance("AAA", "BBB", "miles") == pytest.approx(
            1000 / 1609.344
        )

    def test_default_unit_is_kilometres(self, calculator: TrackDistanceCalculator) -> None:
        assert calculator.calculate_distance("AAA", "CCC") == pytest.approx(2.0)

    def test_distance_is_symmetric(self, calculator: TrackDistanceCalculator) -> None:
        there = calculator.calculate_distance("AAA", "CCC", "metres")
        back = calculator.calculate_distance("CCC", "AAA", "metres")
        assert there == pytest.approx(back)

    def test_codes_normalised(self, calculator: TrackDistanceCalculator) -> None:
        assert calculator.calculate_distance(" aaa ", "bbb", "metres") == pytest.approx(1000.0)

    def test_unknown_station_names_the_code(self, calculator: TrackDistanceCalculator) -> None:
        with pytest.raises(StationNotFoundError, match="ZZZ"):
            calculator.calculate_distance("ZZZ", "AAA")


class TestSnapping:
    def test_station_on_node(self, calculator: TrackDistanceCalculator) -> None:
        assert calculator._station_nodes["BBB"] == NODE_B

    def test_station_near_node(self, calculator: TrackDistanceCalculator) -> None:
        # NEA sits 30 m from B.
        assert calculator._station_nodes["NEA"] == NODE_B

    def test_offset_station_routes(self, calculator: TrackDistanceCalculator) -> None:
        assert calculator.calculate_distance("NEA", "CCC", "metres") == pytest.approx(1000.0)

    def test_station_beside_stub_rescued(self, calculator: TrackDistanceCalculator) -> None:
        # STR's nearest node is on an isolated stub. Left there it would
        # have no routes, which looks downstream like a station with no
        # demand. It must be moved onto the main component instead.
        from .conftest import STUB_END, STUB_START

        assert calculator._station_nodes["STR"] not in (STUB_START, STUB_END)
        assert calculator.calculate_distance("STR", "AAA") >= 0

    def test_snapping_can_be_narrowed(
        self, track_shapefile: pathlib.Path, stations_csv: pathlib.Path
    ) -> None:
        # With a single candidate there is no rescue, and STR strands.
        calculator = TrackDistanceCalculator(track_shapefile, stations_csv, snap_candidates=1)
        from .conftest import STUB_END, STUB_START

        assert calculator._station_nodes["STR"] in (STUB_START, STUB_END)
        with pytest.raises(NoRouteError, match="unconnected"):
            calculator.calculate_distance("STR", "AAA")


class TestDistancesFrom:
    def test_reaches_every_connected_station(self, calculator: TrackDistanceCalculator) -> None:
        distances = calculator.distances_from("AAA", "metres")
        assert distances["BBB"] == pytest.approx(1000.0)
        assert distances["CCC"] == pytest.approx(2000.0)
        assert distances["DDD"] == pytest.approx(2000.0)

    def test_origin_zero(self, calculator: TrackDistanceCalculator) -> None:
        assert calculator.distances_from("AAA", "metres")["AAA"] == pytest.approx(0.0)

    def test_agrees_with_pairwise_calculation(self, calculator: TrackDistanceCalculator) -> None:
        bulk = calculator.distances_from("AAA", "km")
        for code in ("BBB", "CCC", "DDD"):
            assert bulk[code] == pytest.approx(calculator.calculate_distance("AAA", code, "km"))

    def test_unreachable_omitted(
        self, track_shapefile: pathlib.Path, stations_csv: pathlib.Path
    ) -> None:
        calculator = TrackDistanceCalculator(track_shapefile, stations_csv, snap_candidates=1)
        assert "STR" not in calculator.distances_from("AAA")

    def test_unknown_origin_raises(self, calculator: TrackDistanceCalculator) -> None:
        with pytest.raises(StationNotFoundError):
            calculator.distances_from("ZZZ")


class TestRouteGeometry:
    def test_edge_keys(self, calculator: TrackDistanceCalculator) -> None:
        assert len(calculator.route_edges("AAA", "CCC")) == 2

    def test_edge_keys_are_direction_independent(
        self, calculator: TrackDistanceCalculator
    ) -> None:
        there = calculator.route_edges("AAA", "CCC")
        back = calculator.route_edges("CCC", "AAA")
        assert set(there) == set(back)

    def test_geometry_comes_back_as_lines(self, calculator: TrackDistanceCalculator) -> None:
        geometry = calculator.route_geometry("AAA", "CCC")
        assert len(geometry) == 2
        assert all(line.geom_type == "LineString" for line in geometry)

    def test_route_frame_is_in_the_working_crs(self, calculator: TrackDistanceCalculator) -> None:
        frame = calculator.route_frame("AAA", "CCC")
        assert frame.crs is not None
        assert frame.crs.to_string() == "EPSG:27700"
        assert len(frame) == 2


class TestStationSource:
    def test_custom_column_names(
        self, track_shapefile: pathlib.Path, tmp_path: pathlib.Path, stations_csv: pathlib.Path
    ) -> None:
        renamed = tmp_path / "renamed.csv"
        text = stations_csv.read_text().replace("crsCode,lat,long", "code,latitude,longitude")
        renamed.write_text(text)

        calculator = TrackDistanceCalculator(
            track_shapefile,
            StationSource(
                path=renamed,
                code_column="code",
                latitude_column="latitude",
                longitude_column="longitude",
            ),
        )
        assert calculator.calculate_distance("AAA", "BBB", "metres") == pytest.approx(1000.0)

    def test_membership_and_station_set(self, calculator: TrackDistanceCalculator) -> None:
        assert "AAA" in calculator
        assert "aaa" in calculator
        assert "ZZZ" not in calculator
        assert {"AAA", "BBB", "CCC", "DDD"} <= calculator.stations
