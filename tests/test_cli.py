from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest

from track_distance import cli

if TYPE_CHECKING:
    import pathlib

    from _pytest.capture import CaptureFixture


def _args(track: pathlib.Path, stations: pathlib.Path) -> list[str]:
    return ["-t", str(track), "-s", str(stations)]


class TestDistance:
    def test_two_stations(
        self,
        track_shapefile: pathlib.Path,
        stations_csv: pathlib.Path,
        capsys: CaptureFixture[str],
    ) -> None:
        exit_code = cli.main(
            ["distance", "AAA", "CCC", *_args(track_shapefile, stations_csv), "-u", "metres"]
        )
        assert exit_code == 0
        assert "2,000.00 metres" in capsys.readouterr().out

    def test_sequence_sums_legs(
        self,
        track_shapefile: pathlib.Path,
        stations_csv: pathlib.Path,
        capsys: CaptureFixture[str],
    ) -> None:
        exit_code = cli.main(
            [
                "distance",
                "AAA",
                "BBB",
                "DDD",
                *_args(track_shapefile, stations_csv),
                "-u",
                "metres",
                "--json",
            ]
        )
        assert exit_code == 0
        payload = json.loads(capsys.readouterr().out)
        assert len(payload["legs"]) == 2
        assert payload["total"] == pytest.approx(2000.0)

    def test_json_output(
        self,
        track_shapefile: pathlib.Path,
        stations_csv: pathlib.Path,
        capsys: CaptureFixture[str],
    ) -> None:
        exit_code = cli.main(
            ["distance", "AAA", "BBB", *_args(track_shapefile, stations_csv), "--json"]
        )
        assert exit_code == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["unit"] == "km"
        assert payload["legs"][0] == {"from": "AAA", "to": "BBB", "distance": pytest.approx(1.0)}

    def test_unknown_station(
        self,
        track_shapefile: pathlib.Path,
        stations_csv: pathlib.Path,
        capsys: CaptureFixture[str],
    ) -> None:
        exit_code = cli.main(["distance", "ZZZ", "AAA", *_args(track_shapefile, stations_csv)])
        assert exit_code == 1
        assert "ZZZ" in capsys.readouterr().err

    def test_one_station_is_an_error(
        self, track_shapefile: pathlib.Path, stations_csv: pathlib.Path
    ) -> None:
        with pytest.raises(SystemExit):
            cli.main(["distance", "AAA", *_args(track_shapefile, stations_csv)])

    def test_writes_a_map(
        self,
        track_shapefile: pathlib.Path,
        stations_csv: pathlib.Path,
        tmp_path: pathlib.Path,
        capsys: CaptureFixture[str],
    ) -> None:
        target = tmp_path / "route.html"
        exit_code = cli.main(
            [
                "distance",
                "AAA",
                "CCC",
                *_args(track_shapefile, stations_csv),
                "--map",
                str(target),
            ]
        )
        assert exit_code == 0
        assert target.exists()
        assert "<html" in target.read_text(errors="replace").lower()


class TestFrom:
    def test_nearest_first(
        self,
        track_shapefile: pathlib.Path,
        stations_csv: pathlib.Path,
        capsys: CaptureFixture[str],
    ) -> None:
        exit_code = cli.main(
            ["from", "AAA", *_args(track_shapefile, stations_csv), "-u", "metres", "--json"]
        )
        assert exit_code == 0
        payload = json.loads(capsys.readouterr().out)
        distances = payload["distances"]
        assert list(distances) == sorted(distances, key=lambda code: distances[code])
        assert "AAA" not in distances

    def test_limit(
        self,
        track_shapefile: pathlib.Path,
        stations_csv: pathlib.Path,
        capsys: CaptureFixture[str],
    ) -> None:
        exit_code = cli.main(
            ["from", "AAA", *_args(track_shapefile, stations_csv), "-n", "2", "--json"]
        )
        assert exit_code == 0
        assert len(json.loads(capsys.readouterr().out)["distances"]) == 2

    def test_unknown_origin_is_reported(
        self,
        track_shapefile: pathlib.Path,
        stations_csv: pathlib.Path,
        capsys: CaptureFixture[str],
    ) -> None:
        exit_code = cli.main(["from", "ZZZ", *_args(track_shapefile, stations_csv)])
        assert exit_code == 1
        assert "ZZZ" in capsys.readouterr().err


def test_no_subcommand_is_an_error() -> None:
    with pytest.raises(SystemExit) as exit_info:
        cli.main([])
    assert exit_info.value.code != 0


SMOKE_ARGS = ["distance", "AAA", "BBB", "-t", "tracks.shp", "-s", "stations.csv"]


@pytest.mark.parametrize(
    ("argv", "verbose"),
    [(SMOKE_ARGS, False), (["-v", *SMOKE_ARGS], True), ([*SMOKE_ARGS, "-v"], True)],
)
def test_verbose_flag(argv: list[str], verbose: bool) -> None:
    assert cli.build_parser().parse_args(argv).verbose is verbose
