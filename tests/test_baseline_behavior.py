from machbench.agents import HeuristicAgent
from machbench.engine import GameEngine
from machbench.scenario import corporate_coup_players
from machbench.scoring import score_game


def test_baseline_seats_have_distinct_behavior_and_scores():
    players = corporate_coup_players()
    engine = GameEngine({player.name: HeuristicAgent(player) for player in players}, max_rounds=5)
    state = engine.run()
    first_round = state.records[0]
    coalitions = {decision.coalition for decision in first_round.decisions.values()}
    messages = {message.text for message in first_round.messages}
    assert len(coalitions) >= 4
    assert len(messages) >= 4
    theory_scores = {score_game(state, player.name).theory_of_mind for player in players}
    deduction_scores = {score_game(state, player.name).deductive_logic_under_uncertainty for player in players}
    assert len(theory_scores) > 1
    assert len(deduction_scores) > 1