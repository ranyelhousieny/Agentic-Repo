"""golden_facts.py — the mechanical eval gate (Step 15.7).

Facts are derived once from gate-verified evidence and asserted on every run;
drift between the knowledge base and the code must turn into a hard failure.
No LLM, no network — everything here is a real subprocess on a fixture tree.
"""
import json
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "golden_facts.py"


def run(mode, repo, *extra):
    return subprocess.run([sys.executable, str(SCRIPT), mode, str(repo), *extra],
                          capture_output=True, text=True)


def fixture(tmp_path):
    """Minimal converted repo: two endpoints, one entry point, phase-1 row, one edge."""
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "main.py").write_text(
        "import os\n"
        "from fastapi import FastAPI\n"
        "app = FastAPI()\n"
        "@app.get('/chat')\n"
        "def chat():\n"
        "    return {}\n"
        "@app.get('/health')\n"
        "def health():\n"
        "    return {}\n"
    )
    (tmp_path / "Knowledge").mkdir()
    (tmp_path / "Knowledge" / "CODE_INDEX.md").write_text(
        "| Kind | Identifier | Citation | Status |\n"
        "|------|------------|----------|--------|\n"
        "| endpoint | GET /chat | app/main.py:4 | VERIFIED |\n"
        "| endpoint | GET /health | app/main.py:7 | VERIFIED |\n"
        "| entry_point | app = FastAPI() | app/main.py:3 | VERIFIED |\n"
    )
    (tmp_path / "Generated" / "Analysis").mkdir(parents=True)
    (tmp_path / "Generated" / "Analysis" / "PHASE1_DETECTION.md").write_text(
        "| FRAMEWORK | FastAPI | grep | VERIFIED |\n"
    )
    (tmp_path / "Generated" / "graphify").mkdir()
    (tmp_path / "Generated" / "graphify" / "CODE_GRAPH.jsonl").write_text(
        # First edge's target (`os`) is below the 3-char token floor and must be
        # skipped; the second is the derivable one — mirrors real graphs where
        # stdlib one-letter/two-letter imports lead the file.
        json.dumps({"path": "app/main.py", "line": 1, "kind": "dependency",
                    "identifier": "main.py -> os", "engine": "graphifyy==test",
                    "confidence": "EXTRACTED"}) + "\n"
        + json.dumps({"path": "app/main.py", "line": 2, "kind": "dependency",
                      "identifier": "main.py -> fastapi", "engine": "graphifyy==test",
                      "confidence": "EXTRACTED"}) + "\n"
    )
    return tmp_path


def test_derive_then_assert_green_on_fresh_conversion(tmp_path):
    repo = fixture(tmp_path)
    r = run("derive", repo)
    assert r.returncode == 0, r.stderr
    jsonl = repo / "Knowledge" / "golden" / "GOLDEN_FACTS.jsonl"
    facts = [json.loads(l) for l in jsonl.read_text().splitlines()]
    # 2 endpoints + 1 entry_point + framework + 1 edge (the short-token `os`
    # edge is skipped; `fastapi` derives)
    assert len(facts) == 5
    assert any("fastapi" in f["claim"] for f in facts if f["id"] == "GF-005")
    r = run("assert", repo)
    assert r.returncode == 0, r.stderr
    md = (repo / "Knowledge" / "golden" / "GOLDEN_FACTS.md").read_text()
    # "**FAIL**" is the status marker; bare "FAIL" also appears in the header prose
    assert "PASS" in md and "**FAIL**" not in md


def test_drift_is_a_hard_failure(tmp_path):
    """The whole point: KB says line 4, code moved — assert must exit 1."""
    repo = fixture(tmp_path)
    assert run("derive", repo).returncode == 0
    main = repo / "app" / "main.py"
    main.write_text("# a new header comment shifts every line\n" + main.read_text())
    r = run("assert", repo)
    assert r.returncode == 1
    assert "FAIL" in r.stderr
    assert "**FAIL**" in (repo / "Knowledge" / "golden" / "GOLDEN_FACTS.md").read_text()


def test_derive_once_update_mode_never_overwrites_anchors(tmp_path):
    repo = fixture(tmp_path)
    assert run("derive", repo).returncode == 0
    jsonl = repo / "Knowledge" / "golden" / "GOLDEN_FACTS.jsonl"
    original = jsonl.read_text()
    # Index changes (as it would on an UPDATE-mode re-run)...
    (repo / "Knowledge" / "CODE_INDEX.md").write_text(
        "| endpoint | GET /new | app/main.py:7 | VERIFIED |\n")
    r = run("derive", repo)
    assert r.returncode == 0
    assert "derive-once" in r.stdout
    assert jsonl.read_text() == original     # anchors untouched -> drift stays detectable
    # ...and --rederive is the explicit refresh
    r = run("derive", repo, "--rederive")
    assert r.returncode == 0
    assert jsonl.read_text() != original


def test_no_evidence_is_a_loud_usage_error_not_an_empty_pass(tmp_path):
    (tmp_path / "Knowledge").mkdir()
    r = run("derive", tmp_path)
    assert r.returncode == 3
    assert "no derivable facts" in r.stderr
    r = run("assert", tmp_path)
    assert r.returncode == 3
    assert "run derive first" in r.stderr
