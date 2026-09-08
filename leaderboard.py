"""Generate a leaderboard from saved MachBench session reports."""

from __future__ import annotations

import argparse
import json

from machbench.leaderboard import write_leaderboard


def main() -> None:
    parser = argparse.ArgumentParser(description="Create MachBench JSON and SVG model leaderboards.")
    parser.add_argument("--history", default="history", help="directory containing .report.json files")
    parser.add_argument("--output", default="leaderboard.json", help="JSON or SVG output path")
    args = parser.parse_args()
    rows = write_leaderboard(args.history, args.output)
    print(json.dumps({"format": "machbench/leaderboard/v1", "models": rows, "output": args.output}, indent=2))


if __name__ == "__main__":
    main()