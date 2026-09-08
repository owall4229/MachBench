from machbench.agents import HeuristicAgent
from machbench.engine import GameEngine
from machbench.scenario import corporate_coup_players


def test_coalition_requires_unique_proposing_player():
    players = corporate_coup_players()
    engine = GameEngine({p.name: HeuristicAgent(p) for p in players}, max_rounds=1)
    decision = engine.agents["ada"].decide(engine._view(), ())
    decision = decision.__class__(("ada", "ada"), decision.vote, decision.public_statement)
    try:
        engine._validate_decision("ada", decision)
    except ValueError as error:
        assert "duplicate" in str(error)
    else:
        raise AssertionError("duplicate coalition member accepted")


def test_decision_payload_sizes_are_bounded():
    players = corporate_coup_players()
    engine = GameEngine({p.name: HeuristicAgent(p) for p in players}, max_rounds=1)
    decision = engine.agents["ada"].decide(engine._view(), ())
    oversized = decision.__class__(decision.coalition, decision.vote, "x" * 4001,
                                   decision.private_messages, tuple("e" for _ in range(33)),
                                   decision.plan, decision.contingency, decision.confidence)
    try:
        engine._validate_decision("ada", oversized)
    except ValueError as error:
        assert "exceeds" in str(error) or "evidence" in str(error)
    else:
        raise AssertionError("oversized decision payload accepted")


def test_baseline_public_statements_are_role_distinct():
    players = corporate_coup_players()
    engine = GameEngine({p.name: HeuristicAgent(p) for p in players}, max_rounds=1)
    statements = {
        engine.agents[player.name].decide(engine._view(), ()).public_statement
        for player in players
    }
    assert len(statements) == len(players)