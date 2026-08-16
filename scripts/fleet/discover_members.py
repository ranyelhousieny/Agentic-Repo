#!/usr/bin/env python3
"""discover_members.py -- READ-ONLY discovery for an agentic project (fleet layer).

Generic port of the script first proven on the Fabric project layer (2026-08-06),
now owned by the framework so every project inherits fixes. Emits exactly two
artifacts and touches nothing else:

    MEMBERS.yaml           proposed roster; EVERY policy defaults to `observe`
    Generated/DRIFT.md     everything that does not fit the roster cleanly

It never writes into a member repo, never fetches, never mutates git state.

Design notes, each earned from a real failure:

  * Enumerate the group with include_subgroups=true. A flat listing of a the company
    group silently misses whole subgroups (measured: 8 hidden under one apps
    group, 29 under another).

  * Classify by inspecting the literal `.git` entry, NOT by whether
    `git rev-parse` succeeds. Inside a parent clone, rev-parse succeeds for a
    plain directory and would misreport it as a repo.

  * Scan MULTIPLE clone roots. Repos belonging to one group are routinely
    cloned under unrelated parents.

  * Remote liveness is checked over the AUTHENTICATED HTTPS API, never by
    batch `git ls-remote`. Measured failure (2026-08-15): ~50 consecutive SSH
    ls-remote calls tripped GitLab's SSH rate limiting and reported reachable
    repos as dead; the same slugs resolved individually. In-group members cost
    zero extra calls (the group listing already proves existence); out-of-group
    clones get one API GET each; an API ERROR is reported as UNVERIFIED, never
    as dead. A rename still reads as 404 -- it lands in drift for a human.

  * glab auth is a failure mode of ITS OWN: an expired stored token reports
    identically to an empty group. Preflight `glab api user` first and STOP
    loudly on failure instead of emitting a roster of zero members.

  * Every number carries the ref and date it was measured at.

Fleet delta over the original: members whose local clone is already converted
(Knowledge/KNOWLEDGE_GRAPH.md + CLAUDE.md) carry `converted: true` and their
readiness level, so policy promotion (observe -> convert / update-only) starts
from measured state instead of memory.

Usage:
    python3 discover_members.py --group your-org/apps/team-group \
        --roots ~/code/the company/Fabric ~/code/the company/your-org-genai \
        --out-dir /tmp/agentic-project-fabric \
        [--project-slug fabric] [--tracker CRM]
"""
import argparse
import datetime
import json
import os
import re
import sys
import urllib.parse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fleetlib import sh, is_converted, read_readiness_level  # noqa: E402

BOT_HINTS = ("service_account", "pipeline-bot", "SYSTEM", "Administrative Tasks")


def glab(path):
    rc, out, _ = sh(["glab", "api", path])
    if rc != 0:
        return None
    try:
        return json.loads(out)
    except ValueError:
        return None


def glab_raw(path):
    """Response TEXT, for endpoints that do not return JSON. "" on failure.

    The `repository/files/<f>/raw` endpoint returns the file's own bytes, so a
    YAML file routed through glab() above always raises inside json.loads and
    comes back None -- which is exactly how catalog-info.yaml was read until
    2026-08-16, leaving every roster row's `role` and `owning_manager` silently
    empty while the agent prompt told a human to build the Phase 2 policy table
    and Phase 5 TEAM.md out of them. Absence has to mean absence, not "we
    decoded it with the wrong parser".
    """
    rc, out, _ = sh(["glab", "api", path])
    return out if rc == 0 else ""


def _spec_block(text):
    """The body of the top-level `spec:` mapping, or "" when there is none.

    Ends at the next line that starts in column 0 with something other than a
    comment -- i.e. the next top-level key. Deliberately not a YAML parse: same
    rule as fleetlib, this reads only the shapes real catalog-info.yaml files have.
    """
    m = re.search(r"^spec:[^\S\n]*(?:#.*)?$", text, re.M)
    if not m:
        return ""
    body = []
    for line in text[m.end():].splitlines():
        if line[:1] not in ("", " ", "\t", "#") :
            break                       # a new top-level key ends the block
        body.append(line)
    return "\n".join(body)


def catalog_fields(text):
    """(role, owning_manager) from a catalog-info.yaml body; ("", "") when absent.

    `role` is `spec.type`, and it has to be read out of the `spec:` BLOCK -- a
    document-wide `^\\s*type:` search returns the first `type:` in file order, and
    Backstage's `metadata.links[]` entries carry a `type:` (`url`/`title`/`icon`/
    `type`) while `metadata` conventionally precedes `spec`. Measured on exactly that
    shape: role came back `documentation` instead of `service`. Anchoring at line
    start only rules out SUFFIX lookalikes (`mediaType:`, `contentType:`); a nested
    key literally named `type:` still won on document order, which is the half the
    old docstring claimed to have covered.

    That matters beyond a cosmetic column: the agent prompt builds the Phase 2 policy
    table and Phase 5 TEAM.md out of `role`, so a plausible-but-wrong value is worse
    than the empty one the /raw-decoded-as-JSON bug used to leave.

    Inside the block the SHALLOWEST `type:` wins, so a deeper `spec.dependsOn[].type`
    cannot answer either. No `spec:` block at all -> fall back to the document-wide
    search, which is the behaviour non-Backstage shapes had before.

    `owningManager` stays document-wide: it has no nested lookalike in the schema,
    and teams do put it under `metadata` as well as `spec`.

    Pure function -- the network lives in glab_raw().
    """
    if not text:
        return "", ""
    spec = _spec_block(text)
    role = ""
    if spec:
        hits = [(len(m.group(1)), m.group(2))
                for m in re.finditer(r"^([^\S\n]+)type:[^\S\n]*(\S+)", spec, re.M)]
        if hits:
            role = min(hits, key=lambda h: h[0])[1]
    if not role and not spec:
        m = re.search(r"^\s*type:\s*(\S+)", text, re.M)
        role = m.group(1) if m else ""
    m = re.search(r"^\s*owningManager:\s*(\S+)", text, re.M)
    owner = m.group(1) if m else ""
    return role, owner


def project_alive(slug, group_slugs):
    """Liveness by authenticated API, never by batch SSH.
    Returns: in-group | alive-elsewhere | dead | unverified."""
    if slug in group_slugs:
        return "in-group"
    rc, out, err = sh(["glab", "api", "projects/%s" % slug.replace("/", "%2F")])
    if rc == 0:
        return "alive-elsewhere"
    blob = out + " " + err
    if "404" in blob or "Not Found" in blob:
        return "dead"
    return "unverified"


def preflight_auth():
    """STOP loudly when glab cannot authenticate. An expired token otherwise
    reports identically to an empty group and produces a silent zero-roster."""
    me = glab("user")
    if not isinstance(me, dict) or not me.get("username"):
        print(
            "[discover] FATAL: `glab api user` failed -- glab is not authenticated.\n"
            "  Fix: TOK=<a valid PAT>; printf '%s' \"$TOK\" | glab auth login --hostname gitlab.com --stdin\n"
            "  Then re-run. Refusing to emit a roster that would read as an empty group.",
            file=sys.stderr,
        )
        sys.exit(3)
    return me["username"]


def group_projects(group, fetch=glab):
    """Every project in the group INCLUDING subgroups. Paginated to exhaustion.
    `fetch` is injectable for tests."""
    enc = group.replace("/", "%2F")
    out, page = [], 1
    while True:
        batch = fetch(
            "groups/%s/projects?per_page=100&page=%d"
            "&include_subgroups=true&order_by=last_activity_at&sort=desc" % (enc, page)
        )
        if not batch:
            break
        out.extend(batch)
        if len(batch) < 100:
            break
        page += 1
        if page > 20:  # runaway guard
            break
    seen, uniq = set(), []
    for p in out:
        if p["id"] not in seen:
            seen.add(p["id"])
            uniq.append(p)
    return uniq


def classify(path):
    """kind by inspecting the literal .git entry. Never by command success."""
    dotgit = os.path.join(path, ".git")
    if not os.path.exists(dotgit):
        return "not-a-repo"
    if os.path.isdir(dotgit):
        return "clone"
    if os.path.isfile(dotgit):
        try:
            body = open(dotgit).read()
        except OSError:
            return "unknown"
        if "worktrees/" in body:
            return "worktree"
        if "modules/" in body:
            return "submodule"
        return "gitfile-other"
    return "unknown"


def scan_roots(roots):
    """Every directory under each root, classified. Depth 1 only -- members are
    not nested inside one another except as submodules, which we flag."""
    found = {}
    for root in roots:
        root = os.path.expanduser(root)
        if not os.path.isdir(root):
            continue
        for name in sorted(os.listdir(root)):
            p = os.path.join(root, name)
            if not os.path.isdir(p) or name.startswith("."):
                continue
            kind = classify(p)
            rc, url, _ = sh(["git", "-C", p, "remote", "get-url", "origin"])
            url = url if rc == 0 else ""
            slug = ""
            m = re.search(r"gitlab\.com[:/](.+?)(?:\.git)?$", url)
            if m:
                slug = m.group(1)
            rc, head, _ = sh(["git", "-C", p, "rev-parse", "--abbrev-ref", "HEAD"])
            rc2, dirty, _ = sh(["git", "-C", p, "status", "--porcelain"])
            found[p] = {
                "path": p,
                "name": name,
                "kind": kind,
                "url": url,
                "slug": slug,
                "branch": head if rc == 0 else "",
                "dirty": len([l for l in dirty.splitlines() if l]) if rc2 == 0 else None,
            }
    return found


def submodules_of(path):
    f = os.path.join(path, ".gitmodules")
    if not os.path.isfile(f):
        return []
    return re.findall(r"path\s*=\s*(\S+)", open(f).read())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--group", required=True)
    ap.add_argument("--roots", nargs="+", required=True)
    ap.add_argument("--out-dir", default=".")
    ap.add_argument("--project-slug", default="", help="defaults to the group's last path segment")
    ap.add_argument("--tracker", default="CRM", help="JIRA project key for the fleet's tickets")
    a = ap.parse_args()

    stamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    slug_default = a.project_slug or a.group.rstrip("/").split("/")[-1]
    print("[discover] group=%s" % a.group, file=sys.stderr)

    user = preflight_auth()
    print("[discover] glab auth ok (user=%s)" % user, file=sys.stderr)

    projects = group_projects(a.group)
    print("[discover] %d projects (include_subgroups=true)" % len(projects), file=sys.stderr)
    if not projects:
        print(
            "[discover] FATAL: 0 projects returned for an authenticated call. Either the group "
            "path is wrong or the token lacks read_api on it. Refusing to write an empty roster.",
            file=sys.stderr,
        )
        sys.exit(4)
    local = scan_roots(a.roots)
    print("[discover] %d local dirs across %d root(s)" % (len(local), len(a.roots)), file=sys.stderr)

    by_slug = {v["slug"]: v for v in local.values() if v["slug"]}

    members, drift = [], {
        "not-a-repo": [], "worktree": [], "submodule": [], "dead-remote": [],
        "unverified-remote": [], "archived": [], "empty": [],
        "tombstone": [], "uncloned-active": [], "dirty": [], "off-default": [],
    }
    group_slugs = {p["path_with_namespace"] for p in projects}
    default_branch_of = {p["path_with_namespace"]: p.get("default_branch") for p in projects}

    # --- local anomalies -------------------------------------------------
    for v in local.values():
        if v["kind"] == "not-a-repo":
            drift["not-a-repo"].append(v["path"]); continue
        if v["kind"] == "worktree":
            drift["worktree"].append("%s (shares another repo's object store)" % v["path"]); continue
        if v["kind"] == "submodule":
            drift["submodule"].append(v["path"]); continue
        if v["slug"]:
            status = project_alive(v["slug"], group_slugs)
            if status == "dead":
                drift["dead-remote"].append("%s -> %s (API 404)" % (v["name"], v["slug"]))
            elif status == "unverified":
                drift["unverified-remote"].append(
                    "%s -> %s (API error -- NOT proven dead)" % (v["name"], v["slug"]))
        if v["dirty"]:
            drift["dirty"].append("%s: %s path(s)" % (v["name"], v["dirty"]))
        # A clone parked on a feature branch is not the tree the registry claims
        # to measure: is_converted / readiness / freshness all read the CHECKED-OUT
        # working tree, while every remote-side number is the default branch's.
        default_branch = default_branch_of.get(v["slug"])
        if default_branch and v["branch"] and v["branch"] != default_branch:
            drift["off-default"].append(
                "%s: on `%s`, default is `%s` (artifacts measured from the checked-out tree)"
                % (v["name"], v["branch"], default_branch))
        for sm in submodules_of(v["path"]):
            drift["submodule"].append(
                "%s/%s (submodule of %s -- do not double-count)" % (v["name"], sm, v["name"])
            )

    # --- the roster ------------------------------------------------------
    for p in projects:
        slug, name = p["path_with_namespace"], p["path"]
        if "deletion_scheduled" in slug:
            drift["tombstone"].append(slug); continue
        if p.get("archived"):
            drift["archived"].append("%s (last activity %s)" % (slug, p["last_activity_at"][:10])); continue
        if p.get("empty_repo"):
            drift["empty"].append(slug); continue

        lv = by_slug.get(slug)
        if not lv:
            drift["uncloned-active"].append("%s  last activity %s" % (slug, p["last_activity_at"][:10]))

        ci = glab_raw("projects/%s/repository/files/catalog-info.yaml/raw?ref=%s"
                      % (p["id"], urllib.parse.quote(p["default_branch"] or "", safe="")))
        role, owner = catalog_fields(ci)

        converted, readiness = False, ""
        if lv and lv["kind"] == "clone":
            converted = is_converted(lv["path"])
            if converted:
                readiness = read_readiness_level(lv["path"]) or ""

        members.append({
            "slug": name, "url": p["ssh_url_to_repo"], "gitlab_path": slug,
            "kind": lv["kind"] if lv else "not-cloned",
            "policy": "observe",  # FAIL-SAFE. A human promotes.
            "role": role, "owning_manager": owner,
            "default_branch": p["default_branch"],
            "last_activity": p["last_activity_at"][:10],
            "local_path": lv["path"] if lv else "",
            "converted": converted,
            "readiness": readiness,
        })

    os.makedirs(os.path.join(a.out_dir, "Generated"), exist_ok=True)

    # ---- MEMBERS.yaml ---------------------------------------------------
    mp = os.path.join(a.out_dir, "MEMBERS.yaml")
    with open(mp, "w") as f:
        f.write("""# MEMBERS.yaml -- PROPOSED roster. Generated, not hand-edited.
#
# Measured %s against the live GitLab API with include_subgroups=true.
# Group: %s
# Clone roots scanned: %s
#
# EVERY policy below is `observe` -- the fail-safe default. Discovery proposes;
# a human promotes. Nothing is written to any member repo at `observe`.
#
#   observe      indexed, never written to        (default)
#   minimal      IaC/config/registry -- a stub, not a knowledge layer
#   update-only  already has a knowledge layer; refresh generated blocks only
#   convert      full conversion
#   exclude      never touched (worktrees, submodules, non-repos, tombstones)
#
schema_version: 1
project:
  slug: %s
  group: %s
  tracker: %s
  measured_at: "%s"

members:
""" % (stamp, a.group, ", ".join(a.roots), slug_default, a.group, a.tracker, stamp))
        for m in sorted(members, key=lambda x: x["last_activity"], reverse=True):
            f.write("  - slug: %s\n" % m["slug"])
            f.write("    gitlab_path: %s\n" % m["gitlab_path"])
            f.write("    url: %s\n" % m["url"])
            f.write("    policy: %s\n" % m["policy"])
            f.write("    kind: %s\n" % m["kind"])
            if m["role"]:
                f.write("    role: %s\n" % m["role"])
            if m["owning_manager"]:
                f.write("    owning_manager: %s\n" % m["owning_manager"])
            f.write("    default_branch: %s\n" % m["default_branch"])
            f.write("    last_activity: %s\n" % m["last_activity"])
            if m["local_path"]:
                f.write("    local_path: %s\n" % m["local_path"])
            if m["converted"]:
                f.write("    converted: true\n")
            if m["readiness"]:
                f.write("    readiness: %s\n" % m["readiness"])
            f.write("\n")

    # ---- DRIFT.md -------------------------------------------------------
    dp = os.path.join(a.out_dir, "Generated", "DRIFT.md")
    with open(dp, "w") as f:
        f.write("# DRIFT -- %s\n\nMeasured %s. Read-only discovery; nothing here was changed.\n\n" % (a.group, stamp))
        f.write("**Roster:** %d member(s) proposed, all at `observe`.\n\n" % len(members))
        titles = {
            "uncloned-active": "Active on GitLab, not cloned locally",
            "dead-remote":     "Local clone whose remote does not resolve (API 404)",
            "unverified-remote": "Liveness UNVERIFIED (API error; do not treat as dead)",
            "not-a-repo":      "Directory with no `.git` -- forced `exclude`",
            "worktree":        "Git worktree, not a clone -- forced `exclude`",
            "submodule":       "Submodule -- do not double-count, forced `exclude`",
            "archived":        "Archived on GitLab",
            "empty":           "Empty repo",
            "tombstone":       "Deletion-scheduled tombstone",
            "dirty":           "Uncommitted local changes",
            "off-default":     "Local clone not on its default branch",
        }
        # Iterate the BUCKETS, not the titles: a bucket added to `drift` without a
        # title here used to vanish from the report while still counting on stdout,
        # which is the silent-drop this file exists to prevent. An untitled bucket
        # prints under its own key instead of disappearing.
        for k in list(titles) + [k for k in drift if k not in titles]:
            title = titles.get(k, "%s (untitled bucket -- add a title in discover_members.py)" % k)
            items = drift.get(k) or []
            f.write("## %s -- %d\n\n" % (title, len(items)))
            if not items:
                f.write("_none_\n\n"); continue
            for i in sorted(set(items)):
                f.write("- `%s`\n" % i)
            f.write("\n")

    print("\nWROTE (2 files only):\n  %s\n  %s" % (mp, dp))
    print("\n  members proposed : %d  (all policy=observe)" % len(members))
    conv = [m for m in members if m["converted"]]
    print("  already converted: %d  (%s)" % (len(conv), ", ".join(m["slug"] for m in conv) or "none"))
    for k, v in drift.items():
        if v:
            print("  %-18s: %d" % (k, len(set(v))))


if __name__ == "__main__":
    main()
