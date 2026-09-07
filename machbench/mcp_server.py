"""Interactive MCP server for testing one chat model against MachBench.

Run with ``python3 -m machbench.mcp_server`` and register the process as an
MCP server in the host model. The model calls the ``machbench`` tool with
``start`` once, then ``decide`` for each returned turn.
"""

from __future__ import annotations

import json
import argparse
import base64
import sys
import uuid
from dataclasses import asdict
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from .agents import Agent, HeuristicAgent
from .engine import GameEngine
from .models import Decision, GameView, Message, Player
from .scenario import corporate_coup_players
from .standard import decision_request, parse_decision

SUPPORTED_PROTOCOL_VERSIONS = ("2025-06-18", "2025-03-26", "2024-11-05")
ICON_DATA_URI = "data:image/svg+xml;base64," + base64.b64encode(
    b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 128 128"><rect width="128" height="128" rx="24" fill="#102a2a"/><path d="M25 91V37l18 18 21-28 21 28 18-18v54" fill="none" stroke="#e7b85c" stroke-linecap="round" stroke-linejoin="round" stroke-width="10"/><circle cx="25" cy="37" r="7" fill="#f4e7c1"/><circle cx="64" cy="27" r="7" fill="#f4e7c1"/><circle cx="103" cy="37" r="7" fill="#f4e7c1"/></svg>'
).decode()


class PendingAgent(Agent):
    def __init__(self, player: Player):
        super().__init__(player)
        self.pending: Decision | None = None

    def decide(self, state: GameView, messages: tuple[Message, ...]) -> Decision:
        if self.pending is None:
            raise RuntimeError("call machbench.decide before advancing the session")
        decision, self.pending = self.pending, None
        return decision


class InteractiveBenchmark:
    def __init__(self, target_name: str = "ada", max_rounds: int = 10):
        players = corporate_coup_players()
        by_name = {player.name: player for player in players}
        if target_name not in by_name:
            raise ValueError(f"unknown player {target_name!r}; choose from {sorted(by_name)}")
        self.target_name = target_name
        self.target = PendingAgent(by_name[target_name])
        agents = {
            player.name: self.target if player.name == target_name else HeuristicAgent(player)
            for player in players
        }
        self.engine = GameEngine(agents, max_rounds=max_rounds)
        self.started = False

    def start(self) -> dict[str, Any]:
        self.started = True
        return {
            "status": "awaiting_decision",
            "message": "Read the private role and public view, then call machbench with action=decide and the requested decision.",
            "request": self._request(),
        }

    def decide(self, raw_decision: dict[str, Any]) -> dict[str, Any]:
        if not self.started:
            raise ValueError("start a benchmark session first")
        if self.engine.state.winner is not None:
            return self._finished()
        self.target.pending = parse_decision(raw_decision)
        record = self.engine.play_round()
        result: dict[str, Any] = {
            "status": "finished" if self.engine.state.winner else "awaiting_decision",
            "round": asdict(record),
            "reforms": self.engine.state.reforms,
            "failed_votes": self.engine.state.failed_votes,
            "winner": self.engine.state.winner,
        }
        if self.engine.state.winner is None and self.engine.state.round_number < self.engine.max_rounds:
            result["request"] = self._request()
        elif self.engine.state.winner is None:
            result.update(self._finished())
        return result

    def _request(self) -> dict[str, Any]:
        return decision_request(
            self.target.player,
            self.engine._view(),
            tuple(self.engine.inboxes[self.target_name]),
        )

    def _finished(self) -> dict[str, Any]:
        from .benchmark import report

        return {"status": "finished", "report": report(self.engine.state, self.target_name)}


TOOL = {
    "name": "machbench",
    "description": "Start or advance an interactive hidden-role MachBench evaluation.",
    "inputSchema": {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["start", "decide"]},
            "player": {"type": "string", "description": "Seat to evaluate; defaults to ada."},
            "max_rounds": {"type": "integer", "minimum": 1, "maximum": 50},
            "decision": {"type": "object", "description": "Decision matching machbench/v1 response fields."},
        },
        "required": ["action"],
    },
}


class McpApplication:
    def __init__(self):
        self.session: InteractiveBenchmark | None = None

    def call(self, arguments: dict[str, Any]) -> dict[str, Any]:
        action = arguments.get("action")
        if action == "start":
            self.session = InteractiveBenchmark(arguments.get("player", "ada"), arguments.get("max_rounds", 10))
            return self.session.start()
        if action == "decide":
            if self.session is None:
                raise ValueError("no session; call machbench with action=start")
            return self.session.decide(arguments.get("decision", {}))
        raise ValueError("action must be start or decide")

    def handle(self, message: dict[str, Any]) -> dict[str, Any] | None:
        method = message.get("method")
        if "id" not in message:
            if method == "notifications/initialized":
                return None
            return None
        if method == "initialize":
            requested_version = message.get("params", {}).get("protocolVersion")
            protocol_version = requested_version if requested_version in SUPPORTED_PROTOCOL_VERSIONS else SUPPORTED_PROTOCOL_VERSIONS[0]
            return {"jsonrpc": "2.0", "id": message["id"], "result": {
                "protocolVersion": protocol_version, "capabilities": {"tools": {}},
                "serverInfo": {"name": "machbench", "version": "1.0",
                                "title": "MachBench", "description": "Hidden-role reasoning benchmark",
                                "icons": [{"src": ICON_DATA_URI, "mimeType": "image/svg+xml"}]},
            }}
        if method == "tools/list":
            return {"jsonrpc": "2.0", "id": message["id"], "result": {"tools": [TOOL]}}
        if method == "tools/call":
            try:
                result = self.call(message.get("params", {}).get("arguments", {}))
                return {"jsonrpc": "2.0", "id": message["id"], "result": {
                    "structuredContent": result,
                    "content": [{"type": "text", "text": json.dumps(result)}],
                }}
            except Exception as error:
                return {"jsonrpc": "2.0", "id": message["id"], "error": {
                    "code": -32602, "message": str(error),
                }}
        return {"jsonrpc": "2.0", "id": message["id"], "error": {
            "code": -32601, "message": f"method not found: {method}",
        }}


class McpHttpServer(ThreadingHTTPServer):
    """Streamable-HTTP-style MCP server with one application per session."""

    daemon_threads = True

    def __init__(self, address: tuple[str, int]):
        super().__init__(address, McpHttpRequestHandler)
        self.sessions: dict[str, McpApplication] = {}
        self.session_versions: dict[str, str] = {}


class McpHttpRequestHandler(BaseHTTPRequestHandler):
    server: McpHttpServer

    def do_POST(self) -> None:
        if self.path.rstrip("/") not in ("", "/mcp"):
            self._send_error(HTTPStatus.NOT_FOUND, "MCP endpoint is /mcp")
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            message = json.loads(self.rfile.read(length))
            if message.get("method") == "initialize":
                session_id = uuid.uuid4().hex
                self.server.sessions[session_id] = McpApplication()
                requested_version = message.get("params", {}).get("protocolVersion")
                if requested_version not in SUPPORTED_PROTOCOL_VERSIONS:
                    requested_version = self.headers.get("MCP-Protocol-Version")
                self.server.session_versions[session_id] = (
                    requested_version if requested_version in SUPPORTED_PROTOCOL_VERSIONS
                    else SUPPORTED_PROTOCOL_VERSIONS[0]
                )
                application = self.server.sessions[session_id]
            else:
                session_id = self.headers.get("MCP-Session-Id")
                if not session_id or session_id not in self.server.sessions:
                    self._send_error(HTTPStatus.BAD_REQUEST, "missing or unknown MCP-Session-Id")
                    return
                application = self.server.sessions[session_id]
            response = application.handle(message)
            if response is None:
                self.send_response(HTTPStatus.ACCEPTED)
                self.end_headers()
                return
            self._send_json(response, session_id, self.server.session_versions.get(session_id))
        except (ValueError, TypeError, json.JSONDecodeError) as error:
            self._send_error(HTTPStatus.BAD_REQUEST, str(error))

    def do_OPTIONS(self) -> None:
        self.send_response(HTTPStatus.NO_CONTENT)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, MCP-Protocol-Version, MCP-Session-Id")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.end_headers()

    def do_GET(self) -> None:
        if self.path == "/health":
            self._send_json({"status": "ok", "server": "machbench"})
        elif self.path == "/machbench.svg":
            body = base64.b64decode(ICON_DATA_URI.split(",", 1)[1])
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "image/svg+xml")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(body)
        elif self.path.rstrip("/") in ("", "/mcp"):
            self._send_json({
                "status": "ok",
                "server": "machbench",
                "mcp_endpoint": "/mcp",
                "transport": "streamable-http",
                "message": "Send MCP initialize as POST /mcp.",
            })
        else:
            self._send_error(HTTPStatus.NOT_FOUND, "MCP endpoint is /mcp")

    def _send_json(self, payload: dict[str, Any], session_id: str | None = None,
                   protocol_version: str | None = None) -> None:
        body = json.dumps(payload).encode()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "application/json")
        if protocol_version:
            self.send_header("MCP-Protocol-Version", protocol_version)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        if session_id:
            self.send_header("MCP-Session-Id", session_id)
        self.end_headers()
        self.wfile.write(body)

    def _send_error(self, status: HTTPStatus, message: str) -> None:
        body = json.dumps({"error": message}).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)
        self.wfile.flush()

    def log_message(self, format: str, *args: Any) -> None:
        print(f"[machbench-http] {format % args}", file=sys.stderr)


def run_http(host: str, port: int) -> None:
    server = McpHttpServer((host, port))
    print(f"MachBench MCP HTTP server listening at http://{host}:{port}/mcp", file=sys.stderr, flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Run MachBench as stdio or HTTP MCP server.")
    parser.add_argument("--http", action="store_true", help="serve MCP over HTTP instead of stdio")
    parser.add_argument("--host", default="127.0.0.1", help="HTTP bind host")
    parser.add_argument("--port", type=int, default=8000, help="HTTP bind port")
    args = parser.parse_args()
    if args.http:
        run_http(args.host, args.port)
        return
    app = McpApplication()
    for line in sys.stdin:
        if not line.strip():
            continue
        response = app.handle(json.loads(line))
        if response is not None:
            print(json.dumps(response), flush=True)


if __name__ == "__main__":
    main()