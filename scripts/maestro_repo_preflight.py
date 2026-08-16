#!/usr/bin/env python3
"""
Maestro repo PREFLIGHT -- resolve a target repo to its LIVE full GitLab path, and
REFUSE a Maestro handoff when the resolved project is stale/dead.

Lives in the Agentic-Repos framework checkout (your-org/agentic-repo)
and is invoked from there, like every other script in scripts/: callers resolve
$FRAMEWORK_HOME and run "$FRAMEWORK_HOME/scripts/maestro_repo_preflight.py".
It is NOT copied into converted repos -- the conversion template never emitted it, so
the old "converted repos receive a copy" note sent /start-sdlc-feature Step 1 at a
relative path that does not exist in a target repo.
Used by the /start-sdlc-feature command (Step 1).

Why this exists (2026-07-20): a meeting-doc reroute (PROJ-2340) failed because Maestro
resolved the bare name "team_group" to the DELETION-SCHEDULED, empty placeholder
`your-org/apps/team-group/sample-service_fabric-deletion_scheduled-83695743` instead
of the live `your-org/apps/TEAM-A/team_group`. The repo was migrated
team-group -> TEAM-A group; the old empty shell still resolves by name and traps Maestro.

This guard makes a wrong-repo handoff structurally impossible from the caller's side:
- Always resolve to a FULL path (never hand Maestro a bare name).
- Rank an EXACT name match above group preference. `?search=` is a substring match,
  so `--repo foo-service` also returns `foo-service-iac`; group-first ranking used to
  return the `-iac` sibling and print PASS on it.
- FAIL on ambiguity (two live projects with the same last path segment) rather than
  guessing which team's repo was meant.
- FAIL if the resolved project is deletion-scheduled, archived, empty, or under a
  migrated-away group; suggest the live replacement.

Usage:
  python3 scripts/maestro_repo_preflight.py --repo team_group
  python3 scripts/maestro_repo_preflight.py --repo your-org/apps/TEAM-A/team_group
Exit 0 = PASS (prints canonical full path + default branch). Exit 2 = FAIL (prints reason).

Auth: uses `glab api` (must be authenticated: `glab auth status`). An expired glab
token makes every lookup FAIL identically to a missing project, so the FIRST thing
this script does is `glab api user`; a broken token exits 2 saying so in as many
words, instead of leaving the caller to run the control test by hand.
Tests: scripts/tests/test_maestro_repo_preflight.py (stubbed API, no network).
"""
import sys, json, subprocess, argparse, urllib.parse

# Repos we KNOW migrated; map bare name -> canonical live full path.
CANONICAL = {
    "team_group": "your-org/apps/TEAM-A/team_group",
}
# Groups a repo must NOT be handed off under (migrated away; only tombstones remain).
#
# 2026-08-06: EMPTIED. This previously held "your-org/apps/team-group/",
# which banned the ENTIRE group. That was an over-generalisation of a single repo's move:
# only `team_group` migrated team-group -> TEAM-A (see CANONICAL above), but the whole
# group got blocked. Measured 2026-08-06: apps/team-group has 61 ACTIVE projects and ran
# 1,263 MRs in the preceding 90 days -- it is a live group, not a graveyard.
#
# Removing this loses NO protection: the real tombstones are caught by name via the
# "deletion_scheduled" test in liveness() (e.g. team_group-deletion_scheduled-83695743,
# argocd-fabric-deletion_scheduled-84568894), and archived/empty repos are caught by their
# own independent checks. Re-add a prefix here only for a group that is genuinely dead.
BAD_GROUP_PREFIXES = []


def glab_api(path):
    r = subprocess.run(["glab", "api", path], capture_output=True, text=True)
    if r.returncode != 0:
        return None
    try:
        return json.loads(r.stdout)
    except Exception:
        return None


def get_project(path_or_id):
    enc = str(path_or_id) if str(path_or_id).isdigit() else urllib.parse.quote(path_or_id, safe="")
    return glab_api("projects/%s" % enc)


def search(name):
    return glab_api("projects?search=%s&per_page=50" % urllib.parse.quote(name)) or []


def liveness(proj):
    """(ok, reason). ok=True means safe to hand to Maestro."""
    p = proj.get("path_with_namespace", "") or ""
    nm = proj.get("name", "") or ""
    if "deletion_scheduled" in p or "deletion_scheduled" in nm:
        return False, "deletion-scheduled placeholder (%s)" % p
    if proj.get("archived"):
        return False, "archived (%s)" % p
    for bg in BAD_GROUP_PREFIXES:
        if p.startswith(bg):
            return False, "stale/migrated-away group (%s)" % p
    if proj.get("empty_repo"):
        return False, "empty repo, cannot push initial commit (%s)" % p
    return True, p


def live_candidates(name, cands=None):
    """LIVE search hits for `name`, best first.

    Ranking, in order: EXACT last-path-segment match, then apps/TEAM-A, then path.

    The exact-match key is not cosmetic. GitLab's `?search=` is a SUBSTRING match,
    so `--repo foo-service` also returns `foo-service-iac`; ranking the group ahead
    of the name handed back `apps/TEAM-A/foo-service-iac` while the real
    `apps/OTHER/foo-service` sat in the same result set -- a wrong-repo handoff,
    which is the single failure class this whole script exists to prevent.
    """
    base = name.split("/")[-1]
    cands = search(base) if cands is None else cands
    live = [c for c in cands if liveness(c)[0]]
    live.sort(key=lambda c: (
        0 if (c.get("path_with_namespace", "").split("/")[-1] == base) else 1,
        0 if "/apps/TEAM-A/" in c.get("path_with_namespace", "") else 1,
        c.get("path_with_namespace", ""),
    ))
    return live


def ambiguous(live, name):
    """Other exact-name matches beyond the winner -- a human must choose.

    Two live repos whose last segment is literally the requested name differ only
    by group; picking one by group preference is a guess, and a guess here hands
    Maestro somebody else's repo.
    """
    base = name.split("/")[-1]
    exact = [c for c in live if c.get("path_with_namespace", "").split("/")[-1] == base]
    return exact[1:] if len(exact) > 1 else []


def suggest_live(name):
    """The single best LIVE candidate for `name`, or None."""
    live = live_candidates(name)
    return live[0] if live else None


def auth_ok():
    """glab authenticated? An expired token makes every lookup FAIL identically
    to a missing project, so a plain FAIL here is not evidence a repo is dead.
    Checked FIRST so the caller never has to run the manual control test."""
    me = glab_api("user")
    return isinstance(me, dict) and bool(me.get("username")), (me or {}).get("username", "")


def resolve(repo):
    """(project, alternates). Never guesses past an ambiguity."""
    lookup = CANONICAL.get(repo, repo)          # known-migrated repos
    proj = get_project(lookup) if "/" in lookup else None
    if proj is not None:
        return proj, []
    live = live_candidates(repo)
    if live:
        return live[0], ambiguous(live, repo)
    # nothing live: surface the first hit so liveness() can name WHY it is dead
    hits = search(repo.split("/")[-1])
    return (hits[0] if hits else None), []


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default="team_group", help="repo name or full GitLab path")
    a = ap.parse_args()
    repo = a.repo.strip()

    ok_auth, who = auth_ok()
    if not ok_auth:
        print("FAIL: glab is not authenticated -- `glab api user` returned nothing.")
        print("  This is NOT evidence that '%s' is dead: an expired token fails every" % repo)
        print("  lookup identically to a missing project.")
        print("  Fix: TOK=<a valid PAT>; printf '%s' \"$TOK\" | glab auth login --hostname gitlab.com --stdin")
        sys.exit(2)

    proj, alts = resolve(repo)

    if proj is None:
        print("FAIL: could not resolve repo '%s' to any GitLab project (glab auth ok as %s)"
              % (repo, who))
        sys.exit(2)

    ok, reason = liveness(proj)
    if not ok:
        print("FAIL: '%s' resolved to a dead target -> %s" % (repo, reason))
        alt = suggest_live(repo)
        if alt:
            print("  USE INSTEAD: %s (branch %s, id %s)"
                  % (alt["path_with_namespace"], alt.get("default_branch"), alt.get("id")))
        print("  Do NOT hand this ticket to Maestro until the target is the live full path above.")
        sys.exit(2)

    if alts:
        print("FAIL: '%s' is AMBIGUOUS -- %d live projects share that exact name:" % (repo, len(alts) + 1))
        for c in [proj] + alts:
            print("  - %s (branch %s, id %s)"
                  % (c["path_with_namespace"], c.get("default_branch"), c.get("id")))
        print("  Re-run with the full path. Picking one by group preference would be a guess,")
        print("  and a guess here hands Maestro another team's repo.")
        sys.exit(2)

    print("PASS: %s (branch %s, id %s)"
          % (proj["path_with_namespace"], proj.get("default_branch"), proj.get("id")))
    sys.exit(0)


if __name__ == "__main__":
    main()
