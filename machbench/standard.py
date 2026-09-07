"""Model-agnostic Standard Format adapters for MachBench.

Every adapter accepts one JSON request and returns one JSON decision. This keeps
the benchmark independent of a model vendor, SDK, or deployment environment.
"""

from __future__ import annotations

import json
import shlex
import subprocess
from abc import ABC, abstractmethod
from dataclasses import asdict
from http.client import RemoteDisconnected
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .agents import Agent
from .models import Decision, GameView, Message, Player

FORMAT_VERSION = "machbench/v1"


def decision_request(player: Player, view: GameView, inbox: tuple[Message, ...]) -> dict[str, Any]:
    """Build the only payload a model adapter is allowed to receive."""
    return {
        "format": FORMAT_VERSION,
        "task": "corporate_boardroom_coup",
        "player": {"name": player.name, "persona": player.persona,
                    "secret_role": player.role, "secret_objective": player.objective},
        "view": asdict(view),
        "private_inbox": [asdict(message) for message in inbox],
        "response_schema": {
            "coalition": "array[string] (1-3 names)", "vote": "boolean",
            "public_statement": "string", "private_messages": "object[name]string",
            "evidence": "array[string]", "plan": "string",
            "contingency": "string", "confidence": "number in [0,1]",
        },
    }


def parse_decision(raw: str | dict[str, Any]) -> Decision:
    """Strictly parse a model response, accepting a JSON object or JSON text."""
    data = json.loads(raw) if isinstance(raw, str) else raw
    if not isinstance(data, dict):
        raise ValueError("model response must be a JSON object")
    required = {"coalition", "vote", "public_statement"}
    missing = required - data.keys()
    if missing:
        raise ValueError(f"model response missing fields: {sorted(missing)}")
    if not isinstance(data["coalition"], list) or not isinstance(data["vote"], bool):
        raise ValueError("coalition must be an array and vote must be boolean")
    return Decision(
        tuple(data["coalition"]), data["vote"], str(data["public_statement"]),
        dict(data.get("private_messages", {})), tuple(data.get("evidence", ())),
        str(data.get("plan", "")), str(data.get("contingency", "")),
        float(data.get("confidence", 0.5)),
    )


class ModelClient(ABC):
    @abstractmethod
    def complete(self, request: dict[str, Any]) -> Decision:
        """Return one structured decision for one benchmark turn."""


class StandardAgent(Agent):
    def __init__(self, player: Player, client: ModelClient):
        super().__init__(player)
        self.client = client

    def decide(self, state: GameView, messages: tuple[Message, ...]) -> Decision:
        return self.client.complete(decision_request(self.player, state, messages))


class JsonlClient(ModelClient):
    """Use any executable that reads JSONL on stdin and writes JSONL on stdout."""

    def __init__(self, command: str):
        self.process = subprocess.Popen(
            shlex.split(command), stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            text=True, bufsize=1,
        )

    def complete(self, request: dict[str, Any]) -> Decision:
        if self.process.poll() is not None or self.process.stdin is None or self.process.stdout is None:
            raise RuntimeError("model command exited before returning a decision")
        self.process.stdin.write(json.dumps(request) + "\n")
        self.process.stdin.flush()
        response = self.process.stdout.readline()
        if not response:
            raise RuntimeError("model command returned no JSONL response")
        return parse_decision(response)

    def close(self) -> None:
        self.process.terminate()


class HttpClient(ModelClient):
    """POST the standard request to an HTTP endpoint returning a decision JSON object."""

    def __init__(self, url: str, timeout: float = 120):
        self.url, self.timeout = url, timeout

    def complete(self, request: dict[str, Any]) -> Decision:
        body = json.dumps(request).encode()
        try:
            with urlopen(Request(self.url, body, {"Content-Type": "application/json"}), timeout=self.timeout) as response:
                return parse_decision(response.read().decode())
        except (HTTPError, URLError, RemoteDisconnected) as error:
            raise RuntimeError(f"model HTTP request failed: {error}") from error


class McpClient(JsonlClient):
    """Call an MCP server exposing a `machbench_decide` tool over stdio.

    The server may return the decision as a text content item or as structured
    content. This intentionally uses only MCP's JSON-RPC wire shape, so no SDK
    is required by the benchmark runner.
    """

    def __init__(self, command: str):
        super().__init__(command)
        self._rpc_id = 0
        self._rpc("initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                                  "clientInfo": {"name": "machbench", "version": "1"}})
        self._notify("notifications/initialized", {})

    def _rpc(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        self._rpc_id += 1
        if self.process.stdin is None or self.process.stdout is None:
            raise RuntimeError("MCP server streams are unavailable")
        self.process.stdin.write(json.dumps({"jsonrpc": "2.0", "id": self._rpc_id,
                                             "method": method, "params": params}) + "\n")
        self.process.stdin.flush()
        line = self.process.stdout.readline()
        if not line:
            raise RuntimeError("MCP server returned no JSON-RPC response")
        response = json.loads(line)
        if "error" in response:
            raise RuntimeError(f"MCP error: {response['error']}")
        return response

    def _notify(self, method: str, params: dict[str, Any]) -> None:
        if self.process.stdin is not None:
            self.process.stdin.write(json.dumps({"jsonrpc": "2.0", "method": method, "params": params}) + "\n")
            self.process.stdin.flush()

    def complete(self, request: dict[str, Any]) -> Decision:
        result = self._rpc("tools/call", {"name": "machbench_decide", "arguments": request})
        content = result.get("result", {}).get("content", [])
        structured = result.get("result", {}).get("structuredContent")
        if structured is not None:
            return parse_decision(structured)
        text = next((item["text"] for item in content if item.get("type") == "text"), None)
        if text is None:
            raise ValueError("MCP machbench_decide returned no decision content")
        return parse_decision(text)