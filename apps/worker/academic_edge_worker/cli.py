"""CLI entry points for the worker (seed, doctor, opportunities, alerts, ledger).

Usage:  ``python -m academic_edge_worker.cli <command>``
"""

from __future__ import annotations

import argparse
import sys


def main() -> None:
    parser = argparse.ArgumentParser(description="Academic Edge worker CLI")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("seed", help="Bootstrap the labelled fixture demo dataset.")
    sub.add_parser("doctor", help="Diagnose configuration, policy gates, connectivity.")
    sub.add_parser("opportunities", help="Print the current opportunity board.")
    sub.add_parser("alerts", help="Print open alerts.")
    sub.add_parser("ledger", help="Print paper ledger entries.")
    sub.add_parser("run-schedule", help="Run the local APScheduler (never production).")

    args = parser.parse_args()

    if args.command == "seed":
        from academic_edge_worker.seed import seed_database

        seed_database()
        print("Seed complete.")
    elif args.command == "doctor":
        print("Doctor: checking configuration, policy gates, connectivity...")
        from academic_edge_domain.settings import get_settings

        s = get_settings()
        print(f"  env={s.academic_edge_env}  fixture_only={s.fixture_only}")
        print(f"  database={s.resolve_db_url()}")
        print(f"  crocobet_web_enabled={s.crocobet_web_enabled}")
        print("  (CROCOBET_WEB_ENABLED=false is enforced by settings validator)")
    elif args.command == "opportunities":
        print("Opportunity board: use GET /v1/opportunities via the API.")
    elif args.command == "alerts":
        print("Alert inbox: use GET /v1/alerts via the API.")
    elif args.command == "ledger":
        print("Paper ledger: use GET /v1/paper-ledger via the API.")
    elif args.command == "run-schedule":
        print("Local APScheduler: not wired yet in this build. Use `make seed` + `make api`.")
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()