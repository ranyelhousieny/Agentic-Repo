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
    either     Contract alternatives: a repo is governed by CODEOWNERS or has
               the derived CODEOWNERS.proposed awaiting review; the engine left
               CODE_GRAPH.jsonl or the loud-skip contract left
               GRAPHIFY_BOOTSTRAP.err naming the reason. Absence of BOTH halves
               is the failure.
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
    "Knowledge/golden/GOLDEN_FACTS.jsonl", "Knowledge/golden/GOLDEN_FACTS.md",
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
    ("Generated/graphify/CODE_GRAPH.jsonl", "Generated/Analysis/GRAPHIFY_BOOTSTRAP.err"),
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

    for a, b in EITHER:
        ok = nonempty(repo / a) or nonempty(repo / b)
        rows.append(("either", "%s | %s" % (a, b), ok,
                     "" if ok else "neither half present"))

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
