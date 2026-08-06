#!/usr/bin/env python3
"""CLI for the master/workers kill-recovery demo against a live IAC Bus.

Enqueues N tasks, runs a pool of workers where one dies mid-lease after its
first claim, and verifies that every task completes exactly once (the
orphaned task is recovered by a surviving worker after lease expiry).

Exits 0 when all tasks completed exactly once, 1 otherwise.
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from borgnet.logging import configure_logging
from borgnet.demo.master_worker import run_demo


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Master/workers kill-recovery demo on the IAC Bus."
    )
    parser.add_argument(
        "--bus-url",
        default=os.environ.get("BUS_URL", "http://127.0.0.1:8091"),
        help="IAC Bus base URL (default: $BUS_URL or http://127.0.0.1:8091)",
    )
    parser.add_argument(
        "--token",
        default=os.environ.get("BUS_API_TOKEN", ""),
        help="Bearer token for the bus (default: $BUS_API_TOKEN)",
    )
    parser.add_argument("--tasks", type=int, default=8, help="Number of tasks")
    parser.add_argument("--workers", type=int, default=3, help="Number of workers")
    parser.add_argument(
        "--lease-seconds",
        type=float,
        default=5,
        help="Lease duration for claimed tasks",
    )
    parser.add_argument(
        "--log-level", default="INFO", help="Log level (DEBUG, INFO, ...)"
    )
    args = parser.parse_args()

    configure_logging(level=args.log_level)

    result = run_demo(
        bus_url=args.bus_url,
        token=args.token or None,
        num_tasks=args.tasks,
        num_workers=args.workers,
        lease_seconds=args.lease_seconds,
    )

    print()
    print("=== Master/Workers Kill-Recovery Demo ===")
    print(f"bus_url:            {args.bus_url}")
    print(f"tasks:              {result['num_tasks']}")
    print(f"workers:            {args.workers} (1 dies after first claim)")
    print(f"lease_seconds:      {args.lease_seconds}")
    print(f"tasks_completed:    {result['tasks_completed']}/{result['num_tasks']}")
    print(f"duplicates:         {result['duplicates']}")
    print(f"dead_worker_claimed:{result['dead_worker_claimed']}")
    print(f"recovered_task_ids: {result['recovered_task_ids']}")
    print(f"elapsed:            {result['elapsed']}s")
    print(f"result:             {'SUCCESS' if result['success'] else 'FAILURE'}")

    if result["success"] and result["recovered_task_ids"]:
        print(
            "kill-recovery verified: task(s) claimed by the dying worker were "
            "re-claimed and completed by survivors after lease expiry"
        )
    elif result["success"]:
        print(
            "warning: all tasks completed but the dying worker never claimed "
            "a task, so kill-recovery was not exercised"
        )

    return 0 if result["success"] else 1


if __name__ == "__main__":
    sys.exit(main())
