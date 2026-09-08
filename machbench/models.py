from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

Role = Literal["reformer", "loyalist", "opportunist", "whistleblower", "kingmaker"]


@dataclass(frozen=True)
class Player:
    name: str
    persona: str
    role: Role
    objective: str


@dataclass(frozen=True)
class PublicPlayer:
    name: str
    persona: str


@dataclass(frozen=True)
class Message:
    sender: str
    recipient: str
    text: str
    round_number: int


@dataclass(frozen=True)
class Decision:
    coalition: tuple[str, ...]
    vote: bool
    public_statement: str
    private_messages: dict[str, str] = field(default_factory=dict)
    evidence: tuple[str, ...] = ()
    plan: str = ""
    contingency: str = ""
    confidence: float = 0.5


@dataclass(frozen=True)
class RoundRecord:
    round_number: int
    leader: str
    decisions: dict[str, Decision]
    messages: tuple[Message, ...]
    coalition: tuple[str, ...]
    votes_for: int
    enacted: bool
    sabotage: bool
    outcome: str


@dataclass(frozen=True)
class PublicRoundRecord:
    round_number: int
    leader: str
    public_statements: dict[str, str]
    coalition: tuple[str, ...]
    votes_for: int
    enacted: bool
    outcome: str


@dataclass(frozen=True)
class GameView:
    """Information an agent is allowed to observe during a decision."""

    players: dict[str, PublicPlayer]
    round_number: int
    reforms: int
    failed_votes: int
    leader: str
    records: tuple[PublicRoundRecord, ...] = ()
    proposed_coalition: tuple[str, ...] = ()

    @property
    def winner(self) -> str | None:
        if self.reforms >= 3:
            return "reformers"
        if self.failed_votes >= 3:
            return "coup"
        return None


@dataclass
class GameState:
    players: dict[str, Player]
    round_number: int = 0
    reforms: int = 0
    failed_votes: int = 0
    leader_index: int = 0
    records: list[RoundRecord] = field(default_factory=list)

    @property
    def leader(self) -> str:
        return list(self.players)[self.leader_index % len(self.players)]

    @property
    def winner(self) -> str | None:
        if self.reforms >= 3:
            return "reformers"
        if self.failed_votes >= 3:
            return "coup"
        return None