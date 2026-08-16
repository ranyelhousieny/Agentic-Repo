#!/usr/bin/env python3
"""build_cross_repo_graph.py -- edges BETWEEN member repos, with evidence.

Per-repo CODE_GRAPH.jsonl files structurally cannot hold an edge that crosses a
repo boundary. This script derives those edges -- the knowledge a project layer
adds that no single repo can -- and refuses to guess: every edge carries the
resolver that produced it, a confidence tag, and file:line evidence in the
SOURCE repo. References that look cross-repo but match no roster member go to a
needs-verification sidecar instead of being dropped or invented.

Resolvers (kind, confidence):
    code-import  (imports, EXTRACTED)  member CODE_GRAPH dependency records whose
                 target module is published by a SIBLING member. Publication is
                 evidence-based: pyproject name / top-level python packages.
    iac-pair     (deploys, PATTERN)    roster pairs `X` and `X-iac*`. Upgraded to
                 file:line evidence when the IaC member's *.tf/*.yaml literally
                 names the sibling; otherwise the pairing itself is the evidence.
    config-ref   (references, PATTERN) bounded scan of config-ish files
                 (catalog-info.yaml, openapi*.y*ml, values*.yaml, fleet.yaml,
                 nginx*.conf, *.tf) for word-boundary mentions of sibling slugs.

Outputs (into <project-dir>/Generated/):
    CROSS_REPO_GRAPH.jsonl              one edge per line
    ARCHITECTURE_MAP.md                 rendered mermaid + fan-in/fan-out table
    CROSS_REPO_NEEDS_VERIFICATION.jsonl near-miss references for human promotion

READ-ONLY against members. Stdlib only, py3.9.

Usage:
    python3 build_cross_repo_graph.py --project-dir <dir with MEMBERS.yaml>
"""
import argparse
import datetime
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fleetlib import parse_members, member_root, iter_code_graph, member_aliases  # noqa: E402

CONFIG_GLOBS = re.compile(
    r"(^catalog-info\.ya?ml$|openapi.*\.ya?ml$|^values.*\.ya?ml$|^fleet\.ya?ml$"
    r"|^nginx.*\.conf$|\.tf$|\.openapi\.json$)"
)
MAX_CONFIG_FILES = 400          # per member -- bounded, stated in the map header
MIN_SLUG_LEN = 4                # shorter slugs create word-collision false edges
PY_STDLIBISH = None             # resolved lazily; see _stdlib_names()

# `sys.stdlib_module_names` is 3.10+, and this directory's floor is 3.9. Falling back
# to an empty set (the previous behaviour) silently turned the stdlib filter OFF on the
# declared floor interpreter, so `import json` in a member could be matched against a
# roster member named `json` and land in the near-miss sidecar. This list is the
# top-level stdlib names an alias could plausibly collide with -- a repo slug is
# lowercase and >= 3 chars, so single-letter and dunder modules cannot collide.
_STDLIB_FALLBACK = frozenset("""
abc argparse array ast asyncio base64 binascii bisect builtins bz2 calendar cgi chunk cmath cmd
code codecs collections colorsys compileall concurrent configparser contextlib contextvars copy
copyreg crypt csv ctypes curses dataclasses datetime dbm decimal difflib dis doctest email
encodings ensurepip enum errno faulthandler fcntl filecmp fileinput fnmatch fractions ftplib
functools gc getopt getpass gettext glob graphlib grp gzip hashlib heapq hmac html http idlelib
imaplib imghdr importlib inspect io ipaddress itertools json keyword linecache locale logging
lzma mailbox mailcap marshal math mimetypes mmap modulefinder multiprocessing netrc nntplib
numbers operator optparse os ossaudiodev pathlib pdb pickle pickletools pipes pkgutil platform
plistlib poplib posix pprint profile pstats pty pwd py_compile pyclbr pydoc queue quopri random
re readline reprlib resource rlcompleter runpy sched secrets select selectors shelve shlex shutil
signal site smtplib sndhdr socket socketserver spwd sqlite3 sre_compile sre_constants sre_parse
ssl stat statistics string stringprep struct subprocess sunau symtable sys sysconfig syslog
tabnanny tarfile telnetlib tempfile termios test textwrap threading time timeit tkinter token
tokenize tomllib trace traceback tracemalloc tty turtle types typing unicodedata unittest urllib
uu uuid venv warnings wave weakref webbrowser wsgiref xdrlib xml xmlrpc zipapp zipfile zipimport
zlib zoneinfo
""".split())


def _stdlib_names():
    global PY_STDLIBISH
    if PY_STDLIBISH is None:
        PY_STDLIBISH = set(getattr(sys, "stdlib_module_names", ())) or set(_STDLIB_FALLBACK)
    return PY_STDLIBISH


def config_files(repo, max_depth=3):
    """Bounded walk for config-ish files. Skips dot-dirs and the generated
    framework dirs -- the graph is about the SERVICE, not about our artifacts."""
    skip_dirs = {".git", "node_modules", "Generated", "Knowledge", ".claude",
                 ".windsurf", "__pycache__", ".venv", "venv", "dist", "build"}
    out = []
    root_depth = repo.rstrip(os.sep).count(os.sep)
    for cur, dirs, files in os.walk(repo):
        if cur.count(os.sep) - root_depth >= max_depth:
            dirs[:] = []
            continue
        dirs[:] = [d for d in dirs if d not in skip_dirs and not d.startswith(".")]
        for name in files:
            if CONFIG_GLOBS.search(name):
                out.append(os.path.join(cur, name))
                if len(out) >= MAX_CONFIG_FILES:
                    return out
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--project-dir", required=True)
    a = ap.parse_args()

    try:
        project, members = parse_members(os.path.join(a.project_dir, "MEMBERS.yaml"))
    except ValueError as e:
        print("[xgraph] FATAL: %s" % e, file=sys.stderr)
        sys.exit(2)

    for m in members:
        m["_root"], m["_source"] = member_root(m, a.project_dir)
    local = [m for m in members if m["_root"]]
    slugs = {m["slug"] for m in members}

    # Alias map: alias -> owning slug. Collisions are dropped LOUDLY (an alias
    # owned by two members can only produce wrong edges).
    alias_owner, collisions = {}, set()
    for m in local:
        for al in member_aliases(m["_root"], m["slug"]):
            if al in alias_owner and alias_owner[al] != m["slug"]:
                collisions.add(al)
            else:
                alias_owner[al] = m["slug"]
    for al in collisions:
        alias_owner.pop(al, None)

    edges, sidecar = [], []
    seen = set()

    def add_edge(src, dst, kind, resolver, confidence, ev_path, ev_line, ident):
        if src == dst:
            return
        key = (src, dst, kind, resolver)
        if key in seen:
            for e in edges:
                if (e["source"], e["target"], e["kind"], e["resolver"]) == key:
                    e["count"] += 1
                    return
        seen.add(key)
        edges.append({
            "source": src, "target": dst, "kind": kind, "resolver": resolver,
            "confidence": confidence, "evidence_path": ev_path,
            "evidence_line": ev_line, "identifier": ident, "count": 1,
        })

    # ---- R1: code-import over member CODE_GRAPHs -------------------------
    for m in local:
        src = m["slug"]
        for rec in iter_code_graph(m["_root"]):
            if rec.get("kind") != "dependency":
                continue
            ident = rec.get("identifier", "")
            if "->" not in ident:
                continue
            target = ident.split("->", 1)[1].strip()
            root = re.split(r"[./]", target)[0].strip().lower()
            if not root or root in _stdlib_names():
                continue
            owner = alias_owner.get(root) or alias_owner.get(root.replace("-", "_"))
            if owner and owner != src:
                add_edge(src, owner, "imports", "code-import", "EXTRACTED",
                         rec.get("path", "?"), rec.get("line", 0), ident)
            else:
                # near-miss: looks like a sibling slug with dash/underscore drift
                loose = root.replace("_", "-")
                cands = [s for s in slugs if s.lower() in (root, loose) and s != src]
                if cands:
                    sidecar.append({
                        "source": src, "candidate_target": cands[0],
                        "reason": "import root matches a roster slug but the member "
                                  "publishes no such alias (verify before promoting)",
                        "evidence_path": rec.get("path", "?"),
                        "evidence_line": rec.get("line", 0), "identifier": ident,
                    })

    # ---- R2: iac-pair -----------------------------------------------------
    by_slug = {m["slug"]: m for m in members}
    for m in members:
        s = m["slug"]
        base = re.sub(r"-iac.*$", "", s)
        if base == s or base not in by_slug:
            continue
        ev_path, ev_line = "MEMBERS.yaml (name pairing)", 0
        lp = m.get("_root", "")
        if lp:
            found = False
            for fp in config_files(lp):
                try:
                    with open(fp, encoding="utf-8", errors="replace") as f:
                        for i, line in enumerate(f, 1):
                            if re.search(r"\b%s\b" % re.escape(base), line):
                                ev_path = os.path.relpath(fp, lp)
                                ev_line, found = i, True
                                break
                except OSError:
                    continue
                if found:
                    break
        add_edge(s, base, "deploys", "iac-pair", "PATTERN", ev_path, ev_line,
                 "%s -> %s" % (s, base))

    # ---- R3: config-ref ---------------------------------------------------
    for m in local:
        src, lp = m["slug"], m["_root"]
        others = [s for s in slugs if s != src and len(s) >= MIN_SLUG_LEN]
        if not others:
            continue
        pat = re.compile(r"\b(%s)\b" % "|".join(re.escape(s) for s in sorted(others, key=len, reverse=True)))
        for fp in config_files(lp):
            try:
                with open(fp, encoding="utf-8", errors="replace") as f:
                    for i, line in enumerate(f, 1):
                        for hit in set(pat.findall(line)):
                            # Namespace guard: in "apps/team-group/<anything>"
                            # the hit is a gitlab namespace segment, not a
                            # reference to the repo that shares the group's
                            # name. A hit followed by "/" inside a gitlab
                            # URL/path context is noise; a hit that ends the
                            # path (".../team-group.git") is a real reference.
                            after = line.split(hit, 1)[1] if hit in line else ""
                            path_ctx = ("gitlab" in line or "apps/" in line
                                        or "your-org" in line)
                            if after.startswith("/") and path_ctx:
                                continue
                            add_edge(src, hit, "references", "config-ref", "PATTERN",
                                     os.path.relpath(fp, lp), i, line.strip()[:160])
            except OSError:
                continue

    # ---- write ------------------------------------------------------------
    gen = os.path.join(a.project_dir, "Generated")
    os.makedirs(gen, exist_ok=True)
    stamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")

    gp = os.path.join(gen, "CROSS_REPO_GRAPH.jsonl")
    with open(gp, "w") as f:
        for e in sorted(edges, key=lambda x: (x["source"], x["target"], x["kind"])):
            f.write(json.dumps(e, sort_keys=True) + "\n")

    sp = os.path.join(gen, "CROSS_REPO_NEEDS_VERIFICATION.jsonl")
    with open(sp, "w") as f:
        for e in sidecar:
            f.write(json.dumps(e, sort_keys=True) + "\n")

    mp = os.path.join(gen, "ARCHITECTURE_MAP.md")
    fan_out, fan_in = {}, {}
    for e in edges:
        fan_out[e["source"]] = fan_out.get(e["source"], 0) + 1
        fan_in[e["target"]] = fan_in.get(e["target"], 0) + 1
    with open(mp, "w") as f:
        f.write("# ARCHITECTURE MAP -- %s\n\n" % project.get("group", "?"))
        f.write("**Measured:** %s by scripts/fleet/build_cross_repo_graph.py. Do not hand-edit.\n" % stamp)
        n_cache = sum(1 for m in local if m["_source"] == "cache")
        f.write("**Scope honesty:** edges come from %d readable member root(s) (%d local clones, "
                "%d remote-cache replicas holding only the fetched artifact set) out of %d roster "
                "members; config scan bounded to %d files/member, depth 3; alias collisions "
                "dropped: %s. An absent edge here is NOT evidence of no relationship.\n\n"
                % (len(local), len(local) - n_cache, n_cache, len(members), MAX_CONFIG_FILES,
                   ", ".join(sorted(collisions)) or "none"))
        f.write("Edges: %d (dedup by source/target/kind/resolver; `count` carries multiplicity). "
                "Sidecar: %d near-miss reference(s) awaiting human verification.\n\n"
                % (len(edges), len(sidecar)))
        if edges:
            f.write("```mermaid\ngraph LR\n")
            for e in sorted(edges, key=lambda x: (x["source"], x["target"])):
                style = "-->" if e["confidence"] == "EXTRACTED" else "-.->"
                f.write("    %s %s|%s x%d| %s\n" % (
                    e["source"].replace("-", "_"), style, e["kind"], e["count"],
                    e["target"].replace("-", "_")))
            f.write("```\n\n")
        f.write("| source | target | kind | resolver | confidence | count | evidence |\n")
        f.write("|---|---|---|---|---|---|---|\n")
        for e in sorted(edges, key=lambda x: (x["source"], x["target"], x["kind"])):
            f.write("| %s | %s | %s | %s | %s | %d | `%s:%s` |\n" % (
                e["source"], e["target"], e["kind"], e["resolver"], e["confidence"],
                e["count"], e["evidence_path"], e["evidence_line"]))
        if fan_in or fan_out:
            f.write("\n## Fan-in / fan-out\n\n| member | out | in |\n|---|---|---|\n")
            for s in sorted(set(list(fan_in) + list(fan_out))):
                f.write("| %s | %d | %d |\n" % (s, fan_out.get(s, 0), fan_in.get(s, 0)))

    print("[xgraph] %d edge(s), %d sidecar row(s) -> %s" % (len(edges), len(sidecar), gp))


if __name__ == "__main__":
    main()
