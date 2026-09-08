import json
from pathlib import Path
import threading
from urllib.request import Request, urlopen

from machbench.mcp_server import McpApplication, McpHttpServer


def test_mcp_advertises_machbench_tool_and_runs_session(tmp_path: Path):
    app = McpApplication(tmp_path)
    tools = app.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    assert tools["result"]["tools"][0]["name"] == "machbench"
    initialized = app.handle({"jsonrpc": "2.0", "id": 2, "method": "initialize",
                               "params": {"protocolVersion": "2024-11-05"}})
    assert initialized["result"]["protocolVersion"] == "2024-11-05"
    assert initialized["result"]["serverInfo"]["icons"][0]["mimeType"] == "image/svg+xml"

    started_response = app.handle({
        "jsonrpc": "2.0", "id": 3, "method": "tools/call",
        "params": {"name": "machbench", "arguments": {"action": "start", "model": "gpt-6-astra", "max_rounds": 1}},
    })
    started = started_response["result"]["structuredContent"]
    decision = {
        "coalition": ["ada", "bo"], "vote": True,
        "public_statement": "I support this limited proposal.",
        "evidence": ["history"], "plan": "secure a majority",
        "contingency": "switch coalition", "confidence": 0.7,
    }
    finished_response = app.handle({
        "jsonrpc": "2.0", "id": 4, "method": "tools/call",
        "params": {"name": "machbench", "arguments": {"action": "decide", "decision": decision}},
    })
    finished = finished_response["result"]["structuredContent"]
    assert started["request"]["format"] == "machbench/v1"
    assert app.session.model_name == "gpt-6-astra"
    assert finished["status"] == "finished"
    assert finished["report"]["format"] == "machbench/report/v1"
    assert finished["report"]["model"] == "gpt-6-astra"
    assert finished["report"]["measurement"]["max_points"] == 100
    assert "gpt-6-astra" in finished["message"]
    assert "/100" in finished["message"]
    assert (tmp_path / "leaderboard.json").exists()
    assert (tmp_path / "leaderboard.svg").exists()
    leaderboard_data = json.loads((tmp_path / "leaderboard.json").read_text())
    assert leaderboard_data["models"][0]["model"] == "gpt-6-astra"
    histories = list(tmp_path.glob("*.jsonl"))
    reports = list(tmp_path.glob("*.report.json"))
    assert len(histories) == 1
    assert len(reports) == 1
    events = [json.loads(line) for line in histories[0].read_text().splitlines()]
    assert any(event["direction"] == "inbound" and event["method"] == "tools/call" for event in events)
    assert any(event["direction"] == "outbound" for event in events)
    saved_text = "\n".join(path.read_text() for path in histories)
    assert "Pass three reforms without empowering the coup." not in saved_text
    assert '"secret_role": "reformer"' not in saved_text
    assert "[redacted]" in saved_text
    timeline = (tmp_path / f"{app.session_id}.md").read_text()
    assert "- `" in timeline
    assert "```json" not in timeline


def test_http_transport_creates_isolated_session():
    server = McpHttpServer(("127.0.0.1", 0))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{server.server_port}/mcp"
    try:
        for probe_url in (url, url + "/", f"http://127.0.0.1:{server.server_port}/health", f"http://127.0.0.1:{server.server_port}/favicon.ico"):
            with urlopen(probe_url) as response:
                if probe_url.endswith("favicon.ico"):
                    assert response.headers["Content-Type"] == "image/x-icon"
                else:
                    assert json.loads(response.read())["status"] == "ok"
        with urlopen(f"http://127.0.0.1:{server.server_port}/") as response:
            assert response.headers["Content-Type"].startswith("text/html")
            assert "MachBench MCP Server" in response.read().decode()
        request = Request(url, json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}).encode(),
                          {"Content-Type": "application/json", "MCP-Protocol-Version": "2024-11-05"})
        with urlopen(request) as response:
            session_id = response.headers["MCP-Session-Id"]
            assert response.headers["MCP-Protocol-Version"] == "2024-11-05"
            payload = json.loads(response.read())
        assert payload["result"]["serverInfo"]["name"] == "machbench"
        assert payload["result"]["serverInfo"]["icons"]
        tools_request = Request(url, json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}).encode(),
                                {"Content-Type": "application/json", "MCP-Session-Id": session_id})
        with urlopen(tools_request) as response:
            assert json.loads(response.read())["result"]["tools"][0]["name"] == "machbench"
    finally:
        server.shutdown()
        server.server_close()


def test_mcp_max_rounds_returns_stable_final_report(tmp_path: Path):
    app = McpApplication(tmp_path)
    app.call({"action": "start", "model": "test-model", "max_rounds": 1})
    decision = {"coalition": ["ada", "bo"], "vote": True,
                "public_statement": "support", "confidence": 0.5}
    first = app.call({"action": "decide", "decision": decision})
    second = app.call({"action": "decide", "decision": decision})
    assert first["status"] == "finished"
    assert first["report"]["model"] == "test-model"
    assert second["status"] == "finished"
    assert second["report"]["rounds"] == 1


def test_protocol_validation_ping_unknown_tool_and_idempotent_start(tmp_path: Path):
    app = McpApplication(tmp_path)
    for value in (0, 51, "3"):
        try:
            app.call({"action": "start", "max_rounds": value})
        except ValueError as error:
            assert "max_rounds" in str(error)
        else:
            raise AssertionError(f"accepted invalid max_rounds={value!r}")
    ping = app.handle({"jsonrpc": "2.0", "id": 1, "method": "ping"})
    assert ping["result"] == {}
    unknown = app.handle({"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                           "params": {"name": "wrong-tool", "arguments": {"action": "start"}}})
    assert unknown["error"]["code"] == -32601
    app.call({"action": "start", "max_rounds": 1})
    try:
        app.call({"action": "start", "max_rounds": 1})
    except ValueError as error:
        assert "already started" in str(error)
    else:
        raise AssertionError("start silently reset the active session")