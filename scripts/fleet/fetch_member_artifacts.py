#!/usr/bin/env python3
"""fetch_member_artifacts.py -- remote read cache for members with no local clone.

The pipeline lane means members get converted on GitLab without ever being cloned
to this machine (decision 2026-08-15: conversions always through the pipeline,
no local cloning). Aggregation still has to MEASURE those members, so this
script fetches a fixed, small artifact set from each member's default branch
over the authenticated API into:

    <project-dir>/Generated/remote_cache/<slug>/<repo-relative paths>
    <project-dir>/Generated/remote_cache/<slug>/_meta.json

and the fleet readers resolve a member's root as local-clone-first, cache
second (fleetlib.member_root). SHA-gated: if the cached head SHA still matches
the live branch head, nothing is refetched (--force overrides).

Honesty rules carried from the rest of the fleet tooling:
  * A 404 on an artifact is RECORDED in _meta.json (absent), never guessed at.
  * An API error that is not a 404 marks the member UNVERIFIED for this run and
    leaves any previous cache intact -- an error is not evidence of absence.
  * The cache is a read replica of the DEFAULT BRANCH, and says so: registry
    rows sourced from cache carry "(cache)".

Usage:
    python3 fetch_member_artifacts.py --project-dir DIR            # all uncloned members
    python3 fetch_member_artifacts.py --project-dir DIR --members a b c
    python3 fetch_member_artifacts.py --project-dir DIR --force
"""
import argparse
import datetime
import json
import os
import sys
import urllib.parse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fleetlib import sh, parse_members, CACHE_DIRNAME  # noqa: E402

# The fixed artifact set. Everything the registry, router, and cross-repo graph
# read AND that can actually exist on a default branch -- nothing else. Fetching a
# whole repo is what CLONING is for.
#
# Deliberately NOT fetched, because the converter git-ignores them in the target
# repo and they therefore never reach any branch:
#   Generated/READINESS_REPORT.md      readiness_report.py:ensure_report_ignored()
#                                      writes a scoped Generated/.gitignore entry
#   Generated/graphify/CODE_GRAPH.jsonl  extract_graphify.py:ensure_output_ignored()
#                                      writes Generated/graphify/.gitignore with `*`
#   Generated/Analysis/CODE_GRAPH.jsonl  the legacy path of the same artifact
# Requesting them cost one guaranteed-404 API call per member per run and made the
# registry render `readiness` and `graph edges` as `--` for every cache row, which
# reads as "absent" when the truth is "local-only, unmeasurable from a branch".
# build_fleet_registry.CACHE_BLIND keeps that distinction in the registry legend,
# and build_project_index applies the same marker to the router's readiness badge.
ARTIFACTS = (
    "CLAUDE.md",
    "AGENTS.md",
    "README.md",
    "catalog-info.yaml",
    "pyproject.toml",
    "BINDING.yml",
    "Knowledge/KNOWLEDGE_GRAPH.md",
    "Knowledge/CODE_INDEX.md",
    "Knowledge/golden/GOLDEN_FACTS.jsonl",
    "Generated/CODE_INDEX_VALIDATION.md",
)


def _enc(s):
    return urllib.parse.quote(s, safe="")


def api_head(gitlab_path, branch):
    """(sha, committed_date, err) of the branch head. err set on non-404 failures."""
    rc, out, err = sh(["glab", "api",
                       "projects/%s/repository/commits?ref_name=%s&per_page=1"
                       % (_enc(gitlab_path), _enc(branch))])
    if rc != 0:
        return None, None, err or out or "glab api failed"
    try:
        commits = json.loads(out)
        return commits[0]["id"], commits[0]["committed_date"][:10], None
    except (ValueError, KeyError, IndexError):
        return None, None, "unparseable commits payload"


def api_raw(gitlab_path, rel, ref):
    """(content, status) where status is 'ok' | 'absent' | 'error'."""
    rc, out, err = sh(["glab", "api",
                       "projects/%s/repository/files/%s/raw?ref=%s"
                       % (_enc(gitlab_path), _enc(rel), _enc(ref))])
    if rc == 0:
        return out, "ok"
    blob = (out or "") + " " + (err or "")
    if "404" in blob or "Not Found" in blob:
        return None, "absent"
    return None, "error"


def fetch_member(member, cache_root, force=False,
                 head_fn=api_head, raw_fn=api_raw):
    """Fetch one member's artifact set. Returns a result dict (also written to
    _meta.json on success). head_fn/raw_fn injectable for tests."""
    slug, gp = member["slug"], member.get("gitlab_path", "")
    branch = member.get("default_branch", "main") or "main"
    dest = os.path.join(cache_root, slug)
    meta_path = os.path.join(dest, "_meta.json")

    sha, head_date, err = head_fn(gp, branch)
    if err:
        return {"slug": slug, "status": "UNVERIFIED", "error": err}

    if not force and os.path.isfile(meta_path):
        try:
            old = json.load(open(meta_path))
            if old.get("sha") == sha:
                return {"slug": slug, "status": "current", "sha": sha}
        except (OSError, ValueError):
            pass

    files, fetched, absent, errors = {}, 0, 0, 0
    # Deletions are DEFERRED, not applied inline. Applied inline they ran before the
    # bail-out below, so a run whose first artifacts came back 404 and whose rest
    # errored unlinked cached files and then returned UNVERIFIED without rewriting
    # _meta.json -- leaving metadata that still said `ok` beside files that were gone,
    # and breaking this module's own promise to "leave any previous cache intact".
    to_delete = []
    for rel in ARTIFACTS:
        content, status = raw_fn(gp, rel, sha)
        files[rel] = status
        if status == "ok":
            p = os.path.join(dest, rel)
            os.makedirs(os.path.dirname(p), exist_ok=True)
            with open(p, "w", encoding="utf-8") as f:
                f.write(content)
            fetched += 1
        elif status == "absent":
            absent += 1
            to_delete.append(os.path.join(dest, rel))
        else:
            errors += 1

    if errors and not fetched:
        return {"slug": slug, "status": "UNVERIFIED",
                "error": "%d API errors, nothing fetched" % errors}

    for stale in to_delete:
        if os.path.isfile(stale):
            os.remove(stale)  # artifact deleted upstream: cache must not lie

    os.makedirs(dest, exist_ok=True)
    meta = {
        "slug": slug, "gitlab_path": gp, "branch": branch, "sha": sha,
        "head_committed_date": head_date,
        "fetched_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
        "files": files,
    }
    with open(meta_path, "w") as f:
        json.dump(meta, f, indent=1, sort_keys=True)
    return {"slug": slug, "status": "fetched", "sha": sha,
            "ok": fetched, "absent": absent, "errors": errors}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--project-dir", required=True)
    ap.add_argument("--members", nargs="*", default=None,
                    help="slugs to fetch; default = every roster member with no local clone")
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args()

    try:
        _, members = parse_members(os.path.join(a.project_dir, "MEMBERS.yaml"))
    except ValueError as e:
        print("[fetch] FATAL: %s" % e, file=sys.stderr)
        sys.exit(2)

    if a.members:
        targets = [m for m in members if m["slug"] in set(a.members)]
        missing = set(a.members) - {m["slug"] for m in targets}
        if missing:
            print("[fetch] FATAL: not in roster: %s" % ", ".join(sorted(missing)), file=sys.stderr)
            sys.exit(2)
    else:
        targets = [m for m in members
                   if not (m.get("local_path") and os.path.isdir(m.get("local_path", "")))]

    cache_root = os.path.join(a.project_dir, CACHE_DIRNAME)
    results = [fetch_member(m, cache_root, force=a.force) for m in targets]

    unverified = [r for r in results if r["status"] == "UNVERIFIED"]
    for r in results:
        if r["status"] == "fetched":
            print("  %-40s fetched sha=%s ok=%d absent=%d errors=%d"
                  % (r["slug"], r["sha"][:7], r["ok"], r["absent"], r["errors"]))
        elif r["status"] == "current":
            print("  %-40s current sha=%s (skipped)" % (r["slug"], r["sha"][:7]))
        else:
            print("  %-40s UNVERIFIED: %s" % (r["slug"], r["error"][:80]))
    print("[fetch] %d target(s): %d fetched, %d current, %d UNVERIFIED"
          % (len(results), sum(1 for r in results if r["status"] == "fetched"),
             sum(1 for r in results if r["status"] == "current"), len(unverified)))
    sys.exit(1 if unverified and len(unverified) == len(results) else 0)


if __name__ == "__main__":
    main()
