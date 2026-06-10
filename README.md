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
# place a GWSW GeoPackage at data/stedelijk_water_pilot.gpkg
```

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
- `ii_hotspot.bro` -- BRO public REST helpers for groundwater wells, plus
  IDW interpolation of the head field to zone centroids.
- `ii_hotspot.synthetic` -- the validation harness used by `--demo`.

## Documentation

- [`docs/method.md`](docs/method.md) -- the model, the two-stage
  estimation, and why physics-residual.
- [`docs/data-sources.md`](docs/data-sources.md) -- exact endpoints,
  dataset names, and licences for KNMI, GWSW, BRO, BGT/BAG.

## Status

Stage A and the synthetic harness are complete and tested. The Stage B
regression layer, the SWMM input builder, and the operational dashboard
are next.

## License

MIT
