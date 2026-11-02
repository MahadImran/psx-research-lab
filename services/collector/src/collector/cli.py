"""
PSX Research Lab — Collector CLI Entrypoint.
Commands:
  run       - Execute collector cycle (options: --force, --force-eod, --dry-run)
  calendar  - Inspect market session status and trading hours
  budget    - Display 24h upstream budget usage and active runner lease
  reconcile - Run standalone EOD reconciliation for a specific date
"""

import argparse
import json
import logging
import sys

from .calendar import MarketCalendar
from .pipeline import CollectorPipeline
from .persistent_budget import PersistentCoordinator


def setup_logging(verbose: bool = False):
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def cmd_calendar(args):
    now = MarketCalendar.now_pkt()
    session, is_open = MarketCalendar.get_market_session(now)
    should_run, reason = MarketCalendar.should_scheduled_collector_run(now)

    print(json.dumps({
        "current_pkt": now.isoformat(),
        "date": now.date().isoformat(),
        "time": now.time().strftime("%H:%M:%S"),
        "session": session,
        "is_market_open": is_open,
        "should_collector_run": should_run,
        "reason": reason,
    }, indent=2))


def cmd_budget(args):
    coord = PersistentCoordinator()
    state = coord.load_remote_state()
    remaining = coord.get_remaining_requests()

    print(json.dumps({
        "runner_id": coord.runner_id,
        "daily_limit": coord.daily_limit,
        "requests_used_24h": coord.daily_limit - remaining,
        "remaining_budget_24h": remaining,
        "active_lease": state.get("lease"),
        "recent_requests_count": len(coord.history),
    }, indent=2))


def cmd_run(args):
    pipeline = CollectorPipeline()
    result = pipeline.run(
        force=args.force,
        force_eod=args.force_eod,
        dry_run=args.dry_run,
    )
    print(json.dumps(result, indent=2, default=str))
    if result.get("status") in ("SKIPPED", "SUCCESS", "SKIPPED_LEASE_CONFLICT"):
        sys.exit(0)
    sys.exit(1)


def main():
    parser = argparse.ArgumentParser(description="PSX Research Lab Collector CLI")
    parser.add_argument("-v", "--verbose", action="store_true", help="Enable debug logging")
    subparsers = parser.add_subparsers(dest="command")

    # run command
    run_parser = subparsers.add_parser("run", help="Run scheduled collector cycle")
    run_parser.add_argument("--force", action="store_true", help="Bypass market hours calendar check")
    run_parser.add_argument("--force-eod", action="store_true", help="Force EOD reconciliation fetch")
    run_parser.add_argument("--dry-run", action="store_true", help="Do not write to remote git or API")

    # calendar command
    subparsers.add_parser("calendar", help="Inspect market session status")

    # budget command
    subparsers.add_parser("budget", help="Display 24h budget and active runner lease")

    args = parser.parse_args()
    setup_logging(args.verbose)

    if args.command == "calendar":
        cmd_calendar(args)
    elif args.command == "budget":
        cmd_budget(args)
    elif args.command == "run" or args.command is None:
        if args.command is None:
            # Default to running collector
            args.force = False
            args.force_eod = False
            args.dry_run = False
        cmd_run(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
