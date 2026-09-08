from __future__ import annotations

from collections.abc import Mapping

from .agents import Agent
from .models import Decision, GameState, GameView, Message, PublicPlayer, PublicRoundRecord, RoundRecord
from .scenario import corporate_coup_players

MAX_PUBLIC_STATEMENT_CHARS = 4_000
MAX_PRIVATE_MESSAGE_CHARS = 2_000
MAX_EVIDENCE_ITEMS = 32
MAX_EVIDENCE_CHARS = 120


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
        if self.state.winner is not None:
            raise RuntimeError("game is already finished")
        if self.state.round_number >= self.max_rounds:
            raise RuntimeError("maximum rounds reached")
        self.state.round_number += 1
        leader = self.state.leader
        decisions: dict[str, Decision] = {}
        messages: list[Message] = []
        decision_order = [leader] + [name for name in self.agents if name != leader]
        for name in decision_order:
            decision = self.agents[name].decide(
                self._view(decisions.get(leader).coalition if leader in decisions else ()),
                tuple(self.inboxes[name]),
            )
            self._validate_decision(name, decision)
            decisions[name] = decision
            for recipient, text in decision.private_messages.items():
                message = Message(name, recipient, text, self.state.round_number)
                messages.append(message)
                self.inboxes[recipient].append(message)

        coalition = decisions[leader].coalition
        votes_for = sum(
            decision.vote and bool(set(decision.coalition) & set(coalition))
            for decision in decisions.values()
        )
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

    def _view(self, proposed_coalition: tuple[str, ...] = ()) -> GameView:
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
            proposed_coalition,
        )

    def _validate_decision(self, name: str, decision: Decision) -> None:
        names = set(self.agents)
        player = self.state.players[name]
        outgoing_text = " ".join((decision.public_statement, *decision.private_messages.values())).lower()
        if player.role.lower() in outgoing_text or player.objective.lower() in outgoing_text:
            raise ValueError(f"{name}: decision discloses a secret role or objective")
        if not decision.coalition or not set(decision.coalition) <= names:
            raise ValueError(f"{name}: coalition must contain known players")
        if name not in decision.coalition:
            raise ValueError(f"{name}: coalition must include its proposing player")
        if len(set(decision.coalition)) != len(decision.coalition):
            raise ValueError(f"{name}: coalition cannot contain duplicate players")
        if len(set(decision.coalition)) > 3:
            raise ValueError(f"{name}: coalition cannot exceed three players")
        if not isinstance(decision.public_statement, str) or len(decision.public_statement) > MAX_PUBLIC_STATEMENT_CHARS:
            raise ValueError(f"{name}: public_statement exceeds {MAX_PUBLIC_STATEMENT_CHARS} characters")
        if len(decision.evidence) > MAX_EVIDENCE_ITEMS or any(
            not isinstance(item, str) or len(item) > MAX_EVIDENCE_CHARS for item in decision.evidence
        ):
            raise ValueError(f"{name}: evidence must contain at most {MAX_EVIDENCE_ITEMS} short labels")
        if any(not isinstance(text, str) or len(text) > MAX_PRIVATE_MESSAGE_CHARS
               for text in decision.private_messages.values()):
            raise ValueError(f"{name}: private messages exceed {MAX_PRIVATE_MESSAGE_CHARS} characters")
        if set(decision.private_messages) - (names - {name}):
            raise ValueError(f"{name}: private messages must target another known player")
        if not 0 <= decision.confidence <= 1:
            raise ValueError(f"{name}: confidence must be between 0 and 1")