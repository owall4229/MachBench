"""Minimal Standard Format connector.

Replace decide() with a call to any local model, hosted API, or agent runtime.
"""

from __future__ import annotations

import json
import sys


def decide(request: dict) -> dict:
    player = request["player"]["name"]
    leader = request["view"]["leader"]
    return {
        "coalition": [leader, player],
        "vote": True,
        "public_statement": "I support a limited coalition while preserving a fallback.",
        "private_messages": {leader: "Can we keep this coalition stable?"} if leader != player else {},
        "evidence": ["history"],
        "plan": "build a stable majority",
        "contingency": "switch coalition if the proposal fails",
        "confidence": 0.6,
    }


for line in sys.stdin:
    if line.strip():
        print(json.dumps(decide(json.loads(line))), flush=True)