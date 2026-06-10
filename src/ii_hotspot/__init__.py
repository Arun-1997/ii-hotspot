"""I&I hotspot mapping: physics-residual spatial attribution for sewer networks."""

from .config import STEP_MIN, STEPS_PER_DAY, Config
from .events import segment_events
from .kernels import exp_kernel, zone_response_columns
from .stage_a import stage_a_unmix

__version__ = "0.1.0"
__all__ = [
    "Config",
    "STEP_MIN",
    "STEPS_PER_DAY",
    "exp_kernel",
    "zone_response_columns",
    "stage_a_unmix",
    "segment_events",
]
