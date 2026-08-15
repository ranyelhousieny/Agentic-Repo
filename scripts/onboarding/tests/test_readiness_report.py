"""
tests/test_readiness_report.py — Tests for the agent-readiness reporter.

The reporter is a local-artifact-only scorer:
  1. Always exits 0; report goes to Generated/READINESS_REPORT.md (or stdout).
  2. Levels gate at 80% of APPLICABLE criteria and unlock contiguously.
  3. None outcomes are not-applicable and excluded from the denominator.
  4. No network, no git origin requirement — a bare directory scores.
"""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent.parent
REPORTER = SCRIPTS_DIR / "readiness_report.py"

spec = importlib.util.spec_from_file_location("readiness_report", REPORTER)
reporter = importlib.util.module_from_spec(spec)
spec.loader.exec_module(reporter)


def run_reporter(repo: Path, *extra) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(REPORTER), str(repo), *extra],
                          capture_output=True, text=True)


def make_converted_repo(root: Path) -> Path:
    """A repo shaped like /convert-repo-to-agentic output, all five layers."""
    (root / ".gitignore").write_text("Generated/\n")
    (root / "README.md").write_text("# Service\n")
    (root / "pyproject.toml").write_text("[tool.ruff]\nline-length = 100\n")
    (root / "CLAUDE.md").write_text("# Instructions\n")
    (root / "AGENTS.md").write_text("# Agents\n")
    (root / "START_HERE.md").write_text("# Start\n")
    (root / "CODEOWNERS").write_text("* @team\n")
    (root / ".gitlab-ci.yml").write_text("stages: [test]\n")
    (root / "tests").mkdir()
    (root / "tests" / "test_x.py").write_text("def test_x(): pass\n")
    kn = root / "Knowledge"
    (kn / "Source of Truth").mkdir(parents=True)
    (kn / "KNOWLEDGE_GRAPH.md").write_text("# KG\n")
    (kn / "DOCUMENT_INDEX.md").write_text("# Index\n")
    (kn / "CODE_INDEX.md").write_text("# Code index\n")
    gen = root / "Generated"
    (gen / "session_logs").mkdir(parents=True)
    (gen / "PROGRESS_TRACKER.md").write_text("# Tracker\n")
    (root / "scripts" / "eval" / "golden").mkdir(parents=True)
    return root


def test_bare_directory_scores_without_git_or_network(tmp_path):
    result = run_reporter(tmp_path)
    assert result.returncode == 0
    assert (tmp_path / "Generated" / "READINESS_REPORT.md").is_file()
    summary = json.loads(result.stderr.strip().splitlines()[-1]
                         .split("[readiness_report] ", 1)[1])
    assert summary["achieved_level"] == 0


def test_converted_repo_reaches_level_five(tmp_path):
    make_converted_repo(tmp_path)
    result = run_reporter(tmp_path)
    assert result.returncode == 0
    summary = json.loads(result.stderr.strip().splitlines()[-1]
                         .split("[readiness_report] ", 1)[1])
    assert summary["achieved_level"] == 5, result.stderr
    report = (tmp_path / "Generated" / "READINESS_REPORT.md").read_text()
    assert "Achieved level:** L5" in report


def test_stdout_mode_writes_nothing(tmp_path):
    result = run_reporter(tmp_path, "--stdout")
    assert result.returncode == 0
    assert "# Agent Readiness Report" in result.stdout
    assert not (tmp_path / "Generated").exists()


def test_gate_is_eighty_percent_of_applicable():
    results = [
        {"level": 1, "outcome": True}, {"level": 1, "outcome": True},
        {"level": 1, "outcome": True}, {"level": 1, "outcome": False},
        {"level": 1, "outcome": False},
    ]
    scores = reporter.level_scores(results)
    assert scores[1]["fraction"] == 0.6
    assert not scores[1]["unlocked"]
    results[3]["outcome"] = True  # 4/5 = 80% exactly — unlocks
    scores = reporter.level_scores(results)
    assert scores[1]["unlocked"]


def test_levels_unlock_contiguously_not_cherry_picked():
    """Passing L2 while failing L1 must not report an achieved level of 2."""
    results = ([{"level": 1, "outcome": False}] * 3
               + [{"level": 2, "outcome": True}] * 4
               + [{"level": lvl, "outcome": False} for lvl in (3, 4, 5)])
    scores = reporter.level_scores(results)
    assert scores[2]["unlocked"] and not scores[1]["unlocked"]
    assert reporter.achieved_level(scores) == 0


def test_not_applicable_excluded_from_denominator(tmp_path):
    """code-graph is N/A when the optional engine never ran — a repo with no
    Generated/graphify must not be penalized at L4 for a tool it never used."""
    make_converted_repo(tmp_path)
    results = reporter.evaluate(tmp_path)
    code_graph = [r for r in results if r["id"] == "code-graph"][0]
    assert code_graph["outcome"] is None
    scores = reporter.level_scores(results)
    assert scores[4]["applicable"] == 3  # KG, doc index, code index — not code-graph
    assert scores[4]["unlocked"]


def test_code_graph_applicable_and_failing_when_engine_ran_without_output(tmp_path):
    make_converted_repo(tmp_path)
    (tmp_path / "Generated" / "graphify").mkdir(parents=True)
    results = reporter.evaluate(tmp_path)
    code_graph = [r for r in results if r["id"] == "code-graph"][0]
    assert code_graph["outcome"] is False


def test_eager_budget_measured_against_cap(tmp_path):
    make_converted_repo(tmp_path)
    (tmp_path / "CLAUDE.md").write_text("x" * (reporter.EAGER_LOAD_CHAR_CAP + 1))
    results = reporter.evaluate(tmp_path)
    budget = [r for r in results if r["id"] == "eager-budget"][0]
    assert budget["outcome"] is False


def test_failing_criteria_carry_remediation_in_report(tmp_path):
    (tmp_path / "README.md").write_text("# Bare\n")
    result = run_reporter(tmp_path)
    report = (tmp_path / "Generated" / "READINESS_REPORT.md").read_text()
    assert "FAIL" in report
    assert "/convert-repo-to-agentic" in report  # the converter IS the remediation
    assert result.returncode == 0


def test_missing_repo_path_skips_cleanly():
    result = subprocess.run([sys.executable, str(REPORTER), "/nonexistent/xyz"],
                            capture_output=True, text=True)
    assert result.returncode == 0
    assert "does not exist" in result.stderr
