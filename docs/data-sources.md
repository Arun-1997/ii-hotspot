# Data sources

All datasets used by this project are open and free. Nothing is committed
to the repo; download into `data/` as instructed below.

## KNMI radar precipitation (5-min, 1 km, gauge-adjusted)

- **Provider:** KNMI Data Platform
- **Dataset (historical training):** `rad_nl25_rac_mfbs_em_5min` v2.0 -- the
  climatological gauge-adjusted product, updated monthly, lagging real time
  by a few months. Best for training Stage A on past events.
- **Dataset (near-real-time):** `nl_rdr_data_rtcor_5m` v1.0 -- the
  real-time product, with an archive variant going back to 2018.
- **Format:** HDF5
- **Licence:** CC-BY-4.0
- **API:** `https://api.dataplatform.knmi.nl/open-data/v1`
- **Auth:** free API key from the
  [Developer Portal](https://developer.dataplatform.knmi.nl). Set as
  the `KNMI_API_KEY` environment variable; the loader picks it up.

## GWSW sewer network

- **Provider:** Stichting RIONED (national wastewater standard) via
  individual municipalities.
- **Two access routes:**
  1. **`apps.gwsw.nl/item_geo`** -- per-municipality GeoPackage / GML
     download with selectable Geo-themes (object groupings).
  2. **PDOK "Stedelijk Water (Riolering)"** -- aggregated national service,
     also available as an Atom GeoPackage download.
- **Format:** GeoPackage (`.gpkg`), GML, or via WFS.
- **Bonus:** the GWSW server can also export HydX files for hydraulic
  modelling -- a useful starting point for SWMM input generation.

## BRO groundwater (GLD + GMW)

- **Provider:** Basisregistratie Ondergrond.
- **REST APIs** (for spot lookups, no certificate required):
  - GMW (wells): `https://publiek.broservices.nl/gm/gmw/v1`
  - GLD (level time series): `https://publiek.broservices.nl/gm/gld/v1`
  - Visualisation helper: `/gm/gld/v1/waterlevel`
- **Bulk:** for whole-municipality history, download the GLD dataset via
  PDOK / Nationaal Georegister and load it locally; the REST APIs are
  documented as suitable for incidental use only.

## BGT and BAG (surface topography, buildings)

- **PDOK BGT (Basisregistratie Grootschalige Topografie)** -- precise
  paved-surface, building, road geometry; useful for impervious-area
  fraction per zone.
- **PDOK BAG** -- building footprints and construction years.

## Flow telemetry

Not openly available at meter level. Use the synthetic harness
(`ii_hotspot.synthetic.run_synthetic`) for end-to-end validation, then
arrange a data-sharing agreement with a water authority (waterschap) or
municipality for a pilot. The strongest opening is the night-flow excess
metric, which only needs a few weeks of dry-weather pump-station data.
