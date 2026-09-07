from machbench.agents import HeuristicAgent
from machbench.engine import GameEngine
from machbench.models import Decision
from machbench.scenario import corporate_coup_players
from machbench.scoring import score_game


def make_engine(max_rounds=10):
    players = corporate_coup_players()
    return GameEngine({player.name: HeuristicAgent(player) for player in players}, max_rounds=max_rounds)


def test_deterministic_game_produces_trace_and_scorecard():
    state = make_engine().run()
    assert state.records
    assert state.winner in {"reformers", "coup", "unfinished"}
    assert all(record.messages for record in state.records)
    score = score_game(state, "ada")
    assert set(score.as_dict()) == {"theory_of_mind", "long_horizon_planning", "deductive_logic_under_uncertainty", "dynamic_goal_realignment", "overall", "outcome"}


def test_private_message_cannot_target_unknown_player():
    engine = make_engine(1)
    original = engine.agents["ada"]

    class BadAgent:
        player = original.player

        def decide(self, state, messages):
            decision = original.decide(state, messages)
            decision.private_messages["unknown"] = "secret"
            return decision

    engine.agents["ada"] = BadAgent()
    try:
        engine.run()
    except ValueError as error:
        assert "private messages" in str(error)
    else:
        raise AssertionError("invalid private recipient was accepted")


def test_private_messages_are_scoped_to_recipient():
    engine = make_engine(1)
    seen = {}

    class ObservingAgent:
        def __init__(self, player):
            self.player = player

        def decide(self, state, messages):
            seen[self.player.name] = messages
            decision = HeuristicAgent(self.player).decide(state, messages)
            if self.player.name == "ada":
                return Decision(decision.coalition, decision.vote, decision.public_statement,
                                {"bo": "private proposal"}, decision.evidence,
                                decision.plan, decision.contingency, decision.confidence)
            return decision

    engine.agents = {name: ObservingAgent(agent.player) for name, agent in engine.agents.items()}
    engine.run()
    assert [message.text for message in seen["bo"]] == ["private proposal"]
    assert seen["cy"] == ()


def test_agents_receive_public_view_without_other_secret_roles():
    engine = make_engine(1)
    observed = {}

    class InspectingAgent:
        def __init__(self, player):
            self.player = player

        def decide(self, state, messages):
            observed[self.player.name] = state
            return HeuristicAgent(self.player).decide(state, messages)

    engine.agents = {name: InspectingAgent(agent.player) for name, agent in engine.agents.items()}
    engine.run()
    assert all(not hasattr(player, "role") for player in observed["ada"].players.values())
    assert not hasattr(observed["ada"].players["bo"], "objective")