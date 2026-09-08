from __future__ import annotations

import argparse
import json

from .agents import HeuristicAgent
from .engine import GameEngine
from .scenario import corporate_coup_players
from .scoring import score_game
from .benchmark import run_standard, score_summary
from .standard import HttpClient, JsonlClient, McpClient
from .leaderboard import write_leaderboard


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a deterministic MachBench smoke benchmark.")
    parser.add_argument("--rounds", type=int, default=10, help="maximum rounds")
    parser.add_argument("--player", default="ada", help="player to score")
    parser.add_argument("--trace", action="store_true", help="include the complete observable decision trace")
    parser.add_argument("--model", default="reference-heuristic", help="stable model identifier stored in the report")
    parser.add_argument("--leaderboard", metavar="DIR", help="read saved reports from DIR")
    parser.add_argument("--graph", metavar="PATH", help="write leaderboard JSON or SVG to PATH")
    transport = parser.add_mutually_exclusive_group()
    transport.add_argument("--command", help="JSONL model command")
    transport.add_argument("--url", help="HTTP model endpoint")
    transport.add_argument("--mcp-command", help="MCP stdio server command")
    args = parser.parse_args()
    if args.leaderboard:
        output = args.graph or "machbench-leaderboard.json"
        print(json.dumps({"format": "machbench/leaderboard/v1", "models": write_leaderboard(args.leaderboard, output), "output": output}, indent=2))
        return
    if args.command or args.url or args.mcp_command:
        client = (JsonlClient(args.command) if args.command else
                  HttpClient(args.url) if args.url else McpClient(args.mcp_command))
        result = run_standard(client, args.player, args.rounds, args.model)
        if not args.trace:
            result.pop("trace", None)
        if hasattr(client, "close"):
            client.close()
    else:
        players = corporate_coup_players()
        agents = {player.name: HeuristicAgent(player) for player in players}
        state = GameEngine(agents, max_rounds=args.rounds).run()
        selected_score = score_game(state, args.player)
        result = {
            "format": "machbench/report/v1", "task": "corporate_boardroom_coup",
            "model": args.model, "player": args.player, "rounds": len(state.records),
            "reforms": state.reforms, "failed_votes": state.failed_votes, "winner": state.winner,
            "score": selected_score.as_dict(),
            "measurement": selected_score.measured(selected_score.evidence),
        }
        result["score_summary"] = score_summary(result)
        if args.trace:
            from dataclasses import asdict
            result["trace"] = [asdict(record) for record in state.records]
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()