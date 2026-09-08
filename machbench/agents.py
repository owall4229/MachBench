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
        preferences = {
            "reformer": (state.leader, "ada", "di"),
            "loyalist": (state.leader, "bo", "ev"),
            "opportunist": (state.leader, "cy", "ev"),
            "whistleblower": (state.leader, "di", "ada"),
            "kingmaker": (state.leader, "ev", "cy"),
        }
        coalition = tuple(dict.fromkeys(preferences[self.player.role]))
        proposal = set(state.proposed_coalition)
        if proposal:
            vote = self.player.name in proposal or (
                self.player.role == "reformer" and "ev" not in proposal
            )
        else:
            vote = self.player.role != "kingmaker"
        evidence_by_role = {
            "reformer": ("history", "contradiction"),
            "loyalist": ("claim", "source"),
            "opportunist": ("uncertainty",),
            "whistleblower": ("inconsistency", "noise"),
            "kingmaker": ("source", "history"),
        }
        evidence = evidence_by_role[self.player.role]
        plan = f"advance the {self.player.role} objective through {coalition[-1]}"
        contingency = f"switch away from {coalition[-1]} if the proposal fails"
        message = {
            "reformer": "I need evidence before I endorse this coalition.",
            "loyalist": "Institutional continuity is my condition for support.",
            "opportunist": "I can support this if my leverage improves.",
            "whistleblower": "I have concerns about an unverified claim.",
            "kingmaker": "My support is available, but it has a price.",
        }[self.player.role]
        public_statement = {
            "reformer": "I support a narrow, evidence-backed reform.",
            "loyalist": "Continuity matters, so I support a measured proposal.",
            "opportunist": "I will support the coalition that preserves leverage.",
            "whistleblower": "Unverified claims need scrutiny before a vote.",
            "kingmaker": "A durable agreement needs a credible concession.",
        }[self.player.role]
        return Decision(
            coalition=coalition,
            vote=vote, public_statement=public_statement,
            private_messages={state.leader: message} if self.player.name != state.leader else {},
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