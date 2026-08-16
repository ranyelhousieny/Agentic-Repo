"""
tests/test_min_interpreter_smoke.py — Runtime smoke tests for minimum-interpreter compliance.

Verifies that each script under scripts/onboarding/ executes without crashing under the
declared minimum interpreter versions:

  python3 3.9+  (for all .py scripts and the embedded Python heredoc in verify_citations.sh)
  bash 3.2+     (for all .sh scripts)

Architecture notes (PROJ-2574):
  - The smoke test MUST discover a real python3.9 interpreter (via PYTHON39 env var,
    PATH search, or known pyenv/homebrew locations) and pytest.skip when it is absent.
    It must NEVER fall back to sys.executable — doing so reproduces the exact failure mode
    (test passes under Python 3.12+, defect ships to Python 3.9) that this test exists to
    catch.  See load-bearing constraint in PROJ-2574.

  - For bash, the test uses the system /bin/bash.  On macOS, /bin/bash is bash 3.2
    (Apple's GPL2 freeze).  On Linux, /bin/bash is typically 4.x or 5.x, but the scripts
    are written to be compatible with 3.2, so running under a newer bash is still valid
    as a compilation/syntax check.  The test skip fires only when bash is missing entirely.

  - verify_citations.sh's shell wrapper parses --help / flag arguments BEFORE the
    embedded Python heredoc executes.  A bare --help invocation would exit in the shell
    wrapper and never trigger the def-time TypeError.  To exercise the embedded Python
    body, the smoke test MUST pass a real (or minimal tempdir fixture) artifact path so
    the heredoc actually executes.

Interpreter discovery (for python3.9):
  Priority order:
    1. PYTHON39 environment variable (e.g. PYTHON39=/usr/bin/python3.9)
    2. First of "python3.9" / "python3.9.6" resolved from PATH via shutil.which
    3. Known homebrew location: /usr/local/bin/python3.9
    4. Known pyenv location:    ~/.pyenv/versions/3.9.*/bin/python3.9  (glob, first match)
  If none found: pytest.skip with a message telling the operator how to install 3.9.
"""
from __future__ import annotations

import ast
import glob
import os
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parent.parent   # scripts/onboarding/
REPO_ROOT   = SCRIPTS_DIR.parent.parent                # repository root


# ─── interpreter discovery ────────────────────────────────────────────────────

def _probe_python_version(binary: str) -> tuple:
    """
    Execute `binary -c 'import sys; print(sys.version_info[:2])'` and return the
    reported (major, minor) tuple, or () on any failure.
    """
    try:
        result = subprocess.run(
            [binary, "-c", "import sys; print(sys.version_info[:2])"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode != 0:
            return ()
        # stdout looks like "(3, 9)\n"
        import ast
        v = ast.literal_eval(result.stdout.strip())
        if isinstance(v, tuple) and len(v) == 2:
            return v
    except Exception:
        pass
    return ()


def _find_python39() -> str | None:
    """
    Return the path to a Python 3.9 interpreter, or None if not found.

    Discovery strategy (PROJ-2574 fix):
      Priority order:
        1. PYTHON39 environment variable — accept only if it reports version (3, 9).
           Fail loudly (assert) if it reports something else, so the operator knows
           they set PYTHON39 to a non-3.9 binary.
        2. Plain 'python3' and 'python' from PATH — accept if version is (3, 9).
           This is the critical addition: on the target machine /usr/bin/python3 IS
           Python 3.9.6, but the previous implementation only searched for binaries
           literally named 'python3.9' or 'python3.9.6', returning None on such boxes
           and causing every 3.9 guard to SKIP silently.
        3. 'python3.9' / 'python3.9.6' from PATH (explicit name search, verified).
        4. Known homebrew locations.
        5. pyenv versions glob.

    Returns the first candidate whose reported sys.version_info[:2] == (3, 9).
    """
    # 1. Explicit env var override — verify version, fail loudly on mismatch
    env_override = os.environ.get("PYTHON39", "").strip()
    if env_override:
        if Path(env_override).is_file():
            v = _probe_python_version(env_override)
            if v == (3, 9):
                return env_override
            assert False, (
                f"PYTHON39={env_override!r} was set but the interpreter reports "
                f"version {v}, not (3, 9).  Set PYTHON39 to a real Python 3.9.x binary."
            )
        # Path does not exist — fall through to PATH search

    # 2. & 3. Candidate list: plain names first (catches /usr/bin/python3 == 3.9),
    #         then explicit version-named binaries.
    for name in ("python3", "python", "python3.9", "python3.9.6"):
        found = shutil.which(name)
        if found and _probe_python_version(found) == (3, 9):
            return found

    # 4. Known homebrew locations (macOS + Linux)
    for brew_path in (
        "/usr/local/bin/python3.9",
        "/opt/homebrew/bin/python3.9",
        "/home/linuxbrew/.linuxbrew/bin/python3.9",
    ):
        if Path(brew_path).is_file() and _probe_python_version(brew_path) == (3, 9):
            return brew_path

    # 5. pyenv versions glob
    pyenv_glob = os.path.expanduser("~/.pyenv/versions/3.9.*/bin/python3.9")
    matches = sorted(glob.glob(pyenv_glob))
    for m in reversed(matches):   # newest 3.9.x first
        if _probe_python_version(m) == (3, 9):
            return m

    return None


def _find_bash() -> str | None:
    """Return the path to a bash interpreter, or None."""
    for candidate in ("/bin/bash", "/usr/bin/bash"):
        if Path(candidate).is_file():
            return candidate
    return shutil.which("bash")


PYTHON39 = _find_python39()
BASH     = _find_bash()

_SKIP_PYTHON39 = pytest.mark.skipif(
    PYTHON39 is None,
    reason=(
        "python3.9 not found on this machine. "
        "Install it with: pyenv install 3.9.6 && pyenv local 3.9.6 "
        "(or set PYTHON39=/path/to/python3.9 in your environment)."
    ),
)

_SKIP_BASH = pytest.mark.skipif(
    BASH is None,
    reason="bash not found at /bin/bash, /usr/bin/bash, or PATH.",
)


# ─── helpers ─────────────────────────────────────────────────────────────────

def _run(
    cmd: list[str],
    *,
    cwd: str = None,
    env: dict = None,
    timeout: int = 30,
) -> subprocess.CompletedProcess:
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=timeout,
        cwd=cwd,
        env=env,
    )


def _make_minimal_code_index(tmp_path: Path) -> Path:
    """
    Create a minimal fixture that verify_citations.sh can run against.

    verify_citations.sh's shell wrapper exits early on --help, --dry-run with no
    artifact, etc., before the python3 heredoc fires.  To exercise the embedded Python
    body (where the def-time TypeError was) we must pass a real artifact path and a
    real REPO_PATH so the heredoc actually executes.

    A CODE_INDEX.md with zero citations triggers B5 (exit 1) but that happens inside
    the Python body — which proves the body compiled and executed.  We use
    --min-citations 0 to get a clean exit-0 for the smoke test.
    """
    artifact = tmp_path / "CODE_INDEX.md"
    artifact.write_text(
        "# Minimal smoke-test fixture\n\nNo citations — smoke test only.\n",
        encoding="utf-8",
    )
    return artifact


# ─── Python 3.9 smoke: embedded heredoc in verify_citations.sh ───────────────

@_SKIP_PYTHON39
def test_verify_citations_compiles_under_python39(tmp_path: Path) -> None:
    """
    The embedded Python body in verify_citations.sh must compile and execute
    under Python 3.9 without a TypeError at def-time.

    This is the regression test for PROJ-2574: `Path | None` at line 311 caused a
    TypeError under Python 3.9 because `|` as a union operator on types is PEP 604
    (Python 3.10+).  The fix (`Optional[Path]`) is verified here.

    We pass a real minimal artifact so the python3 heredoc actually executes;
    --min-citations 0 suppresses the B5 exit-1 for a zero-citation artifact.
    """
    artifact = _make_minimal_code_index(tmp_path)
    verify_sh = SCRIPTS_DIR / "verify_citations.sh"

    env = os.environ.copy()
    # Override python3 in the PATH with our discovered python3.9
    bin_dir = tmp_path / "py39_bin"
    bin_dir.mkdir()
    py39_wrapper = bin_dir / "python3"
    py39_wrapper.write_text(
        f"#!/bin/sh\nexec {PYTHON39} \"$@\"\n",
        encoding="utf-8",
    )
    py39_wrapper.chmod(0o755)
    env["PATH"] = f"{bin_dir}:{os.environ.get('PATH', '')}"

    result = _run(
        ["bash", str(verify_sh), str(artifact), str(tmp_path),
         "--min-citations", "0", "--dry-run"],
        cwd=str(tmp_path),
        env=env,
    )

    assert result.returncode == 0, (
        f"verify_citations.sh crashed under Python 3.9 (returncode={result.returncode}).\n"
        f"This is the PROJ-2574 regression: check for 'Path | None' (PEP 604) annotations "
        f"in the embedded Python body — replace with Optional[Path] from typing.\n"
        f"stderr: {result.stderr}\n"
        f"stdout: {result.stdout}"
    )
    # Confirm Python actually executed (not just the shell wrapper)
    assert "Citations:" in result.stdout or "VALIDATION_SUMMARY" in result.stdout, (
        f"Expected Python body output in stdout; got:\n{result.stdout}\nstderr: {result.stderr}"
    )


# ─── Python 3.9 smoke: extract_fastapi.py ────────────────────────────────────

@_SKIP_PYTHON39
def test_extract_fastapi_compiles_under_python39(tmp_path: Path) -> None:
    """extract_fastapi.py must import and run without SyntaxError under Python 3.9."""
    result = _run(
        [PYTHON39, str(SCRIPTS_DIR / "extract_fastapi.py"), str(tmp_path)],
    )
    assert result.returncode == 0, (
        f"extract_fastapi.py crashed under Python 3.9.\n"
        f"stderr: {result.stderr}\nstdout: {result.stdout}"
    )
    # An empty repo produces no output — that is correct and expected
    assert "TypeError" not in result.stderr, (
        f"TypeError in extract_fastapi.py under Python 3.9: {result.stderr}"
    )


# ─── Python 3.9 smoke: merge_sme_contacts.py ─────────────────────────────────

@_SKIP_PYTHON39
def test_merge_sme_contacts_compiles_under_python39(tmp_path: Path) -> None:
    """merge_sme_contacts.py must compile and run --dry-run under Python 3.9."""
    result = _run(
        [PYTHON39, str(SCRIPTS_DIR / "merge_sme_contacts.py"),
         "--repo-path", str(tmp_path), "--dry-run"],
    )
    assert result.returncode == 0, (
        f"merge_sme_contacts.py crashed under Python 3.9.\n"
        f"stderr: {result.stderr}\nstdout: {result.stdout}"
    )
    assert "TypeError" not in result.stderr, (
        f"TypeError in merge_sme_contacts.py under Python 3.9: {result.stderr}"
    )


# ─── Python 3.9 smoke: readiness_report.py ───────────────────────────────────

@_SKIP_PYTHON39
def test_readiness_report_compiles_under_python39(tmp_path: Path) -> None:
    """readiness_report.py must compile and run --stdout under Python 3.9.

    py_compile (test_no_match_case_in_py_scripts below) only proves the file
    parses; it never executes os.walk / Path.glob / stat, so a runtime-only 3.9
    regression would ship. Every other .py script in this directory carries an
    execute-it smoke test for that reason.
    """
    result = _run(
        [PYTHON39, str(SCRIPTS_DIR / "readiness_report.py"), str(tmp_path), "--stdout"],
    )
    assert result.returncode == 0, (
        f"readiness_report.py crashed under Python 3.9.\n"
        f"stderr: {result.stderr}\nstdout: {result.stdout}"
    )
    assert "# Agent Readiness Report" in result.stdout, (
        f"Expected the rendered report on stdout; got:\n{result.stdout}\n"
        f"stderr: {result.stderr}"
    )
    assert "TypeError" not in result.stderr, (
        f"TypeError in readiness_report.py under Python 3.9: {result.stderr}"
    )


# ─── Bash 3.2 compatibility smoke tests ──────────────────────────────────────
#
# On most Linux CI environments /bin/bash is 4.x or 5.x.  These tests run the
# scripts under the *system* bash, which is sufficient to catch syntax errors
# and confirm the scripts reach their normal exit path.  On macOS, /bin/bash IS
# bash 3.2 (Apple GPL2 freeze), so the test runs under the exact declared minimum.
#
# These tests are NOT skipped on Linux — the scripts are declared 3.2-compatible
# and must work on any bash >= 3.2.

@_SKIP_BASH
def test_extract_express_syntax_check(tmp_path: Path) -> None:
    """extract_express.sh must pass bash -n syntax check and exit 0 on an empty repo."""
    # Syntax check
    syntax = _run([BASH, "-n", str(SCRIPTS_DIR / "extract_express.sh")])
    assert syntax.returncode == 0, (
        f"extract_express.sh failed bash -n syntax check: {syntax.stderr}"
    )
    # Functional check against empty repo
    result = _run([BASH, str(SCRIPTS_DIR / "extract_express.sh"), str(tmp_path)])
    assert result.returncode == 0, (
        f"extract_express.sh exited non-zero on empty repo: {result.stderr}"
    )


@_SKIP_BASH
def test_extract_express_path_with_space(tmp_path: Path) -> None:
    """
    PROJ-2574 regression: extract_express.sh must emit a non-zero record count
    from a repo whose path contains a space.

    Before the SRC_DIRS array fix, $SRC_DIRS (a space-separated string) was
    word-split at every iteration site, producing 0 records and exit 0 when
    the repo path contained a space — silent data loss.
    """
    # Create a repo dir whose path contains a space
    space_repo = tmp_path / "my repo with spaces"
    space_repo.mkdir()

    # Add a minimal Express entry point that the extractor should pick up
    src_dir = space_repo / "src"
    src_dir.mkdir()
    entry = src_dir / "app.ts"
    entry.write_text(
        "import express from 'express';\n"
        "const app = express();\n"
        "app.get('/health', (req, res) => res.json({ ok: true }));\n",
        encoding="utf-8",
    )

    result = _run([BASH, str(SCRIPTS_DIR / "extract_express.sh"), str(space_repo)])
    assert result.returncode == 0, (
        f"extract_express.sh exited non-zero on space-path repo: {result.stderr}"
    )
    assert result.stdout.strip(), (
        "extract_express.sh must emit at least one JSON-lines record from a repo "
        "with spaces in its path.  Got zero records — the SRC_DIRS word-split bug "
        "has regressed.\n"
        f"stdout: {result.stdout!r}\nstderr: {result.stderr}"
    )
    # Verify at least one record is valid JSON with required keys
    import json
    records = [
        json.loads(line)
        for line in result.stdout.splitlines()
        if line.strip()
    ]
    assert records, "No JSON records found in extract_express.sh output"
    assert all("path" in r and "line" in r and "kind" in r for r in records), (
        f"Records missing required fields: {records}"
    )


@_SKIP_BASH
def test_extract_spring_boot_syntax_check(tmp_path: Path) -> None:
    """extract_spring_boot.sh must pass bash -n syntax check and exit 0 on an empty repo."""
    syntax = _run([BASH, "-n", str(SCRIPTS_DIR / "extract_spring_boot.sh")])
    assert syntax.returncode == 0, (
        f"extract_spring_boot.sh failed bash -n syntax check: {syntax.stderr}"
    )
    result = _run([BASH, str(SCRIPTS_DIR / "extract_spring_boot.sh"), str(tmp_path)])
    assert result.returncode == 0, (
        f"extract_spring_boot.sh exited non-zero on empty repo: {result.stderr}"
    )


@_SKIP_BASH
def test_extract_terraform_syntax_check(tmp_path: Path) -> None:
    """extract_terraform.sh must pass bash -n syntax check and exit 0 on an empty repo."""
    syntax = _run([BASH, "-n", str(SCRIPTS_DIR / "extract_terraform.sh")])
    assert syntax.returncode == 0, (
        f"extract_terraform.sh failed bash -n syntax check: {syntax.stderr}"
    )
    result = _run([BASH, str(SCRIPTS_DIR / "extract_terraform.sh"), str(tmp_path)])
    assert result.returncode == 0, (
        f"extract_terraform.sh exited non-zero on empty repo: {result.stderr}"
    )


@_SKIP_BASH
def test_verify_citations_syntax_check() -> None:
    """verify_citations.sh must pass bash -n syntax check."""
    syntax = _run([BASH, "-n", str(SCRIPTS_DIR / "verify_citations.sh")])
    assert syntax.returncode == 0, (
        f"verify_citations.sh failed bash -n syntax check: {syntax.stderr}"
    )


@_SKIP_BASH
def test_extract_git_ownership_syntax_check(tmp_path: Path) -> None:
    """extract_git_ownership.sh must pass bash -n syntax check."""
    syntax = _run([BASH, "-n", str(SCRIPTS_DIR / "extract_git_ownership.sh")])
    assert syntax.returncode == 0, (
        f"extract_git_ownership.sh failed bash -n syntax check: {syntax.stderr}"
    )


# ─── No-3.10+ syntax sweep ────────────────────────────────────────────────────
#
# These tests assert the sweep guarantees stated in README.md — they are not
# "rerun the grep on the filesystem" but rather "compile each file and assert
# the absence of the 3.10+ syntax that would raise at def-time under 3.9".

@_SKIP_PYTHON39
def test_no_pep604_union_in_heredoc(tmp_path: Path) -> None:
    """
    No PEP-604 (X | Y) type annotation may exist in verify_citations.sh's embedded
    Python body.  This is the root-cause test for the original PROJ-2574 crash.

    Method: run the full script under Python 3.9 with a minimal fixture and assert
    exit 0 (done by test_verify_citations_compiles_under_python39 above).  Additionally,
    run a direct Python compile of a snippet that would crash on 3.9 if the bug recurs.

    PROJ-2574 fix: the canary uses a multi-line -c string with an embedded newline so
    `def f() -> Path | None:` is a proper function definition — NOT joined with `;`
    which is a SyntaxError on every Python version regardless of PEP-604 support.
    """
    # Confirm that Path | None fails under 3.9 (proves our test can catch it).
    # Use a real multi-line snippet via embedded newline — `;` after `def` is a
    # SyntaxError on all Pythons and would misread as "interpreter supports PEP 604".
    canary_snippet = "from pathlib import Path\ndef f() -> Path | None:\n    pass\n"
    canary = _run(
        [PYTHON39, "-c", canary_snippet],
    )
    if canary.returncode == 0:
        pytest.skip(
            "PYTHON39 interpreter supports PEP 604 (it is actually >= 3.10). "
            "The interpreter at PYTHON39 is not a true 3.9 interpreter. "
            "Set PYTHON39 to a real Python 3.9.x binary."
        )

    # Now confirm that Optional[Path] is fine on the same interpreter
    optional_snippet = (
        "from pathlib import Path\n"
        "from typing import Optional\n"
        "def f() -> Optional[Path]:\n"
        "    pass\n"
    )
    optional_ok = _run(
        [PYTHON39, "-c", optional_snippet],
    )
    assert optional_ok.returncode == 0, (
        f"Optional[Path] should compile fine on Python 3.9 but failed: {optional_ok.stderr}"
    )


@_SKIP_PYTHON39
def test_no_match_case_in_py_scripts() -> None:
    """
    No match/case statement (Python 3.10+) may appear in any .py script under
    scripts/onboarding/.  A match/case statement causes a SyntaxError on Python 3.9.
    """
    py_scripts = list(SCRIPTS_DIR.glob("*.py"))
    assert py_scripts, "No .py scripts found under scripts/onboarding/ — check SCRIPTS_DIR"

    for script in py_scripts:
        result = _run(
            [PYTHON39, "-m", "py_compile", str(script)],
        )
        assert result.returncode == 0, (
            f"{script.name} has a syntax error under Python 3.9:\n{result.stderr}\n"
            "Possible causes: match/case statement, PEP-604 union (X | Y), or other "
            "Python 3.10+ syntax."
        )


def test_no_pep604_union_in_py_scripts() -> None:
    """
    No PEP-604 (X | Y) union may appear in an annotation in any .py script under
    scripts/onboarding/ — the ban README.md states, enforced rather than asserted.

    This runs on any interpreter and does NOT duplicate the py_compile sweep above:
    every one of these scripts carries `from __future__ import annotations`, which turns
    annotations into strings and lets a PEP-604 union compile and run cleanly on 3.9.
    That is exactly how three of them reached `extract_fastapi.py` after PROJ-2574 swept
    the directory clean — a compile check cannot see them, so this walks annotation
    subtrees for `BinOp(op=BitOr)` instead. Scoped to the shipped scripts, matching the
    sweep in README.md; tests/ runs on the developer interpreter, not the 3.9 floor.
    """
    py_scripts = sorted(SCRIPTS_DIR.glob("*.py"))
    assert py_scripts, "No .py scripts found under scripts/onboarding/ — check SCRIPTS_DIR"

    hits = []
    for script in py_scripts:
        tree = ast.parse(script.read_text(encoding="utf-8"), filename=str(script))
        annotations = []
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                annotations.append(node.returns)
                annotations.extend(a.annotation for a in node.args.args)
                annotations.extend(a.annotation for a in node.args.kwonlyargs)
                annotations.extend(a.annotation for a in node.args.posonlyargs)
                if node.args.vararg is not None:
                    annotations.append(node.args.vararg.annotation)
                if node.args.kwarg is not None:
                    annotations.append(node.args.kwarg.annotation)
            elif isinstance(node, ast.AnnAssign):
                annotations.append(node.annotation)
        for annotation in annotations:
            if annotation is None:
                continue
            for sub in ast.walk(annotation):
                if isinstance(sub, ast.BinOp) and isinstance(sub.op, ast.BitOr):
                    hits.append(f"{script.name}:{sub.lineno}")

    assert not hits, (
        f"PEP-604 union annotations found (Python 3.10+, forbidden by "
        f"scripts/onboarding/README.md): {hits}\n"
        "Use typing.Optional[X] / typing.Union[X, Y] instead."
    )
