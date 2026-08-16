#!/usr/bin/env python3
"""build_project_index.py -- PROJECT_INDEX.md, the router. One line per member.

The router POINTS at each member's own knowledge; it never inlines it. This is
the structural fix for the hand-maintained mega-knowledge-graph failure mode:
the project file a session eager-loads stays small because detail lives where
it is owned, one hop away.

Description source order (evidence-based, first hit wins):
    1. member README.md -- first non-empty, non-heading, non-badge line
    2. member Knowledge/KNOWLEDGE_GRAPH.md -- the "**Purpose:**" line
    3. "--" (absence stated, never invented)

Reads MEMBERS.yaml (+ FLEET_REGISTRY.jsonl when present, for readiness).
Writes PROJECT_INDEX.md into the project dir. READ-ONLY against members.

Usage:
    python3 build_project_index.py --project-dir <dir with MEMBERS.yaml>
"""
import argparse
import datetime
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fleetlib import parse_members, member_root, KG_REL  # noqa: E402

DESC_CAP = 140
# Same distinction the registry makes: `--` = the member has no readiness report,
# `n/a*` = THIS SOURCE cannot see one. Generated/READINESS_REPORT.md is git-ignored
# by the converter, so it exists only in a local clone and never on the default
# branch a cache row replicates -- and the Maestro lane makes cache the primary
# source, so printing `--` there mislabels most rows under a legend that promises
# "achieved readiness level from the member's own report".
CACHE_BLIND = "n/a*"


def readiness_badge(value, source):
    value = (value or "").strip()
    if value:
        return value.split()[0]
    return CACHE_BLIND if source == "cache" else "--"


def _first_prose_line(path):
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            text = f.read()
    except OSError:
        return None
    for line in text.splitlines():
        s = line.strip()
        if not s or s.startswith(("#", "!", "[", "|", ">", "```", "---", "<")):
            continue
        s = re.sub(r"\*\*([^*]+)\*\*", r"\1", s)
        return (s[: DESC_CAP - 1] + "\u2026") if len(s) > DESC_CAP else s
    return None


def _kg_purpose(path):
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            head = f.read(2000)
    except OSError:
        return None
    m = re.search(r"\*\*Purpose:\*\*\s*(.+)", head)
    if not m:
        return None
    s = m.group(1).strip()
    return (s[: DESC_CAP - 1] + "\u2026") if len(s) > DESC_CAP else s


def describe(member, project_dir):
    repo, source = member_root(member, project_dir)
    if repo:
        d = _first_prose_line(os.path.join(repo, "README.md"))
        if d:
            return d
        d = _kg_purpose(os.path.join(repo, KG_REL))
        if d:
            return d
    return "--"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--project-dir", required=True)
    a = ap.parse_args()

    try:
        project, members = parse_members(os.path.join(a.project_dir, "MEMBERS.yaml"))
    except ValueError as e:
        print("[index] FATAL: %s" % e, file=sys.stderr)
        sys.exit(2)

    readiness = {}
    reg = os.path.join(a.project_dir, "Generated", "FLEET_REGISTRY.jsonl")
    if os.path.isfile(reg):
        with open(reg) as f:
            for line in f:
                try:
                    r = json.loads(line)
                    readiness[r["slug"]] = r
                except (ValueError, KeyError):
                    continue

    stamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    out = os.path.join(a.project_dir, "PROJECT_INDEX.md")

    def sort_key(m):
        conv = str(m.get("converted", "")).lower() == "true"
        return (not conv, m.get("slug", ""))

    with open(out, "w") as f:
        f.write("# PROJECT_INDEX -- %s\n\n" % project.get("group", "?"))
        f.write("**Generated:** %s by scripts/fleet/build_project_index.py. Do not hand-edit.\n" % stamp)
        f.write("**Contract:** one line per member, POINTING at the member's own knowledge. "
                "Never inline a member's knowledge graph here -- load it in a scoped subagent. "
                "This file is part of the project session's eager-load budget; keep it a router.\n\n")
        f.write("Legend: `[LX]` = achieved readiness level from the member's own report; "
                "`(policy)` = roster write policy; `--` = not measured/absent; "
                "`[%s]` = this source cannot see it -- the readiness report is git-ignored in the "
                "member repo, so a remote-cache replica of the default branch never carries one.\n\n"
                % CACHE_BLIND)

        conv_members = [m for m in members
                        if readiness.get(m.get("slug", ""), {}).get("converted")
                        or (m.get("slug", "") not in readiness
                            and str(m.get("converted", "")).lower() == "true")]
        f.write("## Converted members -- %d\n\n" % len(conv_members))
        for m in sorted(members, key=sort_key):
            slug = m.get("slug", "?")
            r = readiness.get(slug, {})
            conv = r.get("converted") or (slug not in readiness
                                          and str(m.get("converted", "")).lower() == "true")
            if not conv:
                continue
            root, source = member_root(m, a.project_dir)
            level = readiness_badge(r.get("readiness") or m.get("readiness"), source)
            kg = os.path.join(root, KG_REL) if root else ""
            suffix = " (remote cache)" if source == "cache" else ""
            f.write("- **%s** [%s] (%s) -- %s\n  -> `%s`%s\n"
                    % (slug, level, m.get("policy", "observe"), describe(m, a.project_dir),
                       kg or ("remote: " + m.get("gitlab_path", "?")), suffix))

        f.write("\n## Not yet converted -- %d\n\n" % (len(members) - len(conv_members)))
        for m in sorted(members, key=sort_key):
            slug = m.get("slug", "?")
            r = readiness.get(slug, {})
            conv = r.get("converted") or (slug not in readiness
                                          and str(m.get("converted", "")).lower() == "true")
            if conv:
                continue
            root, source = member_root(m, a.project_dir)
            where = root or ("not readable locally -- " + m.get("gitlab_path", "?"))
            f.write("- **%s** (%s, %s) -- %s\n  -> `%s`\n"
                    % (slug, m.get("policy", "observe"), m.get("kind", "?"),
                       describe(m, a.project_dir), where))

    n = len(members)
    print("[index] wrote %s (%d members, %d converted)" % (out, n, len(conv_members)))


if __name__ == "__main__":
    main()
