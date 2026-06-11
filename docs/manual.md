# The ii-hotspot manual

A complete guide to understanding and operating this repository: the
problem it solves, how every module works, the math behind it, and a
step-by-step path from a fresh clone to a real deliverable.

Companion documents:

- [method.md](method.md) — the scientific method in compact form
- [data-sources.md](data-sources.md) — datasets, endpoints, licences
- [deployment.md](deployment.md) — the operational/production contract

This manual is the long-form version that ties them together.

---

## Part I — Understand the problem

### 1.1 What is I&I and why does anyone pay for this?

A foul (sanitary) sewer is supposed to carry only wastewater. In
practice, **inflow and infiltration (I&I)** adds clean water to it:

- **Inflow** — rainwater entering directly: leaky manhole lids, roof
  drains or street gullies illegally cross-connected to the foul sewer.
  It arrives *fast*: the flow meter spikes within about an hour of rain.
- **Infiltration** — groundwater seeping in through cracked pipes and
  bad joints, mostly where pipes sit below the water table. It arrives
  *slowly*: flow stays elevated for a day or more after rain recharges
  the groundwater.

Utilities pay to pump and treat this clean water — often 20–40% of
everything that reaches the treatment plant. Fixing it requires knowing
*which pipes* leak, and the only definitive check is CCTV inspection at
~€1–2 per meter over hundreds of kilometers. Inspecting randomly wastes
most of that budget.

**The product**: a ranked list of network zones, ordered by how much
rain they leak into the sewer, so the inspection budget is spent where
the leaks are.

### 1.2 The key insight: storms are natural experiments

The network has only a handful of flow meters (typically at pump
stations), each draining dozens of zones. One meter alone cannot tell
you *which* upstream zone leaks. But rain at the 1-km radar resolution
is **spatially patchy**: storm 1 soaks the north zones, storm 2 the
east, storm 3 everything. Each storm "illuminates" a different subset of
zones with different intensities. Across many storms, the combination
of (which zones got rain) × (how much extra flow the meter saw) pins
down the leaky zones — the same way multiple X-ray angles pin down a 3-D
structure.

### 1.3 The physics-residual idea

Rather than asking a machine-learning model to learn everything about
the network, we subtract what we can already explain — the dry-weather
diurnal pattern (later: a full SWMM hydraulic model) — and model only
the **residual**: observed flow minus expected flow. After rain, that
residual *is* the I&I signal. This is far more data-efficient than pure
ML and the output is physically interpretable.

### 1.4 The model in one equation

For each meter `m`, at every 5-minute step `t`:

```
residual_m(t) =  Σ over zones z upstream of m :
                 A_z · [ a_z_fast · (P_z ⊛ h_fast)(t) + a_z_slow · (P_z ⊛ h_slow)(t) ]
                 + noise
```

| Symbol | Meaning | Where it comes from |
| --- | --- | --- |
| `P_z(t)` | rain on zone z (mm / 5 min) | KNMI radar |
| `A_z` | zone drained area (m²) | network geometry |
| `h_fast`, `h_slow` | exponential unit hydrographs, τ ≈ 1 h and 36 h | `kernels.py` |
| `⊛` | convolution in time | `numpy.convolve` |
| `a_z_fast`, `a_z_slow` | **the unknowns** — capture fractions | solved by Stage A |

`a_z_fast = 0.05` reads as: "5% of the rain volume falling on zone z
enters the foul sewer through fast (inflow) paths." These coefficients
are the same quantity as **R** in the EPA RTK method, which is why
wastewater engineers can read the output without translation.

Everything in the model is linear in the unknowns, so estimation is one
large constrained least-squares problem — no training loop, no
hyperparameter search, reproducible to the bit.

---

## Part II — Understand the code

### 2.1 Repository map

```
ii-hotspot/
├── src/ii_hotspot/
│   ├── config.py      # Config dataclass + time-grid constants
│   ├── kernels.py     # unit hydrographs, design-matrix construction
│   ├── stage_a.py     # the core solver: ridge-regularized NNLS unmixing
│   ├── events.py      # rain-series → discrete storm events (QC)
│   ├── synthetic.py   # validation harness with known ground truth
│   ├── baseline.py    # dry-weather baseline → meter residuals
│   ├── knmi.py        # KNMI radar download + pixel extraction
│   ├── pdok.py        # automated GWSW network download (no key)
│   ├── gwsw.py        # GeoPackage → GeoDataFrame → directed graph
│   ├── bro.py         # groundwater wells + IDW (Stage B feature, future)
│   ├── pipeline.py    # orchestrator: stages, gates, run_pipeline()
│   ├── report.py      # deliverables: CSV / GeoJSON / HTML / manifest
│   └── __main__.py    # CLI: --demo --selftest --fetch-* --run
├── tests/             # one test file per module
├── configs/           # pilot TOML templates
├── scripts/           # bootstrap + run wrappers (bash & PowerShell)
├── docs/              # method, data sources, deployment, this manual
├── data/              # external data (never committed)
└── Dockerfile         # containerized batch runner
```

Dependency layers (each layer only imports from the ones above it):

```
config
  └── kernels, events
        └── stage_a, baseline, synthetic
              └── pipeline ── knmi, pdok, gwsw, report
                    └── __main__
```

Heavy geospatial imports (`geopandas`, `networkx`, `sklearn`,
`requests`, `h5py`) are always done *inside* functions, so the core
package imports and the demo runs with nothing but numpy/scipy/pandas.

### 2.2 Module-by-module

**`config.py`** — one `Config` dataclass with the pilot bounding box
(EPSG:28992), KNMI dataset names (key read from the `KNMI_API_KEY` env
var), GWSW GeoPackage path + auto-fetch flag, the two kernel time
constants, and the ridge strength. Constants `STEP_MIN = 5` and
`STEPS_PER_DAY = 288` define the time grid everything lives on.

**`kernels.py`** — the physics. `exp_kernel(tau_h)` builds a discrete
exponential unit hydrograph that sums to 1 (so it conserves volume).
`zone_response_columns(rain, areas, kernels)` builds the design matrix
`X`: for every (kernel, zone) pair, convolve the zone's rain with the
kernel and scale by area — each column is "m³ per step that the meter
would see *if* that zone had capture fraction 1." Column block layout:
all zones for kernel 1, then all zones for kernel 2.

**`stage_a.py`** — the solver. `stage_a_unmix(...)`:

1. Build `X_full` once from rain, areas, both kernels.
2. Per meter: copy `X_full`, zero the columns of zones *not* upstream of
   that meter (topology as a hard constraint), stack vertically.
3. Column-scale, then ridge-regularize by appending `ridge · I` rows
   (the standard augmented-rows trick — turns NNLS into ridge-NNLS).
4. Solve `min ‖Xa − r‖²` subject to `a ≥ 0` with `scipy.optimize.nnls`.

Non-negativity is the secret weapon: capture fractions can't be
negative, and that constraint alone produces naturally sparse solutions
that resist smearing signal across correlated neighbours.

**`events.py`** — segments the continuous rain series into discrete
storms (wet spell ends after 6 dry hours; storms under 2 mm discarded).
Used as a QC diagnostic: fewer than ~5 events means weak
identifiability.

**`synthetic.py`** — the ground-truth harness. Builds a 6×6 zone grid,
simulates 12 spatially patchy storms over 30 days, plants 15 hotspots
with known `a` values, generates the meter signals *with* noise, then
asks Stage A to recover them blind. Returns Spearman rank correlations
and top-10 overlap. This is both the `--demo` and the publication gate.

**`baseline.py`** — turns raw meter data into the residual Stage A
needs. `load_meter_csv` (contract: `timestamp,flow_m3`),
`resample_to_grid` (5-min grid; gaps > 30 min stay NaN rather than being
invented), `wet_mask` (rain + 48 h tail, covering the slow kernel's
recession), `dry_weather_baseline` (median diurnal profile over dry
days, weekday/weekend split), `residual_series` (observed − baseline).
Interim by design: when the SWMM builder lands it replaces only this.

**`knmi.py`** — radar ingestion. Lists and downloads 5-min HDF5 files
from the KNMI Open Data API (with retry/backoff and clear 4xx errors),
then `rain_at_points` reads each file's *own* calibration formula and
projection metadata (never hardcoded — survives KNMI algorithm
revisions) to extract mm-per-5-min at zone centroids.

**`pdok.py`** — automated network download. Queries the PDOK national
"Beheer Stedelijk Watersystemen (GWSW)" OGC API (open data, no key,
native EPSG:28992) for the `beheerleiding` (pipes) collection within the
pilot bbox, follows `rel=next` paging, retries transient failures, and
writes a GeoPackage the gwsw loader reads directly.

**`gwsw.py`** — network topology. Normalizes Dutch column names via the
`RENAMES` map (extend it when a municipality uses different keys),
explodes multi-part geometries, then `build_graph` snaps pipe endpoints
to nodes and directs each edge by falling invert levels (gravity flow)
when known. `upstream_zone_ids` = graph ancestors of a meter node —
this is what zeroes design-matrix columns in Stage A. `make_zones`
clusters manholes into zones with DBSCAN (prefer the operator's own
`rioleringsgebied` partition when the data carries one).

**`pipeline.py`** — the conductor. `RunConfig` + `load_run_config`
(TOML), then five stage functions:

| Stage | Function | In → out |
| --- | --- | --- |
| 1 network | `network_stage` | gpkg (auto-fetched if missing) → graph, zones, centroids, areas, upstream sets |
| 2 rain | `rain_stage` | KNMI window → (time × zone) matrix, cached as CSV |
| 3 residuals | `residual_stage` | meter CSVs → residual arrays on the rain grid |
| 4 unmix | `stage_a_unmix` | everything above → per-zone `a_fast`, `a_slow` |
| 5 deliver | `write_deliverables` | ranked outputs + manifest |

`run_pipeline()` strings them together behind the **selftest gate**
(synthetic recovery must beat ρ ≥ 0.6 and 8/10 overlap, or the run
aborts). `run_demo_deliverables()` produces the same deliverable
contract from synthetic data — the zero-data staging path.

**`report.py`** — deliverables. `rank_hotspots` (score = `a_fast +
a_slow`), `write_deliverables` (CSV, GeoJSON if geometry is available,
self-contained HTML report, and `run_manifest.json` pinning git
revision, package version, redacted config, inputs, and QC metrics).

**`bro.py`** — groundwater helpers (wells lookup + inverse-distance
interpolation of head to zone centroids). Not yet wired into the
pipeline; it feeds the Stage B feature "fraction of pipe length below
the water table," the strongest static predictor of slow infiltration.

### 2.3 Suggested code-reading order

1. `config.py` (2 min) — vocabulary.
2. `kernels.py` (10 min) — hand-simulate one zone, one storm.
3. `synthetic.py` (15 min) — how truth is planted and recovered.
4. `stage_a.py` (15 min) — the masking and ridge-augmentation tricks.
5. `baseline.py` (10 min) — where the residual comes from.
6. `pipeline.py` (15 min) — how it assembles on real data.
7. The loaders (`pdok`, `gwsw`, `knmi`) as needed.

Reading `tests/` in parallel pays off: each test file doubles as
executable documentation of its module's contract.

---

## Part III — Execution manual

Commands shown for Windows PowerShell first, bash in comments where
different. Run everything from the repository root.

### Step 0 — Prerequisites

- Python ≥ 3.10 (3.12 recommended) on PATH, plus git.
- For real pilots only: a KNMI API key. Self-service signup is
  sometimes disabled (bot countermeasures) — email `opendata@knmi.nl`
  to register, mentioning dataset `rad_nl25_rac_mfbs_em_5min`. Not
  needed for anything in steps 1–4.

### Step 1 — Bootstrap and verify

```powershell
powershell -ExecutionPolicy Bypass -File scripts\bootstrap.ps1
# bash: scripts/bootstrap.sh
```

Creates `.venv`, installs `.[dev,geo]`, runs lint, the full test suite,
and the synthetic selftest. Green output means the machine is verified.
If the geospatial extras fail to install/import, rerun with `-CoreOnly`
(`--core-only`): everything in steps 2–4 still works.

Activate the venv for the rest of the session:

```powershell
.\.venv\Scripts\Activate.ps1
# bash: source .venv/bin/activate
```

### Step 2 — Run the demo and read it

```powershell
python -m ii_hotspot --demo
```

Expected: Spearman ≈ 0.69/0.76 and `Top-10 hotspot overlap: 10/10` —
with only 3 meters and 12 storms, all ten planted hotspots are found.
Now build intuition by perturbing it:

```powershell
python -m ii_hotspot --demo --n-events 4     # fewer storms -> worse recovery
python -m ii_hotspot --demo --n-meters 1     # one meter -> still works, thanks to rain patchiness
python -m ii_hotspot --demo --seed 7         # different random world
```

This is the method's identifiability argument made tangible: recovery
quality tracks the number of independent storm "experiments."

### Step 3 — Produce the demo deliverables

```powershell
python -m ii_hotspot --demo --out outputs\demo
```

Open `outputs\demo\report.html` in a browser and `hotspots.csv` in a
spreadsheet. The CSV carries `true_a_fast`/`true_a_slow` columns so you
can check rank-by-rank how estimate matches truth. `run_manifest.json`
shows the provenance every real run will also carry. This is the exact
output contract a customer receives.

### Step 4 — Explore the pieces interactively (optional but instructive)

```python
# python (inside the venv)
from ii_hotspot.config import Config
from ii_hotspot.kernels import exp_kernel
from ii_hotspot.synthetic import run_synthetic

h = exp_kernel(1.0)        # the fast kernel: 60 taps of 5 min
h.sum()                    # 1.0 -- volume conserved
res = run_synthetic(seed=42)
res.estimate.head()        # the DataFrame Stage A returns
```

### Step 5 — Configure a real pilot

```powershell
Copy-Item configs\pilot.example.toml configs\mypilot.toml
notepad configs\mypilot.toml
```

Set, in order of importance:

1. `[config] bbox_rd` — pilot bounding box in EPSG:28992
   (xmin, ymin, xmax, ymax). Get it from QGIS or rdnaptrans tools.
2. `[run] start` / `end` — the rain window. Prefer ≥ 3 months including
   an unsettled season; the gauge-adjusted radar product lags real time
   by a few months.
3. `[[meters]]` — one block per flow meter: a CSV path and the meter's
   RD coordinates (snapped to the nearest sewer node automatically).

Then stage the only non-automatable input — meter telemetry from the
utility (it is their private data, not a public download):

```
data\meters\<name>.csv     with columns: timestamp,flow_m3
```

`timestamp` ISO 8601 at any regular interval; `flow_m3` is volume per
interval. Gaps ≤ 30 min are interpolated, longer gaps excluded.

Validate the config parses before going further:

```powershell
python -c "from ii_hotspot.pipeline import load_run_config; print(load_run_config('configs/mypilot.toml'))"
```

### Step 6 — Fetch the network (automated, no key)

```powershell
python -m ii_hotspot --fetch-network --config configs\mypilot.toml
```

Downloads the sewer pipes for your bbox from PDOK into the configured
GeoPackage path. This also happens implicitly during `--run` if the
file is missing; running it explicitly lets you inspect the network in
QGIS first. If your municipality shares a richer export (invert levels,
`rioleringsgebied`), place it at the configured path instead — your file
wins, and you may need to extend `gwsw.RENAMES` with its column names.

### Step 7 — Fetch the rain (needs the KNMI key)

```powershell
$env:KNMI_API_KEY = "your-key"
# bash: export KNMI_API_KEY=...
python -m ii_hotspot --fetch-rain --config configs\mypilot.toml
```

Downloads ~288 radar files per day of window (the slow step — fine to
leave overnight; progress prints every 500 files) and caches the
extracted (time × zone) matrix at `rain_cache`. Reruns are instant;
delete the cache file to force a refetch.

### Step 8 — Run the pipeline

```powershell
powershell -ExecutionPolicy Bypass -File scripts\run_pipeline.ps1 configs\mypilot.toml
# bash: scripts/run_pipeline.sh configs/mypilot.toml
# or directly: python -m ii_hotspot --run --config configs\mypilot.toml
```

What happens, in order: selftest gate → network load/fetch → rain
load/fetch → event segmentation (warns below 5 events) → per-meter
dry-weather baselines and residuals → Stage A unmix → ranked
deliverables written to a fresh `outputs\<name>-<timestamp>\`.

### Step 9 — Interpret the output

Open `report.html` first. Then, per zone in `hotspots.csv`:

- **`score` high, `a_fast` dominant** → direct inflow. Field check:
  manhole lids, gully connections, roof drains. Often cheap fixes.
- **`score` high, `a_slow` dominant** → groundwater infiltration.
  Field check: CCTV below the water table; expect pipe defects.
- **`metered = False`** → the zone is upstream of *no* meter; its zero
  score means "unobserved," **not** "clean." Filter these out when
  presenting, until Stage B (which predicts them from static features)
  lands.

Sanity checks worth doing on a first pilot: do the top zones make sense
against pipe age/material maps? Does total estimated I&I volume roughly
match the utility's own mass-balance estimate? Treat a run with < 5
storm events as indicative only.

### Step 10 — Operate it on a schedule

The radar product updates monthly, so monthly runs match the data
cadence. Wire the run script into Task Scheduler / cron / a container
scheduler — exact commands and the alerting contract are in
[deployment.md](deployment.md) §7–8, and §8's failure-mode table is the
first place to look when a run goes red.

---

## Part IV — Verify, extend, troubleshoot

### 4.1 Test suite

```powershell
pytest                       # all tests (~seconds, no network, no key)
pytest tests\test_stage_a.py # just the solver contract
ruff check src tests         # lint
python -m ii_hotspot --selftest   # the publication gate, exit code 0/1
```

The test files mirror the modules: `test_kernels` (volume conservation,
shapes), `test_stage_a`/`test_pipeline` (synthetic recovery and gates),
`test_events`, `test_baseline` (diurnal recovery, storm isolation, gap
handling), `test_report` (deliverable contract), `test_pdok` (paging,
retries, failure modes — fully offline via mocks).

### 4.2 Extension points, in likely order of need

| Want to… | Touch |
| --- | --- |
| support a municipality's column names | `gwsw.RENAMES` |
| use operator catchments instead of DBSCAN zones | `pipeline.network_stage` (swap `make_zones`) |
| replace the empirical baseline with SWMM | `baseline.dry_weather_baseline` only — the residual interface is the seam |
| add a third response kernel (e.g. τ = 6 h) | `kernels` list in `stage_a_unmix` + `Config` |
| predict unmetered zones (Stage B) | new module consuming `hotspots.csv` + `bro.py` features |
| new deliverable format | `report.write_deliverables` |

### 4.3 Troubleshooting

The operational failure table (KNMI/PDOK errors, cache mismatches,
zoning failures, dry-record errors) lives in
[deployment.md](deployment.md) §8. Two learning-phase additions:

- **Recovery looks bad on real data but selftest passes** — usually the
  baseline, not the solver: check meter CSVs for unit errors (m³/h vs
  m³/interval), daylight-saving timestamp jumps, or pump-cycle
  oscillations that need smoothing before differencing.
- **Stage A puts everything in one zone** — neighbouring zones got
  identical rain in every event (too-small bbox or too few storms).
  More events is the fix; raising `ridge` spreads it but blurs ranking.
