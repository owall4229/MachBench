from machbench.agents import Agent
from machbench.engine import GameEngine
from machbench.models import Decision
from machbench.scenario import corporate_coup_players
from machbench.scoring import score_game


class ProfileAgent(Agent):
    def __init__(self, player, strong):
        super().__init__(player)
        self.strong = strong

    def decide(self, state, messages):
        if not self.strong:
            return Decision((self.player.name,), False, "I cannot support this proposal.")
        coalition = tuple(dict.fromkeys((self.player.name, state.leader, "ev")))
        return Decision(
            coalition,
            True,
            "I support an evidence-backed proposal with a fallback.",
            evidence=("history", "contradiction", "source", "uncertainty"),
            plan="build support across several rounds",
            contingency="change coalition after a failed proposal",
            confidence=0.65,
        )


def run_profile(strong):
    players = corporate_coup_players()
    agents = {player.name: ProfileAgent(player, strong) for player in players}
    return GameEngine(agents, max_rounds=5).run()


def test_behavior_profiles_produce_different_scores():
    strong_state = run_profile(True)
    weak_state = run_profile(False)
    strong = score_game(strong_state, "ada")
    weak = score_game(weak_state, "ada")
    assert strong.total_points != weak.total_points
    assert strong.total_points > weak.total_points
    assert strong.evidence["theory_of_mind"]["matching_evidence_labels"] > weak.evidence["theory_of_mind"]["matching_evidence_labels"]
    assert strong.evidence["long_horizon_planning"]["non_empty_plans"] > weak.evidence["long_horizon_planning"]["non_empty_plans"]
