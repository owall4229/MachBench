import json
from pathlib import Path

from machbench.leaderboard import leaderboard, write_leaderboard


def test_leaderboard_groups_models_and_writes_svg(tmp_path: Path):
    for model, points in (("gpt-6-astra", 80), ("claude-opus-5", 60), ("gpt-6-astra", 100),
                          ("unknown-model", 99), ("claude", 99)):
        (tmp_path / f"{model}-{points}.report.json").write_text(json.dumps({
            "format": "machbench/report/v1", "model": model,
            "measurement": {"points": points},
        }))
    rows = leaderboard(tmp_path)
    assert rows[0]["model"] == "gpt-6-astra"
    assert rows[0]["percentage"] == 90
    assert {row["model"] for row in rows} == {"gpt-6-astra", "claude-opus-5"}
    output = tmp_path / "leaderboard.svg"
    write_leaderboard(tmp_path, output)
    assert "MachBench model leaderboard" in output.read_text()