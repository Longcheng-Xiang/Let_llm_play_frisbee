from __future__ import annotations

import argparse
import json
from pathlib import Path

from .live_server import serve
from .policies import policy_from_name
from .simulator import FrisbeeSimulator


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the offline Frisbee 5v5 simulator.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_parser = subparsers.add_parser("run-offline", help="Run an offline simulation with a local policy.")
    run_parser.add_argument("--policy", choices=["hold", "heuristic"], default="heuristic")
    run_parser.add_argument("--max-frames", type=int, default=30)
    run_parser.add_argument("--seed", type=int, default=7)
    run_parser.add_argument("--log", type=Path, help="Optional JSONL replay log path.")

    obs_parser = subparsers.add_parser("observation", help="Print one player observation from the initial state.")
    obs_parser.add_argument("player_id")
    obs_parser.add_argument("--seed", type=int, default=7)

    serve_parser = subparsers.add_parser("serve-live", help="Serve the replay viewer with live DeepSeek controls.")
    serve_parser.add_argument("--host", default="127.0.0.1")
    serve_parser.add_argument("--port", type=int, default=8766)

    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    if args.command == "serve-live":
        serve(args.host, args.port)
        return 0

    simulator = FrisbeeSimulator(seed=args.seed)
    if args.command == "observation":
        print(json.dumps(simulator.observation_for(args.player_id), indent=2, sort_keys=True))
        return 0

    policy = policy_from_name(args.policy)
    summary = simulator.run(policy, max_frames=args.max_frames, log_path=args.log)
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
