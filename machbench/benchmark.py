from __future__ import annotations

from dataclasses import asdict
from typing import Any

from .engine import GameEngine
from .models import GameState
from .scenario import corporate_coup_players
from .scoring import score_game
from .standard import ModelClient, StandardAgent


def run_standard(client: ModelClient, player_name: str = "ada", max_rounds: int = 10,
                 model_name: str = "unknown-model") -> dict[str, Any]:
    """Run the same model as every seat and return a portable benchmark report."""
    players = corporate_coup_players()
    agents = {player.name: StandardAgent(player, client) for player in players}
    state = GameEngine(agents, max_rounds=max_rounds).run()
    return report(state, player_name, model_name)


def report(state: GameState, player_name: str, model_name: str = "unknown-model") -> dict[str, Any]:
    scores = {name: score_game(state, name).as_dict() for name in state.players}
    selected = score_game(state, player_name)
    result = {
        "format": "machbench/report/v1", "task": "corporate_boardroom_coup",
        "model": model_name, "player": player_name, "rounds": len(state.records), "reforms": state.reforms,
        "failed_votes": state.failed_votes, "winner": state.winner,
        "score": selected.as_dict(), "measurement": selected.measured(selected.evidence), "scores": scores,
        "trace": [asdict(record) for record in state.records],
    }
    result["score_summary"] = score_summary(result)
    return result


def score_summary(report_data: dict[str, Any]) -> str:
    measurement = report_data["measurement"]
    dimensions = measurement.get("dimensions", {})
    details = ", ".join(
        f"{name.replace('_', ' ')} {values.get('points', 0)}/{values.get('max_points', 100)}"
        for name, values in dimensions.items()
    )
    return (f"Model {report_data.get('model', 'unknown-model')} finished with "
            f"{measurement.get('points', 0)}/{measurement.get('max_points', 100)} points "
            f"({report_data.get('winner')}). Dimensions: {details}.")