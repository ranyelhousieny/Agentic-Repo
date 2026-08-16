"""Tests for scripts/sdlc_repo_preflight.py -- the pipeline handoff guard.

No network and no `glab` binary: `search` / `get_project` / `glab_api` are stubbed
on the imported module. Every case here is a wrong-handoff shape the script exists
to refuse, so a regression shows up as a FAILING test rather than as a ticket
pointed at somebody else's repo.

# Requires: python3 3.9+
"""
import importlib.util
import os

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(os.path.dirname(HERE), "sdlc_repo_preflight.py")


def load():
    spec = importlib.util.spec_from_file_location("sdlc_repo_preflight", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def proj(path, **kw):
    d = {"path_with_namespace": path, "name": path.split("/")[-1],
         "default_branch": "main", "id": abs(hash(path)) % 10000}
    d.update(kw)
    return d


@pytest.fixture()
def pf():
    mod = load()
    mod.glab_api = lambda path: {"username": "tester"} if path == "user" else None
    mod.get_project = lambda p: None
    mod.search = lambda name: []
    return mod


# ------------------------------------------------------- resolution ranking
def test_exact_name_outranks_group_preference(pf):
    """`?search=` is a substring match: asking for `foo-service` also returns
    `foo-service-iac`. Group-first ranking handed back the -iac sibling."""
    pf.search = lambda name: [
        proj("your-org/apps/TEAM-A/foo-service-iac"),
        proj("your-org/apps/OTHER/foo-service"),
    ]
    best = pf.suggest_live("foo-service")
    assert best["path_with_namespace"] == "your-org/apps/OTHER/foo-service"


def test_group_preference_still_breaks_ties_between_exact_matches(pf):
    pf.search = lambda name: [
        proj("your-org/apps/OTHER/svc"),
        proj("your-org/apps/TEAM-A/svc"),
    ]
    live = pf.live_candidates("svc")
    assert live[0]["path_with_namespace"] == "your-org/apps/TEAM-A/svc"


def test_dead_candidates_never_win(pf):
    pf.search = lambda name: [
        proj("your-org/apps/TEAM-A/svc-deletion_scheduled-83695743"),
        proj("your-org/apps/TEAM-A/svc-archived", archived=True),
        proj("your-org/apps/TEAM-A/svc-empty", empty_repo=True),
        proj("your-org/apps/OTHER/svc"),
    ]
    assert pf.suggest_live("svc")["path_with_namespace"] == "your-org/apps/OTHER/svc"


def test_full_path_resolution_skips_search(pf):
    called = []
    pf.get_project = lambda p: (called.append(p), proj(p))[1]
    got, alts = pf.resolve("your-org/apps/TEAM-A/team_group")
    assert got["path_with_namespace"] == "your-org/apps/TEAM-A/team_group"
    assert alts == [] and called == ["your-org/apps/TEAM-A/team_group"]


def test_canonical_override_redirects_a_migrated_repo(pf):
    seen = []
    pf.get_project = lambda p: (seen.append(p), proj(p))[1]
    got, _ = pf.resolve("team_group")
    assert seen == ["your-org/apps/TEAM-A/team_group"]
    assert got["path_with_namespace"] == "your-org/apps/TEAM-A/team_group"


# ------------------------------------------------------------- ambiguity
def test_two_exact_matches_are_ambiguous(pf):
    pf.search = lambda name: [
        proj("your-org/apps/TEAM-A/svc"),
        proj("your-org/apps/OTHER/svc"),
    ]
    _, alts = pf.resolve("svc")
    assert len(alts) == 1, "a second live repo with the same name must not be silently dropped"


def test_a_substring_sibling_is_not_an_ambiguity(pf):
    pf.search = lambda name: [
        proj("your-org/apps/OTHER/svc"),
        proj("your-org/apps/TEAM-A/svc-iac"),
    ]
    _, alts = pf.resolve("svc")
    assert alts == []


def test_main_exits_2_on_ambiguity(pf, capsys):
    pf.search = lambda name: [
        proj("your-org/apps/TEAM-A/svc"),
        proj("your-org/apps/OTHER/svc"),
    ]
    import sys
    argv = sys.argv
    sys.argv = ["sdlc_repo_preflight.py", "--repo", "svc"]
    try:
        with pytest.raises(SystemExit) as e:
            pf.main()
    finally:
        sys.argv = argv
    assert e.value.code == 2
    assert "AMBIGUOUS" in capsys.readouterr().out


# ------------------------------------------------------------------ auth
def test_broken_auth_fails_loudly_and_does_not_call_the_repo_dead(pf, capsys):
    pf.glab_api = lambda path: None            # expired token: everything fails
    import sys
    argv = sys.argv
    sys.argv = ["sdlc_repo_preflight.py", "--repo", "svc"]
    try:
        with pytest.raises(SystemExit) as e:
            pf.main()
    finally:
        sys.argv = argv
    out = capsys.readouterr().out
    assert e.value.code == 2
    assert "not authenticated" in out
    assert "NOT evidence" in out, "a broken token must not read as a dead repo"


def test_main_passes_on_a_clean_exact_resolution(pf, capsys):
    pf.search = lambda name: [proj("your-org/apps/TEAM-A/svc")]
    import sys
    argv = sys.argv
    sys.argv = ["sdlc_repo_preflight.py", "--repo", "svc"]
    try:
        with pytest.raises(SystemExit) as e:
            pf.main()
    finally:
        sys.argv = argv
    assert e.value.code == 0
    assert "PASS: your-org/apps/TEAM-A/svc" in capsys.readouterr().out
