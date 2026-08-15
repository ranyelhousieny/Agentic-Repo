#!/usr/bin/env python3
# Requires: python3 3.9+
"""
readiness_report.py — Scored, gated agent-readiness report for a repository.

Usage:
    python3 scripts/onboarding/readiness_report.py <repo_path> [--stdout]

Emits Generated/READINESS_REPORT.md in the target repo (or the full report on
stdout with --stdout, writing nothing), plus a one-line JSON summary on stderr.
Always exits 0.

Design lineage (assessed 2026-08-14): the gated-level mechanics are adapted from
Factory's Agent Readiness Model (docs.factory.ai/agent-readiness/overview) — five
levels, pass 80% of a level's criteria to unlock the next, a difficulty axis per
criterion, and a remediation hint per failure. What is deliberately NOT adopted:
  - No platform persistence. The report is a LOCAL artifact under Generated/;
    nothing leaves the machine and no dashboard association exists.
  - No git `origin` requirement. Factory requires one specifically to associate
    the report with their platform; this reporter runs on a bare directory.
  - No third-party criteria taken on faith: every criterion below is a checkable
    filesystem/git fact with the check visible in this file — no LLM judgment.

The level semantics are the framework's own, not Factory's (theirs score substrate
hygiene; L3-L5 here score the instruction/knowledge/governance layers that the
/convert-repo-to-agentic workflow builds):

    L1 Orientation          a human or agent can find their way in
    L2 Hygiene              the substrate is testable, linted, owned
    L3 Instruction layer    agents get honest instructions inside a token budget
    L4 Knowledge layer      navigable knowledge + cited code index
    L5 Governed autonomy    source-of-truth tiers, session continuity, eval assets

A criterion returns True (pass), False (fail), or None (not applicable — excluded
from that level's denominator; e.g. the code-graph criterion when the optional
engine never ran). Levels gate at >= 80% of applicable criteria, in order; the
achieved level is the highest contiguously unlocked one.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Callable, List, Optional, Tuple

GATE = 0.8
EAGER_LOAD_CHAR_CAP = 100_000  # chars across eager-loaded files; ~25k tokens

EAGER_FILES = ("CLAUDE.md", "AGENTS.md", "START_HERE.md", "START_HERE.agentic.md",
               "Knowledge/CODE_INDEX.md")


def _any(repo: Path, patterns) -> bool:
    for pat in patterns:
        if "*" in pat or "/" in pat:
            if any(repo.glob(pat)):
                return True
        elif (repo / pat).exists():
            return True
    return False


def c_readme(repo: Path):
    return _any(repo, ("README.md", "README.rst", "README.txt", "readme.md"))


def c_gitignore(repo: Path):
    return (repo / ".gitignore").is_file()


def c_build_manifest(repo: Path):
    return _any(repo, ("pyproject.toml", "package.json", "pom.xml", "build.gradle",
                       "build.gradle.kts", "go.mod", "Cargo.toml", "Makefile",
                       "Dockerfile", "setup.py", "requirements.txt"))


def c_tests_exist(repo: Path):
    return _any(repo, ("tests", "test", "src/test", "spec",
                       "**/tests/__init__.py", "**/*_test.go", "**/*.test.ts",
                       "**/*.test.js", "**/test_*.py"))


def c_ci_config(repo: Path):
    return _any(repo, (".gitlab-ci.yml", "Jenkinsfile", ".github/workflows",
                       ".circleci/config.yml", "azure-pipelines.yml"))


def c_linter_config(repo: Path):
    if _any(repo, (".eslintrc", ".eslintrc.js", ".eslintrc.json", ".flake8",
                   ".pylintrc", "ruff.toml", ".ruff.toml", ".golangci.yml",
                   "detekt.yml", "checkstyle.xml", ".editorconfig",
                   ".pre-commit-config.yaml", "sonar-project.properties")):
        return True
    py = repo / "pyproject.toml"
    if py.is_file():
        text = py.read_text(errors="replace")
        return any(k in text for k in ("[tool.ruff", "[tool.flake8", "[tool.pylint",
                                       "[tool.black", "[tool.mypy"))
    return False


def c_codeowners(repo: Path):
    return _any(repo, ("CODEOWNERS", ".gitlab/CODEOWNERS", ".github/CODEOWNERS",
                       "docs/CODEOWNERS"))


def c_agent_instructions(repo: Path):
    return _any(repo, ("CLAUDE.md", "AGENTS.md"))


def c_start_here(repo: Path):
    return _any(repo, ("START_HERE.md", "START_HERE.agentic.md", "AI_Start_Here"))


def c_eager_budget(repo: Path):
    """Measured, not assumed: total chars of eager-loaded files under the cap.
    N/A when no instruction files exist yet (L3's other criteria cover that)."""
    sizes = [(repo / f).stat().st_size for f in EAGER_FILES if (repo / f).is_file()]
    if not sizes:
        return None
    return sum(sizes) <= EAGER_LOAD_CHAR_CAP


def c_knowledge_graph(repo: Path):
    return _any(repo, ("Knowledge/KNOWLEDGE_GRAPH.md", "KNOWLEDGE_GRAPH.md"))


def c_document_index(repo: Path):
    return _any(repo, ("Knowledge/DOCUMENT_INDEX.md",))


def c_code_index(repo: Path):
    return _any(repo, ("Knowledge/CODE_INDEX.md",))


def c_code_graph(repo: Path):
    """N/A unless the optional engine adapter ever ran (its output dir exists)."""
    if not (repo / "Generated" / "graphify").is_dir():
        return None
    return (repo / "Generated" / "graphify" / "CODE_GRAPH.jsonl").is_file()


def c_source_of_truth(repo: Path):
    return _any(repo, ("Knowledge/Source of Truth",))


def c_session_logs(repo: Path):
    return _any(repo, ("Generated/session_logs", ".claude/context-history"))


def c_progress_tracker(repo: Path):
    return _any(repo, ("Generated/PROGRESS_TRACKER.md", "PROGRESS_TRACKER.md"))


def c_eval_assets(repo: Path):
    return _any(repo, ("scripts/eval/golden", "Knowledge/golden", "scripts/eval"))


# (level, criterion id, description, difficulty, check, remediation)
CRITERIA: List[Tuple[int, str, str, str, Callable, str]] = [
    (1, "readme", "README present", "Basic", c_readme,
     "Add a README.md stating what the repo is and how to run it"),
    (1, "gitignore", ".gitignore present", "Basic", c_gitignore,
     "Add a .gitignore for build output and local state"),
    (1, "build-manifest", "Build/run manifest present", "Basic", c_build_manifest,
     "Add the ecosystem manifest (pyproject.toml, package.json, pom.xml, ...)"),
    (2, "tests", "Tests exist", "Basic", c_tests_exist,
     "Create a tests/ tree; even a smoke test changes agent behavior"),
    (2, "ci", "CI configuration present", "Intermediate", c_ci_config,
     "Add CI config (.gitlab-ci.yml / Jenkinsfile / workflow)"),
    (2, "linter", "Linter/formatter configured", "Basic", c_linter_config,
     "Add a linter config (ruff/eslint/detekt/...) or [tool.*] in pyproject"),
    (2, "codeowners", "CODEOWNERS present", "Basic", c_codeowners,
     "Add CODEOWNERS so agents and humans know who reviews what"),
    (3, "instructions", "Agent instruction file (CLAUDE.md / AGENTS.md)", "Intermediate",
     c_agent_instructions,
     "Run /convert-repo-to-agentic Phase 1 to generate honest instruction files"),
    (3, "start-here", "START_HERE entry point", "Basic", c_start_here,
     "Run /convert-repo-to-agentic Phase 1 (START_HERE.md)"),
    (3, "eager-budget", "Eager-loaded files within token budget (measured)",
     "Intermediate", c_eager_budget,
     f"Trim eager-loaded files below {EAGER_LOAD_CHAR_CAP:,} chars; move detail "
     f"into Knowledge/ (loaded on demand)"),
    (4, "knowledge-graph", "Knowledge Graph present", "Intermediate", c_knowledge_graph,
     "Run /convert-repo-to-agentic Phase 2 (Knowledge/KNOWLEDGE_GRAPH.md)"),
    (4, "document-index", "Document index present", "Intermediate", c_document_index,
     "Run /convert-repo-to-agentic Phase 2 (Knowledge/DOCUMENT_INDEX.md)"),
    (4, "code-index", "Cited code index present", "Intermediate", c_code_index,
     "Run /convert-repo-to-agentic Phase 1.5 (extractors emit Knowledge/CODE_INDEX.md)"),
    (4, "code-graph", "Dependency graph from the optional engine", "Advanced",
     c_code_graph,
     "Install the optional engine (see scripts/onboarding/README.md, "
     "extract_graphify.py) and re-run Phase 1.5"),
    (5, "source-of-truth", "Source of Truth tier exists", "Advanced", c_source_of_truth,
     "Create Knowledge/Source of Truth/ for authoritative decisions"),
    (5, "session-logs", "Session continuity wired", "Advanced", c_session_logs,
     "Create Generated/session_logs/ and use the session-context command"),
    (5, "progress-tracker", "Progress tracker present", "Intermediate", c_progress_tracker,
     "Create Generated/PROGRESS_TRACKER.md"),
    (5, "eval-assets", "Eval assets (golden facts / jury harness)", "Advanced",
     c_eval_assets,
     "Add golden-fact assertions so KB claims stay verifiable"),
]

LEVEL_NAMES = {1: "Orientation", 2: "Hygiene", 3: "Instruction layer",
               4: "Knowledge layer", 5: "Governed autonomy"}


def evaluate(repo: Path):
    results = []
    for level, cid, desc, difficulty, check, fix in CRITERIA:
        try:
            outcome = check(repo)
        except OSError:
            outcome = False
        results.append({"level": level, "id": cid, "description": desc,
                        "difficulty": difficulty, "outcome": outcome,
                        "remediation": fix})
    return results


def level_scores(results):
    scores = {}
    for level in sorted(LEVEL_NAMES):
        rows = [r for r in results if r["level"] == level]
        applicable = [r for r in rows if r["outcome"] is not None]
        passed = [r for r in applicable if r["outcome"]]
        frac = (len(passed) / len(applicable)) if applicable else 1.0
        scores[level] = {"passed": len(passed), "applicable": len(applicable),
                         "fraction": frac, "unlocked": frac >= GATE}
    return scores


def achieved_level(scores) -> int:
    achieved = 0
    for level in sorted(scores):
        if scores[level]["unlocked"]:
            achieved = level
        else:
            break
    return achieved


def render(repo: Path, results, scores, achieved: int) -> str:
    lines = [
        "# Agent Readiness Report",
        "",
        f"**Repository:** `{repo}`",
        f"**Achieved level:** L{achieved} — "
        f"{LEVEL_NAMES.get(achieved, 'none unlocked') if achieved else 'none unlocked'}",
        f"**Gate:** pass >= {int(GATE * 100)}% of a level's applicable criteria to "
        f"unlock the next (levels unlock in order)",
        "",
        "This report is a local artifact. Nothing is uploaded and no remote is required.",
        "",
        "| Level | Name | Score | Unlocked |",
        "|---|---|---|---|",
    ]
    for level in sorted(LEVEL_NAMES):
        s = scores[level]
        lines.append(f"| L{level} | {LEVEL_NAMES[level]} | "
                     f"{s['passed']}/{s['applicable']} | "
                     f"{'yes' if s['unlocked'] else 'no'} |")
    lines += ["", "## Criteria", "",
              "| Level | Criterion | Difficulty | Result | Remediation |",
              "|---|---|---|---|---|"]
    for r in results:
        result = ("pass" if r["outcome"] else
                  "n/a" if r["outcome"] is None else "FAIL")
        fix = "—" if r["outcome"] else r["remediation"]
        lines.append(f"| L{r['level']} | {r['description']} | {r['difficulty']} | "
                     f"{result} | {fix} |")
    lines += ["",
              "Failing criteria are ordered work: start with Basic difficulty at the "
              "lowest locked level. The converter is the remediation for L3-L5.", ""]
    return "\n".join(lines)


def main() -> int:
    args = [a for a in sys.argv[1:] if a != "--stdout"]
    to_stdout = "--stdout" in sys.argv[1:]
    if not args:
        print("[readiness_report] usage: readiness_report.py <repo_path> [--stdout]",
              file=sys.stderr)
        return 0
    repo = Path(args[0]).resolve()
    if not repo.is_dir():
        print(f"[readiness_report] repo path does not exist: {repo}", file=sys.stderr)
        return 0

    results = evaluate(repo)
    scores = level_scores(results)
    achieved = achieved_level(scores)
    report = render(repo, results, scores, achieved)

    if to_stdout:
        print(report)
    else:
        out = repo / "Generated" / "READINESS_REPORT.md"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(report)
        print(f"[readiness_report] written: {out}", file=sys.stderr)

    summary = {"achieved_level": achieved,
               "levels": {str(l): f"{s['passed']}/{s['applicable']}"
                          for l, s in scores.items()}}
    print(f"[readiness_report] {json.dumps(summary)}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
