# ii-hotspot

Inflow and infiltration (I&I) hotspot mapping for sewer networks, using
spatially patchy rain events as natural stress tests of the network and
solving a physics-residual spatial-attribution problem.

The pipeline ingests open data only: KNMI 5-minute radar rainfall, GWSW
sewer network GeoPackages, and BRO groundwater monitoring. It outputs a
ranked map of zones for targeted CCTV inspection, turning a random
inspection schedule into a prioritized one.

## Quick start

```bash
pip install -e ".[dev]"
python -m ii_hotspot --demo
```

The `--demo` flag runs a synthetic end-to-end validation harness that
needs no external data. It builds a 6x6 grid of zones, injects 15
known-location I&I sources, simulates 30 days with 12 patchy storms
sensed by only 3 pump-station meters, and checks whether Stage A
recovers the injected hotspots. Expect output similar to:

```
meters=3  events=12  seed=42
Spearman a_fast: 0.694
Spearman a_slow: 0.761
Top-10 hotspot overlap: 10/10
```

Once that passes, install the geospatial extras and configure real data:

```bash
pip install -e ".[geo]"
export KNMI_API_KEY=...      # free at developer.dataplatform.knmi.nl
# the GWSW sewer network downloads itself from PDOK on first run
```

## Running a pilot end to end

```bash
scripts/bootstrap.sh                                   # env + tests + selftest gate
cp configs/pilot.example.toml configs/mypilot.toml     # edit bbox, gpkg, meters
python -m ii_hotspot --fetch-rain --config configs/mypilot.toml   # optional pre-fetch
scripts/run_pipeline.sh configs/mypilot.toml           # gate + pipeline + deliverables
```

Each run writes a versioned `outputs/<name>-<timestamp>/` directory with
`hotspots.csv`, `hotspots.geojson`, `report.html`, and an auditable
`run_manifest.json`. Windows equivalents (`scripts\*.ps1`), a Docker
image, scheduling, and quality gates are covered in the
[deployment plan](docs/deployment.md). A zero-data dry run of the same
deliverable contract: `python -m ii_hotspot --demo --out outputs/demo`.

## What's in the box

- `ii_hotspot.kernels` -- exponential unit hydrographs and the
  convolutional design matrix.
- `ii_hotspot.stage_a` -- ridge-NNLS unmixing of meter residuals into
  per-zone fast/slow capture fractions.
- `ii_hotspot.events` -- segments continuous radar series into discrete
  storm events.
- `ii_hotspot.knmi` -- loader for the KNMI Open Data Platform 5-min
  gauge-adjusted radar product.
- `ii_hotspot.gwsw` -- GWSW GeoPackage loader, column normalization, and
  directed-graph construction from pipe geometries and invert levels.
- `ii_hotspot.pdok` -- automated sewer-network download from the PDOK
  national GWSW service (no key required).
- `ii_hotspot.bro` -- BRO public REST helpers for groundwater wells, plus
  IDW interpolation of the head field to zone centroids.
- `ii_hotspot.synthetic` -- the validation harness used by `--demo`.
- `ii_hotspot.baseline` -- dry-weather baseline and meter residuals.
- `ii_hotspot.pipeline` -- the batch pipeline: stages, gates, and the
  `--run` entry point.
- `ii_hotspot.report` -- deliverable writers (CSV, GeoJSON, HTML report,
  reproducibility manifest).

## Documentation

- [`docs/method.md`](docs/method.md) -- the model, the two-stage
  estimation, and why physics-residual.
- [`docs/data-sources.md`](docs/data-sources.md) -- exact endpoints,
  dataset names, and licences for KNMI, GWSW, BRO, BGT/BAG.
- [`docs/deployment.md`](docs/deployment.md) -- the deployment plan:
  deliverables, runbook, quality gates, scheduling, and rollback.

## Status

Stage A, the synthetic harness, and the batch deployment pipeline
(deliverables, quality gates, scripts, container) are complete and
tested. The Stage B regression layer, the SWMM input builder, and the
operational dashboard are next.

## License

MIT
