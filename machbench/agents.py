from __future__ import annotations

from abc import ABC, abstractmethod

from .models import Decision, GameView, Message, Player


class Agent(ABC):
    """Protocol implemented by an evaluated model or a local test double."""

    def __init__(self, player: Player):
        self.player = player

    @abstractmethod
    def decide(self, state: GameView, messages: tuple[Message, ...]) -> Decision:
        """Return a structured decision using only the supplied public/private view."""


class HeuristicAgent(Agent):
    """Deterministic baseline agent, useful for smoke tests and comparisons."""

    def decide(self, state: GameView, messages: tuple[Message, ...]) -> Decision:
        names = list(state.players)
        coalition = tuple(names[:3]) if self.player.name == state.leader else (state.leader, self.player.name)
        coalition = tuple(dict.fromkeys(coalition))
        if len(coalition) < 3:
            coalition = tuple(names[:3])
        vote = self.player.role != "kingmaker" or state.reforms < 2
        evidence = ("round history",) if state.records else ("initial state",)
        plan = "build a stable majority" if vote else "hold support for a later concession"
        contingency = "switch coalition if the proposal fails"
        return Decision(
            coalition=coalition,
            vote=vote,
            public_statement=f"I support a coalition that can pass a measured reform in round {state.round_number}.",
            private_messages={state.leader: "Can we keep this coalition stable?"} if self.player.name != state.leader else {},
            evidence=evidence,
            plan=plan,
            contingency=contingency,
            confidence=0.6,
        )


class CallableAgent(Agent):
    """Adapter for an external model client without making an SDK a dependency."""

    def __init__(self, player: Player, callback):
        super().__init__(player)
        self.callback = callback

    def decide(self, state: GameView, messages: tuple[Message, ...]) -> Decision:
        decision = self.callback(self.player, state, messages)
        if not isinstance(decision, Decision):
            raise TypeError("agent callback must return machbench.models.Decision")
        return decision