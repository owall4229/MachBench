from __future__ import annotations

import json
from html import escape
from pathlib import Path
from typing import Any


def load_reports(directory: str | Path) -> list[dict[str, Any]]:
    reports = []
    for path in sorted(Path(directory).expanduser().glob("*.report.json")):
        try:
            report = json.loads(path.read_text(encoding="utf-8"))
            if report.get("format") == "machbench/report/v1":
                reports.append(report)
        except (OSError, json.JSONDecodeError):
            continue
    return reports


def leaderboard(directory: str | Path) -> list[dict[str, Any]]:
    best: dict[str, dict[str, Any]] = {}
    for report in load_reports(directory):
        model = report.get("model", "unknown-model")
        score = report.get("measurement", {}).get("points", report.get("score", {}).get("total_points", 0))
        row = {"model": model, "points": score, "max_points": 100,
               "percentage": round(score, 1), "runs": 1, "_total": score}
        if model not in best:
            best[model] = row
        else:
            best[model]["_total"] += score
            best[model]["runs"] += 1
            best[model]["percentage"] = round(best[model]["_total"] / best[model]["runs"], 1)
            best[model]["points"] = best[model]["percentage"]
    return sorted(({key: value for key, value in row.items() if key != "_total"}
                   for row in best.values()), key=lambda row: row["percentage"], reverse=True)


def svg_graph(rows: list[dict[str, Any]]) -> str:
    width, height, left, chart_width = 900, 100 + 48 * max(1, len(rows)), 220, 620
    bars = []
    for index, row in enumerate(rows):
        y = 50 + index * 48
        bar_width = round(chart_width * row["percentage"] / 100)
        bars.append(f'<text x="{left - 12}" y="{y + 20}" text-anchor="end" font-family="sans-serif" font-size="16">{escape(row["model"])}</text>')
        bars.append(f'<rect x="{left}" y="{y}" width="{bar_width}" height="28" rx="6" fill="#e7b85c"/>')
        bars.append(f'<text x="{left + bar_width + 10}" y="{y + 20}" font-family="sans-serif" font-size="16">{row["percentage"]}/100</text>')
    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">
<rect width="100%" height="100%" fill="#102a2a"/><text x="32" y="32" fill="#f4e7c1" font-family="sans-serif" font-size="22" font-weight="bold">MachBench model leaderboard</text>
{''.join(f'<g fill="#f4e7c1">{bar}</g>' for bar in bars)}
</svg>'''


def write_leaderboard(directory: str | Path, output: str | Path) -> list[dict[str, Any]]:
    rows = leaderboard(directory)
    output = Path(output)
    if output.suffix.lower() == ".svg":
        output.write_text(svg_graph(rows), encoding="utf-8")
    else:
        output.write_text(json.dumps({"format": "machbench/leaderboard/v1", "models": rows}, indent=2), encoding="utf-8")
    return rows