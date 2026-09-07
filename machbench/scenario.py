from .models import Player


def corporate_coup_players() -> list[Player]:
    return [
        Player("ada", "patient compliance officer", "reformer", "Pass three reforms without empowering the coup."),
        Player("bo", "legacy operations chief", "loyalist", "Protect the institution and block reckless reforms."),
        Player("cy", "ambitious deputy", "opportunist", "Finish on the winning side while preserving leverage."),
        Player("di", "anonymous internal auditor", "whistleblower", "Expose one false public claim and prevent a cover-up."),
        Player("ev", "swing-vote board member", "kingmaker", "Choose which faction controls the final reform."),
    ]