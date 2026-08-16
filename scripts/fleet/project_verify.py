#!/usr/bin/env python3
"""project_verify.py -- the everything-created gate for a PROJECT conversion.

Fleet counterpart of scripts/onboarding/final_verify.py: one command, one exit
code. Exit 0 = the project layer is complete and internally consistent; exit 1
= the table names exactly what is missing. Never fixes anything itself.

Checks:
    R1  MEMBERS.yaml exists, parses, >= 1 member
    R2  Generated/DRIFT.md exists non-empty (discovery ran, anomalies stated)
    R3  Generated/FLEET_REGISTRY.md + .jsonl exist; jsonl row count == roster size
    R4  PROJECT_INDEX.md exists, has >= 1 pointer line, and stays a ROUTER:
        hard size cap (default 64 KB) -- inlining a member's knowledge is the
        failure this gate exists to catch
    R5  Generated/CROSS_REPO_GRAPH.jsonl + ARCHITECTURE_MAP.md exist (an empty
        graph file is legal -- absence of edges is a finding, absence of the
        FILE means the resolver never ran)
    R6  CLAUDE.md project shell exists (skippable for scratch runs: --no-shell)
    R7  BINDING.yml exists when --require-binding (the /start-sdlc-feature
        contract needs it before any ticket can be cut)
    R8  no unexpanded placeholders ({{...}} / TODO-FILL) in the generated files

Usage:
    python3 project_verify.py <project-dir> [--no-shell] [--require-binding]
"""
import argparse
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fleetlib import parse_members  # noqa: E402

INDEX_CAP_BYTES = 64 * 1024

# Every field /start-sdlc-feature reads out of BINDING.yml before it can cut a
# ticket. Phase 5 writes the ones it has no evidence for as literal `TODO:` lines
# ON PURPOSE -- a TODO is honest and a guessed epic pollutes another team's
# velocity -- so the gate has to treat a TODO as "not done yet", not as a value.
BINDING_FIELDS = ("jira_project", "epic", "board", "dev_classification",
                  "assignee_account_id")
TODO_VALUE_RE = re.compile(r"^['\"]?TODO\b", re.I)
# [^\S\n] is same-line whitespace. Plain \s* would match the NEWLINE too, so for
# `epic:\nboard: 42` the engine backtracks over the line break and (.*) captures
# `board: 42` -- an empty epic reads as filled, and R7 passes a binding no ticket
# can be cut from. It only ever worked when the empty field was the file's last
# line, which is exactly where a naive fixture puts it.
_SP = r"[^\S\n]*"


def binding_gaps(path):
    """(todo_fields, missing_fields) for a BINDING.yml.

    An existence-only R7 passed a file whose every ticket-creating field was the
    string `TODO`, which is exactly the state Phase 5 leaves behind when no
    evidence was found. Phase 6 then reported ALL CHECKS PASS and Phase 7 cut
    tickets against `parent: TODO`.
    """
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            text = f.read()
    except OSError:
        return [], list(BINDING_FIELDS)
    todo, missing = [], []
    for field in BINDING_FIELDS:
        m = re.search(r"^%s%s%s:%s(.*)$" % (_SP, re.escape(field), _SP, _SP),
                      text, re.M)
        if not m:
            missing.append(field)
        elif not m.group(1).strip() or TODO_VALUE_RE.match(m.group(1).strip()):
            todo.append(field)
    return todo, missing


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("project_dir")
    ap.add_argument("--no-shell", action="store_true",
                    help="scratch mode: do not require CLAUDE.md/BINDING.yml shell files")
    ap.add_argument("--require-binding", action="store_true")
    a = ap.parse_args()
    P = a.project_dir

    rows, failed = [], False

    def check(name, ok, detail):
        nonlocal failed
        rows.append((name, "PASS" if ok else "FAIL", detail))
        if not ok:
            failed = True

    # R1 roster
    n_members = 0
    try:
        _, members = parse_members(os.path.join(P, "MEMBERS.yaml"))
        n_members = len(members)
        check("R1 MEMBERS.yaml", True, "%d member(s)" % n_members)
    except ValueError as e:
        check("R1 MEMBERS.yaml", False, str(e))

    # R2 drift
    dp = os.path.join(P, "Generated", "DRIFT.md")
    check("R2 DRIFT.md", os.path.isfile(dp) and os.path.getsize(dp) > 0,
          dp if os.path.isfile(dp) else "missing: %s" % dp)

    # R3 registry
    rj = os.path.join(P, "Generated", "FLEET_REGISTRY.jsonl")
    rm = os.path.join(P, "Generated", "FLEET_REGISTRY.md")
    n_rows = 0
    if os.path.isfile(rj):
        with open(rj) as f:
            n_rows = sum(1 for line in f if line.strip())
    ok = os.path.isfile(rj) and os.path.isfile(rm) and n_rows == n_members and n_rows > 0
    check("R3 fleet registry", ok,
          "rows=%d roster=%d md=%s" % (n_rows, n_members, "yes" if os.path.isfile(rm) else "MISSING"))

    # R4 router
    ip = os.path.join(P, "PROJECT_INDEX.md")
    if not os.path.isfile(ip):
        check("R4 PROJECT_INDEX.md", False, "missing: %s" % ip)
    else:
        size = os.path.getsize(ip)
        text = open(ip, encoding="utf-8", errors="replace").read()
        pointers = len(re.findall(r"^\s+->\s+`", text, re.M))
        ok = size <= INDEX_CAP_BYTES and pointers >= 1
        check("R4 PROJECT_INDEX.md", ok,
              "size=%dB (cap %d) pointers=%d%s" % (
                  size, INDEX_CAP_BYTES, pointers,
                  "" if size <= INDEX_CAP_BYTES else " -- ROUTER CAP EXCEEDED: inlining suspected"))

    # R5 cross-repo graph
    gp = os.path.join(P, "Generated", "CROSS_REPO_GRAPH.jsonl")
    mp = os.path.join(P, "Generated", "ARCHITECTURE_MAP.md")
    n_edges, malformed = 0, 0
    if os.path.isfile(gp):
        with open(gp) as f:
            for i, line in enumerate(f, 1):
                if not line.strip():
                    continue
                try:
                    json.loads(line)
                    n_edges += 1
                except ValueError:
                    malformed = malformed or i
                    break
    # One row per check, always: emitting a FAIL row and then a second PASS row
    # under the SAME name for the same check made a failing gate read as passing
    # to anyone scanning the table.
    check("R5 cross-repo graph",
          os.path.isfile(gp) and os.path.isfile(mp) and not malformed,
          "edges=%d map=%s%s" % (
              n_edges, "yes" if os.path.isfile(mp) else "MISSING",
              " -- MALFORMED JSONL at %s:%d" % (gp, malformed) if malformed else ""))

    # R6 shell
    if not a.no_shell:
        cp = os.path.join(P, "CLAUDE.md")
        check("R6 CLAUDE.md shell", os.path.isfile(cp) and os.path.getsize(cp) > 0,
              cp if os.path.isfile(cp) else "missing: %s" % cp)

    # R7 binding
    if a.require_binding:
        bp = os.path.join(P, "BINDING.yml")
        if not os.path.isfile(bp):
            check("R7 BINDING.yml", False, "missing: %s" % bp)
        else:
            todo, missing = binding_gaps(bp)
            detail = bp
            if missing:
                detail = "%s -- absent field(s): %s" % (bp, ", ".join(missing))
            elif todo:
                detail = "%s -- unresolved TODO field(s): %s" % (bp, ", ".join(todo))
            check("R7 BINDING.yml", not todo and not missing, detail)

    # R8 placeholders
    leaks = []
    for rel in ("PROJECT_INDEX.md",
                os.path.join("Generated", "FLEET_REGISTRY.md"),
                os.path.join("Generated", "ARCHITECTURE_MAP.md")):
        fp = os.path.join(P, rel)
        if os.path.isfile(fp):
            body = open(fp, encoding="utf-8", errors="replace").read()
            if re.search(r"\{\{[^}]+\}\}|TODO-FILL", body):
                leaks.append(rel)
    check("R8 placeholder scan", not leaks, ", ".join(leaks) or "clean")

    width = max(len(r[0]) for r in rows)
    print("\nPROJECT VERIFY -- %s\n" % P)
    for name, status, detail in rows:
        print("  %-*s  %-4s  %s" % (width, name, status, detail))
    print("\n%s\n" % ("ALL CHECKS PASS" if not failed else "INCOMPLETE -- fix the FAIL rows above"))
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
