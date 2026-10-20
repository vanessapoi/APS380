#!/usr/bin/env python3
# /***************************************************************************
#
#     file                 : quality.py
#     created              : 23 May 2026
#     copyright            : (C) 2026 by Bernhard Wymann
#     email                : berniw@bluewin.ch
#
#  ***************************************************************************/
#
#  This program is free software; you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation; either version 2 of the License, or
#  (at your option) any later version.

"""Run the local tracktools quality gate and write metric reports."""

from __future__ import annotations

import argparse
import json
import pathlib
import subprocess
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

ROOT = pathlib.Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_DIR = ROOT / "build" / "quality"


@dataclass(frozen=True)
class Step:
    name: str
    command: list[str]
    output_name: str
    advisory: bool = False


@dataclass(frozen=True)
class StepResult:
    step: Step
    returncode: int
    stdout_path: pathlib.Path
    stderr_path: pathlib.Path | None

    @property
    def ok(self) -> bool:
        return self.returncode == 0


@dataclass(frozen=True)
class CoverageFloorResult:
    name: str
    actual: float | None
    threshold: float
    report_path: pathlib.Path

    @property
    def ok(self) -> bool:
        return self.actual is not None and self.actual + 1e-9 >= self.threshold


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run tracktools tests, coverage, lint, and local code quality metrics")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR), help="Directory for reports and logs")
    parser.add_argument("--coverage-fail-under", type=float, default=75.0, help="Minimum total line coverage percentage; pass 0 to disable")
    parser.add_argument("--branch-fail-under", type=float, default=65.0, help="Minimum total branch coverage percentage; pass 0 to disable")
    parser.add_argument("--strict-advisory", action="store_true", help="Fail when advisory metric tools report findings")
    parser.add_argument("--skip-advisory", action="store_true", help="Run only required gates: ruff and pytest coverage")
    return parser.parse_args()


def display_command(command: list[str]) -> str:
    return " ".join(f'"{part}"' if " " in part else part for part in command)


def report_path(path: pathlib.Path) -> str:
    resolved = path.resolve()
    try:
        return resolved.relative_to(ROOT).as_posix()
    except ValueError:
        return resolved.as_posix()


def run_step(step: Step, output_dir: pathlib.Path) -> StepResult:
    output_path = output_dir / step.output_name
    stderr_path = output_path.with_suffix(output_path.suffix + ".err.txt")
    result = subprocess.run(step.command, cwd=ROOT, text=True, capture_output=True, check=False)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(result.stdout, encoding="utf-8")
    if result.stderr:
        stderr_path.write_text(result.stderr, encoding="utf-8")
        actual_stderr_path: pathlib.Path | None = stderr_path
    else:
        if stderr_path.exists():
            stderr_path.unlink()
        actual_stderr_path = None
    return StepResult(step, result.returncode, output_path, actual_stderr_path)


def load_json(path: pathlib.Path) -> Any:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def coverage_totals(path: pathlib.Path) -> dict[str, Any]:
    data = load_json(path)
    if not isinstance(data, dict):
        return {}
    totals = data.get("totals")
    return totals if isinstance(totals, dict) else {}


def coverage_percentages(path: pathlib.Path) -> tuple[float | None, float | None]:
    totals = coverage_totals(path)
    line_percent = totals.get("percent_covered")
    branches = totals.get("num_branches")
    covered_branches = totals.get("covered_branches")
    branch_percent = None
    if branches:
        branch_percent = 100.0 * float(covered_branches or 0) / float(branches)
    return (float(line_percent) if line_percent is not None else None, branch_percent)


def coverage_summary(path: pathlib.Path) -> list[str]:
    totals = coverage_totals(path)
    if not totals:
        return ["- Coverage: report missing or unreadable"]
    percent = totals.get("percent_covered")
    covered = totals.get("covered_lines")
    statements = totals.get("num_statements")
    branches = totals.get("num_branches")
    covered_branches = totals.get("covered_branches")
    lines = [f"- Line coverage: {float(percent):.2f}% ({covered}/{statements})" if percent is not None else "- Line coverage: unknown"]
    if branches:
        branch_percent = 100.0 * float(covered_branches or 0) / float(branches)
        lines.append(f"- Branch coverage: {branch_percent:.2f}% ({covered_branches}/{branches})")
    return lines


def coverage_floor_results(path: pathlib.Path, line_threshold: float, branch_threshold: float) -> list[CoverageFloorResult]:
    line_percent, branch_percent = coverage_percentages(path)
    results = []
    if line_threshold > 0.0:
        results.append(CoverageFloorResult("line coverage floor", line_percent, line_threshold, path))
    if branch_threshold > 0.0:
        results.append(CoverageFloorResult("branch coverage floor", branch_percent, branch_threshold, path))
    return results


def radon_cc_summary(path: pathlib.Path) -> list[str]:
    data = load_json(path)
    if not isinstance(data, dict):
        return ["- Cyclomatic complexity: report missing or unreadable"]
    entries: list[tuple[int, str, str, int, str]] = []
    for file_name, values in data.items():
        if not isinstance(values, list):
            continue
        for item in values:
            if not isinstance(item, dict):
                continue
            complexity = int(item.get("complexity", 0) or 0)
            entries.append((complexity, str(file_name), str(item.get("name", "?")), int(item.get("lineno", 0) or 0), str(item.get("rank", "?"))))
    if not entries:
        return ["- Cyclomatic complexity: no entries"]
    entries.sort(reverse=True)
    average = sum(item[0] for item in entries) / len(entries)
    lines = [f"- Cyclomatic complexity: average {average:.2f}, max {entries[0][0]} ({entries[0][4]})"]
    for complexity, file_name, name, line, rank in entries[:8]:
        rel = pathlib.Path(file_name).as_posix()
        lines.append(f"  - {rel}:{line} `{name}` CC {complexity} ({rank})")
    return lines


def radon_mi_summary(path: pathlib.Path) -> list[str]:
    data = load_json(path)
    if not isinstance(data, dict):
        return ["- Maintainability index: report missing or unreadable"]
    entries: list[tuple[float, str, str]] = []
    for file_name, item in data.items():
        if isinstance(item, dict):
            entries.append((float(item.get("mi", 0.0) or 0.0), str(file_name), str(item.get("rank", "?"))))
    if not entries:
        return ["- Maintainability index: no entries"]
    entries.sort()
    lines = [f"- Maintainability index: lowest {entries[0][0]:.2f} ({entries[0][2]})"]
    for mi, file_name, rank in entries[:8]:
        lines.append(f"  - {pathlib.Path(file_name).as_posix()} MI {mi:.2f} ({rank})")
    return lines


def bandit_summary(path: pathlib.Path) -> list[str]:
    data = load_json(path)
    if not isinstance(data, dict):
        return ["- Bandit: report missing or unreadable"]
    results = data.get("results") if isinstance(data.get("results"), list) else []
    by_severity: dict[str, int] = {}
    for item in results:
        if isinstance(item, dict):
            severity = str(item.get("issue_severity", "UNKNOWN"))
            by_severity[severity] = by_severity.get(severity, 0) + 1
    if not results:
        return ["- Bandit: 0 findings"]
    parts = ", ".join(f"{key}={value}" for key, value in sorted(by_severity.items()))
    return [f"- Bandit: {len(results)} findings ({parts})"]


def text_finding_summary(label: str, path: pathlib.Path) -> list[str]:
    if not path.exists():
        return [f"- {label}: report missing"]
    lines = [line for line in path.read_text(encoding="utf-8", errors="replace").splitlines() if line.strip()]
    if not lines:
        return [f"- {label}: 0 findings"]
    out = [f"- {label}: {len(lines)} finding(s)"]
    for line in lines[:8]:
        out.append(f"  - `{line}`")
    return out


def status_line(result: StepResult) -> str:
    kind = "advisory" if result.step.advisory else "required"
    status = "PASS" if result.ok else "FAIL"
    return f"- {status} `{result.step.name}` ({kind}, exit {result.returncode}) -> `{report_path(result.stdout_path)}`"


def coverage_floor_status_line(result: CoverageFloorResult) -> str:
    status = "PASS" if result.ok else "FAIL"
    actual = "unknown" if result.actual is None else f"{result.actual:.2f}%"
    return f"- {status} `{result.name}` (required, {actual} >= {result.threshold:.2f}%) -> `{report_path(result.report_path)}`"


def metric_summary(output_dir: pathlib.Path, results: list[StepResult]) -> list[str]:
    step_names = {result.step.name for result in results}
    lines = [*coverage_summary(output_dir / "coverage.json")]
    if "radon cyclomatic complexity" in step_names:
        lines.extend(radon_cc_summary(output_dir / "radon-cc.json"))
    if "radon maintainability index" in step_names:
        lines.extend(radon_mi_summary(output_dir / "radon-mi.json"))
    if "bandit" in step_names:
        lines.extend(bandit_summary(output_dir / "bandit.json"))
    if "cognitive complexity" in step_names:
        lines.extend(text_finding_summary("Cognitive complexity", output_dir / "cognitive-complexity.txt"))
    if "vulture" in step_names:
        lines.extend(text_finding_summary("Vulture dead-code candidates", output_dir / "vulture.txt"))
    return lines


def artifact_summary(output_dir: pathlib.Path, results: list[StepResult]) -> list[str]:
    step_names = {result.step.name for result in results}
    lines = [
        f"- Coverage HTML: `{report_path(output_dir / 'coverage-html' / 'index.html')}`",
        f"- Coverage XML: `{report_path(output_dir / 'coverage.xml')}`",
        f"- Coverage JSON: `{report_path(output_dir / 'coverage.json')}`",
    ]
    if "radon cyclomatic complexity" in step_names:
        lines.append(f"- Radon CC JSON: `{report_path(output_dir / 'radon-cc.json')}`")
    if "radon maintainability index" in step_names:
        lines.append(f"- Radon MI JSON: `{report_path(output_dir / 'radon-mi.json')}`")
    if "bandit" in step_names:
        lines.append(f"- Bandit JSON: `{report_path(output_dir / 'bandit.json')}`")
    if "vulture" in step_names:
        lines.append(f"- Vulture output: `{report_path(output_dir / 'vulture.txt')}`")
    if "cognitive complexity" in step_names:
        lines.append(f"- Cognitive complexity output: `{report_path(output_dir / 'cognitive-complexity.txt')}`")
    return lines


def write_summary(output_dir: pathlib.Path, results: list[StepResult], coverage_floors: list[CoverageFloorResult], strict_advisory: bool) -> str:
    summary_path = output_dir / "summary.md"
    required_failed = [result for result in results if not result.step.advisory and not result.ok]
    coverage_failed = [result for result in coverage_floors if not result.ok]
    advisory_steps = [result for result in results if result.step.advisory]
    advisory_failed = [result for result in results if result.step.advisory and not result.ok]
    lines = [
        "# Tracktools Quality Summary",
        "",
        f"Generated: {datetime.now(UTC).isoformat(timespec='seconds')}",
        "",
        "## Gate Status",
        "",
        *[status_line(result) for result in results],
        *[coverage_floor_status_line(result) for result in coverage_floors],
        "",
        "## Metrics",
        "",
        *metric_summary(output_dir, results),
        "",
        "## Artifacts",
        "",
        *artifact_summary(output_dir, results),
        "",
    ]
    required_failure_count = len(required_failed) + len(coverage_failed)
    if required_failure_count:
        lines.append(f"Required gate failures: {required_failure_count}")
    elif strict_advisory and advisory_failed:
        lines.append(f"Advisory failures promoted by --strict-advisory: {len(advisory_failed)}")
    elif not advisory_steps:
        lines.append("All required checks passed; advisory checks were skipped.")
    elif advisory_failed:
        lines.append(f"Advisory findings/non-zero exits: {len(advisory_failed)}. Use --strict-advisory to fail on these.")
    else:
        lines.append("All required and advisory checks passed.")
    text = "\n".join(lines) + "\n"
    summary_path.write_text(text, encoding="utf-8")
    return text


def main() -> int:
    args = parse_args()
    output_dir = pathlib.Path(args.output_dir)
    if not output_dir.is_absolute():
        output_dir = ROOT / output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    python = sys.executable
    coverage_command = [
        python,
        "-m",
        "pytest",
        "--cov=torcs_track_tools",
        "--cov-branch",
        "--cov-report=term-missing:skip-covered",
        f"--cov-report=html:{output_dir / 'coverage-html'}",
        f"--cov-report=xml:{output_dir / 'coverage.xml'}",
        f"--cov-report=json:{output_dir / 'coverage.json'}",
    ]

    steps = [
        Step("ruff", [python, "-m", "ruff", "check", "."], "ruff.txt"),
        Step("pytest coverage", coverage_command, "pytest-coverage.txt"),
    ]
    if not args.skip_advisory:
        steps.extend(
            [
                Step("radon cyclomatic complexity", [python, "-m", "radon", "cc", "src", "tests", "-s", "-a", "-j"], "radon-cc.json", True),
                Step("radon maintainability index", [python, "-m", "radon", "mi", "src", "-s", "-j"], "radon-mi.json", True),
                Step("xenon complexity thresholds", [python, "-m", "xenon", "--max-absolute", "C", "--max-modules", "B", "--max-average", "A", "src"], "xenon.txt", True),
                Step("cognitive complexity", [python, "-m", "flake8", "src", "--select=CCR", "--max-cognitive-complexity=15"], "cognitive-complexity.txt", True),
                Step("bandit", [python, "-m", "bandit", "-q", "-r", "src", "-f", "json", "-o", str(output_dir / "bandit.json")], "bandit.txt", True),
                Step("vulture", [python, "-m", "vulture", "src", "tests", "--min-confidence", "80"], "vulture.txt", True),
            ]
        )

    results = []
    for step in steps:
        print(f"Running {step.name}: {display_command(step.command)}")
        results.append(run_step(step, output_dir))

    coverage_floors = coverage_floor_results(output_dir / "coverage.json", max(0.0, args.coverage_fail_under), max(0.0, args.branch_fail_under))
    summary = write_summary(output_dir, results, coverage_floors, bool(args.strict_advisory))
    print(summary)
    required_failed = any(not result.step.advisory and not result.ok for result in results)
    coverage_failed = any(not result.ok for result in coverage_floors)
    advisory_failed = any(result.step.advisory and not result.ok for result in results)
    if required_failed or coverage_failed or (args.strict_advisory and advisory_failed):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
