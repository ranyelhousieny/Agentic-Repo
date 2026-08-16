#!/usr/bin/env python3
"""build_fleet_registry.py -- the fleet registry: one measured row per member.

Reads MEMBERS.yaml plus each cloned member's OWN conversion artifacts and writes:

    Generated/FLEET_REGISTRY.md      human table, one row per member
    Generated/FLEET_REGISTRY.jsonl   machine view, one JSON object per member

READ-ONLY against members. Absence is reported as "--", never guessed. Every
run stamps measured_at; volatile values are dated snapshots, not facts.

Columns and their sources (all verified against real converted repos 2026-08-15):
    converted    Knowledge/KNOWLEDGE_GRAPH.md + CLAUDE.md both exist
    readiness    Generated/READINESS_REPORT.md "**Achieved level:**"
    code_index   Knowledge/CODE_INDEX.md header "**Records:**" + "**Framework:**"
    graph_edges  Generated/graphify/CODE_GRAPH.jsonl line count (legacy path tried second)
    golden       Knowledge/golden/GOLDEN_FACTS.jsonl line count
    gate         Generated/CODE_INDEX_VALIDATION.md "Verification rate" -- NOTE:
                 that file holds the LAST validation run; the artifact it covers
                 is printed with the rate ("100.0% (SME_CONTACTS.md)") so the
                 scope is stated instead of implied
    freshness    STALE when git history moved after the KG header date;
                 UNKNOWN when either side is unparseable (date granularity)

Usage:
    python3 build_fleet_registry.py --project-dir <dir with MEMBERS.yaml> [--out-dir DIR]
"""
import argparse
import datetime
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fleetlib import (  # noqa: E402
    parse_members,
    member_root,
    is_converted,
    read_readiness_level,
    read_code_index,
    read_golden_count,
    read_gate,
    code_graph_stats,
    freshness_for,
    last_commit_for,
)


def measure_member(m, project_dir):
    row = {
        "slug": m.get("slug", ""),
        "gitlab_path": m.get("gitlab_path", ""),
        "policy": m.get("policy", "observe"),
        "kind": m.get("kind", ""),
        "local_path": m.get("local_path", ""),
        "source": "none",
        "converted": False,
        "readiness": None,
        "code_index_records": None,
        "framework": None,
        "graph_edges": None,
        "golden_facts": None,
        "gate_rate": None,
        "gate_scope": None,
        "last_commit": None,
        "freshness": "UNKNOWN",
    }
    repo, source = member_root(m, project_dir)
    row["source"] = source
    if source == "none":
        return row
    row["converted"] = is_converted(repo)
    row["last_commit"] = last_commit_for(repo, source)
    if not row["converted"]:
        return row
    row["readiness"] = read_readiness_level(repo)
    ci = read_code_index(repo)
    if ci:
        row["code_index_records"] = ci["records"]
        row["framework"] = ci["framework"]
    cg = code_graph_stats(repo)
    if cg:
        row["graph_edges"] = cg["edges"]
    row["golden_facts"] = read_golden_count(repo)
    gate = read_gate(repo)
    if gate and gate["rate"] is not None:
        row["gate_rate"] = gate["rate"]
        row["gate_scope"] = gate["artifact"]
    row["freshness"] = freshness_for(repo, source)
    return row


def dash(v):
    return "--" if v is None or v == "" else str(v)


# Columns whose source artifact the converter git-ignores in the target repo
# (Generated/READINESS_REPORT.md, Generated/graphify/CODE_GRAPH.jsonl), so they
# exist only in a local clone and can never be read from a default-branch replica.
# Rendering them as `--` alongside genuinely-absent artifacts told the reader
# "this repo has none", when the truth is "this SOURCE cannot see it" -- and the
# Maestro lane makes cache the primary source, so that was most rows.
CACHE_BLIND = "n/a*"


def cell(value, source, blind=False):
    if blind and source == "cache":
        return CACHE_BLIND
    return dash(value)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--project-dir", required=True)
    ap.add_argument("--out-dir", default="")
    a = ap.parse_args()

    out_dir = a.out_dir or a.project_dir
    members_path = os.path.join(a.project_dir, "MEMBERS.yaml")
    try:
        project, members = parse_members(members_path)
    except ValueError as e:
        print("[registry] FATAL: %s" % e, file=sys.stderr)
        sys.exit(2)

    stamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    rows = [measure_member(m, a.project_dir) for m in members]
    gen = os.path.join(out_dir, "Generated")
    os.makedirs(gen, exist_ok=True)

    jl = os.path.join(gen, "FLEET_REGISTRY.jsonl")
    with open(jl, "w") as f:
        for r in rows:
            f.write(json.dumps(r, sort_keys=True) + "\n")

    md = os.path.join(gen, "FLEET_REGISTRY.md")
    conv = [r for r in rows if r["converted"]]
    stale = [r for r in conv if r["freshness"] == "STALE"]
    with open(md, "w") as f:
        f.write("# FLEET REGISTRY -- %s\n\n" % project.get("group", project.get("slug", "?")))
        f.write("**Measured:** %s. Generated by scripts/fleet/build_fleet_registry.py -- do not hand-edit.\n" % stamp)
        f.write("**Scope:** %d roster members; %d read from local clones, %d from the remote cache "
                "(default-branch replica), %d unreadable; %d converted; %d converted-and-stale.\n\n"
                % (len(rows), sum(1 for r in rows if r["source"] == "local"),
                   sum(1 for r in rows if r["source"] == "cache"),
                   sum(1 for r in rows if r["source"] == "none"), len(conv), len(stale)))
        f.write("A `--` cell means the artifact is absent at the member's root, not that the value "
                "is zero. A `%s` cell means this SOURCE cannot see it: `readiness` and `graph edges` "
                "come from `Generated/READINESS_REPORT.md` and `Generated/graphify/CODE_GRAPH.jsonl`, "
                "which the converter git-ignores in the target repo, so they exist only in a local "
                "clone and never on the default branch a cache row replicates. `gate` states the "
                "artifact the rate was measured on -- the validation file holds the last run, which "
                "is not always CODE_INDEX.\n\n" % CACHE_BLIND)
        f.write("| member | policy | source | converted | readiness | CODE_INDEX | graph edges | golden | gate | last commit | KB freshness |\n")
        f.write("|---|---|---|---|---|---|---|---|---|---|---|\n")
        for r in sorted(rows, key=lambda x: (not x["converted"], x["slug"])):
            ci = dash(r["code_index_records"])
            if r["code_index_records"] is not None and r["framework"]:
                ci = "%s (%s)" % (r["code_index_records"], r["framework"])
            gate = "--"
            if r["gate_rate"] is not None:
                gate = "%.1f%%%s" % (r["gate_rate"], " (%s)" % r["gate_scope"] if r["gate_scope"] else "")
            f.write("| %s | %s | %s | %s | %s | %s | %s | %s | %s | %s | %s |\n" % (
                r["slug"], r["policy"], r["source"], "yes" if r["converted"] else "no",
                cell(r["readiness"], r["source"], blind=r["converted"]), ci,
                cell(r["graph_edges"], r["source"], blind=r["converted"]),
                dash(r["golden_facts"]), gate, dash(r["last_commit"]),
                r["freshness"] if r["converted"] else "--",
            ))
        if stale:
            f.write("\n## Stale knowledge bases (git moved after KG date)\n\n")
            for r in stale:
                f.write("- `%s` -- last commit %s, KG older. Re-run the converter in UPDATE mode.\n"
                        % (r["slug"], dash(r["last_commit"])))

    print("[registry] wrote %s (%d rows) and %s" % (md, len(rows), jl))
    print("[registry] converted=%d stale=%d" % (len(conv), len(stale)))


if __name__ == "__main__":
    main()
