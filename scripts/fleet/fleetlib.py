#!/usr/bin/env python3
"""fleetlib.py -- shared READ-ONLY parsers for the fleet (project-level) scripts.

Stdlib only. Python 3.9 compatible (no PEP 604 unions). Every reader returns None
(or an empty value) when an artifact is absent -- callers render absence as "--".
Nothing is ever fabricated: a value that cannot be parsed from a file on disk is
reported as unknown, never guessed.

MEMBERS.yaml parsing note: parse_members() is NOT a general YAML parser. It parses
exactly the shape scripts/fleet/discover_members.py writes (fixed two-space
indents, scalar values, one `- slug:` block per member). Writer and parser live in
the same directory so they change together. Do not point it at hand-written YAML.
"""
import datetime
import json
import os
import re
import subprocess

# Artifact locations relative to a member repo root. Candidates are searched in
# order; first hit wins. Sourced from real converted repos on 2026-08-15
# (sample-service-a, sample-monorepo): CODE_GRAPH.jsonl lives under
# Generated/graphify/ on current conversions; Generated/Analysis/ is kept as a
# legacy candidate for pre-graphify layouts.
CODE_GRAPH_CANDIDATES = (
    os.path.join("Generated", "graphify", "CODE_GRAPH.jsonl"),
    os.path.join("Generated", "Analysis", "CODE_GRAPH.jsonl"),
)
CACHE_DIRNAME = os.path.join("Generated", "remote_cache")
KG_REL = os.path.join("Knowledge", "KNOWLEDGE_GRAPH.md")
CODE_INDEX_REL = os.path.join("Knowledge", "CODE_INDEX.md")
GOLDEN_REL = os.path.join("Knowledge", "golden", "GOLDEN_FACTS.jsonl")
READINESS_REL = os.path.join("Generated", "READINESS_REPORT.md")
GATE_REL = os.path.join("Generated", "CODE_INDEX_VALIDATION.md")


def sh(cmd, cwd=None):
    r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    return r.returncode, r.stdout.strip(), r.stderr.strip()


def _read(path):
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            return f.read()
    except OSError:
        return None


# ---------------------------------------------------------------- MEMBERS.yaml
def parse_members(path):
    """Parse the generated MEMBERS.yaml. Returns (project: dict, members: list[dict]).

    Raises ValueError when the file is missing or has no members section, so a
    caller cannot silently proceed on an empty roster.
    """
    text = _read(path)
    if text is None:
        raise ValueError("MEMBERS.yaml not found at %s" % path)
    project, members, cur = {}, [], None
    in_project, in_members = False, False
    for line in text.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if re.match(r"^project:\s*$", line):
            in_project, in_members = True, False
            continue
        if re.match(r"^members:\s*$", line):
            in_project, in_members = False, True
            continue
        if in_project:
            m = re.match(r"^\s{2}(\w+):\s*(.*)$", line)
            if m:
                project[m.group(1)] = m.group(2).strip().strip('"')
            continue
        if in_members:
            m = re.match(r"^\s{2}-\s+slug:\s*(.+)$", line)
            if m:
                cur = {"slug": m.group(1).strip()}
                members.append(cur)
                continue
            m = re.match(r"^\s{4}(\w+):\s*(.*)$", line)
            if m and cur is not None:
                cur[m.group(1)] = m.group(2).strip().strip('"')
    if not members:
        raise ValueError("MEMBERS.yaml at %s parsed to zero members" % path)
    return project, members


# ------------------------------------------------------- member root resolution
def member_root(member, project_dir):
    """Where to READ a member's artifacts from. Returns (root, source).

    source: 'local'  -- a local clone (authoritative working tree)
            'cache'  -- Generated/remote_cache/<slug>/ fetched from the member's
                        default branch by fetch_member_artifacts.py
            'none'   -- nothing to read; the member appears as an unmeasured row
    Local wins over cache: a clone is at worst as stale as the cache and carries
    git history the cache does not.
    """
    lp = member.get("local_path", "")
    if lp and os.path.isdir(lp):
        return lp, "local"
    c = os.path.join(project_dir, CACHE_DIRNAME, member.get("slug", ""))
    if os.path.isfile(os.path.join(c, "_meta.json")):
        return c, "cache"
    return "", "none"


def read_cache_meta(root):
    try:
        with open(os.path.join(root, "_meta.json")) as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


# ------------------------------------------------------------ member artifacts
def is_converted(repo):
    """Converted = the two anchor artifacts of a conversion both exist."""
    return os.path.isfile(os.path.join(repo, KG_REL)) and os.path.isfile(
        os.path.join(repo, "CLAUDE.md")
    )


def read_kg_updated(repo):
    text = _read(os.path.join(repo, KG_REL))
    if not text:
        return None
    m = re.search(r"\*\*Last Updated:\*\*\s*(.+)", text)
    return m.group(1).strip() if m else None


def parse_prose_date(s):
    """Parse dates as they appear in generated headers. Returns datetime.date or None.

    Handles: 'Saturday, August 15, 2026 (initial conversion ...)',
    'Friday, August 15, 2026 10:03 PDT', '2026-08-15'. Unknown shapes -> None.
    """
    if not s:
        return None
    m = re.search(r"(\d{4})-(\d{2})-(\d{2})", s)
    if m:
        return datetime.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    m = re.search(r"([A-Z][a-z]+ \d{1,2}, \d{4})", s)
    if m:
        try:
            return datetime.datetime.strptime(m.group(1), "%B %d, %Y").date()
        except ValueError:
            return None
    return None


def read_code_index(repo):
    """Header fields of Knowledge/CODE_INDEX.md: records, framework, derivation date."""
    text = _read(os.path.join(repo, CODE_INDEX_REL))
    if not text:
        return None
    head = text[:2000]
    out = {"records": None, "framework": None, "derived": None}
    m = re.search(r"\*\*Records:\*\*\s*(\d+)", head)
    if m:
        out["records"] = int(m.group(1))
    m = re.search(r"\*\*Framework:\*\*\s*(.+)", head)
    if m:
        out["framework"] = m.group(1).strip()
    m = re.search(r"\*\*Derivation date:\*\*\s*(.+)", head)
    if m:
        out["derived"] = m.group(1).strip()
    return out


def read_golden_count(repo):
    text = _read(os.path.join(repo, GOLDEN_REL))
    if text is None:
        return None
    return sum(1 for line in text.splitlines() if line.strip())


def read_readiness_level(repo):
    text = _read(os.path.join(repo, READINESS_REL))
    if not text:
        return None
    m = re.search(r"\*\*Achieved level:\*\*\s*(L\d)\s*(?:--|-|\u2014)\s*(.+)", text)
    if m:
        return "%s %s" % (m.group(1), m.group(2).strip())
    m = re.search(r"\*\*Achieved level:\*\*\s*(.+)", text)
    return m.group(1).strip() if m else None


def read_gate(repo):
    """Verification rate from Generated/CODE_INDEX_VALIDATION.md.

    IMPORTANT scope honesty: on current conversions this file holds the LAST
    validation run, which may be a different artifact than CODE_INDEX (observed:
    SME_CONTACTS.md on 2026-08-15). The header names the artifact; we return it
    so the registry can state the scope instead of implying CODE_INDEX coverage.
    """
    text = _read(os.path.join(repo, GATE_REL))
    if not text:
        return None
    out = {"artifact": None, "rate": None, "citations": None}
    m = re.search(r"VALIDATION_SUMMARY\s*(?:--|\u2014)\s*(\S+)", text)
    if m:
        out["artifact"] = m.group(1).strip("`")
    m = re.search(r"\|\s*Verification rate\s*\|\s*([\d.]+)%\s*\|", text)
    if m:
        out["rate"] = float(m.group(1))
    m = re.search(r"\|\s*Total citations\s*\|\s*(\d+)\s*\|", text)
    if m:
        out["citations"] = int(m.group(1))
    return out


def code_graph_stats(repo):
    """First CODE_GRAPH.jsonl candidate that exists: its path and edge count."""
    for rel in CODE_GRAPH_CANDIDATES:
        p = os.path.join(repo, rel)
        if os.path.isfile(p):
            n = 0
            with open(p, encoding="utf-8", errors="replace") as f:
                for line in f:
                    if line.strip():
                        n += 1
            return {"path": rel, "edges": n}
    return None


def iter_code_graph(repo):
    """Yield parsed CODE_GRAPH.jsonl records. Silently ends if absent (caller
    already knows via code_graph_stats); malformed lines are skipped, counted
    by the caller if it cares."""
    for rel in CODE_GRAPH_CANDIDATES:
        p = os.path.join(repo, rel)
        if not os.path.isfile(p):
            continue
        with open(p, encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    yield json.loads(line)
                except ValueError:
                    continue
        return


def git_last_commit(repo):
    rc, out, _ = sh(["git", "-C", repo, "log", "-1", "--format=%cs %h"])
    if rc != 0 or not out:
        return None
    parts = out.split()
    if len(parts) != 2:
        return None
    return {"date": parts[0], "sha": parts[1]}


def freshness(repo):
    """STALE / FRESH / UNKNOWN: did the member's git history move after its KG header date?

    Same-day commits count as FRESH (date granularity only -- stated, not hidden).
    """
    kg_date = parse_prose_date(read_kg_updated(repo) or "")
    last = git_last_commit(repo)
    if kg_date is None or last is None:
        return "UNKNOWN"
    try:
        commit_date = datetime.datetime.strptime(last["date"], "%Y-%m-%d").date()
    except ValueError:
        return "UNKNOWN"
    return "STALE" if commit_date > kg_date else "FRESH"


def freshness_for(root, source):
    """Freshness for either root kind. Cache roots have no .git; the fetcher
    recorded the branch head's committed date in _meta.json at fetch time."""
    if source == "local":
        return freshness(root)
    if source != "cache":
        return "UNKNOWN"
    meta = read_cache_meta(root) or {}
    kg_date = parse_prose_date(read_kg_updated(root) or "")
    head = parse_prose_date(meta.get("head_committed_date", ""))
    if kg_date is None or head is None:
        return "UNKNOWN"
    return "STALE" if head > kg_date else "FRESH"


def last_commit_for(root, source):
    """'YYYY-MM-DD@sha' from git (local) or fetch metadata (cache); None if unknowable."""
    if source == "local":
        lc = git_last_commit(root)
        return "%s@%s" % (lc["date"], lc["sha"]) if lc else None
    if source == "cache":
        meta = read_cache_meta(root) or {}
        d = parse_prose_date(meta.get("head_committed_date", ""))
        sha = (meta.get("sha") or "")[:7]
        if d and sha:
            return "%s@%s (cache)" % (d.isoformat(), sha)
    return None


# ----------------------------------------------------------- publish aliases
def member_aliases(repo, slug):
    """Names under which a member is importable/referable by siblings.

    Sources, all evidence-based: the roster slug itself (dash and underscore
    forms), pyproject [project] name / [tool.poetry] name, and top-level python
    package directories (dirs containing __init__.py, depth 1-2).
    """
    aliases = set()

    def add(name):
        name = (name or "").strip().strip('"').strip("'")
        if len(name) >= 3:
            aliases.add(name.lower())
            aliases.add(name.lower().replace("-", "_"))

    add(slug)
    text = _read(os.path.join(repo, "pyproject.toml"))
    if text:
        for pat in (r'^\s*name\s*=\s*["\']([^"\']+)["\']',):
            for m in re.finditer(pat, text, re.M):
                add(m.group(1))
    if os.path.isdir(repo):
        for d1 in sorted(os.listdir(repo))[:200]:
            p1 = os.path.join(repo, d1)
            if os.path.isdir(p1) and os.path.isfile(os.path.join(p1, "__init__.py")):
                add(d1)
            elif os.path.isdir(p1) and not d1.startswith("."):
                try:
                    for d2 in sorted(os.listdir(p1))[:200]:
                        p2 = os.path.join(p1, d2)
                        if os.path.isdir(p2) and os.path.isfile(
                            os.path.join(p2, "__init__.py")
                        ):
                            add(d2)
                except OSError:
                    pass
    return aliases
