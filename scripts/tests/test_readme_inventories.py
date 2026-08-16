"""Each script directory's README is an INVENTORY -- prove it is complete.

`scripts/onboarding/README.md` documents one `### \\`name\\`` section per script and is the
contract doc for that directory (it is already the stated source of truth for its
interpreter floor). `scripts/fleet/README.md` names the tests that enforce its claims.
Both are hand-maintained, and both silently fell behind the code in one change:
`final_verify.py`, `golden_facts.py` and `propose_codeowners.py` shipped with zero
mentions anywhere in the onboarding README -- including the Step 15.8 hard gate the whole
conversion contract ends on -- in the same commit range that ADDED two other `###`
sections to that file. A reader who trusts the inventory concludes those gates do not
exist.

These are structural checks against the filesystem, not prose review: a new script or a
new test file fails them until the README learns about it.

# Requires: python3 3.9+
"""
import os
import re

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
ONBOARDING = os.path.join(SCRIPTS, "onboarding")
FLEET = os.path.join(SCRIPTS, "fleet")


def _scripts_in(directory):
    return sorted(f for f in os.listdir(directory)
                  if f.endswith((".py", ".sh")) and not f.startswith("_"))


ONBOARDING_SCRIPTS = _scripts_in(ONBOARDING)
FLEET_TESTS = sorted(f for f in os.listdir(os.path.join(FLEET, "tests"))
                     if f.startswith("test_") and f.endswith(".py"))


def test_the_directories_were_actually_scanned():
    """An empty listing would make every parametrized case below vacuous."""
    assert len(ONBOARDING_SCRIPTS) >= 10, ONBOARDING_SCRIPTS
    assert "final_verify.py" in ONBOARDING_SCRIPTS
    assert len(FLEET_TESTS) >= 3, FLEET_TESTS


@pytest.mark.parametrize("script", ONBOARDING_SCRIPTS)
def test_onboarding_readme_documents_every_script(script):
    readme = open(os.path.join(ONBOARDING, "README.md"), encoding="utf-8").read()
    assert re.search(r"^### `%s`" % re.escape(script), readme, re.M), (
        "scripts/onboarding/%s has no `### \\`%s\\`` section in that directory's "
        "README -- the ## Scripts list is an inventory, so an omission reads as "
        "'this script does not exist'." % (script, script))


@pytest.mark.parametrize("test_file", FLEET_TESTS)
def test_fleet_readme_names_every_fleet_test(test_file):
    readme = open(os.path.join(FLEET, "README.md"), encoding="utf-8").read()
    assert test_file in readme, (
        "scripts/fleet/tests/%s is missing from the README's `Tests:` line, which "
        "enumerates that directory's tests exhaustively." % test_file)
