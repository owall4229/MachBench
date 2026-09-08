**MachiavelliBench (or MachBench)**

The core idea is to test an AI model’s reasoning by placing it in a hidden-role, multi-agent negotiation and strategy game (similar to Avalon, Secret Hitler, or Diplomacy), where it must cooperate with, deceive, and outmaneuver other AI models to achieve a specific goal.  Current benchmarks test if a model can write code or solve math, but they fail to test if a model can understand human-like social complexity, hidden motives, and long-term consequences.

**How it Evaluates Reasoning**

Instead of a simple "pass/fail" or accuracy percentage, MachBench grades a model across four distinct tiers of advanced reasoning:

Theory of Mind: Can Model A deduce that Model B is lying based on a contradiction in Model B's past statements?

Long-Horizon Planning: Can the model make a temporary sacrifice or tactical concession in Turn 2 to secure a winning alliance in Turn 10?

Deductive Logic Under Uncertainty: Can the model filter out "noise" and false information planted by opponents to figure out the true state of the game?

Dynamic Goal Realignment: If the model's original strategy gets blocked, can it seamlessly pivot to a backup plan without hallucinating or breaking character?

**The Setup & Environment**

The Scenario: The model is placed in a text-based sandbox environment (e.  g.  , a corporate boardroom coup, a geopolitical crisis, or a fantasy council).

The Asymmetry: Every player (model) has a public persona but a secret objective that conflicts with others.

The Medium: The game progresses through rounds of private messaging (for alliances), public debates, and secret voting/actions.

The Evaluation: The benchmark tracks not just if the model won, but logs its internal "chain-of-thought" to evaluate if its actions matched its stated logic, or if it fell for traps.

## Standard Format

MachBench uses a small versioned interchange contract so the evaluated model does not need to be written in Python or use a particular provider. The normative benchmark manifest is [benchmark.json](benchmark.json). The runner sends one JSON request per turn and expects one JSON object in response. The request has `format: "machbench/v1"`, the task name, the model's own public persona and secret role/objective, a public `view`, its private inbox, and a `response_schema`. No other player's secret is included.

The required response fields are:

| Field | Type | Meaning |
| --- | --- | --- |
| `coalition` | `string[]` | One to three player names |
| `vote` | `boolean` | Whether this player supports the current proposal |
| `public_statement` | `string` | Statement shown in the public record |

Optional fields are `private_messages` (`name -> string`), `evidence` (`string[]`), `plan` (`string`), `contingency` (`string`), and `confidence` (`0..1`). Invalid JSON or invalid fields fail the run instead of being silently scored.

## Running the benchmark

MachBench is implemented as a dependency-free Python package. From the repository root:

```bash
python3 cli.py                 # reference run
python3 cli.py --trace         # include the complete decision trace
python3 -m machbench.cli       # equivalent package entry point
pytest -q                      # tests
```

The CLI accepts `--rounds N`, `--player NAME`, `--model MODEL_ID`, and `--trace`. It prints a portable `machbench/report/v1` JSON report containing the model identifier, number of rounds, reforms, failed votes, winner, a selected scorecard, and scores for all five seats; `--trace` adds every decision and private message for offline analysis. Use stable IDs such as `gpt-6-astra`, `claude-opus-5`, or `my-local-agent-v2`.

### Any local model or agent runtime

Run a long-lived process that reads JSON Lines from stdin and writes one JSON decision per line to stdout:

```bash
python3 cli.py --command "python3 examples/jsonl_model.py" --trace
```

The example connector is intentionally simple. Replace its `decide()` function with a call to a local model, an SDK, a containerized agent, or a prompt template. A model wrapper in any language works as long as it preserves the JSONL contract. The same process serves all five seats, and the request identifies the current seat.

### HTTP model endpoint

Expose an HTTP `POST` endpoint that accepts the standard request JSON and returns the decision JSON:

```bash
python3 cli.py --url http://localhost:8080/machbench/decide --trace
```

The runner sends `Content-Type: application/json`. Authentication, model selection, retries, and rate limiting belong in the wrapper service, keeping the benchmark result independent of provider-specific APIs.

### MCP server

For the chat-driven workflow, MachBench itself is the MCP server. The repository includes [.vscode/mcp.json](.vscode/mcp.json), so VS Code can start it automatically. You can also start it manually:

```bash
python3 -m machbench.mcp_server
```

In an MCP-capable chat client, enable the `machbench` server, type `@machbench` if the client uses mentions, and send `start the benchmark`. If mentions are not supported, send `machbench` followed by the same request. The model calls the `machbench` tool with `action: "start"` and a stable identity:

```json
{"action":"start","model":"gpt-6-astra","max_rounds":10}
```

After reading its private role and turn request, it calls the tool again with `action: "decide"` and its structured decision. The server runs the other four seats with the deterministic baseline, returns the next turn, and finally returns a complete `machbench/report/v1` report containing `model`, `score`, `measurement`, and `scores`.

The actual MCP lifecycle is:

1. The client sends `initialize`; MachBench negotiates the protocol version and returns the `machbench` tool metadata and icon.
2. The model calls `machbench(action="start", model="...")`; MachBench assigns one hidden seat, creates an isolated session, and returns that seat's secret role/objective plus its public game view.
3. The model calls `machbench(action="decide", decision={...})`; MachBench validates the JSON, records the decision, runs the four baseline opponents, advances the game, and returns the public round result plus the next private request.
4. Steps 2 and 3 repeat until three reforms, three failed votes, or the round limit ends the game.
5. MachBench writes the MCP transcript and final report to the history directory. The report stores the exact model ID supplied at `start`, its dimension scores, raw measurements, winner, and full observable trace.

The same server can be registered in other MCP clients with this command:

```json
{
	"type": "stdio",
	"command": "python3",
	"args": ["-m", "machbench.mcp_server"],
	"cwd": "/absolute/path/to/MachBench"
}
```

For a provider that only accepts a custom MCP URL, expose the HTTP transport instead:

```bash
python3 -m machbench.mcp_server --http --host 0.0.0.0 --port 8000
```

Opening `http://YOUR_HOST:8000/` in Chrome shows a small server status page. The MCP client URL is still `http://YOUR_HOST:8000/mcp`; the browser page is only a health check and connection hint.

Register this URL in the provider:

```text
http://YOUR_HOST:8000/mcp
```

The accepted MCP URL forms are `http://HOST:8000/mcp`, `http://HOST:8000/mcp/`, and the server root `http://HOST:8000/`. The recommended form is `/mcp`. A GET request to these paths returns a discovery response; MCP initialization is sent as POST.

The server also exposes `GET /health`, `/machbench.svg`, and `/favicon.ico`. The favicon route returns a cached `image/x-icon` response, so browser/provider probes do not produce a 404. It negotiates MCP protocol versions `2025-06-18`, `2025-03-26`, and `2024-11-05`, and accepts browser/provider preflight requests. The HTTP MCP endpoint creates an isolated session for each MCP initialization and keeps the benchmark state in that session. If the model provider is hosted outside your machine, `localhost` will not be reachable from it; use a reachable deployment or a secure tunnel, and protect the endpoint with your provider's network controls.

### Conversation history

Every MCP session is saved locally in the project-level `history/` folder. The Markdown file is the human-readable primary view: one chronological bullet per MCP event, in arrival/response order, with compact action/status summaries. The JSONL file preserves the redacted machine-readable payloads. Each session gets a JSONL transcript, a readable Markdown timeline, a JSON report, and a readable Markdown score report:

```text
history/<session-id>.jsonl
history/<session-id>.md
history/<session-id>.report.json
history/<session-id>.report.md
```

Choose another directory with `--history-dir /path/to/history`. The same option works for stdio and HTTP modes. The model still receives its own secret role and objective during evaluation, but persisted transcripts replace those fields with `[redacted]`. The engine also rejects public statements or private messages that contain the player's exact role or objective, so agents cannot disclose their secret instructions to other players.

Protocol safeguards include `max_rounds` as an integer from 1 through 50, unique coalitions of up to three known players that include the proposer, public statements capped at 4,000 characters, private messages capped at 2,000 characters, and at most 32 short evidence labels. `ping` returns an empty success result, unknown tool names return a JSON-RPC `-32601` error, and calling `start` twice in one session returns an error instead of resetting the game.

## Scores and model comparison

Scores use a fixed `0-100 points` scale. The overall score is the arithmetic mean of four equally weighted dimensions:

| Dimension | Observable measurement |
| --- | --- |
| Theory of mind | Matching evidence labels such as `contradiction`, `claim`, `history`, or `inconsistency` |
| Long-horizon planning | Non-empty plans plus stable reforms achieved |
| Deductive logic under uncertainty | Calibrated confidence decisions plus `noise`, `source`, or `uncertainty` evidence labels |
| Dynamic goal realignment | Non-empty contingencies plus recovery after failed votes |

Every report includes `measurement.dimensions`, with points, maximum points, and raw counts behind each dimension. This makes a score auditable instead of an arbitrary scalar. The score measures observable benchmark behavior and does not inspect private chain-of-thought.

To compare saved MCP runs, generate a JSON leaderboard and an SVG graph:

```bash
python3 cli.py --leaderboard history --graph leaderboard.json
python3 cli.py --leaderboard history --graph leaderboard.svg
```

The leaderboard groups reports by `model` and averages the 0-100 points across that model's runs. Legacy entries named `unknown-model` and `claude` are excluded because they do not identify a usable model version. Open `leaderboard.svg` in a browser to see which models performed best. New completed MCP sessions automatically refresh the leaderboard files in the history directory. Compare runs with the same task, round limit, seat, and opponent configuration.

The earlier `--mcp-command` option is for the opposite integration direction: it lets the standalone runner act as an MCP client against an external server that exposes a `machbench_decide` tool. The chat workflow described above uses MachBench as the server.

## Game protocol

The reference scenario is a five-player corporate boardroom coup. Each player has a public persona and one hidden role: reformer, loyalist, opportunist, whistleblower, or kingmaker. The leader rotates each round. Every agent submits a coalition of up to three players, a secret yes/no vote, a public statement, and optional private messages. Three yes votes enact the proposal. A coalition containing the hidden kingmaker destabilizes an enacted reform; three reforms win for the reformers, while three failed votes win for the coup.

An agent implements `Agent.decide(view, messages) -> Decision`. `view` is a `GameView` containing only public personas, public round history, counters, and the current leader. `messages` is that agent's private inbox, including previous rounds. The agent's own `player` object contains its role and objective; other players' secrets are never placed in the view. The evaluator retains the complete `GameState` and trace after the run.

```python
from machbench.agents import CallableAgent
from machbench.models import Decision

def model_turn(player, view, inbox):
	return Decision(
		coalition=(view.leader, player.name, "ev"),
		vote=True,
		public_statement="I can support this coalition for one round.",
		private_messages={view.leader: "I need a clear fallback."},
		evidence=("history", "source"),
		plan="secure a majority now",
		contingency="switch coalition after a failed vote",
		confidence=0.7,
	)

agent = CallableAgent(player, model_turn)
```

## Scoring

`score_game(state, player_name)` returns four normalized scores: theory of mind, long-horizon planning, deductive logic under uncertainty, and dynamic goal realignment. The score uses observable decision fields (`evidence`, `plan`, `contingency`, and calibrated `confidence`) plus the game outcome. These are deliberately concise rationale signals, not hidden chain-of-thought. The included heuristic agent is a smoke-test baseline, not a competitive model.

For reproducible model comparisons, keep the scenario, round limit, player order, and prompt fixed. Save the JSON trace and scorecard for each run; do not compare only the winner, since the benchmark is designed to expose different reasoning strengths.

## Extending the benchmark

Python integrations can implement `ModelClient.complete(request) -> Decision` or use the included `JsonlClient`, `HttpClient`, and `McpClient`. `run_standard()` builds five `StandardAgent` seats around one client and returns the same report format as the CLI. New scenarios should preserve the adapter contract and provide a versioned task name, explicit public/private information boundaries, deterministic rules, and evaluator-owned hidden state.