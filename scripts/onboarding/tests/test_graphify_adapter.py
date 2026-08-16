"""
tests/test_graphify_adapter.py — Tests for the optional Graphify adapter.

Installing the engine is the opt-in, so the adapter is ON by default and
GRAPHIFY_ADAPTER is a kill switch that fails CLOSED. It must NEVER be load-bearing:
  1. Flag set to a non-affirmative (e.g. `0`, `disabled`, or a typo): clean skip,
     exit 0, zero stdout records. Unset means ENABLED, and an affirmative
     (`1`/`true`/`yes`/`on`, any case, surrounding whitespace ignored) also enables.
  2. Flag on, engine not installed — or no interpreter at the engine's Python
     floor: clean skip, exit 0, zero stdout records.
  3. Mapper: graph nodes/edges -> contract records {path, line, kind, identifier}
     with additive {engine, confidence}; INFERRED -> sidecar; AMBIGUOUS -> dropped;
     unknown kinds counted, never emitted.
  4. Credential env sanitization strips provider prefixes, a credential-shaped
     suffix regex, and an exact-name denylist (SSH_AUTH_SOCK, proxies, NETRC,
     bare API_KEY). It is best-effort defence in depth, NOT the egress guarantee --
     $HOME-file credentials stay reachable and there is no network sandbox. The
     gated code-only invocation (item 5) is what the posture rests on.
  5. The code-only invocation is GATED, not merely defaulted: GRAPHIFY_SUBCOMMAND
     and GRAPHIFY_ARGS are ignored unless GRAPHIFY_ALLOW_LLM_PATH=1, and when the
     gate is set the log withdraws the code-only claim for that run.
  6. Always exits 0 -- malformed env, an unwritable repo, and a graph.json that is
     not an object all skip cleanly rather than raising.

Mapper tests import the module directly (no graphifyy install required), and the
end-to-end tests drive a stub engine through an explicitly gated GRAPHIFY_CMD, so
this file runs green on any machine — the removal drill, continuously proven.
"""
from __future__ import annotations

import importlib.util
import json
import os
import shutil
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
    # Drop the whole GRAPHIFY_ namespace, not just GRAPHIFY_ADAPTER. With the double gates
    # an exported knob from the developer's shell changes outcomes rather than just being
    # untidy: GRAPHIFY_ALLOW_CMD_OVERRIDE=1 makes test_cmd_override_ignored_without_allow_gate
    # assert the opposite of what it means, and GRAPHIFY_ALLOW_LLM_PATH=1 does the same to
    # the code-only gate tests. The person most likely to have those exported is whoever is
    # working on the adapter.
    env = {k: v for k, v in os.environ.items() if not k.startswith("GRAPHIFY_")}
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


def write_stub_engine(tmp_path: Path, records_json: str = "{}") -> str:
    """A stub engine that accepts ANY subcommand and writes `records_json` as the graph.

    Deliberately does not assert on argv[1]: tests that exercise the LLM-path gate need to
    drive a non-`update` subcommand, and the invocation itself is asserted from the
    adapter's own "engine invocation" log line rather than from inside the stub.
    """
    stub = tmp_path / "stub_engine_any.py"
    stub.write_text(
        "import json,sys,pathlib\n"
        "out = pathlib.Path(sys.argv[2]) / 'graphify-out'\n"
        "out.mkdir(parents=True, exist_ok=True)\n"
        f"(out/'graph.json').write_text({records_json!r})\n"
    )
    return f"{sys.executable} {stub}"


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
    nodes = [{"id": 1, "name": "relFn", "type": "function",
              "path": str(tmp_path / "pkg" / "mod.py"), "line": 3}]
    records, _ = adapter.map_nodes(nodes, tmp_path, "e", fresh_counters())
    assert records[0]["path"] == "pkg/mod.py"


def test_map_nodes_confidence_gate(tmp_path):
    nodes = [
        {"id": 1, "name": "alphaFn", "type": "function", "path": "a.py", "line": 1,
         "confidence": "EXTRACTED"},
        {"id": 2, "name": "betaFn", "type": "function", "path": "b.py", "line": 1,
         "confidence": "INFERRED"},
        {"id": 3, "name": "gammaFn", "type": "function", "path": "c.py", "line": 1,
         "confidence": "AMBIGUOUS"},
    ]
    counters = fresh_counters()
    records, sidecar = adapter.map_nodes(nodes, tmp_path, "e", counters)
    assert [r["identifier"] for r in records] == ["alphaFn"]
    assert [r["identifier"] for r in sidecar] == ["betaFn"]
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
        [{"id": 1, "name": "presentFn", "type": "function", "path": "a.py", "line": 1}],
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
    ({"GRAPHIFY_TIMEOUT": "0"}, "not a positive"),
    ({"GRAPHIFY_TIMEOUT": "-30"}, "not a positive"),
    # GRAPHIFY_ARGS only reaches shlex once the LLM-path gate is set; without the gate it
    # is ignored (covered by test_llm_path_knobs_ignored_without_gate).
    ({"GRAPHIFY_ARGS": "--filter 'unclosed", "GRAPHIFY_ALLOW_LLM_PATH": "1"},
     "not parseable"),
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


# ─── the code-only invocation is GATED, not merely defaulted ────────────────

@pytest.mark.parametrize("knob,value", [
    ("GRAPHIFY_SUBCOMMAND", "extract"),
    ("GRAPHIFY_ARGS", "--cluster"),
])
def test_llm_path_knobs_ignored_without_gate(tmp_path, knob, value):
    """The code-only invocation IS the egress guarantee, so it must not be one ungated
    env var away from false.

    Before the gate, GRAPHIFY_SUBCOMMAND=extract reached the engine's LLM path while the
    invocation log still announced "code-only path". Now the knob is ignored, said so
    loudly, and the recorded argv is still `update ... --no-cluster`.
    """
    stub = write_stub_engine(tmp_path, records_json="{}")
    result = run_adapter(tmp_path, stub_env(stub, **{knob: value}))
    assert result.returncode == 0, result.stderr
    assert f"ignoring ['{knob}']" in result.stderr
    assert "GRAPHIFY_ALLOW_LLM_PATH=1 is not set" in result.stderr
    invocation = [l for l in result.stderr.splitlines() if "engine invocation" in l]
    assert invocation and "code-only path" in invocation[0]
    # Split off the log prefix before searching for the rejected value -- "extract" is a
    # substring of the "[extract_graphify]" prefix on every line this module logs.
    argv = invocation[0].split("): ", 1)[1]
    assert value not in argv
    assert " update " in argv and "--no-cluster" in argv


def test_llm_path_knobs_honoured_with_gate_withdraw_the_claim(tmp_path):
    """With the gate explicitly set the override is honoured -- and the log must STOP
    claiming the code-only guarantee for that run."""
    stub = write_stub_engine(tmp_path, records_json="{}")
    result = run_adapter(tmp_path, stub_env(stub, GRAPHIFY_SUBCOMMAND="extract",
                                            GRAPHIFY_ALLOW_LLM_PATH="1"))
    assert result.returncode == 0, result.stderr
    assert "code-only invocation OVERRIDDEN" in result.stderr
    assert "DOES NOT APPLY to this run" in result.stderr
    invocation = [l for l in result.stderr.splitlines() if "engine invocation" in l]
    assert invocation and "OVERRIDDEN path" in invocation[0]
    assert "code-only path" not in invocation[0]


# ─── one shared "operator named their own engine" predicate ─────────────────

@pytest.mark.parametrize("cmd_value", ["", None])
def test_empty_cmd_override_does_not_skip_the_version_floor(tmp_path, cmd_value):
    """main() and run_engine() must agree on what counts as a custom engine.

    They used to disagree: GRAPHIFY_CMD="" plus the allow gate made main() skip the
    packaged version floor and stamp provenance `graphifyy==unknown`, while run_engine
    fell back to the REAL packaged engine -- a run whose provenance was a lie.
    """
    env = {"GRAPHIFY_ADAPTER": "1", "GRAPHIFY_ALLOW_CMD_OVERRIDE": "1"}
    if cmd_value is not None:
        env["GRAPHIFY_CMD"] = cmd_value
    result = run_adapter(tmp_path, env)
    assert result.returncode == 0, result.stderr
    assert "packaged version floor skipped" not in result.stderr
    assert "graphifyy==unknown" not in result.stderr


def test_cmd_override_equal_to_default_does_not_skip_the_floor(tmp_path):
    """Setting GRAPHIFY_CMD to exactly the default string is not naming your own engine."""
    result = run_adapter(tmp_path, {"GRAPHIFY_ADAPTER": "1",
                                    "GRAPHIFY_ALLOW_CMD_OVERRIDE": "1",
                                    "GRAPHIFY_CMD": adapter.default_engine_cmd()})
    assert result.returncode == 0, result.stderr
    assert "packaged version floor skipped" not in result.stderr


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


def _clean_preflight_env(monkeypatch, repo: Path):
    monkeypatch.setattr(adapter.sys, "argv", ["extract_graphify.py", str(repo)])
    for var in ("GRAPHIFY_CMD", "GRAPHIFY_ALLOW_CMD_OVERRIDE", "GRAPHIFY_SKIP_PREFLIGHT",
                "GRAPHIFY_PYTHON"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("GRAPHIFY_ADAPTER", "1")


def test_python_floor_skips_cleanly_with_actionable_message(tmp_path, monkeypatch, capsys):
    """When NO interpreter at or above the engine floor can be found, state the floor and
    skip — not pip's 200-line version-skew noise that never names the problem.

    `find_modern_python` is stubbed to None so this exercises the give-up branch on any
    machine. Without that stub the probe finds a real python3.13 here and the run falls
    through to the "not installed" path, which happens to contain ">= 3.10" (via PIN_HINT)
    and "3.9" (via the interpreter-resolution log) — so the assertions below would pass
    while covering nothing.
    """
    (tmp_path / "app.py").write_text("x = 1\n")
    monkeypatch.setattr(adapter.sys, "version_info", (3, 9, 6))
    monkeypatch.setattr(adapter, "find_modern_python", lambda: None)
    monkeypatch.setattr(adapter, "_ENGINE_PYTHON_CACHE", {})
    _clean_preflight_env(monkeypatch, tmp_path)
    rc = adapter.main()
    captured = capsys.readouterr()
    assert rc == 0
    assert captured.out == ""                      # no records emitted
    assert ">= 3.10" in captured.err               # the floor is stated
    assert "3.9" in captured.err                   # the running version is named
    assert "no suitable interpreter was found" in captured.err
    assert "GRAPHIFY_PYTHON" in captured.err       # the escape hatch is named
    assert "graphifyy==0.9.43" in captured.err     # the remediation actually works


def test_engine_floor_is_checked_against_the_engine_interpreter(tmp_path, monkeypatch,
                                                                capsys):
    """The floor must be checked against the interpreter that RUNS the engine.

    Phase 1.5 invokes this adapter as bare `python3` — 3.9.6 on a stock macOS box, the
    floor this directory declares. Checking the ADAPTER's interpreter made the default-on
    feature unreachable through the only path that invokes it: the adapter returned 0
    before ever looking for the engine, no matter what the operator installed.
    """
    modern = next((shutil.which(n) for n in ("python3.13", "python3.12", "python3.11",
                                             "python3.10")
                   if shutil.which(n)), None)
    if modern is None:
        pytest.skip("no 3.10+ interpreter on PATH other than the test runner")
    (tmp_path / "app.py").write_text("x = 1\n")
    monkeypatch.setattr(adapter.sys, "version_info", (3, 9, 6))
    _clean_preflight_env(monkeypatch, tmp_path)
    # A real 3.10+ interpreter, named explicitly, and NOT sys.executable -- so its version
    # is probed for real rather than read from the monkeypatched sys.version_info. It has
    # no graphifyy, so the run must get PAST the Python floor and fail on the ENGINE.
    monkeypatch.setenv("GRAPHIFY_PYTHON", modern)
    rc = adapter.main()
    captured = capsys.readouterr()
    assert rc == 0
    assert "no suitable interpreter was found" not in captured.err
    assert "not installed" in captured.err


def test_engine_python_probe_finds_a_modern_interpreter(monkeypatch):
    """Fallback path: no GRAPHIFY_PYTHON, adapter under 3.9 — probe PATH rather than give
    up, so an operator who installed the engine into python3.13 needs no extra config."""
    monkeypatch.setattr(adapter.sys, "version_info", (3, 9, 6))
    monkeypatch.setattr(adapter, "_ENGINE_PYTHON_CACHE", {})
    monkeypatch.delenv("GRAPHIFY_PYTHON", raising=False)
    monkeypatch.setattr(adapter, "find_modern_python", lambda: "/fake/python3.13")
    assert adapter.engine_python() == "/fake/python3.13"
    assert adapter.default_engine_cmd() == "/fake/python3.13 -m graphify"


def test_engine_python_explicit_value_wins(monkeypatch):
    monkeypatch.setenv("GRAPHIFY_PYTHON", "  /opt/py313  ")
    assert adapter.engine_python() == "/opt/py313"


# ─── stale derived artifacts (not just the engine's own output) ─────────────

def _seed_stale_artifacts(repo: Path) -> Path:
    out = repo / "Generated" / "graphify"
    out.mkdir(parents=True, exist_ok=True)
    (out / "CODE_GRAPH.jsonl").write_text(
        '{"path":"old.py","line":1,"kind":"dependency","identifier":"STALE -> STALE"}\n')
    (out / "NEEDS_VERIFICATION.jsonl").write_text(
        '{"path":"old.py","line":1,"kind":"module","identifier":"STALE_INFERRED"}\n')
    (out / "CODE_INDEX_RECORDS.jsonl").write_text(
        '{"path":"old.py","line":1,"kind":"module","identifier":"STALE_MIRROR"}\n')
    return out


def test_clean_run_with_no_edges_leaves_no_stale_code_graph(tmp_path):
    """A run that honestly produces zero dependency edges must not leave the PREVIOUS
    run's CODE_GRAPH.jsonl on disk looking current.

    Both derived files are written conditionally, so clearing only the engine's own output
    left them behind stamped with the previous run's engine version — the same stale
    republishing that was fixed for stdout, displaced onto the on-disk artifacts.
    NEEDS_VERIFICATION.jsonl is the list an operator is told to check before promoting
    records, so a stale one is actively misleading.
    """
    repo = tmp_path / "repo"
    repo.mkdir()
    out = _seed_stale_artifacts(repo)
    graph = {"nodes": [{"id": 1, "name": "fresh", "type": "function",
                        "path": "app.py", "line": 3}],
             "edges": []}
    stub = write_stub_engine(tmp_path, records_json=json.dumps(graph))
    result = run_adapter(repo, stub_env(stub))
    assert result.returncode == 0, result.stderr
    assert [json.loads(l)["identifier"] for l in result.stdout.splitlines()] == ["fresh"]
    assert not (out / "CODE_GRAPH.jsonl").exists()
    assert not (out / "NEEDS_VERIFICATION.jsonl").exists()


def test_failed_run_leaves_no_stale_derived_artifacts(tmp_path):
    """Same guarantee on the failure path: a non-zero engine exit clears everything."""
    repo = tmp_path / "repo"
    repo.mkdir()
    out = _seed_stale_artifacts(repo)
    failing = tmp_path / "failing_engine.py"
    failing.write_text("import sys\nsys.exit(3)\n")
    result = run_adapter(repo, stub_env(f"{sys.executable} {failing}"))
    assert result.returncode == 0, result.stderr
    assert result.stdout == ""
    for name in ("CODE_GRAPH.jsonl", "NEEDS_VERIFICATION.jsonl",
                 "CODE_INDEX_RECORDS.jsonl"):
        assert not (out / name).exists(), name


def test_gitignore_survives_the_clear(tmp_path):
    """clear_engine_output must not delete the .gitignore the adapter itself writes."""
    repo = tmp_path / "repo"
    repo.mkdir()
    out = _seed_stale_artifacts(repo)
    graph = {"nodes": [{"id": 1, "name": "fresh", "type": "function",
                        "path": "app.py", "line": 3}], "edges": []}
    stub = write_stub_engine(tmp_path, records_json=json.dumps(graph))
    result = run_adapter(repo, stub_env(stub))
    assert result.returncode == 0, result.stderr
    assert (out / ".gitignore").is_file()
    assert (out / ".gitignore").read_text().rstrip().endswith("*")


# ─── provenance survives the Phase 1.5 boundary ────────────────────────────

def test_emitted_records_are_mirrored_with_provenance(tmp_path):
    """The Phase 1.5 materialiser keeps only {path,line,kind,identifier}, marks every row
    VERIFIED, and then rm -f's the extractor file — so without this mirror nothing records
    which CODE_INDEX.md rows came from a third-party engine rather than our extractors."""
    repo = tmp_path / "repo"
    repo.mkdir()
    graph = {"nodes": [{"id": 1, "name": "get_user", "type": "function",
                        "path": "app/api.py", "line": 12}],
             "edges": []}
    stub = write_stub_engine(tmp_path, records_json=json.dumps(graph))
    result = run_adapter(repo, stub_env(stub, GRAPHIFY_ENGINE_ID="graphifyy==testpin"))
    assert result.returncode == 0, result.stderr
    mirror = repo / "Generated" / "graphify" / "CODE_INDEX_RECORDS.jsonl"
    assert mirror.is_file()
    records = [json.loads(l) for l in mirror.read_text().splitlines()]
    assert [r["identifier"] for r in records] == ["get_user"]
    assert records[0]["engine"] == "graphifyy==testpin"
    assert records[0]["confidence"] == "EXTRACTED"
    # and the mirror matches exactly what went to stdout
    assert records == [json.loads(l) for l in result.stdout.splitlines()]


# ─── identifier cleaning ───────────────────────────────────────────────────

@pytest.mark.parametrize("raw,expected", [
    (".main()", "main()"),
    ("main()", "main()"),
    ("..utils", ".utils"),      # relative imports keep their remaining dots
    ("...pkg", "..pkg"),
    ("  .run  ", "run"),
    ("...", ""),                # nothing but dots carries no name -- caller drops it
    ("..", ""),
    (".", ""),
])
def test_clean_identifier_strips_at_most_one_leading_dot(raw, expected):
    """`lstrip('.')` removed EVERY leading dot, so the Python relative import `..utils`
    became `utils` — a different module."""
    assert adapter.clean_identifier(raw) == expected


def test_dots_only_node_label_is_dropped_not_emitted_blank(tmp_path):
    """The emptiness guard runs on the RAW label, so "..." passed it and then stripped to
    "" — defeating the guard whose whole job is keeping unnamed symbols out of the index."""
    counters = fresh_counters()
    nodes = [{"id": 1, "name": "...", "type": "function", "path": "a.py", "line": 4},
             {"id": 2, "name": ".okayFn()", "type": "function", "path": "a.py", "line": 9}]
    records, _ = adapter.map_nodes(nodes, Path("/repo"), "graphifyy==test", counters)
    assert [r["identifier"] for r in records] == ["okayFn()"]
    assert counters["nodes_missing_fields"] == 1


def test_dots_only_edge_endpoint_is_dropped_not_emitted_as_arrow(tmp_path):
    """Two dots-only labels used to produce the identifier " -> "."""
    counters = {"edges_unparseable": 0, "edges_non_dependency": 0,
                "edges_unresolvable": 0, "inferred_to_sidecar": 0,
                "ambiguous_dropped": 0,
                "node_index": {"a": {"name": "...", "path": "src/app.py", "line": 5,
                                     "confidence": "EXTRACTED"},
                               "b": {"name": "...", "path": "src/lib.py", "line": 9,
                                     "confidence": "EXTRACTED"}}}
    edges = [{"source": "a", "target": "b", "relation": "calls",
              "source_file": "src/app.py", "source_location": "L6"}]
    records, _ = adapter.map_edges(edges, counters, "graphifyy==test", Path("/repo"))
    assert records == []
    assert counters["edges_unresolvable"] == 1


# ─── confidence diagnostic: expected baseline vs actual drift ──────────────

def test_all_absent_confidence_is_reported_as_expected_not_a_warning(tmp_path):
    """On graphifyy==0.9.43 every node lacks the field, so warning on a non-zero count
    warned on every clean run at a count equal to the whole node set — telling the
    operator the schema had drifted from the very baseline the README documents."""
    repo = tmp_path / "repo"
    repo.mkdir()
    graph = {"nodes": [{"id": 1, "name": "a", "type": "function", "path": "a.py", "line": 1},
                       {"id": 2, "name": "b", "type": "function", "path": "b.py", "line": 2}],
             "edges": []}
    stub = write_stub_engine(tmp_path, records_json=json.dumps(graph))
    result = run_adapter(repo, stub_env(stub))
    assert result.returncode == 0, result.stderr
    assert "expected baseline" in result.stderr
    # Scoped to the confidence diagnostic by its unique phrase: a bare "WARNING" check
    # would match the (correct) gated-GRAPHIFY_CMD warning every stub-engine test emits,
    # and a substring check on "confidence" also matches this test's own tmp_path.
    assert "schema-drift signal" not in result.stderr


def test_partial_absent_confidence_is_the_warning(tmp_path):
    """A PARTIAL split is the only shape that actually signals drift."""
    repo = tmp_path / "repo"
    repo.mkdir()
    graph = {"nodes": [
        {"id": 1, "name": "a", "type": "function", "path": "a.py", "line": 1},
        {"id": 2, "name": "b", "type": "function", "path": "b.py", "line": 2,
         "confidence": "EXTRACTED"}],
        "edges": []}
    stub = write_stub_engine(tmp_path, records_json=json.dumps(graph))
    result = run_adapter(repo, stub_env(stub))
    assert result.returncode == 0, result.stderr
    assert "WARNING" in result.stderr
    assert "1 of 2" in result.stderr


def test_dependency_edges_do_not_inflate_the_confidence_count(tmp_path):
    """Edges carry no confidence key BY DESIGN — that is why weakest_confidence exists —
    so counting them fired the alarm at 1,803-of-3,159 magnitude on a clean run."""
    counters = fresh_counters()
    counters["confidence_present"] = 0
    nodes = [{"id": 1, "name": "a", "type": "function", "path": "a.py", "line": 1},
             {"id": 2, "name": "b", "type": "function", "path": "b.py", "line": 2}]
    adapter.map_nodes(nodes, Path("/repo"), "graphifyy==test", counters)
    before = counters["confidence_absent"]
    edges = [{"source": 1, "target": 2, "relation": "import",
              "source_file": "a.py", "source_location": "L1"}]
    adapter.map_edges(edges, counters, "graphifyy==test", Path("/repo"))
    assert counters["confidence_absent"] == before == 2


# ─── guarantee 6: always exit 0 ────────────────────────────────────────────

def test_unwritable_repo_skips_cleanly_instead_of_crashing(tmp_path):
    """An unguarded out_dir.mkdir() raised PermissionError and exited 1. The Phase 1.5 hook
    ends in `|| true`, so that traceback would be buried in a log file and the conversion
    would silently lose the adapter with no diagnosis."""
    repo = tmp_path / "repo"
    (repo / "Generated").mkdir(parents=True)
    (repo / "Generated").chmod(0o500)          # read+execute, not writable
    try:
        result = run_adapter(repo, {"GRAPHIFY_ADAPTER": "1",
                                    "GRAPHIFY_SKIP_PREFLIGHT": "1"})
        assert result.returncode == 0, result.stderr
        assert result.stdout == ""
        assert "Traceback" not in result.stderr
        assert "cannot create" in result.stderr
    finally:
        (repo / "Generated").chmod(0o700)


@pytest.mark.parametrize("payload", ['[{"nodes": []}]', '"a string"', "42", "null"])
def test_non_object_graph_json_skips_cleanly(tmp_path, payload):
    """A graph.json whose top level is not an object must not crash the adapter.

    `graph.get("nodes")` was called before anything checked the container, so a top-level
    JSON array raised AttributeError and exited 1 — through the real __main__ path, with a
    traceback the Phase 1.5 hook's `|| true` would bury in a log file.
    """
    repo = tmp_path / "repo"
    repo.mkdir()
    stub = write_stub_engine(tmp_path, records_json=payload)
    result = run_adapter(repo, stub_env(stub))
    assert result.returncode == 0, result.stderr
    assert result.stdout == ""
    assert "Traceback" not in result.stderr
    assert "UNRECOGNIZED SCHEMA" in result.stderr or "no records emitted" in result.stderr


def test_non_list_edges_maps_nodes_and_does_not_crash(tmp_path):
    """`edges` arriving as an object must degrade to nodes-only, not raise."""
    repo = tmp_path / "repo"
    repo.mkdir()
    graph = {"nodes": [{"id": 1, "name": "okayFn", "type": "function",
                        "path": "a.py", "line": 2}],
             "edges": {"not": "a list"}}
    stub = write_stub_engine(tmp_path, records_json=json.dumps(graph))
    result = run_adapter(repo, stub_env(stub))
    assert result.returncode == 0, result.stderr
    assert "Traceback" not in result.stderr
    assert [json.loads(l)["identifier"] for l in result.stdout.splitlines()] == ["okayFn"]


# ---------------------------------------------------------------------------
# Line snap (2026-08-15): align engine declaration-start citations with the
# T3 exact-line overlap contract (found by the deep e2e conversion test —
# 1,751 of 1,774 citation-gate failures were annotation-line citations)
# ---------------------------------------------------------------------------

def _snap_counters():
    return {"nodes_unparseable": 0, "nodes_missing_fields": 0,
            "inferred_to_sidecar": 0, "ambiguous_dropped": 0}


def _java_node(line, label=".run()"):
    return [{"id": "a", "label": label, "_callable": True,
             "source_file": "src/Main.java", "source_location": f"L{line}",
             "confidence": "EXTRACTED"}]


def test_annotation_line_citation_snaps_to_naming_line(tmp_path):
    src = tmp_path / "src" / "Main.java"
    src.parent.mkdir()
    src.write_text("package x;\nclass Main {\n  @Override\n  public void run() {\n  }\n}\n")
    counters = _snap_counters()
    records, _ = adapter.map_nodes(_java_node(3), tmp_path, "graphifyy==test", counters)
    assert records[0]["line"] == 4          # snapped @Override -> declaration
    assert counters["line_snapped"] == 1


def test_snap_noop_when_already_on_naming_line(tmp_path):
    src = tmp_path / "src" / "Main.java"
    src.parent.mkdir()
    src.write_text("package x;\nclass Main {\n  public void run() {\n  }\n}\n")
    counters = _snap_counters()
    records, _ = adapter.map_nodes(_java_node(3), tmp_path, "graphifyy==test", counters)
    assert records[0]["line"] == 3
    assert "line_snapped" not in counters and "line_snap_miss" not in counters


def test_snap_miss_routes_to_sidecar_not_the_index(tmp_path):
    """An identifier that cannot be found at/near its own citation is by definition
    unverified — it goes to the sidecar with the engine's original line, never the
    gate-verified index (where it would be a guaranteed citation failure)."""
    src = tmp_path / "src" / "Main.java"
    src.parent.mkdir()
    src.write_text("\n".join(["// filler"] * 20) + "\n")
    counters = _snap_counters()
    records, sidecar = adapter.map_nodes(_java_node(3), tmp_path, "graphifyy==test", counters)
    assert records == []
    assert sidecar[0]["line"] == 3          # engine's line preserved for human judgment
    assert counters["line_snap_miss"] == 1
    assert counters["snap_miss_to_sidecar"] == 1


def test_missing_file_keeps_line_but_empty_file_routes_to_sidecar(tmp_path):
    """A MISSING file keeps the engine's line unjudged (the adapter rules only on
    content it read; absence is the gate's jurisdiction). An EMPTY file was read
    successfully and provably has no verifying line — sidecar (measured: 48 engine
    records for empty __init__.py files were guaranteed gate failures)."""
    counters = _snap_counters()
    records, sidecar = adapter.map_nodes(_java_node(3), tmp_path, "graphifyy==test", counters)
    assert records[0]["line"] == 3           # no src/Main.java on disk -> unjudged
    assert sidecar == []

    empty = tmp_path / "src" / "Empty.java"
    empty.parent.mkdir(exist_ok=True)
    empty.write_text("")
    nodes = [{"id": "e", "label": ".run()", "_callable": True,
              "source_file": "src/Empty.java", "source_location": "L1",
              "confidence": "EXTRACTED"}]
    counters = _snap_counters()
    records, sidecar = adapter.map_nodes(nodes, tmp_path, "graphifyy==test", counters)
    assert records == [] and len(sidecar) == 1
    assert counters["unverifiable_file_to_sidecar"] == 1


def test_snap_window_is_bounded(tmp_path):
    """The naming line 11+ lines away is OUTSIDE the window — do not snap to it:
    a distant match is more plausibly a different symbol than this declaration."""
    src = tmp_path / "src" / "Main.java"
    src.parent.mkdir()
    body = ["@A"] * 12 + ["public void run() {", "}"]
    src.write_text("\n".join(["package x;", "class Main {"] + body) + "\n")
    counters = _snap_counters()
    records, sidecar = adapter.map_nodes(_java_node(3), tmp_path, "graphifyy==test", counters)
    assert records == [] and sidecar[0]["line"] == 3
    assert counters["line_snap_miss"] == 1


@pytest.mark.parametrize("path,expected", [
    ("Generated/scripts/run_verify_citations.sh", True),
    ("Knowledge/CODE_INDEX.md", True),
    (".claude/agents/developer.md", True),
    ("CLAUDE.md", True),
    ("prompts/templates/AI Agents/X_AI_AGENT.md", True),
    ("BINDING.yml", True),
    ("src/main/java/App.java", False),
    ("src/KnowledgeService.java", False),      # segment match only, not substring
    ("app/GeneratedCode.py", False),
])
def test_framework_artifacts_excluded_from_engine_records(path, expected):
    """The conversion creates Generated/, Knowledge/, .claude/ etc. inside the target
    repo BEFORE Phase 1.5, and the engine indexes them as if they were the team's
    code (measured: 261 unverifiable records on a re-run). Knowledge-layer paths are
    excluded; real code whose names merely contain those words is not."""
    assert adapter.is_framework_artifact(path) is expected


def test_framework_artifact_node_records_excluded_and_counted(tmp_path):
    nodes = [
        {"id": "a", "label": "run_verify_citations.sh script", "_callable": False,
         "file_type": "code", "source_file": "Generated/scripts/run_verify_citations.sh",
         "source_location": "L1", "confidence": "EXTRACTED"},
        {"id": "b", "label": "realHandler()", "_callable": True,
         "source_file": "src/Real.java", "source_location": "L2",
         "confidence": "EXTRACTED"},
    ]
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "Real.java").write_text("class R {\n  void realHandler() {}\n}\n")
    counters = _snap_counters()
    records, _ = adapter.map_nodes(nodes, tmp_path, "graphifyy==test", counters)
    assert [r["path"] for r in records] == ["src/Real.java"]
    assert counters["framework_artifacts_excluded"] == 1


def test_file_node_dropped_so_it_cannot_claim_a_declaration_line(tmp_path):
    """The per-file node is not a symbol: dropped and counted, never scanned or sidecar'd.

    The token scan turned `ClientRestricted.java` into a citation of the line that
    declares the CLASS `ClientRestricted`, publishing one location as the definition of
    two symbols — 161 of the 164 duplicated path:line locations on the JAX-RS service
    were this exact pair. `Main` is kept to show only the filename label is affected.
    """
    src = tmp_path / "src"
    src.mkdir()
    (src / "ClientRestricted.java").write_text(
        "package x;\n\n@interface ClientRestricted {\n}\n")
    (src / "Main.java").write_text("package x;\nclass Main {\n  void run() {}\n}\n")
    nodes = [
        {"id": "f", "label": "ClientRestricted.java", "file_type": "code",
         "source_file": "src/ClientRestricted.java", "source_location": "L1"},
        {"id": "c", "label": "ClientRestricted", "_callable": True, "file_type": "code",
         "source_file": "src/ClientRestricted.java", "source_location": "L3"},
        {"id": "m", "label": "Main", "_callable": True, "file_type": "code",
         "source_file": "src/Main.java", "source_location": "L2"},
    ]
    counters = _snap_counters()
    records, sidecar = adapter.map_nodes(nodes, tmp_path, "graphifyy==test", counters)
    assert [(r["identifier"], r["line"]) for r in records] == \
        [("ClientRestricted", 3), ("Main", 2)]
    assert sidecar == []
    assert counters["file_nodes_not_symbols"] == 1


@pytest.mark.parametrize("path,identifier,expected", [
    ("services/nexus/nexus/s3/s3_async.py", "s3_async.py", True),
    ("src/main/java/com/ca/smws/Main.java", "Main.java", True),
    ("s3_async.py", "s3_async.py", True),
    ("scripts/run_local.sh", "run_local.sh script", True),   # bash_entrypoint 2nd node
    ("services/nexus/nexus/s3/s3_async.py", "_upload_file_async()", False),
    ("pom.xml", "sample-legacy-pom", False),        # a package, named in the file
    ("libs/campaign-lib/pyproject.toml", "campaign-lib", False),
    ("scripts/shared_script_lib.sh", "run_in_directory()", False),
])
def test_names_its_own_file_isolates_the_per_file_node(path, identifier, expected):
    """The predicate must catch filename labels and nothing else — package artifactIds
    and shell functions are named BY a line in their file and keep the token scan.

    graphifyy emits a SECOND per-file node for every shell script: a `bash_entrypoint`
    labelled "<basename> script" (measured on graphifyy==0.9.43 against a real
    run_local.sh fixture — id `scripts_run_local_sh__entry`). Exact equality against
    the bare basename alone did not catch it, so it fell through to the token scan and
    republished a header comment as its declaration line."""
    assert adapter.names_its_own_file(path, identifier) is expected


def test_gate_unverifiable_identifiers_route_to_sidecar(tmp_path):
    """`US` (stem shorter than 3) and `with()` (stopword) can never pass the T3
    gate's tokenizer regardless of citation correctness — quarantine, don't emit."""
    src = tmp_path / "src" / "E.java"
    src.parent.mkdir()
    src.write_text("enum D {\n  US,\n  EU\n}\n")
    nodes = [{"id": "a", "label": ".US", "_callable": False, "file_type": "code",
              "source_file": "src/E.java", "source_location": "L2",
              "confidence": "EXTRACTED"},
             {"id": "b", "label": ".with()", "_callable": True,
              "source_file": "src/E.java", "source_location": "L2",
              "confidence": "EXTRACTED"}]
    counters = _snap_counters()
    records, sidecar = adapter.map_nodes(nodes, tmp_path, "graphifyy==test", counters)
    assert records == []
    assert len(sidecar) == 2
    assert counters["gate_unverifiable_identifier"] == 2


def test_python_declarations_parses_raw_text_not_a_splitlines_roundtrip(tmp_path):
    """python_declarations() must ast.parse() the cached RAW text, not a
    text.splitlines() / "\\n".join(...) reconstruction of it.

    str.splitlines() treats a form feed (U+000C) as a line boundary; Python's own
    tokenizer/ast does not. A form feed inside a line-1 comment, followed by `def foo()`
    on line 2 of the ACTUAL file, stays on line 2 under ast.parse(raw_text) — but a
    splitlines()/join round-trip first splits that comment into two list entries at the
    form feed, then rejoins them with `\\n`, inserting a line break the raw file never
    had and shifting `def foo():` (and every line after it) down by one. The citation
    this function backs must match the file ast actually parsed, not a reconstruction —
    a real repo's form-feed or U+2028 byte would otherwise silently mis-cite every
    subsequent declaration in the file.
    """
    src = tmp_path / "module.py"
    src.write_bytes("# note\x0c\ndef foo():\n    pass\n".encode("utf-8"))
    cache: dict = {}
    declarations = adapter.python_declarations(tmp_path, "module.py", cache)
    assert declarations is not None, "module.py should parse cleanly"
    decl_line, _start, _end = declarations["foo"][0]
    assert decl_line == 2, (
        f"def foo(): is on line 2 of the raw file on disk; python_declarations "
        f"reported line {decl_line} — a splitlines()/join round-trip would report 3"
    )
