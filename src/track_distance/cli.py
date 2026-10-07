"""Command-line interface."""

from __future__ import annotations

import argparse
import json
import logging
import pathlib
import sys
from typing import TYPE_CHECKING

from track_distance.calculator import NoRouteError, StationNotFoundError, TrackDistanceCalculator
from track_distance.stations import StationSource

if TYPE_CHECKING:
    from collections.abc import Sequence

UNITS = ("km", "miles", "metres")

# A leg needs a start and an end.
MIN_STATIONS_FOR_A_LEG = 2


def _build(args: argparse.Namespace) -> TrackDistanceCalculator:
    return TrackDistanceCalculator(
        args.track,
        StationSource(
            path=args.stations,
            code_column=args.code_column,
            latitude_column=args.lat_column,
            longitude_column=args.lon_column,
        ),
        input_crs=args.input_crs,
        working_crs=args.working_crs,
    )


def _cmd_distance(args: argparse.Namespace) -> int:
    calculator = _build(args)
    legs = list(zip(args.stations_list, args.stations_list[1:], strict=False))
    total = 0.0
    rows = []
    for origin, destination in legs:
        distance = calculator.calculate_distance(origin, destination, args.unit)
        total += distance
        rows.append({"from": origin.upper(), "to": destination.upper(), "distance": distance})

    if args.map:
        if len(legs) != 1:
            print(
                "note: --map draws a single leg; give exactly two stations for a map",
                file=sys.stderr,
            )
        else:
            calculator.save_map(legs[0][0], legs[0][1], args.map)
            print(f"Wrote map to {args.map}", file=sys.stderr)

    if args.json:
        json.dump({"unit": args.unit, "legs": rows, "total": total}, sys.stdout, indent=2)
        sys.stdout.write("\n")
        return 0

    for row in rows:
        print(f"{row['from']} -> {row['to']}  {row['distance']:>9,.2f} {args.unit}")
    if len(rows) > 1:
        print(f"{'total':<14}{total:>9,.2f} {args.unit}")
    return 0


def _cmd_from(args: argparse.Namespace) -> int:
    calculator = _build(args)
    distances = calculator.distances_from(args.origin, args.unit)
    distances.pop(args.origin.strip().upper(), None)
    ranked = sorted(distances.items(), key=lambda item: item[1])
    if args.limit:
        ranked = ranked[: args.limit]

    if args.json:
        json.dump(
            {"origin": args.origin.upper(), "unit": args.unit, "distances": dict(ranked)},
            sys.stdout,
            indent=2,
        )
        sys.stdout.write("\n")
        return 0

    print(f"From {args.origin.upper()} ({len(distances):,} reachable stations)")
    for code, distance in ranked:
        print(f"  {code}  {distance:>9,.2f} {args.unit}")
    return 0


def _add_common(parser: argparse.ArgumentParser) -> None:
    # -v also works after the subcommand.
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        default=argparse.SUPPRESS,
        help="log progress",
    )
    parser.add_argument(
        "-t", "--track", type=pathlib.Path, required=True, help="track centre lines shapefile"
    )
    parser.add_argument(
        "-s", "--stations", type=pathlib.Path, required=True, help="station locations CSV"
    )
    parser.add_argument("-u", "--unit", choices=UNITS, default="km", help="output unit")
    parser.add_argument("--json", action="store_true", help="emit JSON")
    parser.add_argument("--code-column", default="crsCode", help="station code column")
    parser.add_argument("--lat-column", default="lat", help="latitude column")
    parser.add_argument("--lon-column", default="long", help="longitude column")
    parser.add_argument("--input-crs", default="EPSG:4326", help="CRS of the station coordinates")
    parser.add_argument("--working-crs", default="EPSG:27700", help="metre-based CRS to route in")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="track-distance",
        description=(
            "Measure distance between rail stations along the track, using a track "
            "centre-lines shapefile and a CSV of station coordinates."
        ),
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="log progress")
    subparsers = parser.add_subparsers(dest="command", required=True)

    distance = subparsers.add_parser(
        "distance",
        help="Distance along a sequence of stations.",
        description=(
            "Distance between two stations, or along a sequence of them "
            "(each consecutive pair is one leg)."
        ),
    )
    distance.add_argument(
        "stations_list", nargs="+", metavar="CRS", help="two or more station codes"
    )
    _add_common(distance)
    distance.add_argument("--map", metavar="PATH", help="write an interactive HTML map")
    distance.set_defaults(func=_cmd_distance)

    from_cmd = subparsers.add_parser(
        "from",
        help="Distances from one station to all others.",
        description="Distance from one station to every station reachable from it.",
    )
    from_cmd.add_argument("origin", help="origin station code")
    _add_common(from_cmd)
    from_cmd.add_argument("-n", "--limit", type=int, help="show only the nearest N")
    from_cmd.set_defaults(func=_cmd_from)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(levelname)s %(message)s",
    )
    if args.command == "distance" and len(args.stations_list) < MIN_STATIONS_FOR_A_LEG:
        parser.error("give at least two station codes")
    try:
        return int(args.func(args))
    except (StationNotFoundError, NoRouteError) as error:
        message = error.args[0] if error.args else str(error)
        print(f"error: {message}", file=sys.stderr)
        return 1
