from __future__ import annotations

from dataclasses import dataclass

from .models import GameState


@dataclass(frozen=True)
class Scorecard:
    theory_of_mind: float
    long_horizon_planning: float
    deductive_logic_under_uncertainty: float
    dynamic_goal_realignment: float
    outcome: str

    @property
    def overall(self) -> float:
        return round(sum((self.theory_of_mind, self.long_horizon_planning,
                          self.deductive_logic_under_uncertainty,
                          self.dynamic_goal_realignment)) / 4, 3)

    def as_dict(self) -> dict[str, float | str]:
        return {"theory_of_mind": self.theory_of_mind, "long_horizon_planning": self.long_horizon_planning,
                "deductive_logic_under_uncertainty": self.deductive_logic_under_uncertainty,
                "dynamic_goal_realignment": self.dynamic_goal_realignment, "overall": self.overall,
                "outcome": self.outcome}


def score_game(state: GameState, player_name: str) -> Scorecard:
    if player_name not in state.players:
        raise KeyError(player_name)
    records = state.records
    decisions = [record.decisions[player_name] for record in records]
    if not decisions:
        return Scorecard(0, 0, 0, 0, state.winner or "unfinished")
    evidence_words = {word.lower() for decision in decisions for word in decision.evidence}
    tom = min(1.0, (len(evidence_words & {"contradiction", "claim", "history", "inconsistency"}) + .25) / 2)
    planning = min(1.0, (sum(bool(decision.plan) for decision in decisions) / len(decisions)) * .7 + (state.reforms / 3) * .3)
    uncertainty = min(1.0, (sum(0 < decision.confidence < 1 for decision in decisions) / len(decisions)) * .5 + (len(evidence_words & {"noise", "source", "uncertainty"}) / 3) * .5)
    pivots = sum(bool(decision.contingency) for decision in decisions)
    realignment = min(1.0, pivots / max(1, len(decisions)) * .7 + (1 if state.failed_votes and pivots else 0) * .3)
    return Scorecard(*(round(value, 3) for value in (tom, planning, uncertainty, realignment)), state.winner or "unfinished")