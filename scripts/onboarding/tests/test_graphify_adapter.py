"""
tests/test_graphify_adapter.py — Tests for the optional Graphify adapter.

The adapter is flag-gated (GRAPHIFY_ADAPTER) and must NEVER be load-bearing:
  1. Flag off (default): clean skip, exit 0, zero stdout records.
  2. Flag on, engine not installed: clean skip, exit 0, zero stdout records.
  3. Mapper: graph nodes/edges -> contract records {path, line, kind, identifier}
     with additive {engine, confidence}; INFERRED -> sidecar; AMBIGUOUS -> dropped;
     unknown kinds counted, never emitted.
  4. Credential env sanitization strips every provider variable.

Mapper tests import the module directly (no graphifyy install required), so this
file runs green on any machine — the removal drill, continuously proven.
"""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parent.parent
ADAPTER = SCRIPTS_DIR / "extract_graphify.py"

spec = importlib.util.spec_from_file_location("extract_graphify", ADAPTER)
adapter = importlib.util.module_from_spec(spec)
spec.loader.exec_module(adapter)


def run_adapter(repo_path: Path, env_overrides: dict) -> subprocess.CompletedProcess:
    env = {k: v for k, v in os.environ.items() if k != "GRAPHIFY_ADAPTER"}
    env.update(env_overrides)
    return subprocess.run(
        [sys.executable, str(ADAPTER), str(repo_path)],
        capture_output=True, text=True, env=env,
    )


# ─── flag gate ──────────────────────────────────────────────────────────────

def test_flag_zero_disables(tmp_path):
    result = run_adapter(tmp_path, {"GRAPHIFY_ADAPTER": "0"})
    assert result.returncode == 0
    assert result.stdout == ""
    assert "disabled" in result.stderr


def test_default_is_enabled(tmp_path):
    # No flag set: adapter is ON by default and proceeds to the engine preflight.
    # Point GRAPHIFY_CMD at a missing binary so the test never runs a real engine;
    # the skip reason must be the ENGINE (absent), never the flag.
    result = run_adapter(tmp_path, {"GRAPHIFY_CMD": "definitely-not-a-real-binary"})
    assert result.returncode == 0
    assert result.stdout == ""
    assert "disabled" not in result.stderr
    assert ("not installed" in result.stderr) or ("NOT FOUND" in result.stderr)


def test_flag_on_without_engine_is_clean_skip(tmp_path):
    result = run_adapter(tmp_path, {"GRAPHIFY_ADAPTER": "1",
                                    "GRAPHIFY_CMD": "definitely-not-a-real-binary"})
    assert result.returncode == 0
    assert result.stdout == ""
    # Either the package is absent (preflight skip) or the command is not found.
    assert ("not installed" in result.stderr) or ("NOT FOUND" in result.stderr)


def test_missing_repo_path_is_clean_skip(tmp_path):
    result = run_adapter(tmp_path / "does-not-exist", {"GRAPHIFY_ADAPTER": "1"})
    assert result.returncode == 0
    assert result.stdout == ""


# ─── env sanitization ───────────────────────────────────────────────────────

def test_sanitized_env_strips_credentials(monkeypatch):
    for var in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "AWS_SECRET_ACCESS_KEY",
                "AWS_PROFILE", "GEMINI_BASE_URL", "OLLAMA_HOST", "MOONSHOT_API_KEY",
                "DEEPSEEK_API_KEY", "AZURE_OPENAI_KEY", "MY_SERVICE_TOKEN",
                "SOMETHING_SECRET", "CUSTOM_BASE_URL"):
        monkeypatch.setenv(var, "leak-me")
    monkeypatch.setenv("PATH", "/usr/bin")
    monkeypatch.setenv("HOME", "/tmp/home")
    env = adapter.sanitized_env()
    leaked = [k for k, v in env.items() if v == "leak-me"]
    assert leaked == [], f"credentials leaked into engine env: {leaked}"
    assert env["PATH"] == "/usr/bin"
    assert env["HOME"] == "/tmp/home"


# ─── mapper: nodes ──────────────────────────────────────────────────────────

def fresh_counters():
    return {"nodes_unparseable": 0, "nodes_missing_fields": 0,
            "inferred_to_sidecar": 0, "ambiguous_dropped": 0,
            "edges_unparseable": 0, "edges_non_dependency": 0,
            "edges_unresolvable": 0}


def test_map_nodes_contract_shape(tmp_path):
    nodes = [
        {"id": 1, "name": "create_account", "type": "function",
         "path": "src/accounts.py", "line": 42},
        {"id": 2, "name": "AccountService", "type": "class",
         "path": "src/service.py", "line": 7},
    ]
    records, sidecar = adapter.map_nodes(nodes, tmp_path, "graphifyy==0.9.43",
                                         fresh_counters())
    assert sidecar == []
    assert len(records) == 2
    for record in records:
        assert set(record) == {"path", "line", "kind", "identifier", "engine", "confidence"}
        assert record["path"] and isinstance(record["line"], int) and record["line"] > 0
    assert records[0]["kind"] == "handler"
    assert records[1]["kind"] == "module"


def test_map_nodes_absolute_paths_become_relative(tmp_path):
    nodes = [{"id": 1, "name": "f", "type": "function",
              "path": str(tmp_path / "pkg" / "mod.py"), "line": 3}]
    records, _ = adapter.map_nodes(nodes, tmp_path, "e", fresh_counters())
    assert records[0]["path"] == "pkg/mod.py"


def test_map_nodes_confidence_gate(tmp_path):
    nodes = [
        {"id": 1, "name": "a", "type": "function", "path": "a.py", "line": 1,
         "confidence": "EXTRACTED"},
        {"id": 2, "name": "b", "type": "function", "path": "b.py", "line": 1,
         "confidence": "INFERRED"},
        {"id": 3, "name": "c", "type": "function", "path": "c.py", "line": 1,
         "confidence": "AMBIGUOUS"},
    ]
    counters = fresh_counters()
    records, sidecar = adapter.map_nodes(nodes, tmp_path, "e", counters)
    assert [r["identifier"] for r in records] == ["a"]
    assert [r["identifier"] for r in sidecar] == ["b"]
    assert counters["ambiguous_dropped"] == 1


def test_map_nodes_unknown_kinds_counted_not_emitted(tmp_path):
    nodes = [{"id": 1, "name": "x", "type": "community", "path": "x.py", "line": 1}]
    counters = fresh_counters()
    records, sidecar = adapter.map_nodes(nodes, tmp_path, "e", counters)
    assert records == [] and sidecar == []
    assert counters["skipped_kinds"] == {"community": 1}


def test_map_nodes_alternate_key_spellings(tmp_path):
    nodes = [{"id": 1, "label": "handler_fn", "kind": "method",
              "file_path": "api/h.py", "lineno": 9}]
    records, _ = adapter.map_nodes(nodes, tmp_path, "e", fresh_counters())
    assert records == [{"path": "api/h.py", "line": 9, "kind": "handler",
                        "identifier": "handler_fn", "engine": "e",
                        "confidence": "EXTRACTED"}]


# ─── mapper: edges ──────────────────────────────────────────────────────────

def test_map_edges_dependency_records(tmp_path):
    counters = fresh_counters()
    adapter.map_nodes(
        [{"id": 1, "name": "svc", "type": "module", "path": "svc.py", "line": 1},
         {"id": 2, "name": "db", "type": "module", "path": "db.py", "line": 1}],
        tmp_path, "e", counters)
    records, sidecar = adapter.map_edges(
        [{"source": 1, "target": 2, "type": "import"},
         {"source": 1, "target": 2, "type": "contains"}],
        counters, "e")
    assert sidecar == []
    assert len(records) == 1
    assert records[0]["kind"] == "dependency"
    assert records[0]["identifier"] == "svc -> db"
    assert records[0]["path"] == "svc.py"
    assert counters["edges_non_dependency"] == 1


def test_map_edges_unresolvable_counted(tmp_path):
    counters = fresh_counters()
    counters["node_index"] = {}
    records, sidecar = adapter.map_edges(
        [{"source": 99, "target": 100, "type": "call"}], counters, "e")
    assert records == [] and sidecar == []
    assert counters["edges_unresolvable"] == 1


# ─── end-to-end with a fake engine ──────────────────────────────────────────

def test_end_to_end_with_stub_engine(tmp_path):
    """Full CLI path: stub engine writes graph.json; adapter emits contract records
    and quarantines INFERRED to the sidecar."""
    repo = tmp_path / "repo"
    repo.mkdir()
    graph = {
        "nodes": [
            {"id": 1, "name": "get_user", "type": "function",
             "path": "app/api.py", "line": 12},
            {"id": 2, "name": "helpers", "type": "module",
             "path": "app/helpers.py", "line": 1, "confidence": "INFERRED"},
        ],
        "edges": [{"source": 1, "target": 2, "type": "import"}],
    }
    # Mimic the real CLI: `<engine> update <repo> --no-cluster` writing the graph to
    # the engine-native <repo>/graphify-out/graph.json (adapter relocates it after).
    stub = tmp_path / "stub_engine.py"
    stub.write_text(
        "import json,sys,pathlib\n"
        "assert sys.argv[1] == 'update', sys.argv\n"
        "out = pathlib.Path(sys.argv[2]) / 'graphify-out'\n"
        "out.mkdir(parents=True, exist_ok=True)\n"
        f"(out/'graph.json').write_text(json.dumps({json.dumps(graph)}))\n"
    )
    result = run_adapter(repo, {
        "GRAPHIFY_ADAPTER": "1",
        "GRAPHIFY_CMD": f"{sys.executable} {stub}",
    })
    # Preflight requires the graphifyy package; absent -> clean skip is the
    # correct behavior and the assertion below still holds (no partial output).
    assert result.returncode == 0
    if "not installed" in result.stderr:
        pytest.skip("graphifyy not installed on this machine — preflight skip verified")
    records = [json.loads(line) for line in result.stdout.splitlines()]
    kinds = sorted(r["kind"] for r in records)
    assert kinds == ["dependency", "handler"]
    sidecar_file = repo / "Generated" / "graphify" / "NEEDS_VERIFICATION.jsonl"
    assert sidecar_file.is_file()
    sidecar = [json.loads(line) for line in sidecar_file.read_text().splitlines()]
    assert [r["identifier"] for r in sidecar] == ["helpers"]
