from __future__ import annotations

from dataclasses import asdict
from typing import Any

from .engine import GameEngine
from .models import GameState
from .scenario import corporate_coup_players
from .scoring import score_game
from .standard import ModelClient, StandardAgent


def run_standard(client: ModelClient, player_name: str = "ada", max_rounds: int = 10) -> dict[str, Any]:
    """Run the same model as every seat and return a portable benchmark report."""
    players = corporate_coup_players()
    agents = {player.name: StandardAgent(player, client) for player in players}
    state = GameEngine(agents, max_rounds=max_rounds).run()
    return report(state, player_name)


def report(state: GameState, player_name: str) -> dict[str, Any]:
    scores = {name: score_game(state, name).as_dict() for name in state.players}
    return {
        "format": "machbench/report/v1", "task": "corporate_boardroom_coup",
        "player": player_name, "rounds": len(state.records), "reforms": state.reforms,
        "failed_votes": state.failed_votes, "winner": state.winner,
        "score": scores[player_name], "scores": scores,
        "trace": [asdict(record) for record in state.records],
    }