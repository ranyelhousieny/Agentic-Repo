#!/usr/bin/env python3
"""final_verify.py — the conversion's last gate: everything created, correctly.

The Step 5 `ls` in the workflow proves files exist; the completion checklist is
prose an agent can skim past. This script makes "everything was created
successfully" MECHANICAL: one command, one exit code, a table naming exactly
what is missing when something is. Runs as the final step of every conversion
and is equally useful standalone as a health check on an already-converted repo.

Check classes (every one derived from the conversion's own contract):

    required   File exists AND is non-empty. An empty CLAUDE.md is a created
               file and a failed conversion at the same time — existence-only
               checks cannot tell the difference.
    glob       At least one match, non-empty (domain-agent skill, -ai command,
               agent source prompt, the three native agents).
    either     Contract alternatives: ANY one of N stated paths satisfies the
               row; absence of all of them is the failure. A repo is governed by
               CODEOWNERS or has the derived CODEOWNERS.proposed awaiting review.
               The engine left CODE_GRAPH.jsonl, or one of the three markers that
               each state WHY there is no graph -- bootstrap failure
               (GRAPHIFY_BOOTSTRAP.err), operator kill switch (GRAPHIFY_SKIPPED),
               or a clean run that found no dependency edges
               (GRAPHIFY_NO_EDGES). Golden facts exist, or GOLDEN_FACTS_NONE.md
               states that this repo has nothing derivable to assert.

               The point of the N-way form: "no dependency graph" and "no golden
               facts" are legitimate outcomes for real repo classes (the kill
               switch is documented, a docs repo has no endpoints), and the
               two-way form turned both into a hard conversion failure with no
               way through. Absence still has to be STATED -- a marker, never
               silence -- which is why the alternatives are files and not a
               loosened check.
    registered Knowledge/CODE_INDEX.md is named in CLAUDE.md (Session-Init),
               KNOWLEDGE_GRAPH.md, and DOCUMENT_INDEX.md — a generated index
               nobody can navigate to is dead weight (this was a prose
               checklist item; now it is enforced).
    no-leak    Unexpanded template placeholders ($REPO_NAME_LOWER,
               ${REPO_NAME_UPPER}, $TODAY ...) in emitted markdown mean a
               substitution failure shipped. Scans only conversion-emitted
               files — shell vars in generated .sh wrappers are legitimate.

Exit 0 all pass / 1 any fail / 3 usage.
"""
import re
import sys
from pathlib import Path

REQUIRED = [
    "CLAUDE.md", "AGENTS.md", "START_HERE.md", "BINDING.yml",
    "Knowledge/KNOWLEDGE_GRAPH.md", "Knowledge/DOCUMENT_INDEX.md",
    "Knowledge/CODE_INDEX.md", "Knowledge/SME_CONTACTS.md",
    "Knowledge/Source of Truth/PROJECT_VISION.md",
    "Generated/PROGRESS_TRACKER.md", "Generated/Analysis/PHASE1_DETECTION.md",
    "Generated/VALIDATION_SUMMARY.md", "Generated/scripts/run_verify_citations.sh",
    ".claude/agents/developer.md", ".claude/agents/researcher.md",
    ".claude/agents/code-reviewer.md",
]
GLOBS = [
    ".claude/skills/*-agent/SKILL.md",
    ".claude/commands/*-ai.md",
    "prompts/templates/AI Agents/*_AI_AGENT.md",
]
EITHER = [
    ("CODEOWNERS", "CODEOWNERS.proposed"),
    # No graph is legal in THREE documented states, and each one names itself with a
    # marker -- a proven-impossible install (GRAPHIFY_BOOTSTRAP.err), the operator kill
    # switch (GRAPHIFY_SKIPPED), and a clean engine run that resolved zero dependency
    # edges (GRAPHIFY_NO_EDGES; write_jsonl leaves no CODE_GRAPH.jsonl, and the success
    # path has already rm -f'd the .err). The last two used to fail this row and abort
    # Step 15.8, contradicting the adapter's own removal drill and
    # readiness_report.py's c_code_graph, which scores the same absence as N/A.
    # The markers are why the row is satisfiable at all: the kill switch does NOT
    # "write nothing" -- Phase 1.5's `*)` arm writes GRAPHIFY_SKIPPED precisely so this
    # contract has a half present. It writes no adapter log and no records; that is the
    # part that stayed true. Absence of a graph is always stated, never assumed.
    ("Generated/graphify/CODE_GRAPH.jsonl",
     "Generated/Analysis/GRAPHIFY_BOOTSTRAP.err",
     "Generated/Analysis/GRAPHIFY_SKIPPED",
     "Generated/Analysis/GRAPHIFY_NO_EDGES"),
    # A repo whose CODE_INDEX has no endpoint / entry_point / config rows has
    # nothing to derive (golden_facts.py derive exits 3). Requiring the facts
    # outright made a docs repo -- including this framework's own
    # self-conversion -- unconvertible.
    ("Knowledge/golden/GOLDEN_FACTS.jsonl", "Knowledge/golden/GOLDEN_FACTS_NONE.md"),
    ("Knowledge/golden/GOLDEN_FACTS.md", "Knowledge/golden/GOLDEN_FACTS_NONE.md"),
]
REGISTERED_IN = ["CLAUDE.md", "Knowledge/KNOWLEDGE_GRAPH.md",
                 "Knowledge/DOCUMENT_INDEX.md"]
LEAK_RE = re.compile(r"\$\{?REPO_NAME(_LOWER|_UPPER)?\}?\b|\$\{?TODAY\}?\b")
LEAK_SCAN = ["CLAUDE.md", "AGENTS.md", "START_HERE.md",
             "Knowledge/KNOWLEDGE_GRAPH.md", "Knowledge/DOCUMENT_INDEX.md",
             "Knowledge/SME_CONTACTS.md", "Generated/PROGRESS_TRACKER.md"]


def nonempty(p):
    return p.is_file() and p.stat().st_size > 0


def main():
    if len(sys.argv) != 2:
        print("usage: final_verify.py <repo_path>", file=sys.stderr)
        return 3
    repo = Path(sys.argv[1]).resolve()
    if not repo.is_dir():
        print("[final_verify] not a directory: %s" % repo, file=sys.stderr)
        return 3

    rows = []

    for rel in REQUIRED:
        ok = nonempty(repo / rel)
        rows.append(("required", rel, ok,
                     "" if ok else "missing or empty"))

    for pattern in GLOBS:
        hits = [h for h in repo.glob(pattern) if nonempty(h)]
        rows.append(("glob", pattern, bool(hits),
                     "%d match(es)" % len(hits) if hits else "no non-empty match"))

    for alternatives in EITHER:
        present = [alt for alt in alternatives if nonempty(repo / alt)]
        rows.append(("either", " | ".join(alternatives), bool(present),
                     present[0] if present else "no alternative present"))

    for rel in REGISTERED_IN:
        f = repo / rel
        ok = f.is_file() and "CODE_INDEX.md" in f.read_text(encoding="utf-8",
                                                            errors="replace")
        rows.append(("registered", "CODE_INDEX.md named in %s" % rel, ok,
                     "" if ok else "not mentioned"))

    for rel in LEAK_SCAN:
        f = repo / rel
        if not f.is_file():
            continue  # absence already reported by the required class
        leaks = LEAK_RE.findall(f.read_text(encoding="utf-8", errors="replace"))
        rows.append(("no-leak", rel, not leaks,
                     "" if not leaks else "unexpanded placeholder(s) found"))

    failed = [(k, name, note) for k, name, ok, note in rows if not ok]
    width = max(len(name) for _, name, _, _ in rows)
    for kind, name, ok, note in rows:
        print("  [%s] %-10s %-*s %s"
              % ("PASS" if ok else "FAIL", kind, width, name, note))
    print("[final_verify] %d/%d checks pass" % (len(rows) - len(failed), len(rows)))
    if failed:
        for kind, name, note in failed:
            print("[final_verify] FAIL %s: %s (%s)" % (kind, name, note),
                  file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
