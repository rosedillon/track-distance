# track-distance

[![PyPI](https://img.shields.io/pypi/v/track-distance)](https://pypi.org/project/track-distance/)
[![Python](https://img.shields.io/pypi/pyversions/track-distance)](https://pypi.org/project/track-distance/)
[![CI](https://github.com/rosedillon/track-distance/actions/workflows/ci.yml/badge.svg)](https://github.com/rosedillon/track-distance/actions/workflows/ci.yml)
[![Licence: GPL-3.0](https://img.shields.io/badge/licence-GPL--3.0-blue)](https://github.com/rosedillon/track-distance/blob/main/LICENSE)

Measure how far apart two railway stations are along the track, rather
than as the crow flies.

Straight-line distance between stations is easy to work out and usually
wrong, because railways do not run in straight lines. Manchester to
Leeds is 36 miles in a straight line and 42 by rail. This package
measures along the rails, using a shapefile of track centre lines and a
list of station coordinates.

```python
from track_distance import TrackDistanceCalculator

calc = TrackDistanceCalculator("NWR_TrackCentreLines.shp", "stations.csv")

calc.calculate_distance("MAN", "LDS", "miles")  # 42.34
calc.calculate_distance("EUS", "MAN", "miles")  # 183.49
calc.distances_from("LDS", "miles")  # every reachable station
```

Compared with published rail mileages:

| Route | Measured | Published |
|---|---|---|
| London Euston to Manchester Piccadilly | 183.49 mi | about 184 mi |
| London King's Cross to Edinburgh | 392.40 mi | about 393 mi |
| London Paddington to Reading | 36.51 mi | about 36 mi |
| Manchester Piccadilly to Leeds | 42.34 mi | about 42 mi |

## Install

Python 3.11 or later.

```sh
pip install track-distance

# with interactive HTML maps
pip install 'track-distance[map]'
```

or, from a clone, `pip install .` (or `pip install '.[map]'`). It
depends on geopandas, networkx, numpy, pandas, scipy and shapely; the
`map` extra adds folium.

## What you need

A track model: a shapefile of track centre lines. Network Rail
publishes one on the [Rail Data Marketplace](https://raildata.org.uk)
as the Network Rail Track Model, and the file you want is
`NWR_TrackCentreLines.shp`. Any line geometry in a metre-based
projection works, including an [OpenStreetMap](https://www.openstreetmap.org)
rail extract.

A station list: a CSV with a station code, latitude and longitude. The
default column names match the widely shared National Rail station
list:

```csv
stationName,tiploc,lat,long,crsCode
Abbey Wood,ABWD,51.490719,0.120343,ABW
```

Other column names can be given:

```python
from track_distance import StationSource, TrackDistanceCalculator

calc = TrackDistanceCalculator(
    "tracks.shp",
    StationSource("stops.csv", code_column="id", latitude_column="y", longitude_column="x"),
)
```

The CLI takes the same as `--code-column`, `--lat-column` and
`--lon-column`.

## Command line

```console
$ track-distance distance MAN LDS -t NWR_TrackCentreLines.shp -s stations.csv -u miles
MAN -> LDS      42.34 miles
```

Give several stations and each consecutive pair is one leg:

```console
$ track-distance distance MAN HUD LDS YRK -t tracks.shp -s stations.csv -u miles
MAN -> HUD      25.31 miles
HUD -> LDS      18.15 miles
LDS -> YRK      26.16 miles
total             69.62 miles
```

Every station reachable from one, nearest first:

```console
$ track-distance from LDS -t tracks.shp -s stations.csv -u miles -n 5
From LDS (2,601 reachable stations)
  COT       1.23 miles
  MLY       1.23 miles
  BUY       1.33 miles
  BLE       2.78 miles
  HDY       2.86 miles
```

Add `--map route.html` to `distance` for an interactive map of a single
leg, `--json` for machine-readable output, or `-v` to log progress.

## How it works

The track model becomes a graph. Each stretch of line is an edge
weighted by its real length, and the points where stretches meet are
nodes. The distance between two nodes is a shortest-path search:
networkx for a single route, and scipy for `distances_from()`, which
finds every station at once.

Only each line's two end points become nodes, not every vertex along
it. Track segments meet end to end, so that is enough to route across
the network, and it keeps the graph to about 39,000 nodes for the whole
of Great Britain.

Stations are not in the track model, so each is projected into the
model's coordinate system and attached to a nearby node, found with a
KD-tree.

### Disconnected fragments

A track model has small fragments that connect to nothing: sidings,
stubs and digitising artefacts. A station beside one would attach to it
and become unreachable from everywhere else. Nothing raises an error
when that happens; the station just has no routes, which looks
downstream like a station nobody travels to.

So the candidate nodes near each station are taken in order of
distance, and the first one on the largest connected part of the
network is used. If none of them is on it, the station goes to the
nearest node on the main network as long as that is within 1 km.
Spondon needs this: it sits beside a 26-node fragment, and its nearest
main-network node is 710 m away. Stations on a genuinely separate
network, such as the Isle of Wight's, are kilometres from the main one
and keep their own nearest node. On the September 2026 Network Rail
model this moves 39 stations off fragments:

```
INFO Snapped 39 station(s) past a disconnected track fragment onto the main network:
ALF, BFE, BFF, BOR, BOW, CEA, CFL, CGW, CLK, CUW, CYK, DUD, DWD, EDL, ENL, ERI, FMT,
FYS, HDW, HOL, HPE, HTW, KEI, KWL, MIR, NAR, NWH, PFY, PNF, PNM, PRT, SDY, SHH, SIN,
SPO, STK, TUR, WDS, WTL
```

Run with `-v` to see the list. If yours is much longer, the track model
probably has connectivity problems worth looking into.

### Routes that cannot be right

Some gaps are in the main network itself. Headbolt Lane and Kirkby are
a mile apart, but the 2023 link between them is not joined up in the
model, so the route goes the long way round:

```console
$ track-distance distance HBL KIR -t tracks.shp -s stations.csv -u miles
HBL -> KIR      39.84 miles
$ track-distance distance HBL KIR -t tracks.shp -s stations.csv -u miles --plausible
HBL -> KIR       1.04 miles
```

With `--plausible` (or `plausible=True` in Python), a route shorter than
0.9 times the straight line or longer than 3 times it is treated as a
gap in the model. The straight line times 1.2 is used instead, 1.2
being the median ratio of route to straight line across about 9,900
station pairs. Stations closer than 800 m are left alone. It is off by
default, so you see what the track model says unless you ask.

## Totals on shared track

`route_edges()` returns the physical segments a route uses, with keys
that do not depend on direction:

```python
from collections import Counter

usage = Counter()
for origin, destination in corridors:
    usage.update(calc.route_edges(origin, destination))
```

Use this to colour a map by flow without overdrawing. Around a hub,
dozens of corridors share the same rails, and drawing one full route
per corridor stacks them on top of each other. Totalling onto shared
segments gives one line per stretch of track with a real total.

## Performance

Building the calculator reads the shapefile and builds the graph, which
takes about a second for the whole network, so build it once and reuse
it. Routes are cached in both directions, since track distance is
symmetric.

For many destinations from one origin, use `distances_from()`. It runs
one shortest-path search for all of them instead of one per pair.

## Limitations

- This is track distance, not journey distance. It is the shortest path
  over the physical network. A train may take a longer route for
  operational reasons, and the route a ticket allows is a separate
  question for the National Routeing Guide.
- Every edge can be used in both directions by any train. Single-line
  working, freight-only lines and closed sections are not distinguished
  unless your track model leaves them out.
- A station attaches to the end of a track segment, not to the closest
  point along it. Over a whole journey that makes little difference;
  for two stations a few hundred metres apart it can.
- The working coordinate system must be in metres, because edge weights
  are geometry lengths. The default is the British National Grid
  (`EPSG:27700`); pass `working_crs` (or `--working-crs`) elsewhere.
- Unreachable pairs raise `NoRouteError` and unknown codes raise
  `StationNotFoundError`. `distances_from()` leaves unreachable
  stations out.

## Python API

| Name | |
|---|---|
| `TrackDistanceCalculator(track_shapefile, stations)` | build the graph and attach the stations |
| `.calculate_distance(origin, destination, unit="km", plausible=False)` | one distance |
| `.distances_from(origin, unit="km", plausible=False)` | every reachable station |
| `.route_edges(origin, destination)` | the track segments a route uses |
| `.route_geometry(origin, destination)` | the route's line geometries |
| `.route_frame(origin, destination)` | the route as a GeoDataFrame |
| `.save_map(origin, destination, path)` | an interactive HTML map (needs the `map` extra) |
| `StationSource(path, ...)` | a station CSV and its column names |
| `convert_metres(metres, unit)` | metres to `km`, `miles` or `metres` |

## Development

```sh
git clone https://github.com/rosedillon/track-distance
cd track-distance
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest
ruff check . && ruff format --check . && mypy src
```

The tests build a small network in British National Grid coordinates
with round metre positions, so the expected distances are exact. The
station CSV is made by projecting those positions back to latitude and
longitude, so the tests go through the real projection code. The
disconnected fragment case has its own fixture. No licensed data is
committed.

## Licence

GPL-3.0. See [LICENSE](https://github.com/rosedillon/track-distance/blob/main/LICENSE).

Not affiliated with or endorsed by Network Rail.
