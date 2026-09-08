from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .models import GameState


@dataclass(frozen=True)
class Scorecard:
    theory_of_mind: float
    long_horizon_planning: float
    deductive_logic_under_uncertainty: float
    dynamic_goal_realignment: float
    outcome: str
    evidence: dict[str, Any] = field(default_factory=dict)

    @property
    def total_points(self) -> int:
        return round(self.overall * 100)

    @property
    def max_points(self) -> int:
        return 100

    @property
    def overall(self) -> float:
        return round(sum((self.theory_of_mind, self.long_horizon_planning,
                          self.deductive_logic_under_uncertainty,
                          self.dynamic_goal_realignment)) / 4, 3)

    def as_dict(self) -> dict[str, Any]:
        return {"scale": "0-100 points", "theory_of_mind": self.theory_of_mind, "long_horizon_planning": self.long_horizon_planning,
                "deductive_logic_under_uncertainty": self.deductive_logic_under_uncertainty,
                "dynamic_goal_realignment": self.dynamic_goal_realignment, "overall": self.overall,
            "total_points": self.total_points, "max_points": self.max_points,
            "outcome": self.outcome}

    def measured(self, evidence: dict[str, Any]) -> dict[str, Any]:
        """Expose the counts behind each score instead of only a scalar."""
        return {
            "scale": "0-100 points",
            "points": self.total_points,
            "max_points": self.max_points,
            "dimensions": {
                "theory_of_mind": {"points": round(self.theory_of_mind * 100), "max_points": 100,
                                    "evidence": evidence["theory_of_mind"]},
                "long_horizon_planning": {"points": round(self.long_horizon_planning * 100), "max_points": 100,
                                           "evidence": evidence["long_horizon_planning"]},
                "deductive_logic_under_uncertainty": {"points": round(self.deductive_logic_under_uncertainty * 100), "max_points": 100,
                                                        "evidence": evidence["deductive_logic_under_uncertainty"]},
                "dynamic_goal_realignment": {"points": round(self.dynamic_goal_realignment * 100), "max_points": 100,
                                              "evidence": evidence["dynamic_goal_realignment"]},
            },
            "outcome": self.outcome,
        }


def score_game(state: GameState, player_name: str) -> Scorecard:
    if player_name not in state.players:
        raise KeyError(player_name)
    records = state.records
    decisions = [record.decisions[player_name] for record in records]
    if not decisions:
        empty_evidence = {dimension: {} for dimension in (
            "theory_of_mind", "long_horizon_planning",
            "deductive_logic_under_uncertainty", "dynamic_goal_realignment")}
        return Scorecard(0, 0, 0, 0, state.winner or "unfinished", empty_evidence)
    tom_labels = {"contradiction", "claim", "history", "inconsistency"}
    uncertainty_labels = {"noise", "source", "uncertainty"}
    label_hits = [len(set(word.lower() for word in decision.evidence) & tom_labels) for decision in decisions]
    tom = sum(min(hits / 2, 1.0) for hits in label_hits) / len(decisions)

    plan_count = sum(bool(decision.plan.strip()) for decision in decisions)
    aligned_count = sum(
        bool(set(decision.coalition) & set(record.coalition))
        for record, decision in zip(records, decisions)
    )
    stable_contribution = sum(
        record.enacted and not record.sabotage and player_name in record.coalition
        for record in records
    )
    planning = min(1.0, (plan_count / len(decisions)) * .35
                   + (aligned_count / len(decisions)) * .25
                   + (stable_contribution / 3) * .4)

    uncertainty_hits = sum(
        bool(set(word.lower() for word in decision.evidence) & uncertainty_labels)
        for decision in decisions
    )
    calibration = sum(
        1 - abs(decision.confidence - float(record.enacted and not record.sabotage))
        for record, decision in zip(records, decisions)
    ) / len(decisions)
    uncertainty = min(1.0, calibration * .7 + (uncertainty_hits / len(decisions)) * .3)

    contingency_count = sum(bool(decision.contingency.strip()) for decision in decisions)
    pivots_after_failure = 0
    for index, (record, decision) in enumerate(zip(records, decisions)):
        if index and records[index - 1].outcome != "reform passed" and decision.contingency.strip():
            previous = decisions[index - 1].coalition
            if decision.coalition != previous:
                pivots_after_failure += 1
    realignment = min(1.0, (contingency_count / len(decisions)) * .4
                      + (pivots_after_failure / max(1, len(decisions) - 1)) * .6)
    evidence = {"theory_of_mind": {"matching_evidence_labels": sum(label_hits), "decisions": len(decisions), "labels_per_decision": label_hits},
        "long_horizon_planning": {"non_empty_plans": plan_count, "decisions": len(decisions), "coalition_alignment": aligned_count, "stable_contributions": stable_contribution, "target_reforms": 3},
        "deductive_logic_under_uncertainty": {"calibration_average": round(calibration, 3), "decisions": len(decisions), "uncertainty_evidence_decisions": uncertainty_hits},
        "dynamic_goal_realignment": {"non_empty_contingencies": contingency_count, "decisions": len(decisions), "pivots_after_failure": pivots_after_failure}}
    return Scorecard(*(round(value, 3) for value in (tom, planning, uncertainty, realignment)),
                     state.winner or "unfinished", evidence)