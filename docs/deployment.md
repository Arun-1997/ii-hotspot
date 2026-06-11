# Deployment plan

This document is the operational contract for ii-hotspot: what ships,
how it is produced, how a run is executed from a clean machine to a
deliverable in a customer's hands, and the gates a run must pass before
its output may be used.

## 1. The deliverables

Every pipeline run writes one **versioned, self-contained output
directory** `outputs/<run-name>-<UTC timestamp>/` containing:

| File | Audience | Contents |
| --- | --- | --- |
| `hotspots.csv` | analysts, GIS | one row per zone: `a_fast`, `a_slow`, combined `score`, `rank`, `metered` flag |
| `hotspots.geojson` | QGIS / web maps | the same table joined to zone geometry (EPSG:4326) |
| `report.html` | asset managers | ranked top-N table with inflow-vs-infiltration interpretation and QC metrics |
| `run_manifest.json` | audit / reproducibility | git commit, package version, full config (API key redacted), input paths, QC metrics |

The ranking statistic is `score = a_fast + a_slow` — the estimated
fraction of rain landing on a zone that reaches the foul sewer. CCTV
inspection proceeds from the top of the list. `a_fast`-dominant zones
indicate direct inflow; `a_slow`-dominant zones indicate groundwater
infiltration.

Output directories are never overwritten: re-running creates a new
timestamped directory, and the manifest pins the exact code revision and
configuration, so any past deliverable can be reproduced or audited.

## 2. Deployment modes

| Mode | Where | Trigger | Purpose |
| --- | --- | --- | --- |
| **Validation (staging)** | CI / any machine | every push, or `--demo --out` | prove the method recovers known synthetic hotspots; publishes a demo deliverable artifact |
| **Analyst workstation** | laptop/desktop | manual, `scripts/run_pipeline.*` | pilot studies, parameter tuning |
| **Scheduled batch** | server, VM, or container host | cron / Task Scheduler, monthly | recurring deliverables as new radar months are published |

There is no always-on service in the current product: the deliverable is
a batch artifact. The planned dashboard (see §8) will sit on top of the
same output directories.

## 3. Prerequisites

- **Python** ≥ 3.10 (3.12 recommended), or Docker.
- **KNMI API key** — free, from
  [developer.dataplatform.knmi.nl](https://developer.dataplatform.knmi.nl).
  Provided **only** via the `KNMI_API_KEY` environment variable (or a
  secret store that injects it). Never committed, never in TOML configs;
  the manifest redacts it.
- **GWSW GeoPackage** for the pilot municipality at the path named in the
  pilot config (download per [data-sources.md](data-sources.md)).
- **Meter flow CSVs** — one per flow meter / pump station, columns:
  - `timestamp`: ISO 8601, any regular interval (resampled to 5 min)
  - `flow_m3`: measured volume per record interval
  Gaps ≤ 30 min are interpolated; longer gaps are excluded, not invented.
- **Pilot config TOML** — copy `configs/pilot.example.toml`, set the
  bounding box (EPSG:28992), GeoPackage path, run window, and one
  `[[meters]]` block per meter with its RD coordinates (snapped to the
  nearest sewer node automatically).

## 4. Pipeline stages

```
GWSW gpkg ─► network: graph, zones, areas, upstream sets ─┐
KNMI radar ─► rain: (time × zone) matrix [cached]  ───────┤
meter CSVs ─► residuals: dry-weather baseline subtraction ┼─► Stage A unmix
                                                          │   (ridge-NNLS)
BRO groundwater (Stage B feature, planned) ───────────────┘        │
                                                                   ▼
                              deliver: hotspots.csv / .geojson / report.html / manifest
```

Stages live in `ii_hotspot.pipeline` as plain functions and run in this
order inside `run_pipeline()`. The rain matrix is cached
(`rain_cache` in the config) because the radar download dominates wall
time (~288 files/day of run window); delete the cache file to force a
refetch. The dry-weather baseline is currently the empirical
weekday/weekend diurnal median over dry days — it is replaced by the
SWMM-modelled baseline when the SWMM input builder lands, with no other
pipeline change.

## 5. Quality gates

A run must pass these gates before its deliverables may be shared:

1. **Unit tests + lint** (CI on every push; `pytest`, `ruff check`).
2. **Synthetic selftest** (`python -m ii_hotspot --selftest`): the build
   must recover injected hotspots with Spearman ρ ≥ 0.6 on both `a_fast`
   and `a_slow` and ≥ 8/10 top-10 overlap. `run_pipeline()` executes this
   gate automatically before touching real data and aborts if it fails;
   `--skip-selftest` exists for debugging only.
3. **Event sufficiency**: the run warns when fewer than 5 usable rain
   events fall in the window. Treat such output as indicative only and
   extend the window.
4. **Coverage transparency**: zones not upstream of any meter get
   `metered = False` in `hotspots.csv`. Until Stage B ships, scores for
   unmetered zones are structurally zero — do not interpret them as
   "clean"; filter on `metered` when presenting results.

## 6. Runbook: clean machine to deliverable

### 6.1 Bootstrap (once per machine)

Linux/macOS:

```bash
git clone <repo-url> && cd ii-hotspot
scripts/bootstrap.sh           # venv + install + lint + tests + selftest
```

Windows (PowerShell):

```powershell
git clone <repo-url>; cd ii-hotspot
powershell -ExecutionPolicy Bypass -File scripts\bootstrap.ps1
```

The bootstrap fails loudly if any verification step fails — do not
proceed past a red bootstrap.

### 6.2 Stage the inputs (once per pilot)

```bash
export KNMI_API_KEY=...                        # PowerShell: $env:KNMI_API_KEY="..."
# 1. GWSW GeoPackage  -> data/<pilot>.gpkg     (docs/data-sources.md)
# 2. meter flow CSVs  -> data/meters/*.csv     (format in §3)
# 3. pilot config     -> configs/<pilot>.toml  (copy pilot.example.toml)
```

### 6.3 Optional: pre-fetch the rain window

The radar download is the slow step; it can be done separately (e.g.
overnight) from the analysis:

```bash
python -m ii_hotspot --fetch-rain --config configs/<pilot>.toml
```

### 6.4 Produce the deliverables

```bash
scripts/run_pipeline.sh configs/<pilot>.toml
# Windows: powershell -ExecutionPolicy Bypass -File scripts\run_pipeline.ps1 configs\<pilot>.toml
```

This runs the selftest gate, then the full pipeline, and prints the
output directory. Total wall time is dominated by the rain fetch on the
first run; with a warm cache a run is minutes.

### 6.5 Hand off

Deliver the whole `outputs/<run>/` directory. `report.html` is the
entry point for non-technical stakeholders; `hotspots.geojson` drops
directly into QGIS on top of the municipality's base map.

### Zero-data dry run

To exercise the full deployment path with no external data (new machine,
new operator, CI):

```bash
python -m ii_hotspot --demo --out outputs/demo
```

This writes the identical deliverable contract (CSV/HTML/manifest) from
the synthetic harness, with ground-truth columns included for
verification.

## 7. Scheduled operation

The gauge-adjusted radar product (`rad_nl25_rac_mfbs_em_5min`) is
published monthly, a few months behind real time — so monthly scheduling
matches the data cadence. Point the schedule at the run script:

Linux (cron, 06:00 on the 2nd of each month):

```cron
0 6 2 * *  cd /opt/ii-hotspot && KNMI_API_KEY=$(cat /etc/ii-hotspot/knmi.key) scripts/run_pipeline.sh configs/pilot.toml >> /var/log/ii-hotspot.log 2>&1
```

Windows (Task Scheduler):

```powershell
schtasks /Create /TN "ii-hotspot monthly" /SC MONTHLY /D 2 /ST 06:00 `
  /TR "powershell -ExecutionPolicy Bypass -File C:\ii-hotspot\scripts\run_pipeline.ps1 C:\ii-hotspot\configs\pilot.toml"
```

Container host (any scheduler that can run a container):

```bash
docker build -t ii-hotspot .
docker run --rm -e KNMI_API_KEY \
  -v /srv/ii-hotspot/data:/app/data \
  -v /srv/ii-hotspot/outputs:/app/outputs \
  -v /srv/ii-hotspot/configs:/app/configs:ro \
  ii-hotspot --run --config configs/pilot.toml
```

Before each scheduled run, update the run window (`start`/`end`) in the
pilot TOML or use a small wrapper that rewrites it; the rain cache only
ever grows by the newly published month.

CI (`.github/workflows/ci.yml`) acts as the continuous staging deploy:
every push runs lint, tests, the selftest gate, and uploads the demo
deliverable set as a build artifact — so the artifact of `main` is
always a verified, shippable build.

## 8. Failure modes and monitoring

| Symptom | Likely cause | Action |
| --- | --- | --- |
| selftest gate fails | regression in kernels/Stage A | do not ship; bisect the code change |
| `KNMI_API_KEY is not set` | missing secret | export the key; check secret store wiring |
| HTTP 4xx from KNMI | expired/invalid key or dataset rename | renew at the developer portal; check `knmi_dataset` in config |
| `no KNMI files found in window` | window ahead of monthly publication lag | move `end` back, or switch to the near-real-time dataset |
| `cached zone count ... does not match` | GeoPackage changed since cache was built | delete `rain_cache` and refetch |
| `zoning produced no clusters` | wrong CRS / wrong layer in GeoPackage | inspect with `gpd.read_file`; extend `gwsw.RENAMES` |
| `no dry steps in the record` | wet window or too-short record | extend the run window |
| < 5 events warning | calm season | extend the window; treat output as indicative |

Each scheduled run should be considered failed unless it exits 0 **and**
a new `outputs/<run>/run_manifest.json` exists; alert on either signal
in your scheduler of choice.

## 9. Versioning, retention, rollback

- **Code**: deliverables record `git_revision` and `package_version`;
  tag releases that produce customer-facing output.
- **Outputs**: timestamped directories are append-only. Keep at least
  the latest two runs per pilot; archive older runs to cold storage.
- **Rollback**: a bad run is rolled back by deleting (or ignoring) its
  output directory — nothing downstream mutates shared state. To
  reproduce a past deliverable: check out the manifest's
  `git_revision`, restore the same config and inputs, re-run.
- **Secrets**: the KNMI key is the only secret; rotate it at the KNMI
  portal and update the environment/secret store. No key material is
  ever written to outputs.

## 10. Planned extensions (not yet deployed)

These do not change the deployment contract above; they extend it:

- **Stage B regression** adds `predicted_score` + SHAP columns for
  unmetered zones to `hotspots.csv`.
- **SWMM input builder** replaces the empirical dry-weather baseline in
  `residual_stage` with a modelled one.
- **Operational dashboard** reads the existing `outputs/` directories;
  it deploys as a separate static or lightweight web app and introduces
  no new pipeline dependencies.
