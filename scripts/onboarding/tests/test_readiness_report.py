"""
tests/test_readiness_report.py — Tests for the agent-readiness reporter.

The reporter is a local-artifact-only scorer:
  1. Always exits 0; report goes to Generated/READINESS_REPORT.md (or stdout).
  2. Levels gate at 80% of APPLICABLE criteria and unlock contiguously.
  3. None outcomes are not-applicable and excluded from the denominator.
  4. No network, no git origin requirement — a bare directory scores.
  5. The report never becomes a commit: the writer drops a scoped
     Generated/.gitignore so `git add -A` cannot pick it up.
"""
from __future__ import annotations

import importlib.util
import json
import os
import stat
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


def summary_of(result: subprocess.CompletedProcess) -> dict:
    return json.loads(result.stderr.strip().splitlines()[-1]
                      .split("[readiness_report] ", 1)[1])


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
    (kn / "Source of Truth" / "PROJECT_VISION.md").write_text("# Vision\n")
    (kn / "KNOWLEDGE_GRAPH.md").write_text("# KG\n")
    (kn / "DOCUMENT_INDEX.md").write_text("# Index\n")
    (kn / "CODE_INDEX.md").write_text("# Code index\n")
    gen = root / "Generated"
    (gen / "session_logs").mkdir(parents=True)
    (gen / "session_logs" / "2026-08-14_session.md").write_text("# Session\n")
    (gen / "PROGRESS_TRACKER.md").write_text("# Tracker\n")
    (root / "scripts" / "eval" / "golden").mkdir(parents=True)
    (root / "scripts" / "eval" / "golden" / "facts.jsonl").write_text("{}\n")
    return root


def test_bare_directory_scores_without_git_or_network(tmp_path):
    result = run_reporter(tmp_path)
    assert result.returncode == 0
    assert (tmp_path / "Generated" / "READINESS_REPORT.md").is_file()
    assert summary_of(result)["achieved_level"] == 0


def test_converted_repo_reaches_level_five(tmp_path):
    make_converted_repo(tmp_path)
    result = run_reporter(tmp_path)
    assert result.returncode == 0
    assert summary_of(result)["achieved_level"] == 5, result.stderr
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
    assert scores[1]["needed"] == 4


def test_printed_threshold_always_matches_the_unlock_decision():
    """passing_threshold() is derived from GATE, so the "Needed" column can never
    tell the reader a number the gate disagrees with — for any denominator."""
    for applicable in range(1, 21):
        needed = reporter.passing_threshold(applicable)
        for passed in range(applicable + 1):
            rows = ([{"level": 1, "outcome": True}] * passed
                    + [{"level": 1, "outcome": False}] * (applicable - passed))
            unlocked = reporter.level_scores(rows)[1]["unlocked"]
            assert unlocked == (passed >= needed), (applicable, passed, needed)


def test_no_level_has_tolerance_under_the_current_criteria_set():
    """Documented honestly in the module docstring and the report: with 3-4
    criteria per level the 80% gate rounds up to ALL applicable criteria. If a
    level ever grows to 5+ criteria this test fails, which is the moment to
    revisit the wording rather than let the report imply tolerance silently."""
    counts = {}
    for level, *_ in reporter.CRITERIA:
        counts[level] = counts.get(level, 0) + 1
    assert set(counts) == set(reporter.LEVEL_NAMES)
    for level, total in counts.items():
        for applicable in range(1, total + 1):
            assert reporter.passing_threshold(applicable) == applicable, (level, applicable)


def test_levels_unlock_contiguously_not_cherry_picked():
    """Passing L2 while failing L1 must not report an achieved level of 2."""
    results = ([{"level": 1, "outcome": False}] * 3
               + [{"level": 2, "outcome": True}] * 4
               + [{"level": lvl, "outcome": False} for lvl in (3, 4, 5)])
    scores = reporter.level_scores(results)
    assert scores[2]["unlocked"] and not scores[1]["unlocked"]
    assert reporter.achieved_level(scores) == 0


def test_report_marks_a_passing_level_that_does_not_count(tmp_path):
    """A level can pass on its own and still not raise the achieved level. The
    report must say so instead of printing a bare "yes" next to "Achieved: L0"."""
    (tmp_path / "CLAUDE.md").write_text("# Instructions\n")
    (tmp_path / "START_HERE.md").write_text("# Start\n")
    result = run_reporter(tmp_path, "--stdout")
    assert summary_of(result)["achieved_level"] == 0
    assert "blocked by L1" in result.stdout, result.stdout


def test_not_applicable_excluded_from_denominator(tmp_path):
    """code-graph is N/A when the optional engine never ran — a repo with no
    CODE_GRAPH.jsonl must not be penalized at L4 for a tool it never used."""
    make_converted_repo(tmp_path)
    results = reporter.evaluate(tmp_path)
    code_graph = [r for r in results if r["id"] == "code-graph"][0]
    assert code_graph["outcome"] is None
    scores = reporter.level_scores(results)
    assert scores[4]["applicable"] == 3  # KG, doc index, code index — not code-graph
    assert scores[4]["unlocked"]


def test_code_graph_is_na_when_engine_output_dir_exists_without_graph(tmp_path):
    """The adapter creates Generated/graphify/ as soon as the engine is INSTALLED,
    and only writes CODE_GRAPH.jsonl once a run produced a dependency edge. Failing
    on that gap would let installing an optional tool LOWER the achieved level."""
    make_converted_repo(tmp_path)
    (tmp_path / "Generated" / "graphify").mkdir(parents=True)
    results = reporter.evaluate(tmp_path)
    code_graph = [r for r in results if r["id"] == "code-graph"][0]
    assert code_graph["outcome"] is None
    scores = reporter.level_scores(results)
    assert scores[4]["applicable"] == 3 and scores[4]["unlocked"]


def test_code_graph_passes_when_a_completed_run_left_its_artifact(tmp_path):
    make_converted_repo(tmp_path)
    graphify = tmp_path / "Generated" / "graphify"
    graphify.mkdir(parents=True)
    (graphify / "CODE_GRAPH.jsonl").write_text('{"from":"a","to":"b"}\n')
    results = reporter.evaluate(tmp_path)
    code_graph = [r for r in results if r["id"] == "code-graph"][0]
    assert code_graph["outcome"] is True
    assert reporter.level_scores(results)[4]["applicable"] == 4


def test_na_rows_carry_no_remediation(tmp_path):
    """An n/a row is not work owed, so it must not print a remediation hint next
    to a closing line that calls failing criteria "ordered work"."""
    make_converted_repo(tmp_path)
    result = run_reporter(tmp_path, "--stdout")
    na_rows = [ln for ln in result.stdout.splitlines() if "| n/a |" in ln]
    assert na_rows, result.stdout
    for row in na_rows:
        assert row.rstrip().endswith("| -- |"), row


def test_eager_budget_measured_against_cap(tmp_path):
    make_converted_repo(tmp_path)
    (tmp_path / "CLAUDE.md").write_text("x" * (reporter.EAGER_LOAD_BUDGET_BYTES + 1))
    results = reporter.evaluate(tmp_path)
    budget = [r for r in results if r["id"] == "eager-budget"][0]
    assert budget["outcome"] is False


def test_eager_budget_matches_the_framework_documented_limit():
    """REPO_ONBOARDING_AGENT.md "Activation Token Budget" measures the same
    boundary with `wc -c` against ~360,000 chars. A tighter private cap would fail
    repos the framework itself calls fine."""
    assert reporter.EAGER_LOAD_BUDGET_BYTES == 360_000


def test_eager_budget_covers_the_whole_session_init_boundary(tmp_path):
    """Every file the injected Session-Init block reads at activation must be in
    the measurement, or "measured, not assumed" under-measures."""
    make_converted_repo(tmp_path)
    skill = tmp_path / ".claude" / "skills" / "svc-agent"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text("# Skill\n")
    for relative in ("Knowledge/KNOWLEDGE_GRAPH.md", "Knowledge/CODE_INDEX.md",
                     "Knowledge/Source of Truth/PROJECT_VISION.md",
                     "Generated/PROGRESS_TRACKER.md",
                     ".claude/skills/svc-agent/SKILL.md"):
        target = tmp_path / relative
        before = reporter.c_eager_budget(tmp_path)
        assert before is True
        target.write_text("y" * (reporter.EAGER_LOAD_BUDGET_BYTES + 1))
        assert reporter.c_eager_budget(tmp_path) is False, relative
        target.write_text("# small\n")


def test_eager_budget_is_na_when_nothing_is_eager_loaded(tmp_path):
    assert reporter.c_eager_budget(tmp_path) is None


def test_l5_rejects_empty_scaffolding_the_converter_creates(tmp_path):
    """The converter itself runs `mkdir -p Generated/session_logs` and creates
    Knowledge/Source of Truth/, so bare directories must not score "in use"."""
    (tmp_path / "Knowledge" / "Source of Truth").mkdir(parents=True)
    (tmp_path / "Generated" / "session_logs").mkdir(parents=True)
    (tmp_path / "Generated" / "session_logs" / ".gitkeep").write_text("")
    (tmp_path / "scripts" / "eval").mkdir(parents=True)
    assert reporter.c_source_of_truth(tmp_path) is False
    assert reporter.c_session_logs(tmp_path) is False
    assert reporter.c_eval_assets(tmp_path) is False


def test_report_is_git_ignored_where_it_lands(tmp_path):
    """Step 16's Next Steps ends with `git add -A && git commit`; the report
    carries an absolute machine path and must not be committable."""
    run_reporter(tmp_path)
    ignore = tmp_path / "Generated" / ".gitignore"
    assert ignore.is_file()
    assert "READINESS_REPORT.md" in ignore.read_text().split()


def test_gitignore_write_is_idempotent_and_preserves_existing_rules(tmp_path):
    gen = tmp_path / "Generated"
    gen.mkdir()
    (gen / ".gitignore").write_text("scratch/\n")
    run_reporter(tmp_path)
    first = (gen / ".gitignore").read_text()
    run_reporter(tmp_path)
    assert (gen / ".gitignore").read_text() == first
    assert "scratch/" in first
    assert first.split().count("READINESS_REPORT.md") == 1


def test_read_only_target_still_exits_zero(tmp_path):
    """The "Always exits 0" guarantee must survive an unwritable tree."""
    repo = tmp_path / "ro"
    repo.mkdir()
    (repo / "README.md").write_text("# ro\n")
    os.chmod(repo, stat.S_IRUSR | stat.S_IXUSR)
    try:
        result = run_reporter(repo)
        assert result.returncode == 0, result.stderr
        assert "WARNING" in result.stderr
        assert summary_of(result)["achieved_level"] == 0
    finally:
        os.chmod(repo, stat.S_IRWXU)


def test_report_body_is_ascii_safe(tmp_path):
    """The report is written and printed on machines with a non-UTF-8 locale;
    keep the body free of characters that raise there."""
    make_converted_repo(tmp_path)
    result = run_reporter(tmp_path, "--stdout")
    result.stdout.encode("ascii")


def test_report_carries_generation_provenance(tmp_path):
    """Every framework artifact is stamped so a stale copy is recognizable, and
    so UPDATE mode can tell generated files from human-edited ones."""
    run_reporter(tmp_path)
    report = (tmp_path / "Generated" / "READINESS_REPORT.md").read_text()
    assert "**Generated by:** scripts/onboarding/readiness_report.py" in report
    assert "**Date:**" in report


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


def test_help_and_unknown_flags_do_not_become_repo_paths(tmp_path):
    for flag in ("--help", "-h"):
        result = subprocess.run([sys.executable, str(REPORTER), flag],
                                capture_output=True, text=True)
        assert result.returncode == 0
        assert "usage:" in result.stderr
        assert "does not exist" not in result.stderr
    result = subprocess.run([sys.executable, str(REPORTER), "--verbose", str(tmp_path)],
                            capture_output=True, text=True)
    assert result.returncode == 0
    assert "unknown option(s): --verbose" in result.stderr
    assert not (tmp_path / "Generated").exists()


def test_tests_criterion_ignores_vendor_and_vcs_directories(tmp_path):
    """node_modules and .git carry other projects' tests; counting them would
    score a repo on someone else's suite (and cost a full walk of both)."""
    for junk in ("node_modules/pkg/tests", ".git/hooks/tests", "vendor/lib/tests"):
        (tmp_path / junk).mkdir(parents=True)
        (tmp_path / junk / "test_vendor.py").write_text("def test(): pass\n")
    assert reporter.c_tests_exist(tmp_path) is False
    (tmp_path / "src" / "test").mkdir(parents=True)
    assert reporter.c_tests_exist(tmp_path) is True
