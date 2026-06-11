"""Command-line entry point: ``python -m ii_hotspot --demo`` and friends."""

from __future__ import annotations

import argparse
import sys

from .config import Config
from .synthetic import run_synthetic


def main() -> None:
    ap = argparse.ArgumentParser(
        prog="ii_hotspot",
        description="I&I hotspot mapping: physics-residual spatial attribution.",
    )
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument(
        "--demo",
        action="store_true",
        help="run the synthetic end-to-end recoverability test",
    )
    mode.add_argument(
        "--selftest",
        action="store_true",
        help="run the publication gate; exit 1 if recovery is below threshold",
    )
    mode.add_argument(
        "--fetch-network",
        action="store_true",
        help="download the GWSW sewer network for the configured bbox from PDOK",
    )
    mode.add_argument(
        "--fetch-rain",
        action="store_true",
        help="download and cache the radar rain matrix for the configured window",
    )
    mode.add_argument(
        "--run",
        action="store_true",
        help="execute the full pipeline and write deliverables",
    )
    ap.add_argument(
        "--config", type=str, help="pilot TOML file (required for --run/--fetch-rain)"
    )
    ap.add_argument(
        "--out", type=str, help="with --demo: also write the deliverable set here"
    )
    ap.add_argument(
        "--skip-selftest",
        action="store_true",
        help="with --run: skip the synthetic gate (not recommended)",
    )
    ap.add_argument(
        "--n-meters", type=int, default=3, help="meters in the synthetic harness"
    )
    ap.add_argument(
        "--n-events", type=int, default=12, help="storms in the synthetic harness"
    )
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    if args.demo:
        cfg = Config()
        res = run_synthetic(
            cfg, n_meters=args.n_meters, n_events=args.n_events, seed=args.seed
        )
        print(f"meters={args.n_meters}  events={args.n_events}  seed={args.seed}")
        print(f"Spearman a_fast: {res.rho_fast:.3f}")
        print(f"Spearman a_slow: {res.rho_slow:.3f}")
        print(f"Top-10 hotspot overlap: {res.top10_overlap}/10")
        if args.out:
            from .pipeline import run_demo_deliverables

            paths = run_demo_deliverables(args.out, seed=args.seed)
            print(f"demo deliverables written to {args.out}: {sorted(paths)}")
    elif args.selftest:
        from .pipeline import selftest

        ok, metrics = selftest(seed=args.seed)
        for k, v in metrics.items():
            print(f"{k}: {v}")
        if not ok:
            print("SELFTEST FAILED")
            sys.exit(1)
        print("selftest passed")
    elif args.fetch_network or args.fetch_rain or args.run:
        if not args.config:
            ap.error(
                "--run, --fetch-network, and --fetch-rain require --config <pilot.toml>"
            )
        from .pipeline import load_run_config, network_stage, rain_stage, run_pipeline

        run = load_run_config(args.config)
        if args.fetch_network:
            from .pdok import fetch_network_gpkg

            fetch_network_gpkg(run.cfg.bbox_rd, run.cfg.gwsw_gpkg)
        elif args.fetch_rain:
            net = network_stage(run)
            rain = rain_stage(run, net["centroids"])
            print(f"rain cache ready: {run.rain_cache} ({len(rain)} steps)")
        else:
            run_pipeline(run, skip_selftest=args.skip_selftest)
    else:
        print(
            "Nothing to do. Use --demo (zero-data validation), --selftest "
            "(publication gate), --fetch-rain/--run with --config (pilot "
            "pipeline). See docs/deployment.md for the full runbook."
        )


if __name__ == "__main__":
    main()
