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


def stub_env(stub_cmd: str, **extra) -> dict:
    """Env for driving the adapter against a stub engine.

    GRAPHIFY_CMD is double-gated on GRAPHIFY_ALLOW_CMD_OVERRIDE=1 (an env var that selects
    an arbitrary binary is a code-execution surface), so any test that supplies its own
    engine must opt in explicitly -- exactly as a real operator would.
    """
    env = {"GRAPHIFY_ADAPTER": "1",
           "GRAPHIFY_CMD": stub_cmd,
           "GRAPHIFY_ALLOW_CMD_OVERRIDE": "1"}
    env.update(extra)
    return env


# ─── flag gate ──────────────────────────────────────────────────────────────

def test_flag_zero_disables(tmp_path):
    result = run_adapter(tmp_path, {"GRAPHIFY_ADAPTER": "0"})
    assert result.returncode == 0
    assert result.stdout == ""
    assert "disabled" in result.stderr


def test_default_is_enabled(tmp_path):
    # No flag set: adapter is ON by default and proceeds to the engine preflight.
    # Point GRAPHIFY_CMD at a missing binary (double-gated with ALLOW_CMD_OVERRIDE so it
    # is honoured) so the test never runs a real engine; the skip reason must be the
    # ENGINE (not runnable), never the flag.
    result = run_adapter(tmp_path, {"GRAPHIFY_CMD": "definitely-not-a-real-binary",
                                    "GRAPHIFY_ALLOW_CMD_OVERRIDE": "1"})
    assert result.returncode == 0
    assert result.stdout == ""
    assert "disabled" not in result.stderr
    assert ("not installed" in result.stderr) or ("NOT RUNNABLE" in result.stderr)


def test_flag_on_without_engine_is_clean_skip(tmp_path):
    result = run_adapter(tmp_path, {"GRAPHIFY_ADAPTER": "1",
                                    "GRAPHIFY_CMD": "definitely-not-a-real-binary",
                                    "GRAPHIFY_ALLOW_CMD_OVERRIDE": "1"})
    assert result.returncode == 0
    assert result.stdout == ""
    # Either the package is absent (preflight skip) or the command is not runnable.
    assert ("not installed" in result.stderr) or ("NOT RUNNABLE" in result.stderr)


def test_cmd_override_ignored_without_allow_gate(tmp_path):
    """GRAPHIFY_CMD alone must NOT choose the binary — it is a code-execution surface.
    Without GRAPHIFY_ALLOW_CMD_OVERRIDE=1 the adapter ignores it, says so loudly, and
    uses the default engine command."""
    result = run_adapter(tmp_path, {"GRAPHIFY_ADAPTER": "1",
                                    "GRAPHIFY_CMD": "definitely-not-a-real-binary",
                                    "GRAPHIFY_SKIP_PREFLIGHT": "1"})
    assert result.returncode == 0
    assert result.stdout == ""
    assert "ignoring the override" in result.stderr


@pytest.mark.parametrize("value", ["0", "false", "no", "off", "OFF", "FALSE",
                                   "disabled", "disable", "none", "n", "f", "nope", ""])
def test_kill_switch_fails_closed(tmp_path, value):
    """Any value that is not an explicit affirmative must STOP the engine.

    The engine is third-party and runs over the target repo's source, so the only safe
    reading of a value we do not recognise is "stop". `GRAPHIFY_ADAPTER=disabled` is the
    likeliest thing an operator types; treating it as enabled would silently run the engine.
    """
    result = run_adapter(tmp_path, {"GRAPHIFY_ADAPTER": value,
                                    "GRAPHIFY_CMD": "definitely-not-a-real-binary",
                                    "GRAPHIFY_ALLOW_CMD_OVERRIDE": "1"})
    assert result.returncode == 0
    assert result.stdout == ""
    assert "disabled" in result.stderr, f"GRAPHIFY_ADAPTER={value!r} did not disable"


@pytest.mark.parametrize("value", ["1", "true", "yes", "on", "TRUE", " On "])
def test_affirmative_values_enable(tmp_path, value):
    result = run_adapter(tmp_path, {"GRAPHIFY_ADAPTER": value,
                                    "GRAPHIFY_CMD": "definitely-not-a-real-binary",
                                    "GRAPHIFY_ALLOW_CMD_OVERRIDE": "1"})
    assert result.returncode == 0
    assert "disabled" not in result.stderr


def test_missing_repo_path_is_clean_skip(tmp_path):
    result = run_adapter(tmp_path / "does-not-exist", {"GRAPHIFY_ADAPTER": "1"})
    assert result.returncode == 0
    assert result.stdout == ""


# ─── env sanitization ───────────────────────────────────────────────────────

def test_sanitized_env_strips_credentials(monkeypatch):
    for var in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "AWS_SECRET_ACCESS_KEY",
                "AWS_PROFILE", "GEMINI_BASE_URL", "OLLAMA_HOST", "MOONSHOT_API_KEY",
                "DEEPSEEK_API_KEY", "AZURE_OPENAI_KEY", "MY_SERVICE_TOKEN",
                "SOMETHING_SECRET", "CUSTOM_BASE_URL",
                # second-pass review additions: suffix classes the first cut missed
                "DB_PASSWORD", "PYPI_PASSWD", "PRIVATE_KEY", "GITHUB_PAT",
                "SERVICE_CREDENTIALS", "snowflake_password",
                # exact-name denylist: live channels, not just readable secrets
                "SSH_AUTH_SOCK", "HTTP_PROXY", "https_proxy", "ALL_PROXY",
                "NETRC", "API_KEY"):
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
    # Mirrors the dict main() seeds, so mapper tests exercise the same shape as production.
    return {"nodes_unparseable": 0, "nodes_missing_fields": 0,
            "inferred_to_sidecar": 0, "ambiguous_dropped": 0,
            "edges_unparseable": 0, "edges_non_dependency": 0,
            "edges_unresolvable": 0, "confidence_absent": 0}


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


def test_map_edges_string_node_ids_never_become_paths(tmp_path):
    """On an edge object `source` is a node id. With string ids the generic PATH_KEYS
    tuple would have accepted the id as the record's path — a citation no file backs.
    The path must come from the node index (or an explicit edge path key), never the id.
    """
    counters = fresh_counters()
    adapter.map_nodes(
        [{"id": "app.py::main", "name": "main", "type": "function",
          "path": "app.py", "line": 3},
         {"id": "lib.py::helper", "name": "helper", "type": "function",
          "path": "lib.py", "line": 8}],
        tmp_path, "e", counters)
    records, _ = adapter.map_edges(
        [{"source": "app.py::main", "target": "lib.py::helper", "type": "call"}],
        counters, "e")
    assert len(records) == 1
    assert records[0]["path"] == "app.py", "edge path must come from the node index"
    assert records[0]["identifier"] == "main -> helper"


def test_edge_inherits_weakest_endpoint_confidence(tmp_path):
    """An edge touching an INFERRED node goes to the sidecar; touching an AMBIGUOUS
    node it is dropped. Emitting `a -> b` as EXTRACTED while `b` sat quarantined would
    smuggle an unverified symbol into the index through the side door."""
    counters = fresh_counters()
    adapter.map_nodes(
        [{"id": 1, "name": "a", "type": "function", "path": "a.py", "line": 1},
         {"id": 2, "name": "b", "type": "function", "path": "b.py", "line": 1,
          "confidence": "INFERRED"},
         {"id": 3, "name": "c", "type": "function", "path": "c.py", "line": 1,
          "confidence": "AMBIGUOUS"}],
        tmp_path, "e", counters)
    # `ambiguous_dropped` is shared by both passes and node `c` already incremented it, so
    # measure the delta across map_edges rather than the absolute total.
    dropped_before = counters["ambiguous_dropped"]
    records, sidecar = adapter.map_edges(
        [{"source": 1, "target": 2, "type": "import"},
         {"source": 1, "target": 3, "type": "import"}],
        counters, "e")
    assert records == [], "no edge touching a non-EXTRACTED node may reach the index"
    assert [r["identifier"] for r in sidecar] == ["a -> b"]
    assert sidecar[0]["confidence"] == "INFERRED"
    assert counters["ambiguous_dropped"] - dropped_before == 1, "the a -> c edge"


# ─── mapper: the REAL graphifyy schema ──────────────────────────────────────
# node_kind()'s docstring documents what graphifyy==0.9.43 actually emits: `_callable` /
# `_callable_class` flags, `file_type`, and `source_location`. The tests above all use the
# synthetic `type: function|class|module` spelling the docstring says is NOT what the engine
# produces, so without these the production branches have no coverage at all.

def test_real_schema_callable_flags_map_to_kinds(tmp_path):
    nodes = [
        {"id": "n1", "label": "getUser", "file_type": "code", "_callable": True,
         "source_file": "src/api.py", "source_location": "src/api.py:42"},
        {"id": "n2", "label": "UserSvc", "file_type": "code", "_callable_class": True,
         "source_file": "src/svc.py", "source_location": "src/svc.py:7"},
        {"id": "n3", "label": "plain module", "file_type": "code",
         "source_file": "src/mod.py", "source_location": "src/mod.py:1"},
    ]
    records, _ = adapter.map_nodes(nodes, tmp_path, "e", fresh_counters())
    assert [r["kind"] for r in records] == ["handler", "module", "module"]
    # The line must come from source_location, NOT be defaulted to 1.
    assert [r["line"] for r in records] == [42, 7, 1]


def test_real_schema_rationale_nodes_are_skipped(tmp_path):
    counters = fresh_counters()
    records, sidecar = adapter.map_nodes(
        [{"id": "r1", "label": "why this exists", "file_type": "rationale",
          "source_file": "src/api.py", "source_location": "src/api.py:9"}],
        tmp_path, "e", counters)
    assert records == [] and sidecar == []
    assert counters["skipped_kinds"] == {"rationale": 1}


# ─── fail-closed citations ──────────────────────────────────────────────────

@pytest.mark.parametrize("raw,expected", [
    ("42", 42), ("L42", 42), ("42:7", 42),
    ("src/api.py:42", 42),          # the shape `source_location` actually carries
    ("src/api.py#L42", 42),
    ("no-digits-here", None),        # must be None, never 1
    ("", None), (None, None), (0, None), (-3, None), ({"line": 4}, None),
])
def test_coerce_line_never_fabricates_line_one(raw, expected):
    assert adapter.coerce_line(raw) == expected


def test_resolve_line_does_not_let_source_location_mask_line(tmp_path):
    """first_key() short-circuits, so an unparseable source_location must not hide `line`."""
    node = {"source_location": "totally unparseable", "line": 42}
    assert adapter.resolve_line(node) == 42


def test_nodes_without_a_resolvable_line_are_dropped(tmp_path):
    """README.md fail-closed guarantee: no citation -> drop, never emit at line 1."""
    counters = fresh_counters()
    records, sidecar = adapter.map_nodes(
        [{"id": 1, "name": "orphan", "type": "function", "path": "a.py"}],
        tmp_path, "e", counters)
    assert records == [] and sidecar == []
    assert counters["nodes_missing_fields"] == 1


def test_edges_without_a_resolvable_line_are_dropped(tmp_path):
    counters = fresh_counters()
    adapter.map_nodes([{"id": 1, "name": "svc", "type": "module", "path": "svc.py"},
                       {"id": 2, "name": "db", "type": "module", "path": "db.py"}],
                      tmp_path, "e", counters)
    records, sidecar = adapter.map_edges(
        [{"source": 1, "target": 2, "type": "import", "path": "svc.py"}], counters, "e")
    assert records == [] and sidecar == []
    assert counters["edges_unresolvable"] == 1


# ─── confidence gate ────────────────────────────────────────────────────────

def test_absent_confidence_is_counted_not_silent(tmp_path):
    """The gate defaults to EXTRACTED, but the drift must be visible in the counters."""
    counters = fresh_counters()
    records, _ = adapter.map_nodes(
        [{"id": 1, "name": "f", "type": "function", "path": "a.py", "line": 1}],
        tmp_path, "e", counters)
    assert records[0]["confidence"] == "EXTRACTED"
    assert counters["confidence_absent"] == 1


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
        "GRAPHIFY_ALLOW_CMD_OVERRIDE": "1",
    })
    # An honoured GRAPHIFY_CMD names an operator-supplied engine, so the packaged version
    # floor does not apply and this runs everywhere -- no graphifyy install required.
    # Previously this test skipped whenever the distribution was absent, which is the
    # default state, so the relocation / sidecar / find_graph_json paths had no coverage.
    assert result.returncode == 0, result.stderr
    assert "not installed" not in result.stderr
    records = [json.loads(line) for line in result.stdout.splitlines()]
    # Only the EXTRACTED symbol reaches stdout. helpers is INFERRED (sidecar), and the
    # edge touching it inherits INFERRED (weakest-of rule) so it is quarantined too.
    assert [r["kind"] for r in records] == ["handler"]
    sidecar_file = repo / "Generated" / "graphify" / "NEEDS_VERIFICATION.jsonl"
    assert sidecar_file.is_file()
    sidecar = [json.loads(line) for line in sidecar_file.read_text().splitlines()]
    assert [r["identifier"] for r in sidecar] == ["helpers", "get_user -> helpers"]


def test_extracted_dependency_edges_go_to_code_graph_not_stdout(tmp_path):
    """Dependency edges are the bulk of real output (1,803 of 3,159 on the largest test
    repo); they land in Generated/graphify/CODE_GRAPH.jsonl, never on stdout, so the
    eager-loaded CODE_INDEX.md stays inside the activation token budget."""
    repo = tmp_path / "repo"
    repo.mkdir()
    graph = {
        "nodes": [
            {"id": 1, "name": "svc", "type": "function", "path": "svc.py", "line": 4},
            {"id": 2, "name": "db", "type": "function", "path": "db.py", "line": 9},
        ],
        "edges": [{"source": 1, "target": 2, "type": "import"}],
    }
    stub = tmp_path / "stub_engine.py"
    stub.write_text(
        "import json,sys,pathlib\n"
        "out = pathlib.Path(sys.argv[2]) / 'graphify-out'\n"
        "out.mkdir(parents=True, exist_ok=True)\n"
        f"(out/'graph.json').write_text(json.dumps({json.dumps(graph)}))\n")
    result = run_adapter(repo, {"GRAPHIFY_ADAPTER": "1",
                                "GRAPHIFY_CMD": f"{sys.executable} {stub}",
                                "GRAPHIFY_ALLOW_CMD_OVERRIDE": "1"})
    assert result.returncode == 0, result.stderr
    stdout_kinds = [json.loads(l)["kind"] for l in result.stdout.splitlines()]
    assert "dependency" not in stdout_kinds
    graph_file = repo / "Generated" / "graphify" / "CODE_GRAPH.jsonl"
    assert graph_file.is_file()
    deps = [json.loads(l) for l in graph_file.read_text().splitlines()]
    assert [d["identifier"] for d in deps] == ["svc -> db"]
    assert all(d["kind"] == "dependency" for d in deps)


def _stub_engine(tmp_path, body: str) -> Path:
    stub = tmp_path / "stub_engine.py"
    stub.write_text(body)
    return stub


def test_engine_output_directory_is_gitignored(tmp_path):
    """Nothing in the framework ignores Generated/graphify/, so the adapter must."""
    repo = tmp_path / "repo"
    repo.mkdir()
    run_adapter(repo, {"GRAPHIFY_ADAPTER": "1",
                       "GRAPHIFY_CMD": "definitely-not-a-real-binary",
                       "GRAPHIFY_ALLOW_CMD_OVERRIDE": "1"})
    ignore = repo / "Generated" / "graphify" / ".gitignore"
    assert ignore.is_file(), "engine output directory left committable"
    assert ignore.read_text().strip().endswith("*")


def test_failed_engine_run_does_not_republish_stale_records(tmp_path):
    """A failed run must emit NOTHING, not the previous run's symbols.

    Without clearing the output dir and returning False on a non-zero exit, find_graph_json()
    picks up the last successful run's graph.json and re-emits it stamped with the CURRENT
    engine version -- stale citations that nothing downstream can detect.
    """
    repo = tmp_path / "repo"
    repo.mkdir()
    stale_dir = repo / "Generated" / "graphify" / "graphify-out"
    stale_dir.mkdir(parents=True)
    (stale_dir / "graph.json").write_text(json.dumps({
        "nodes": [{"id": 1, "name": "OLD_SYMBOL_from_last_week", "type": "function",
                   "path": "old.py", "line": 5}],
        "edges": [],
    }))
    failing = _stub_engine(tmp_path, "import sys\nsys.exit(3)\n")
    result = run_adapter(repo, {"GRAPHIFY_ADAPTER": "1",
                                "GRAPHIFY_CMD": f"{sys.executable} {failing}",
                                "GRAPHIFY_ALLOW_CMD_OVERRIDE": "1"})
    assert result.returncode == 0
    assert result.stdout == "", f"stale records republished: {result.stdout!r}"
    assert "OLD_SYMBOL_from_last_week" not in result.stdout
    assert "ENGINE FAILED" in result.stderr


def test_successful_run_does_not_inherit_previous_output(tmp_path):
    """The output dir is cleared each run, so a fresh graph fully replaces the old one."""
    repo = tmp_path / "repo"
    repo.mkdir()
    stale_dir = repo / "Generated" / "graphify" / "graphify-out"
    stale_dir.mkdir(parents=True)
    (stale_dir / "graph.json").write_text(json.dumps({
        "nodes": [{"id": 9, "name": "STALE", "type": "function",
                   "path": "old.py", "line": 5}], "edges": []}))
    fresh = {"nodes": [{"id": 1, "name": "FRESH", "type": "function",
                        "path": "new.py", "line": 11}], "edges": []}
    stub = _stub_engine(tmp_path,
        "import json,sys,pathlib\n"
        "out = pathlib.Path(sys.argv[2]) / 'graphify-out'\n"
        "out.mkdir(parents=True, exist_ok=True)\n"
        f"(out/'graph.json').write_text(json.dumps({json.dumps(fresh)}))\n")
    result = run_adapter(repo, {"GRAPHIFY_ADAPTER": "1",
                                "GRAPHIFY_CMD": f"{sys.executable} {stub}",
                                "GRAPHIFY_ALLOW_CMD_OVERRIDE": "1"})
    assert result.returncode == 0, result.stderr
    identifiers = [json.loads(line)["identifier"] for line in result.stdout.splitlines()]
    assert identifiers == ["FRESH"]
    assert "STALE" not in result.stdout


# ─── malformed configuration must not raise ─────────────────────────────────

@pytest.mark.parametrize("env,needle", [
    ({"GRAPHIFY_TIMEOUT": "15m"}, "not an integer"),
    ({"GRAPHIFY_TIMEOUT": ""}, "not an integer"),
    ({"GRAPHIFY_ARGS": "--filter 'unclosed"}, "not parseable"),
    ({"GRAPHIFY_CMD": "'unclosed"}, "not parseable"),
])
def test_malformed_env_config_skips_cleanly(tmp_path, env, needle):
    """Docstring guarantee: always exits 0, diagnostics on stderr -- never a traceback."""
    overrides = {"GRAPHIFY_ADAPTER": "1", "GRAPHIFY_CMD": f"{sys.executable} -c pass",
                 "GRAPHIFY_ALLOW_CMD_OVERRIDE": "1"}
    overrides.update(env)
    result = run_adapter(tmp_path, overrides)
    assert result.returncode == 0, result.stderr
    assert result.stdout == ""
    assert "Traceback" not in result.stderr
    assert needle in result.stderr


# ---------------------------------------------------------------------------
# Independent test-report fixes (2026-08-15): vendor exclusion, leading-dot
# identifiers, engine Python floor
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("path,expected", [
    ("src/main/webapp/swagger-ui/swagger-ui.js", True),
    ("node_modules/lodash/index.js", True),
    ("web/static/app.min.js", True),
    ("web/static/swagger-ui-bundle.js", True),
    ("target/classes/Foo.java", True),
    ("build/generated/Bar.kt", True),
    (".venv/lib/site-packages/x.py", True),
    ("src/main/java/App.java", False),
    ("distribution/notes.md", False),      # `dist` must match whole segments only
    ("outline/models.py", False),          # `out` must match whole segments only
    ("src/builders/factory.py", False),    # `build` must not match substrings
])
def test_vendor_re_matches_segments_not_substrings(path, expected):
    assert adapter.is_vendored(path) is expected


def test_vendored_node_records_excluded_and_counted():
    nodes = [
        {"id": "a", "label": "AuthorizeBtn()", "_callable": True,
         "source_file": "src/main/webapp/swagger-ui/swagger-ui.js",
         "source_location": "L8", "confidence": "EXTRACTED"},
        {"id": "b", "label": "realHandler()", "_callable": True,
         "source_file": "src/service/Real.java",
         "source_location": "L10", "confidence": "EXTRACTED"},
    ]
    counters = {"nodes_unparseable": 0, "nodes_missing_fields": 0,
                "inferred_to_sidecar": 0, "ambiguous_dropped": 0}
    records, sidecar = adapter.map_nodes(nodes, Path("/repo"), "graphifyy==test", counters)
    assert [r["path"] for r in records] == ["src/service/Real.java"]
    assert counters["vendor_excluded"] == 1
    assert not sidecar


def test_vendored_edge_records_excluded_and_counted():
    counters = {"edges_unparseable": 0, "edges_non_dependency": 0,
                "edges_unresolvable": 0, "inferred_to_sidecar": 0,
                "ambiguous_dropped": 0, "node_index": {}}
    edges = [
        {"source": "x", "target": "y", "relation": "imports",
         "source_file": "node_modules/left-pad/index.js", "source_location": "L1",
         "confidence": "EXTRACTED"},
        {"source": "m", "target": "n", "relation": "imports",
         "source_file": "src/app.py", "source_location": "L3",
         "confidence": "EXTRACTED"},
    ]
    records, _ = adapter.map_edges(edges, counters, "graphifyy==test", Path("/repo"))
    assert [r["path"] for r in records] == ["src/app.py"]
    assert counters["vendor_excluded"] == 1


def test_leading_dots_stripped_from_identifiers():
    """graphifyy labels methods `.main()`; the human-facing column must not show the dot."""
    nodes = [{"id": "a", "label": ".main()", "_callable": True,
              "source_file": "src/app.py", "source_location": "L5",
              "confidence": "EXTRACTED"}]
    counters = {"nodes_unparseable": 0, "nodes_missing_fields": 0,
                "inferred_to_sidecar": 0, "ambiguous_dropped": 0}
    records, _ = adapter.map_nodes(nodes, Path("/repo"), "graphifyy==test", counters)
    assert records[0]["identifier"] == "main()"

    edge_counters = {"edges_unparseable": 0, "edges_non_dependency": 0,
                     "edges_unresolvable": 0, "inferred_to_sidecar": 0,
                     "ambiguous_dropped": 0,
                     "node_index": {"a": {"name": ".caller()", "path": "src/app.py",
                                          "line": 5, "confidence": "EXTRACTED"},
                                    "b": {"name": ".callee()", "path": "src/lib.py",
                                          "line": 9, "confidence": "EXTRACTED"}}}
    edges = [{"source": "a", "target": "b", "relation": "calls",
              "source_file": "src/app.py", "source_location": "L6",
              "confidence": "EXTRACTED"}]
    records, _ = adapter.map_edges(edges, edge_counters, "graphifyy==test", Path("/repo"))
    assert records[0]["identifier"] == "caller() -> callee()"


def test_python_floor_skips_cleanly_with_actionable_message(tmp_path, monkeypatch, capsys):
    """Under a pre-3.10 interpreter the packaged path must state the floor and skip —
    not surface pip's 200-line version-skew noise that never names the problem."""
    (tmp_path / "app.py").write_text("x = 1\n")
    monkeypatch.setattr(adapter.sys, "version_info", (3, 9, 6))
    monkeypatch.setattr(adapter.sys, "argv", ["extract_graphify.py", str(tmp_path)])
    for var in ("GRAPHIFY_CMD", "GRAPHIFY_ALLOW_CMD_OVERRIDE", "GRAPHIFY_SKIP_PREFLIGHT"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("GRAPHIFY_ADAPTER", "1")
    rc = adapter.main()
    captured = capsys.readouterr()
    assert rc == 0
    assert captured.out == ""                      # no records emitted
    assert ">= 3.10" in captured.err               # the floor is stated
    assert "3.9" in captured.err                   # the running version is named
    assert "graphifyy==0.9.43" in captured.err     # the remediation actually works
