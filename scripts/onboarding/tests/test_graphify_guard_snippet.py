"""The Phase 1.5 graphify guard in REPO_ONBOARDING_AGENT.md is CODE -- so run it.

Same lesson as `scripts/fleet/tests/test_step_c_binding_snippet.py`: that guard is a
fenced bash block in a markdown template, so nothing exercised it, and it is the sole
producer of the three no-graph markers `final_verify.py` reads as an either-contract.
Two marker bugs reached review inside it -- `GRAPHIFY_SKIPPED` had no removal path at
all, and then its removal ran only on the bootstrap-SUCCESS path, so a re-enable that
failed to install left a stale marker naming the operator kill switch as the reason.

This extracts the `case "$GRAPHIFY_FLAG" ... esac` block and executes it under bash with
a stubbed `ensure_graphify.sh` and a stubbed adapter, then asserts the marker set the
conversion is left holding. The rule under test: after this block runs, the markers
present must describe THIS run, and exactly one non-empty half of the either-contract
must exist whenever no CODE_GRAPH.jsonl was produced.

# Requires: python3 3.9+
"""
import os
import re
import shutil
import subprocess

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
ONBOARDING = os.path.dirname(HERE)
REPO_ROOT = os.path.dirname(os.path.dirname(ONBOARDING))
PROMPT = os.path.join(REPO_ROOT, "prompts", "templates", "AI Agents",
                      "REPO_ONBOARDING_AGENT.md")

BASH = shutil.which("bash") or "/bin/bash"

ANALYSIS = os.path.join("Generated", "Analysis")
SKIPPED = os.path.join(ANALYSIS, "GRAPHIFY_SKIPPED")
NO_EDGES = os.path.join(ANALYSIS, "GRAPHIFY_NO_EDGES")
ERR = os.path.join(ANALYSIS, "GRAPHIFY_BOOTSTRAP.err")
LOG = os.path.join(ANALYSIS, "GRAPHIFY_ADAPTER.log")


def extract_guard():
    """The `GRAPHIFY_FLAG=... case ... esac` block from Phase 1.5."""
    text = open(PROMPT, encoding="utf-8").read()
    m = re.search(r'(GRAPHIFY_FLAG="\$\(printf.*?\nesac\n)', text, re.S)
    assert m, "Phase 1.5 graphify guard not found in %s -- did the block change?" % PROMPT
    return m.group(1)


GUARD = extract_guard()


def test_the_guard_was_actually_extracted():
    """A regex that silently matched nothing would make every case below vacuous."""
    assert 'case "$GRAPHIFY_FLAG" in' in GUARD and GUARD.rstrip().endswith("esac")
    assert "ensure_graphify.sh" in GUARD and "GRAPHIFY_SKIPPED" in GUARD


def run_guard(tmp_path, flag=None, bootstrap_rc=0, bootstrap_stderr="boom",
              adapter_writes_graph=False, preexisting=()):
    """Execute the guard against a stubbed framework. Returns (rc, files-present)."""
    repo = tmp_path / "repo"
    (repo / ANALYSIS).mkdir(parents=True)
    for rel in preexisting:
        (repo / rel).write_text("stale marker from a previous run\n", encoding="utf-8")

    framework = tmp_path / "framework" / "scripts" / "onboarding"
    framework.mkdir(parents=True)
    # Stub ensure_graphify.sh: prints an interpreter path on stdout, a reason on stderr.
    (framework / "ensure_graphify.sh").write_text(
        "#!/bin/sh\n"
        "printf '%s' \"$STUB_STDERR\" >&2\n"
        "[ \"$STUB_RC\" -eq 0 ] && echo \"$STUB_PY\"\n"
        "exit \"$STUB_RC\"\n", encoding="utf-8")
    # Stub adapter: the real one writes CODE_GRAPH.jsonl / GRAPHIFY_NO_EDGES itself.
    (framework / "extract_graphify.py").write_text(
        "import os, sys\n"
        "repo = sys.argv[1]\n"
        "if os.environ.get('STUB_GRAPH') == '1':\n"
        "    d = os.path.join(repo, 'Generated', 'graphify')\n"
        "    os.makedirs(d, exist_ok=True)\n"
        "    open(os.path.join(d, 'CODE_GRAPH.jsonl'), 'w').write('{}\\n')\n"
        "sys.stderr.write('adapter ran\\n')\n", encoding="utf-8")

    env = dict(os.environ)
    env.update({
        "REPO_PATH": str(repo),
        "FRAMEWORK_HOME": str(tmp_path / "framework"),
        "EXTRACTOR_OUT_FILE": str(tmp_path / "extractor.jsonl"),
        "STUB_RC": str(bootstrap_rc),
        "STUB_STDERR": bootstrap_stderr,
        "STUB_PY": shutil.which("python3") or "python3",
        "STUB_GRAPH": "1" if adapter_writes_graph else "0",
    })
    if flag is None:
        env.pop("GRAPHIFY_ADAPTER", None)
    else:
        env["GRAPHIFY_ADAPTER"] = flag

    r = subprocess.run([BASH, "-c", GUARD], env=env, capture_output=True, text=True,
                       cwd=str(tmp_path))
    present = {rel for rel in (SKIPPED, NO_EDGES, ERR, LOG)
               if (repo / rel).is_file() and (repo / rel).stat().st_size > 0}
    return r, repo, present


@pytest.mark.parametrize("flag", ["0", "false", "no", "off", "", "  0  ", "nonsense"])
def test_kill_switch_states_the_skip_and_writes_no_log(tmp_path, flag):
    """The documented opt-out has to leave a marker: Step 15.8's either-contract needs
    a half present, and absence must always be explained, never assumed."""
    r, repo, present = run_guard(tmp_path, flag=flag)
    assert (repo / SKIPPED).is_file()
    assert "operator kill switch" in (repo / SKIPPED).read_text()
    assert not (repo / LOG).exists(), "the kill switch must not create the adapter log"
    assert not (repo / ERR).exists()


@pytest.mark.parametrize("flag", [None, "1", "true", "yes", "on", "TRUE", " On "])
def test_affirmative_flags_all_run_the_engine(tmp_path, flag):
    """The guard and ensure_graphify.sh normalise identically (`${VAR-1}`, lowercase,
    strip whitespace), so every documented affirmative must reach the adapter."""
    r, repo, present = run_guard(tmp_path, flag=flag, bootstrap_rc=0,
                                 adapter_writes_graph=True)
    assert (repo / "Generated" / "graphify" / "CODE_GRAPH.jsonl").is_file()
    assert not (repo / SKIPPED).exists()


def test_a_successful_run_clears_a_stale_kill_switch_marker(tmp_path):
    """Convert with GRAPHIFY_ADAPTER=0, then re-run in UPDATE mode with the engine on.
    Without a removal path the repo keeps a file asserting SURFACE-LEVEL next to a
    CODE_GRAPH.jsonl written seconds later."""
    r, repo, present = run_guard(tmp_path, flag="1", bootstrap_rc=0,
                                 adapter_writes_graph=True,
                                 preexisting=(SKIPPED, NO_EDGES))
    assert not (repo / SKIPPED).exists()
    assert not (repo / NO_EDGES).exists()
    assert not (repo / ERR).exists(), "this run's spent bootstrap error must be removed"


def test_a_failed_bootstrap_also_clears_a_stale_kill_switch_marker(tmp_path):
    """The removal used to run only on the SUCCESS path, so a re-enable that failed to
    install (offline pip, no python >= 3.10) left the kill-switch marker standing. The
    report reads whichever marker is present, so it named the wrong cause and pointed
    the operator away from the ensure_graphify.sh remediation."""
    r, repo, present = run_guard(tmp_path, flag="1", bootstrap_rc=3,
                                 bootstrap_stderr="no python >= 3.10 on PATH",
                                 preexisting=(SKIPPED,))
    assert not (repo / SKIPPED).exists(), \
        "entering the affirmative arm means the operator did not kill the engine"
    err = (repo / ERR).read_text()
    assert "no python >= 3.10 on PATH" in err
    assert "GRAPHIFY_BOOTSTRAP_FAILED" in err
    assert "GRAPHIFY_SKIPPED" not in err, \
        "an install failure must not be stamped with the kill switch's marker name"


@pytest.mark.parametrize("stderr", ["", "   "])
def test_a_failed_bootstrap_leaves_a_NON_EMPTY_marker(tmp_path, stderr):
    """final_verify.py's either-contract requires size > 0. A failure whose stderr was
    empty would otherwise leave no half present and abort a conversion for a state the
    adapter documents as legal -- previously masked by a stale marker surviving."""
    r, repo, present = run_guard(tmp_path, flag="1", bootstrap_rc=3,
                                 bootstrap_stderr=stderr)
    assert ERR in present, "no non-empty half of the graph either-contract was left"
    assert "SURFACE-LEVEL" in (repo / ERR).read_text()


def test_a_failed_bootstrap_reaches_the_console_and_the_log(tmp_path):
    """Three surfaces, stated in the block's own comment: marker, log, console."""
    r, repo, present = run_guard(tmp_path, flag="1", bootstrap_rc=3,
                                 bootstrap_stderr="pip install failed (offline?)")
    assert "SURFACE-LEVEL" in r.stderr
    assert "pip install failed (offline?)" in (repo / LOG).read_text()


def _section(start, end=None):
    text = open(PROMPT, encoding="utf-8").read()
    i = text.index(start)
    return text[i:text.index(end, i)] if end else text[i:]


def _graph_markers():
    """The graph either-contract's alternatives, read from the gate that enforces it.

    Derived, not hardcoded: a fourth marker added to final_verify.py must show up on
    the completion surfaces too, and this is what makes that automatic.
    """
    import sys
    sys.path.insert(0, ONBOARDING)
    import final_verify

    for alternatives in final_verify.EITHER:
        if any("CODE_GRAPH" in a for a in alternatives):
            return [os.path.basename(a) for a in alternatives if "CODE_GRAPH" not in a]
    raise AssertionError("no CODE_GRAPH either-contract in final_verify.EITHER")


def test_the_marker_list_was_actually_derived():
    markers = _graph_markers()
    assert len(markers) >= 3 and "GRAPHIFY_SKIPPED" in markers


@pytest.mark.parametrize("marker", _graph_markers())
def test_step_16_report_names_every_no_graph_marker(marker):
    """When a gate stops FAILING on a state, every surface that REPORTS the state has
    to learn it. This MR made that mistake twice -- Step 15.7 continued on rc 3 while
    three completion surfaces still demanded the facts, and then the graph's four-way
    outcome reached final_verify.py while Step 16 had no `Dependency Graph:` line at
    all, so a kill-switch or failed-install conversion reported clean."""
    report = _section("**Step 16: Present results**", "## Quality Checklist")
    assert "Dependency Graph:" in report, "Step 16 does not report the graph outcome"
    assert marker in report, "%s is a legal no-graph state Step 16 never names" % marker


def test_step_16_artifact_table_has_a_code_graph_row():
    """A markdown TABLE ROW, not just the path appearing somewhere nearby -- the
    artifact table is one of the three surfaces that reports the conversion's outcome,
    and the golden-facts row got its none-derivable branch while the graph had no row
    at all. Matching on `| <path>` is what makes deleting the row fail this."""
    rows = [ln for ln in open(PROMPT, encoding="utf-8")
            if ln.startswith("| Generated/graphify/CODE_GRAPH.jsonl")]
    assert len(rows) == 1, "expected exactly one CODE_GRAPH.jsonl artifact row, got %d" % len(rows)
    assert "none" in rows[0], "the row must offer a no-graph status, not only created/updated"


@pytest.mark.parametrize("marker", _graph_markers())
def test_quality_checklist_has_a_graph_outcome_item(marker):
    checklist = _section("## Quality Checklist")
    assert "Dependency Graph:" in checklist and marker in checklist


FRAMEWORK_SOURCES = [
    PROMPT,
    os.path.join(ONBOARDING, "final_verify.py"),
    os.path.join(ONBOARDING, "extract_graphify.py"),
    os.path.join(HERE, "test_propose_and_verify.py"),
    os.path.join(REPO_ROOT, ".windsurf", "workflows", "convert-repo-to-agentic.md"),
]
# The four claims that were live on this branch after the marker contract had already
# falsified them. A verbatim-phrase lint, deliberately: the obvious heuristic -- "the
# claim is fine if GRAPHIFY_SKIPPED appears nearby" -- has a false negative that this
# very check hit, because final_verify.py lists the marker as a PATH in the tuple four
# lines under the comment, which excused the claim it was supposed to catch. This
# cannot prove a NEW phrasing of the same wrong idea is absent; it makes restoring any
# of the known-wrong sentences fail, which is what actually happened here.
BANNED_CLAIMS = [
    "no-op that writes nothing",                 # REPO_ONBOARDING_AGENT.md removal drill
    "any other value writes NOTHING",            # the case arm's own comment
    "GRAPHIFY_ADAPTER=0 writes NOTHING",         # final_verify.py's EITHER justification
    "kill switch and writes NOTHING",            # test_propose_and_verify.py docstring
]


def _flatten(path):
    """Strip comment/quote markers and collapse whitespace, so a claim that wraps
    across two lines is still one searchable sentence."""
    text = open(path, encoding="utf-8").read()
    return re.sub(r"\s+", " ", re.sub(r"[#>]", " ", text))


@pytest.mark.parametrize("path", FRAMEWORK_SOURCES, ids=os.path.basename)
def test_no_file_still_claims_the_kill_switch_writes_nothing(path):
    """The kill switch stopped writing nothing when the marker contract landed, and
    four comments across three files went on asserting it -- including the one that
    justifies final_verify.py's either-contract row (the row only exists BECAUSE
    GRAPHIFY_SKIPPED is written) and one in a test whose body writes the marker a few
    lines below the docstring denying it.

    The true statement is narrower and still worth making: the kill switch writes no
    adapter log and no records. It writes exactly one file, GRAPHIFY_SKIPPED, because
    absence of a graph is always stated and never silent.
    """
    if not os.path.exists(path):
        pytest.skip("%s not present" % path)
    flat = _flatten(path)
    offenders = [c for c in BANNED_CLAIMS if c.lower() in flat.lower()]
    assert not offenders, (
        "%s still carries claim(s) the marker contract falsified: %s"
        % (os.path.basename(path), offenders))


def test_exactly_one_either_contract_half_is_left_on_each_no_graph_path(tmp_path):
    """The contract final_verify.py enforces: CODE_GRAPH.jsonl, or exactly one marker
    that says why there is none. Two markers with contradictory reasons is the bug."""
    for kwargs in ({"flag": "0"},
                   {"flag": "1", "bootstrap_rc": 3},
                   {"flag": "1", "bootstrap_rc": 3, "preexisting": (SKIPPED, NO_EDGES)}):
        r, repo, present = run_guard(tmp_path / str(id(kwargs)), **kwargs)
        markers = present & {SKIPPED, NO_EDGES, ERR}
        assert len(markers) == 1, (kwargs, markers)
