"""Python 3.9 floor, ENFORCED for the fleet layer instead of asserted.

`scripts/fleet/README.md` and every module docstring here declare "stdlib only,
Python 3.9+". Until this file existed that was a claim with nothing behind it:
the sweeps in `scripts/onboarding/tests/test_min_interpreter_smoke.py` are scoped
to `scripts/onboarding/`, and `scripts/eval/tests/lint_interpreter_floor.py` is
scoped to `scripts/eval/` -- so `scripts/fleet/` and the ticket-lane preflight at
`scripts/maestro_repo_preflight.py` sat outside both.

Two guards, deliberately different:

  * AST-based bans (PEP-604 unions, match/case) run on ANY interpreter. This is the
    durable one: every 3.9-targeting script may carry `from __future__ import
    annotations`, which makes a PEP-604 union compile and run cleanly on 3.9 -- so a
    py_compile sweep cannot see it. That is exactly how three re-entered
    `extract_fastapi.py` after a sweep declared its directory clean.
  * A py_compile pass under a real 3.9, skipped when none is installed.

# Requires: python3 3.9+
"""
import ast
import os
import shutil
import subprocess

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
FLEET = os.path.dirname(HERE)                       # scripts/fleet/
SCRIPTS = os.path.dirname(FLEET)                    # scripts/

TARGETS = sorted(
    [os.path.join(FLEET, f) for f in os.listdir(FLEET) if f.endswith(".py")]
    + [os.path.join(SCRIPTS, "maestro_repo_preflight.py")]
)

PYTHON39 = shutil.which("python3.9") or (
    "/usr/bin/python3" if os.path.exists("/usr/bin/python3") else None
)


def _is_39(interp):
    if not interp:
        return False
    r = subprocess.run([interp, "-c", "import sys;print(sys.version_info[:2])"],
                       capture_output=True, text=True)
    return r.returncode == 0 and r.stdout.strip() == "(3, 9)"


def test_targets_are_discovered():
    """A glob that silently matches nothing turns every assertion below vacuous."""
    assert len(TARGETS) >= 8, TARGETS
    assert any(t.endswith("maestro_repo_preflight.py") for t in TARGETS)
    assert any(t.endswith("fleetlib.py") for t in TARGETS)


@pytest.mark.parametrize("path", TARGETS, ids=os.path.basename)
def test_no_pep604_union_annotations(path):
    tree = ast.parse(open(path, encoding="utf-8").read(), filename=path)
    annotations = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            annotations.append(node.returns)
            args = node.args
            annotations.extend(a.annotation for a in args.args)
            annotations.extend(a.annotation for a in args.kwonlyargs)
            annotations.extend(a.annotation for a in getattr(args, "posonlyargs", []))
            for extra in (args.vararg, args.kwarg):
                if extra is not None:
                    annotations.append(extra.annotation)
        elif isinstance(node, ast.AnnAssign):
            annotations.append(node.annotation)
    hits = [
        "%s:%d" % (os.path.basename(path), sub.lineno)
        for ann in annotations if ann is not None
        for sub in ast.walk(ann)
        if isinstance(sub, ast.BinOp) and isinstance(sub.op, ast.BitOr)
    ]
    assert not hits, (
        "PEP-604 union annotations (Python 3.10+) found: %s. "
        "Use typing.Optional[X] / typing.Union[X, Y]." % hits
    )


@pytest.mark.parametrize("path", TARGETS, ids=os.path.basename)
def test_no_match_case(path):
    if not hasattr(ast, "Match"):           # running on 3.9 itself: parse would raise
        pytest.skip("this interpreter cannot represent match/case")
    tree = ast.parse(open(path, encoding="utf-8").read(), filename=path)
    hits = ["%s:%d" % (os.path.basename(path), n.lineno)
            for n in ast.walk(tree) if isinstance(n, ast.Match)]
    assert not hits, "match/case (Python 3.10+) found: %s" % hits


@pytest.mark.parametrize("path", TARGETS, ids=os.path.basename)
def test_compiles_under_python39(path):
    if not _is_39(PYTHON39):
        pytest.skip("no python3.9 on this machine")
    r = subprocess.run([PYTHON39, "-m", "py_compile", path],
                       capture_output=True, text=True)
    assert r.returncode == 0, "%s fails to compile under 3.9:\n%s" % (path, r.stderr)


def test_stdlib_filter_survives_a_39_interpreter():
    """`sys.stdlib_module_names` is 3.10+. Falling back to an empty set turned the
    cross-repo graph's stdlib filter OFF on the declared floor, so an `import json`
    could be matched against a roster member and land in the sidecar."""
    import sys
    sys.path.insert(0, FLEET)
    import build_cross_repo_graph as x

    real = getattr(sys, "stdlib_module_names", None)
    try:
        if real is not None:
            del sys.stdlib_module_names                 # simulate 3.9
        x.PY_STDLIBISH = None
        names = x._stdlib_names()
    finally:
        if real is not None:
            sys.stdlib_module_names = real
        x.PY_STDLIBISH = None

    assert {"json", "logging", "asyncio", "typing"} <= names
