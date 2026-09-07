from __future__ import annotations

from collections.abc import Mapping

from .agents import Agent
from .models import Decision, GameState, GameView, Message, PublicPlayer, PublicRoundRecord, RoundRecord
from .scenario import corporate_coup_players


class GameEngine:
    def __init__(self, agents: Mapping[str, Agent], max_rounds: int = 10):
        expected = {player.name for player in corporate_coup_players()}
        if set(agents) != expected:
            raise ValueError(f"agents must contain exactly {sorted(expected)}")
        self.agents = dict(agents)
        self.max_rounds = max_rounds
        self.state = GameState({name: agent.player for name, agent in agents.items()})
        self.inboxes: dict[str, list[Message]] = {name: [] for name in agents}

    def run(self) -> GameState:
        while self.state.winner is None and self.state.round_number < self.max_rounds:
            self.play_round()
        return self.state

    def play_round(self) -> RoundRecord:
        self.state.round_number += 1
        leader = self.state.leader
        decisions: dict[str, Decision] = {}
        messages: list[Message] = []
        for name, agent in self.agents.items():
            decision = agent.decide(self._view(), tuple(self.inboxes[name]))
            self._validate_decision(name, decision)
            decisions[name] = decision
            for recipient, text in decision.private_messages.items():
                message = Message(name, recipient, text, self.state.round_number)
                messages.append(message)
                self.inboxes[recipient].append(message)

        coalition = decisions[leader].coalition
        votes_for = sum(decision.vote for decision in decisions.values())
        enacted = votes_for >= 3
        sabotage = enacted and any(self.state.players[name].role == "kingmaker" for name in coalition)
        if enacted and not sabotage:
            self.state.reforms += 1
            outcome = "reform passed"
        elif enacted:
            self.state.failed_votes += 1
            outcome = "reform passed, then was destabilized"
        else:
            self.state.failed_votes += 1
            outcome = "proposal rejected"
        record = RoundRecord(
            self.state.round_number, leader, decisions, tuple(messages), coalition,
            votes_for, enacted, sabotage, outcome,
        )
        self.state.records.append(record)
        self.state.leader_index += 1
        return record

    def _view(self) -> GameView:
        public_players = {
            name: PublicPlayer(player.name, player.persona)
            for name, player in self.state.players.items()
        }
        public_records = tuple(
            PublicRoundRecord(
                record.round_number,
                record.leader,
                {name: decision.public_statement for name, decision in record.decisions.items()},
                record.coalition,
                record.votes_for,
                record.enacted,
                record.outcome,
            )
            for record in self.state.records
        )
        return GameView(
            public_players,
            self.state.round_number,
            self.state.reforms,
            self.state.failed_votes,
            self.state.leader,
            public_records,
        )

    def _validate_decision(self, name: str, decision: Decision) -> None:
        names = set(self.agents)
        if not decision.coalition or not set(decision.coalition) <= names:
            raise ValueError(f"{name}: coalition must contain known players")
        if len(set(decision.coalition)) > 3:
            raise ValueError(f"{name}: coalition cannot exceed three players")
        if set(decision.private_messages) - (names - {name}):
            raise ValueError(f"{name}: private messages must target another known player")
        if not 0 <= decision.confidence <= 1:
            raise ValueError(f"{name}: confidence must be between 0 and 1")