#!/usr/bin/env python3
# Requires: python3 3.9+
"""
readiness_report.py — Scored, gated agent-readiness report for a repository.

Usage:
    python3 scripts/onboarding/readiness_report.py <repo_path> [--stdout]

Emits Generated/READINESS_REPORT.md in the target repo (or the full report on
stdout with --stdout, writing nothing), plus a one-line JSON summary on stderr.
Always exits 0 — including when the target tree is read-only.

Design lineage (assessed 2026-08-14): the gated-level mechanics are adapted from
Factory's Agent Readiness Model (docs.factory.ai/agent-readiness/overview) — five
levels, pass 80% of a level's criteria to unlock the next, a difficulty axis per
criterion, and a remediation hint per failure. What is deliberately NOT adopted:
  - No platform persistence. The report is a LOCAL artifact under Generated/;
    nothing leaves the machine and no dashboard association exists. That is
    enforced, not asserted: the writer drops a scoped Generated/.gitignore so the
    conversion's own `git add -A` (Step 16, Next Steps) cannot commit the report.
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

Note on the gate: 80% is the adapted mechanic, but each level here carries only
3-4 criteria, so 80% rounds up to EVERY applicable criterion at every level (2/3
= 67%, 3/4 = 75% — both below the gate). The report prints the derived threshold
per level in a "Needed" column rather than leaving the reader to infer tolerance
that does not exist; passing_threshold() derives it from GATE so the printed
number can never disagree with the unlock decision.
"""
from __future__ import annotations

import json
import os
import sys
from datetime import date
from pathlib import Path
from typing import Callable, List, Optional, Tuple

GATE = 0.8

# Bytes across the eager-load boundary. The framework measures this same boundary
# with `cat ... | wc -c` (bytes) against "Budget limit (rationale in framework history)
# ~360,000 chars" — REPO_ONBOARDING_AGENT.md, "Activation Token Budget" section.
# Same unit and same limit, so a repo inside the framework's own documented budget
# is not failed here.
EAGER_LOAD_BUDGET_BYTES = 360_000

# What every activation actually reads, per the Session-Init block the converter
# injects into CLAUDE.md (REPO_ONBOARDING_AGENT.md Step 6) plus the domain skill's
# own "Eager Load (every activation)" list. Globs are expanded; missing paths are
# skipped. Knowledge/ documents that are NOT in that block (DOCUMENT_INDEX.md,
# Analysis/, VALIDATION_SUMMARY.md) are on-demand and deliberately excluded.
EAGER_FILES = (
    "CLAUDE.md",
    "AGENTS.md",
    "START_HERE.md",
    "START_HERE.agentic.md",
    "Knowledge/KNOWLEDGE_GRAPH.md",
    "Knowledge/CODE_INDEX.md",
    "Knowledge/Source of Truth/PROJECT_VISION.md",
    "Generated/PROGRESS_TRACKER.md",
    # Only the domain agent is in the Session-Init eager block; task skills
    # (deploy helpers, one-off tools) load on invocation. Measured: a repo-native
    # 16KB deploy skill pushed campaign-runner over the cap under the old
    # .claude/skills/*/SKILL.md glob while its actual eager boundary was under.
    ".claude/skills/*-agent/SKILL.md",
)

# Directories that can never hold first-party source or tests. Pruned from the
# recursive walk: Path.glob("**/test_*.py") descends into .git and node_modules,
# which turns a boolean answer into tens of seconds on a large repo.
SKIP_DIRS = {".git", ".hg", ".svn", "node_modules", "vendor", "target", "build",
             "dist", ".venv", "venv", "__pycache__", ".tox", ".mypy_cache",
             ".pytest_cache", ".gradle", ".idea"}

TEST_DIR_NAMES = {"tests", "test", "spec", "specs", "__tests__"}
TEST_FILE_SUFFIXES = ("_test.py", "_test.go", "_test.rb", ".test.ts", ".test.js",
                      ".test.tsx", ".test.jsx", ".spec.ts", ".spec.js", "Test.java",
                      "Tests.java", "Tests.cs", "_spec.rb")

REPORT_NAME = "READINESS_REPORT.md"

GITIGNORE_BODY = (
    "# Machine-local agent-readiness report -- never committed.\n"
    "# It records an absolute repo path and is regenerated on every run.\n"
    "# Written by scripts/onboarding/readiness_report.py.\n"
    f"{REPORT_NAME}\n"
)

USAGE = "[readiness_report] usage: readiness_report.py <repo_path> [--stdout]"


def _matches(repo: Path, pattern: str) -> List[Path]:
    """Every existing path matching one pattern (plain relative path or glob)."""
    if "*" in pattern or "/" in pattern:
        return sorted(repo.glob(pattern))
    target = repo / pattern
    return [target] if target.exists() else []


def _any(repo: Path, patterns) -> bool:
    return any(_matches(repo, pat) for pat in patterns)


def _nonempty(repo: Path, relative: str, pattern: str = "*") -> bool:
    """True when `relative` is a directory holding at least one matching FILE.

    Used wherever a criterion claims something is in use rather than merely
    scaffolded: the converter itself creates Generated/session_logs/ and
    Knowledge/Source of Truth/, so bare directory existence proves nothing.
    """
    directory = repo / relative
    return directory.is_dir() and any(p.is_file() for p in directory.glob(pattern))


def c_readme(repo: Path) -> Optional[bool]:
    return _any(repo, ("README.md", "README.rst", "README.txt", "readme.md"))


def c_gitignore(repo: Path) -> Optional[bool]:
    return (repo / ".gitignore").is_file()


def c_build_manifest(repo: Path) -> Optional[bool]:
    return _any(repo, ("pyproject.toml", "package.json", "pom.xml", "build.gradle",
                       "build.gradle.kts", "go.mod", "Cargo.toml", "Makefile",
                       "Dockerfile", "setup.py", "requirements.txt"))


def c_tests_exist(repo: Path) -> Optional[bool]:
    """A test directory at any depth, or any file named by a test convention.

    Walks top-down with SKIP_DIRS pruned and returns on the first hit, so the
    common case costs a few directory reads. os.walk does not follow symlinks.
    """
    for dirpath, dirnames, filenames in os.walk(repo):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        if dirpath != str(repo) and os.path.basename(dirpath) in TEST_DIR_NAMES:
            return True
        for name in filenames:
            if name.endswith(TEST_FILE_SUFFIXES):
                return True
            if name.startswith("test_") and name.endswith(".py"):
                return True
    return False


def c_ci_config(repo: Path) -> Optional[bool]:
    return _any(repo, (".gitlab-ci.yml", "Jenkinsfile", ".github/workflows",
                       ".circleci/config.yml", "azure-pipelines.yml"))


def c_linter_config(repo: Path) -> Optional[bool]:
    if _any(repo, (".eslintrc", ".eslintrc.js", ".eslintrc.json", ".flake8",
                   ".pylintrc", "ruff.toml", ".ruff.toml", ".golangci.yml",
                   "detekt.yml", "checkstyle.xml", ".editorconfig",
                   ".pre-commit-config.yaml", "sonar-project.properties")):
        return True
    # Monorepos configure linters per service, not at the root (measured:
    # campaign-runner lints via services/*/pyproject.toml [tool.ruff] and was
    # falsely failed by a root-only read). Two levels covers the common
    # services/<name>/ and libs/<name>/ layouts without walking the whole tree.
    for py in [repo / "pyproject.toml",
               *repo.glob("*/pyproject.toml"), *repo.glob("*/*/pyproject.toml")]:
        if py.is_file():
            text = py.read_text(encoding="utf-8", errors="replace")
            if any(k in text for k in ("[tool.ruff", "[tool.flake8", "[tool.pylint",
                                       "[tool.black", "[tool.mypy")):
                return True
    return False


def c_codeowners(repo: Path) -> Optional[bool]:
    return _any(repo, ("CODEOWNERS", ".gitlab/CODEOWNERS", ".github/CODEOWNERS",
                       "docs/CODEOWNERS"))


def c_agent_instructions(repo: Path) -> Optional[bool]:
    return _any(repo, ("CLAUDE.md", "AGENTS.md"))


def c_start_here(repo: Path) -> Optional[bool]:
    return _any(repo, ("START_HERE.md", "START_HERE.agentic.md", "AI_Start_Here"))


def c_eager_budget(repo: Path) -> Optional[bool]:
    """Measured, not assumed: total bytes of the eager-load boundary under the cap.
    N/A when none of those files exist yet (L3's other criteria cover that)."""
    seen = set()
    total = 0
    for pattern in EAGER_FILES:
        for hit in _matches(repo, pattern):
            if not hit.is_file():
                continue
            key = os.path.realpath(hit)
            if key in seen:
                continue
            seen.add(key)
            total += hit.stat().st_size
    if not seen:
        return None
    return total <= EAGER_LOAD_BUDGET_BYTES


def c_knowledge_graph(repo: Path) -> Optional[bool]:
    return _any(repo, ("Knowledge/KNOWLEDGE_GRAPH.md", "KNOWLEDGE_GRAPH.md"))


def c_document_index(repo: Path) -> Optional[bool]:
    return _any(repo, ("Knowledge/DOCUMENT_INDEX.md",))


def c_code_index(repo: Path) -> Optional[bool]:
    return _any(repo, ("Knowledge/CODE_INDEX.md",))


def c_code_graph(repo: Path) -> Optional[bool]:
    """Pass or N/A -- never a penalty, because the engine is optional.

    A code-graph engine adapter is an optional framework motion; nothing in a
    conversion requires one, and none is wired up on this branch. Keyed on the
    artifact of a COMPLETED run rather than on the Generated/graphify/ directory,
    because an adapter would create that directory as soon as the engine is
    installed and write CODE_GRAPH.jsonl only once a run produced at least one
    dependency edge -- so directory existence cannot tell "never ran" apart from
    "ran, found nothing". Failing on that difference would let installing an
    explicitly non-load-bearing tool LOWER a repo's level, contradicting the
    framework rule that a repo is never penalized for a tool it never used.
    """
    if (repo / "Generated" / "graphify" / "CODE_GRAPH.jsonl").is_file():
        return True
    return None


def c_source_of_truth(repo: Path) -> Optional[bool]:
    return _nonempty(repo, "Knowledge/Source of Truth", "*.md")


def c_session_logs(repo: Path) -> Optional[bool]:
    """In use, not merely scaffolded: the converter creates Generated/session_logs/
    itself, so an empty directory (or a lone .gitkeep) proves nothing."""
    return (_nonempty(repo, "Generated/session_logs", "*.md")
            or _nonempty(repo, ".claude/context-history", "*.md"))


def c_progress_tracker(repo: Path) -> Optional[bool]:
    return _any(repo, ("Generated/PROGRESS_TRACKER.md", "PROGRESS_TRACKER.md"))


def c_eval_assets(repo: Path) -> Optional[bool]:
    return (_nonempty(repo, "scripts/eval/golden") or _nonempty(repo, "Knowledge/golden")
            or _nonempty(repo, "scripts/eval"))


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
     "Review the generated CODEOWNERS.proposed (Step 10.9 evidence draft), "
     "rename it to CODEOWNERS, and commit — or write one from scratch"),
    (3, "instructions", "Agent instruction file (CLAUDE.md / AGENTS.md)", "Intermediate",
     c_agent_instructions,
     "Run /convert-repo-to-agentic Phase 1 to generate honest instruction files"),
    (3, "start-here", "START_HERE entry point", "Basic", c_start_here,
     "Run /convert-repo-to-agentic Phase 1 (START_HERE.md)"),
    (3, "eager-budget", "Eager-loaded files within token budget (measured)",
     "Intermediate", c_eager_budget,
     f"Trim the eager-load boundary below {EAGER_LOAD_BUDGET_BYTES:,} bytes; move "
     f"detail into Knowledge/ (loaded on demand)"),
    (4, "knowledge-graph", "Knowledge Graph present", "Intermediate", c_knowledge_graph,
     "Run /convert-repo-to-agentic Phase 2 (Knowledge/KNOWLEDGE_GRAPH.md)"),
    (4, "document-index", "Document index present", "Intermediate", c_document_index,
     "Run /convert-repo-to-agentic Phase 2 (Knowledge/DOCUMENT_INDEX.md)"),
    (4, "code-index", "Cited code index present", "Intermediate", c_code_index,
     "Run /convert-repo-to-agentic Phase 1.5 (extractors emit Knowledge/CODE_INDEX.md)"),
    (4, "code-graph", "Dependency graph from the optional engine", "Advanced",
     c_code_graph,
     "Optional: run the code-graph engine adapter, once that framework motion is "
     "available, and re-run Phase 1.5"),
    (5, "source-of-truth", "Source of Truth tier in use", "Advanced", c_source_of_truth,
     "Add authoritative decisions under Knowledge/Source of Truth/ (an empty tier "
     "does not count)"),
    (5, "session-logs", "Session continuity in use", "Advanced", c_session_logs,
     "Write session logs to Generated/session_logs/ via the session-context command "
     "(an empty directory does not count)"),
    (5, "progress-tracker", "Progress tracker present", "Intermediate", c_progress_tracker,
     "Create Generated/PROGRESS_TRACKER.md"),
    (5, "eval-assets", "Eval assets (golden facts / jury harness)", "Advanced",
     c_eval_assets,
     "Add golden-fact assertions so KB claims stay verifiable"),
]

LEVEL_NAMES = {1: "Orientation", 2: "Hygiene", 3: "Instruction layer",
               4: "Knowledge layer", 5: "Governed autonomy"}


def passing_threshold(applicable: int) -> int:
    """Smallest pass count that satisfies GATE for this denominator.

    Derived from GATE rather than hardcoded so the number printed in the report
    can never disagree with the unlock decision made in level_scores().
    """
    if applicable <= 0:
        return 0
    for k in range(applicable + 1):
        if k / applicable >= GATE:
            return k
    return applicable


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
                         "needed": passing_threshold(len(applicable)),
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
    blocker = next((lvl for lvl in sorted(scores) if not scores[lvl]["unlocked"]), None)
    lines = [
        "# Agent Readiness Report",
        "",
        f"**Repository:** `{repo}`",
        "**Generated by:** scripts/onboarding/readiness_report.py",
        f"**Date:** {date.today().isoformat()}",
        f"**Achieved level:** L{achieved} -- "
        f"{LEVEL_NAMES.get(achieved, 'none unlocked') if achieved else 'none unlocked'}",
        "",
        f"**Gate:** a level passes at >= {int(GATE * 100)}% of its applicable criteria. "
        "The achieved level is the highest level whose own criteria pass AND whose "
        "lower levels all pass -- a passing level above a failing one does not count. "
        "With 3-4 criteria per level the gate rounds up to every applicable criterion; "
        "the Needed column below is the exact threshold.",
        "",
        "This report is a local artifact. Nothing is uploaded and no remote is required.",
        "",
        "| Level | Name | Score | Needed | Level passes | Counts toward achieved level |",
        "|---|---|---|---|---|---|",
    ]
    for level in sorted(LEVEL_NAMES):
        s = scores[level]
        if level <= achieved:
            counts = "yes"
        elif s["unlocked"] and blocker is not None:
            counts = f"no -- blocked by L{blocker}"
        else:
            counts = "no"
        lines.append(f"| L{level} | {LEVEL_NAMES[level]} | "
                     f"{s['passed']}/{s['applicable']} | "
                     f"{s['needed']}/{s['applicable']} | "
                     f"{'yes' if s['unlocked'] else 'no'} | {counts} |")
    lines += ["", "## Criteria", "",
              "| Level | Criterion | Difficulty | Result | Remediation |",
              "|---|---|---|---|---|"]
    for r in results:
        result = ("pass" if r["outcome"] else
                  "n/a" if r["outcome"] is None else "FAIL")
        # Only a real failure is work owed; n/a is not a debt (see c_code_graph).
        fix = r["remediation"] if r["outcome"] is False else "--"
        lines.append(f"| L{r['level']} | {r['description']} | {r['difficulty']} | "
                     f"{result} | {fix} |")
    lines += ["",
              "Failing criteria are ordered work: start with Basic difficulty at the "
              "lowest failing level. The converter is the remediation for L3-L5. "
              "Rows marked n/a are not work owed.", ""]
    return "\n".join(lines)


def ensure_report_ignored(gen_dir: Path) -> None:
    """Keep the report out of the TARGET repo's history.

    The report embeds the absolute repo path, and the conversion's own final
    instruction is `git add -A && git commit` (REPO_ONBOARDING_AGENT.md Step 16,
    Next Steps) -- so without this the "nothing leaves the machine" guarantee is
    only a comment. This framework already git-ignores Generated/Repos/*_PROFILE.md
    for exactly this reason ("carry machine paths... local-only"), but we write
    into a repo whose .gitignore we do not own, so drop a self-scoped one beside
    the report instead. Scoped to the report itself: the rest of Generated/ is
    committed on purpose.
    """
    marker = gen_dir / ".gitignore"
    try:
        existing = marker.read_text(encoding="utf-8") if marker.is_file() else ""
        if REPORT_NAME in existing.split():
            return
        if existing and not existing.endswith("\n"):
            existing += "\n"
        marker.write_text(existing + GITIGNORE_BODY, encoding="utf-8")
    except OSError as exc:
        print(f"[readiness_report] WARNING: could not write {marker} ({exc}) -- "
              f"{gen_dir / REPORT_NAME} is NOT git-ignored; do not commit it",
              file=sys.stderr)


def main() -> int:
    argv = sys.argv[1:]
    if "-h" in argv or "--help" in argv:
        print(USAGE, file=sys.stderr)
        print("[readiness_report] writes Generated/READINESS_REPORT.md in <repo_path>; "
              "--stdout prints the report instead and writes nothing", file=sys.stderr)
        return 0
    to_stdout = "--stdout" in argv
    args = [a for a in argv if a != "--stdout"]
    unknown = [a for a in args if a.startswith("-")]
    if unknown:
        print(f"[readiness_report] unknown option(s): {' '.join(unknown)}",
              file=sys.stderr)
        print(USAGE, file=sys.stderr)
        return 0
    if not args:
        print(USAGE, file=sys.stderr)
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
        out = repo / "Generated" / REPORT_NAME
        try:
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(report, encoding="utf-8")
        except OSError as exc:
            print(f"[readiness_report] WARNING: could not write {out} ({exc}) -- "
                  f"re-run with --stdout to see the report", file=sys.stderr)
        else:
            print(f"[readiness_report] written: {out}", file=sys.stderr)
            ensure_report_ignored(out.parent)

    summary = {"achieved_level": achieved,
               "levels": {str(lvl): f"{s['passed']}/{s['applicable']}"
                          for lvl, s in scores.items()}}
    print(f"[readiness_report] {json.dumps(summary)}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
