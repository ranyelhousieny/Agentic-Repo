"""The Step C binding check in SDLC_FEATURE_AGENT.md is CODE -- so run it.

That snippet is markdown, so nothing exercised it, and two bugs reached review inside
it: a `\\s*` that matched newlines (an empty field absorbed the next field's value) and
then a lookahead form that backtracking defeated (`epic: TODO` -- the normal
formatting -- read as filled while only `epic:TODO` was caught). Both were in the rule
whose entire job is to stop a ticket being cut with `parent: TODO`.

This extracts the fenced heredoc from the prompt and executes it against real files,
and asserts it agrees with `project_verify.binding_gaps()`, the reference
implementation. Two copies of one rule that nothing compares WILL drift.

# Requires: python3 3.9+
"""
import os
import re
import subprocess
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
FLEET = os.path.dirname(HERE)
REPO_ROOT = os.path.dirname(os.path.dirname(FLEET))
PROMPT = os.path.join(REPO_ROOT, "prompts", "templates", "AI Agents",
                      "SDLC_FEATURE_AGENT.md")

sys.path.insert(0, FLEET)
from project_verify import binding_gaps  # noqa: E402


def extract_snippet():
    """The `python3 - "$REPO/BINDING.yml" <<'PY' ... PY` body from Step C."""
    text = open(PROMPT, encoding="utf-8").read()
    m = re.search(r"python3 - \"\$REPO/BINDING\.yml\" <<'PY'\n(.*?)\nPY\n", text, re.S)
    assert m, "Step C's binding snippet not found in %s -- did the fence change?" % PROMPT
    return m.group(1)


SNIPPET = extract_snippet()


def run_snippet(tmp_path, body):
    binding = tmp_path / "BINDING.yml"
    binding.write_text(body, encoding="utf-8")
    script = tmp_path / "check.py"
    script.write_text(SNIPPET, encoding="utf-8")
    r = subprocess.run([sys.executable, str(script), str(binding)],
                       capture_output=True, text=True)
    return r.returncode, r.stdout.strip()


def test_the_snippet_was_actually_extracted():
    """A regex that silently matched nothing would make every case below vacuous."""
    assert "BINDING OK" in SNIPPET and "FIELDS" in SNIPPET
    assert len(SNIPPET.splitlines()) > 5


COMPLETE = ("jira_project: TST\nepic: TST-1234\nboard: 42\n"
            "dev_classification: Growth\nassignee_account_id: \"abc\"\n")


def test_a_complete_binding_passes(tmp_path):
    rc, out = run_snippet(tmp_path, COMPLETE)
    assert rc == 0 and out == "BINDING OK"


@pytest.mark.parametrize("value", [
    "TODO",                 # the form Step 10.8 writes when it finds no evidence
    "  TODO",
    '"TODO: no epic in catalog-info.yaml and no sibling BINDING.yml found"',
    "'TODO'",
    "TODO  # fill this in before cutting a ticket",   # Step 10.8 TODOs carry a reason
    "todo",                 # case must not matter
])
def test_every_written_form_of_TODO_is_caught(tmp_path, value):
    """The lookahead form caught only the unspaced `epic:TODO`. `epic: TODO` and
    `epic: "TODO"` -- the two ways it is actually written -- passed."""
    rc, out = run_snippet(tmp_path, COMPLETE.replace("epic: TST-1234", "epic: %s" % value))
    assert rc == 1, "%r read as a filled value" % value
    assert "epic" in out and "INCOMPLETE" in out


def test_an_empty_value_does_not_absorb_the_next_field(tmp_path):
    """Plain `\\s*` after the colon matches the newline, so `epic:` captured
    `board: 42` and read as filled. Only broken when the empty field is NOT last."""
    rc, out = run_snippet(tmp_path, COMPLETE.replace("epic: TST-1234", "epic:"))
    assert rc == 1 and "epic" in out


def test_a_missing_field_is_caught(tmp_path):
    rc, out = run_snippet(tmp_path, COMPLETE.replace("epic: TST-1234\n", ""))
    assert rc == 1 and "epic" in out


@pytest.mark.parametrize("key", ["EPIC", "Epic", "ePiC"])
def test_a_case_varied_key_counts_as_absent(tmp_path, key):
    """YAML keys are case-sensitive, so `EPIC:` is not a binding anything can read.

    The snippet carried `re.M | re.I` over from the lookahead form while
    `binding_gaps()` passes `re.M` only, so this file printed BINDING OK -- the gate
    immediately before `createJiraIssue` -- while R7 failed it. The value test keeps
    its `re.I`; the KEY match must not have one.
    """
    rc, out = run_snippet(tmp_path, COMPLETE.replace("epic: TST-1234",
                                                     "%s: TST-1234" % key))
    assert rc == 1, "%s: read as a resolved `epic` binding" % key
    assert "epic" in out and "INCOMPLETE" in out


@pytest.mark.parametrize("body", [
    COMPLETE,
    COMPLETE.replace("epic: TST-1234", "epic: TODO"),
    COMPLETE.replace("epic: TST-1234", 'epic: "TODO: no evidence"'),
    COMPLETE.replace("epic: TST-1234", "epic:"),
    COMPLETE.replace("board: 42\n", ""),
    "jira_project: TST\nepic:\nboard:\ndev_classification: TODO\nassignee_account_id: a\n",
    # Case-varied KEYS. Every fixture above uses lowercase keys, so an re.I in one
    # implementation and not the other was invisible here -- and that is exactly what
    # shipped: the snippet carried re.M | re.I from the old lookahead form while
    # binding_gaps() passes re.M only, so `EPIC: TST-1234` printed BINDING OK and R7
    # failed the same file. Both must read a case-varied key as absent: YAML keys are
    # case-sensitive, so it is not a binding any consumer can resolve.
    COMPLETE.replace("epic: TST-1234", "EPIC: TST-1234"),
    COMPLETE.replace("board: 42", "Board: 42"),
    COMPLETE.replace("epic: TST-1234", "EPIC: TODO"),
])
def test_snippet_and_binding_gaps_agree(tmp_path, body):
    """One rule, two implementations -- prove they cannot disagree."""
    rc, out = run_snippet(tmp_path, body)
    binding = tmp_path / "BINDING.yml"          # run_snippet already wrote it
    todo, missing = binding_gaps(str(binding))
    expected_bad = set(todo) | set(missing)
    snippet_bad = set() if rc == 0 else set(
        out.split(":", 1)[1].replace(" ", "").split(","))
    assert snippet_bad == expected_bad, (body, snippet_bad, expected_bad)
