"""Command-line entry point: ``python -m ii_hotspot --demo``."""

from __future__ import annotations

import argparse

from .config import Config
from .synthetic import run_synthetic


def main() -> None:
    ap = argparse.ArgumentParser(
        prog="ii_hotspot",
        description="I&I hotspot mapping: physics-residual spatial attribution.",
    )
    ap.add_argument(
        "--demo",
        action="store_true",
        help="run the synthetic end-to-end recoverability test",
    )
    ap.add_argument(
        "--n-meters", type=int, default=3, help="meters in the synthetic harness"
    )
    ap.add_argument(
        "--n-events", type=int, default=12, help="storms in the synthetic harness"
    )
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    cfg = Config()
    if args.demo:
        res = run_synthetic(
            cfg, n_meters=args.n_meters, n_events=args.n_events, seed=args.seed
        )
        print(f"meters={args.n_meters}  events={args.n_events}  seed={args.seed}")
        print(f"Spearman a_fast: {res.rho_fast:.3f}")
        print(f"Spearman a_slow: {res.rho_slow:.3f}")
        print(f"Top-10 hotspot overlap: {res.top10_overlap}/10")
    else:
        print(
            "Loaders ready. Set KNMI_API_KEY and a GWSW GeoPackage path in "
            "Config, or run with --demo for the zero-data validation test."
        )


if __name__ == "__main__":
    main()
