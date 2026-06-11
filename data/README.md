External data lives here. None of it is committed; see ../docs/data-sources.md
for download instructions.

Expected layout for a pilot run (paths are set in configs/<pilot>.toml):

- `<pilot>.gpkg` -- GWSW sewer network GeoPackage (downloaded automatically
  from PDOK on first run; place a manual export here to use that instead)
- `meters/*.csv` -- one file per flow meter, columns `timestamp,flow_m3`
  (volume per record interval; see docs/deployment.md section 3)
- `radar/` -- KNMI radar downloads (created automatically)
- `rain_zone_series.csv` -- cached (time x zone) rain matrix (created
  automatically; delete to force a refetch)
