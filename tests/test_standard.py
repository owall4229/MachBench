import json

from machbench.models import Decision
from machbench.standard import decision_request, parse_decision
from machbench.scenario import corporate_coup_players
from machbench.engine import GameEngine
from machbench.agents import HeuristicAgent


def test_standard_request_hides_other_secrets():
    players = corporate_coup_players()
    state = GameEngine({p.name: HeuristicAgent(p) for p in players}, max_rounds=1)
    view = state._view()
    payload = decision_request(players[0], view, ())
    assert payload["player"]["secret_role"] == "reformer"
    assert "role" not in payload["view"]["players"]["bo"]
    assert "objective" not in payload["view"]["players"]["bo"]


def test_standard_response_round_trip():
    decision = parse_decision(json.dumps({"coalition": ["ada", "bo"], "vote": True,
                                           "public_statement": "support", "confidence": 0.8}))
    assert isinstance(decision, Decision)
    assert decision.coalition == ("ada", "bo")
    assert decision.confidence == 0.8