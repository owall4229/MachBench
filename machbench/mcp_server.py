"""Interactive MCP server for testing one chat model against MachBench.

Run with ``python3 -m machbench.mcp_server`` and register the process as an
MCP server in the host model. The model calls the ``machbench`` tool with
``start`` once, then ``decide`` for each returned turn.
"""

from __future__ import annotations

import json
import argparse
import base64
from datetime import datetime, timezone
from pathlib import Path
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
    b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 128 128"><rect width="128" height="128" rx="24" fill="#102a2a"/><path d="M18 36H110M18 36L35 91 64 54 93 91 110 36" fill="none" stroke="#5bd2c9" stroke-linecap="round" stroke-linejoin="round" stroke-width="3" opacity=".7"/><path d="M25 92V36l19 29 20-38 20 38 19-29v56" fill="none" stroke="#e7b85c" stroke-linecap="round" stroke-linejoin="round" stroke-width="9"/><circle cx="18" cy="36" r="8" fill="#f4e7c1" stroke="#102a2a" stroke-width="3"/><circle cx="64" cy="27" r="8" fill="#f4e7c1" stroke="#102a2a" stroke-width="3"/><circle cx="110" cy="36" r="8" fill="#f4e7c1" stroke="#102a2a" stroke-width="3"/></svg>'
).decode()
FAVICON_ICO = base64.b64decode(
    "AAABAAEAICAAAAEAIAAWAAAAugAAAIlQTkcNChoKAAAADUlIRFIAAAAgAAAAIAgGAAAAc3p69AAAAIFJREFUeNpjENDS+j+QmGHUAaMOGLQO+PL8IBxTYgEhcxgIaaLEEcSYQ7QDoi+dJBkPXQcMeBqA4ec7YqiS0vGZM+qAoeEAch1CjP7RKBh1wKgDyHYAuhwpaqkWAsRWWBQ5AJdmUhotZDkAZvmAOICQ5XRzAKWNDYrTwGjHZEQ4AADDOIbrtrlaUAAAAABJRU5ErkJggg=="
)
ROOT_HTML = """<!doctype html>
<html lang="en">
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>MachBench MCP Server</title><link rel="icon" href="/favicon.ico">
<style>body{margin:0;background:#102a2a;color:#f4e7c1;font:16px system-ui,sans-serif;display:grid;place-items:center;min-height:100vh}main{max-width:640px;padding:40px}h1{color:#e7b85c}code{color:#5bd2c9}</style></head>
<body><main><h1>MachBench MCP Server</h1><p>The server is running.</p><p>Connect your MCP client to <code>/mcp</code>.</p><p>Health: <a href="/health">/health</a></p></main></body>
</html>"""


class PendingAgent(Agent):
    def __init__(self, player: Player):
        super().__init__(player)
        self.pending: Decision | None = None

    def decide(self, state: GameView, messages: tuple[Message, ...]) -> Decision:
        if self.pending is None:
            raise RuntimeError("call machbench.decide before advancing the session")
        decision, self.pending = self.pending, None
        return decision


class SessionHistory:
    """Append-only JSONL plus readable Markdown storage for one session."""

    def __init__(self, directory: str | Path, session_id: str):
        self.directory = Path(directory).expanduser()
        self.directory.mkdir(parents=True, exist_ok=True)
        self.session_id = session_id
        self.path = self.directory / f"{session_id}.jsonl"
        self.readable_path = self.directory / f"{session_id}.md"
        self.report_path = self.directory / f"{session_id}.report.json"
        self.readable_path.write_text(
            f"# MachBench session `{session_id}`\n\n"
            "> Secret roles and objectives are intentionally redacted from this readable transcript.\n\n",
            encoding="utf-8",
        )

    def record(self, direction: str, method: str, payload: Any) -> None:
        payload = _redact_secrets(payload)
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "session_id": self.session_id,
            "direction": direction,
            "method": method,
            "payload": payload,
        }
        with self.path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(entry, separators=(",", ":")) + "\n")
        with self.readable_path.open("a", encoding="utf-8") as stream:
            stream.write(f"- `{entry['timestamp']}` **{direction}** `{method}`: {self._summary(payload)}\n")

    @staticmethod
    def _summary(payload: Any) -> str:
        if isinstance(payload, dict):
            params = payload.get("params", {})
            arguments = params.get("arguments", {}) if isinstance(params, dict) else {}
            if isinstance(arguments, dict) and arguments.get("action"):
                action = arguments["action"]
                model = arguments.get("model")
                return f"action=`{action}`" + (f", model=`{model}`" if model else "")
            result = payload.get("result", {})
            if isinstance(result, dict) and result.get("structuredContent"):
                content = result["structuredContent"]
                if isinstance(content, dict):
                    return f"status=`{content.get('status', 'response')}`, winner=`{content.get('winner')}`"
            if "error" in payload:
                return f"error: {payload['error'].get('message', payload['error'])}"
        return "protocol event"

    def save_report(self, report: dict[str, Any]) -> None:
        temporary = self.report_path.with_suffix(".report.json.tmp")
        temporary.write_text(json.dumps(report, indent=2), encoding="utf-8")
        temporary.replace(self.report_path)
        readable_report = self.report_path.with_suffix(".report.md")
        score = report.get("measurement", {})
        readable_report.write_text(
            f"# MachBench report: {report.get('model', 'unknown-model')}\n\n"
            f"- Winner: `{report.get('winner')}`\n"
            f"- Score: `{score.get('points', 0)}/{score.get('max_points', 100)}`\n"
            f"- Rounds: `{report.get('rounds', 0)}`\n\n"
            "## Dimension scores\n\n"
            + "\n".join(
                f"- **{name}**: {data.get('points', 0)}/{data.get('max_points', 100)}"
                for name, data in score.get("dimensions", {}).items()
            ) + "\n",
            encoding="utf-8",
        )
        from .leaderboard import write_leaderboard

        write_leaderboard(self.directory, self.directory / "leaderboard.json")
        write_leaderboard(self.directory, self.directory / "leaderboard.svg")


def _redact_secrets(value: Any) -> Any:
    """Remove secret role/objective fields from persisted human-readable history."""
    if isinstance(value, dict):
        return {
            key: "[redacted]" if key in {"secret_role", "secret_objective"}
            else _redact_secrets(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_redact_secrets(item) for item in value]
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return value
        if isinstance(parsed, (dict, list)):
            return json.dumps(_redact_secrets(parsed))
    return value


class InteractiveBenchmark:
    def __init__(self, target_name: str = "ada", max_rounds: int = 10,
                 model_name: str = "unknown-model"):
        players = corporate_coup_players()
        by_name = {player.name: player for player in players}
        if target_name not in by_name:
            raise ValueError(f"unknown player {target_name!r}; choose from {sorted(by_name)}")
        self.target_name = target_name
        self.model_name = model_name
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
        if self.engine.state.winner is not None or self.engine.state.round_number >= self.engine.max_rounds:
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
        else:
            result.update(self._finished())
        return result

    def _request(self) -> dict[str, Any]:
        return decision_request(
            self.target.player,
            self.engine._view(),
            tuple(self.engine.inboxes[self.target_name]),
        )

    def _finished(self) -> dict[str, Any]:
        from .benchmark import report, score_summary

        final_report = report(self.engine.state, self.target_name, self.model_name)
        return {"status": "finished", "message": score_summary(final_report), "report": final_report}


TOOL = {
    "name": "machbench",
    "description": "Start or advance an interactive hidden-role MachBench evaluation.",
    "inputSchema": {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["start", "decide"]},
            "player": {"type": "string", "description": "Seat to evaluate; defaults to ada."},
            "max_rounds": {"type": "integer", "minimum": 1, "maximum": 50},
            "model": {"type": "string", "description": "Stable model identifier, for example gpt-6-astra."},
            "decision": {"type": "object", "description": "Decision matching machbench/v1 response fields."},
        },
        "required": ["action"],
    },
}


class McpApplication:
    def __init__(self, history_dir: str | Path = "history", session_id: str | None = None):
        self.session: InteractiveBenchmark | None = None
        self.session_id = session_id or uuid.uuid4().hex
        self.history = SessionHistory(history_dir, self.session_id)

    def call(self, arguments: dict[str, Any]) -> dict[str, Any]:
        action = arguments.get("action")
        if action == "start":
            if self.session is not None:
                raise ValueError("session already started; finish it before starting another")
            model_name = arguments.get("model", "unknown-model")
            if not isinstance(model_name, str) or not model_name.strip():
                raise ValueError("model must be a non-empty stable identifier")
            max_rounds = arguments.get("max_rounds", 10)
            if isinstance(max_rounds, bool) or not isinstance(max_rounds, int) or not 1 <= max_rounds <= 50:
                raise ValueError("max_rounds must be an integer from 1 to 50")
            self.session = InteractiveBenchmark(arguments.get("player", "ada"), max_rounds, model_name.strip())
            return self.session.start()
        if action == "decide":
            if self.session is None:
                raise ValueError("no session; call machbench with action=start")
            result = self.session.decide(arguments.get("decision", {}))
            if result.get("status") == "finished":
                self.close()
            return result
        raise ValueError("action must be start or decide")

    def handle(self, message: dict[str, Any]) -> dict[str, Any] | None:
        method = message.get("method")
        self.history.record("inbound", method or "unknown", message)
        if "id" not in message:
            if method == "notifications/initialized":
                return None
            return None
        if method == "initialize":
            requested_version = message.get("params", {}).get("protocolVersion")
            protocol_version = requested_version if requested_version in SUPPORTED_PROTOCOL_VERSIONS else SUPPORTED_PROTOCOL_VERSIONS[0]
            response = {"jsonrpc": "2.0", "id": message["id"], "result": {
                "protocolVersion": protocol_version, "capabilities": {"tools": {}},
                "serverInfo": {"name": "machbench", "version": "1.0",
                                "title": "MachBench", "description": "Hidden-role reasoning benchmark",
                                "icons": [{"src": ICON_DATA_URI, "mimeType": "image/svg+xml"}]},
            }}
        elif method == "ping":
            response = {"jsonrpc": "2.0", "id": message["id"], "result": {}}
        elif method == "tools/list":
            response = {"jsonrpc": "2.0", "id": message["id"], "result": {"tools": [TOOL]}}
        elif method == "tools/call":
            try:
                params = message.get("params", {})
                if params.get("name") != TOOL["name"]:
                    response = {"jsonrpc": "2.0", "id": message["id"], "error": {
                        "code": -32601, "message": f"unknown tool: {params.get('name')}"}}
                else:
                    result = self.call(params.get("arguments", {}))
                    response = {"jsonrpc": "2.0", "id": message["id"], "result": {
                        "structuredContent": result,
                        "content": [{"type": "text", "text": json.dumps(result)}],
                    }}
            except Exception as error:
                response = {"jsonrpc": "2.0", "id": message["id"], "error": {
                    "code": -32602, "message": str(error),
                }}
        else:
            response = {"jsonrpc": "2.0", "id": message["id"], "error": {
                "code": -32601, "message": f"method not found: {method}",
            }}
        self.history.record("outbound", method or "unknown", response)
        return response

    def close(self) -> None:
        if self.session is not None and self.session.engine.state.records:
            from .benchmark import report

            self.history.save_report(report(self.session.engine.state, self.session.target_name, self.session.model_name))


class McpHttpServer(ThreadingHTTPServer):
    """Streamable-HTTP-style MCP server with one application per session."""

    daemon_threads = True

    def __init__(self, address: tuple[str, int], history_dir: str | Path = "history"):
        super().__init__(address, McpHttpRequestHandler)
        self.sessions: dict[str, McpApplication] = {}
        self.session_versions: dict[str, str] = {}
        self.history_dir = history_dir


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
                self.server.sessions[session_id] = McpApplication(self.server.history_dir, session_id)
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
        if self.path.rstrip("/") == "":
            body = ROOT_HTML.encode()
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)
        elif self.path == "/health":
            self._send_json({"status": "ok", "server": "machbench"})
        elif self.path == "/favicon.ico":
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "image/x-icon")
            self.send_header("Content-Length", str(len(FAVICON_ICO)))
            self.send_header("Cache-Control", "public, max-age=86400")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(FAVICON_ICO)
        elif self.path == "/machbench.svg":
            body = base64.b64decode(ICON_DATA_URI.split(",", 1)[1])
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "image/svg+xml")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(body)
        elif self.path.rstrip("/") == "/mcp":
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


def run_http(host: str, port: int, history_dir: str = "history") -> None:
    server = McpHttpServer((host, port), history_dir)
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
    parser.add_argument("--history-dir", default="history",
                        help="directory for JSONL session histories and final reports")
    args = parser.parse_args()
    if args.http:
        run_http(args.host, args.port, args.history_dir)
        return
    app = McpApplication(args.history_dir)
    try:
        for line in sys.stdin:
            if not line.strip():
                continue
            response = app.handle(json.loads(line))
            if response is not None:
                print(json.dumps(response), flush=True)
    finally:
        app.close()


if __name__ == "__main__":
    main()