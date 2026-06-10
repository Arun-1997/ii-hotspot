"""Project-wide configuration and time-grid constants."""

from __future__ import annotations

import os
from dataclasses import dataclass, field

STEP_MIN: int = 5
STEPS_PER_DAY: int = 24 * 60 // STEP_MIN


@dataclass
class Config:
    """Pipeline configuration.

    Defaults work for the synthetic demo. For a real pilot, override
    ``bbox_rd``, ``knmi_api_key`` (or set the ``KNMI_API_KEY`` env var),
    and ``gwsw_gpkg``.
    """

    # Pilot bounding box in RD New (EPSG:28992): xmin, ymin, xmax, ymax.
    # Placeholder centred on Apeldoorn -- replace for your pilot.
    bbox_rd: tuple[float, float, float, float] = (191000, 466000, 199000, 474000)

    # KNMI Data Platform -- free key at https://developer.dataplatform.knmi.nl
    knmi_api_key: str = field(default_factory=lambda: os.environ.get("KNMI_API_KEY", ""))
    knmi_dataset: str = "rad_nl25_rac_mfbs_em_5min"
    knmi_version: str = "2.0"

    # GWSW GeoPackage for the pilot municipality.
    gwsw_gpkg: str = "data/stedelijk_water_pilot.gpkg"

    # Unit-hydrograph time constants (hours).
    tau_fast_h: float = 1.0     # direct inflow: lids, cross-connections
    tau_slow_h: float = 36.0    # groundwater infiltration through defects

    # Stage A regularization.
    ridge: float = 1e-3
