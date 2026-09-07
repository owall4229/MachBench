import json
import threading
from urllib.request import Request, urlopen

from machbench.mcp_server import McpApplication, McpHttpServer


def test_mcp_advertises_machbench_tool_and_runs_session():
    app = McpApplication()
    tools = app.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    assert tools["result"]["tools"][0]["name"] == "machbench"
    initialized = app.handle({"jsonrpc": "2.0", "id": 2, "method": "initialize",
                               "params": {"protocolVersion": "2024-11-05"}})
    assert initialized["result"]["protocolVersion"] == "2024-11-05"
    assert initialized["result"]["serverInfo"]["icons"][0]["mimeType"] == "image/svg+xml"

    started = app.call({"action": "start", "max_rounds": 1})
    decision = {
        "coalition": ["ada", "bo"], "vote": True,
        "public_statement": "I support this limited proposal.",
        "evidence": ["history"], "plan": "secure a majority",
        "contingency": "switch coalition", "confidence": 0.7,
    }
    finished = app.call({"action": "decide", "decision": decision})
    assert started["request"]["format"] == "machbench/v1"
    assert finished["status"] == "finished"
    assert finished["report"]["format"] == "machbench/report/v1"


def test_http_transport_creates_isolated_session():
    server = McpHttpServer(("127.0.0.1", 0))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{server.server_port}/mcp"
    try:
        for probe_url in (url, url + "/", f"http://127.0.0.1:{server.server_port}/"):
            with urlopen(probe_url) as response:
                assert json.loads(response.read())["status"] == "ok"
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