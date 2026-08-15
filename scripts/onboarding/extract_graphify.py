#!/usr/bin/env python3
"""
extract_graphify.py — OPTIONAL Graphify adapter for Phase 1.5 (Code Index Extraction).

Runs the graphifyy code-graph pass (deterministic tree-sitter AST, no LLM, no network)
and maps its graph output into the Phase 1.5 extraction contract:

    {"path": str, "line": int, "kind": str, "identifier": str}
    + additive fields: {"engine": str, "confidence": str}

Emitted kinds: handler (functions/methods), module (classes/modules/files),
endpoint (only if the engine ever exposes route semantics), dependency (import/call
edges, identifier "src -> dst"). Unknown node kinds are counted and reported on
stderr, never emitted.

DISABLED BY DEFAULT. This adapter is a tenant behind the extraction contract, not a
load-bearing dependency. Controls:

    GRAPHIFY_ADAPTER=1          enable (anything else: clean skip, exit 0)
    GRAPHIFY_CMD                override engine command (default: adapter's own
                                interpreter, "-m graphify")
    GRAPHIFY_SUBCOMMAND         engine subcommand (default "update" — the code-only,
                                no-LLM re-extraction path per the engine's own help)
    GRAPHIFY_ARGS               extra CLI args (default "--no-cluster")
    GRAPHIFY_TIMEOUT            engine timeout seconds (default 900)

Safety guarantees:
  1. The engine subprocess runs with a SANITIZED environment: every credential-ish
     variable (provider prefixes, *_API_KEY, *_BASE_URL, *_TOKEN, *_SECRET, AWS_*)
     is stripped, so the semantic/LLM pass cannot authenticate anywhere even if
     misconfigured. Code-only by construction.
  2. Engine output stays in $REPO_PATH/Generated/graphify/ (machine-local tier).
     Contract records go to stdout; INFERRED-confidence records go to the
     NEEDS_VERIFICATION.jsonl sidecar, never the index; AMBIGUOUS is dropped and counted.
  3. Requires graphifyy >= 0.9.24 (older builds silently ignore base-URL overrides).
  4. Always exits 0 (Phase 1.5 convention); all diagnostics go to stderr.

Removal drill: unset GRAPHIFY_ADAPTER and the framework degrades to the bash/python
extractors with no other change. Artifacts derived from this engine carry
engine="graphifyy==<version>" for later re-derivation.
"""
from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

MIN_VERSION = (0, 9, 24)
PIN_HINT = "python3 -m pip install 'graphifyy==0.9.43'"

CREDENTIAL_PREFIXES = (
    "OPENAI_", "ANTHROPIC_", "GEMINI_", "GOOGLE_", "MOONSHOT_", "DEEPSEEK_",
    "AZURE_", "OLLAMA_", "AWS_", "GRAPHIFY_LLM", "KIMI_",
)
CREDENTIAL_SUFFIX_RE = re.compile(r"(_API_KEY|_BASE_URL|_TOKEN|_SECRET)$")

PATH_KEYS = ("source_file", "path", "file", "file_path", "filepath", "source", "rel_path")
LINE_KEYS = ("source_location", "line", "lineno", "start_line", "line_start", "start")
KIND_KEYS = ("kind", "type", "node_type", "category")
NAME_KEYS = ("label", "name", "identifier", "symbol", "qualified_name", "id")

KIND_MAP = {
    "function": "handler", "method": "handler", "func": "handler",
    "class": "module", "module": "module", "file": "module", "package": "module",
    "endpoint": "endpoint", "route": "endpoint",
}
DEPENDENCY_EDGE_TYPES = {"import", "imports", "imports_from", "call", "calls",
                         "depends", "depends_on", "dependency", "uses", "references"}
# graphifyy structural relations that are NOT dependencies (counted, never emitted):
# contains, method, rationale_for


def log(msg: str) -> None:
    print(f"[extract_graphify] {msg}", file=sys.stderr, flush=True)


def flag_enabled() -> bool:
    return os.environ.get("GRAPHIFY_ADAPTER", "").strip().lower() in ("1", "true", "on")


def engine_version() -> tuple[int, ...] | None:
    try:
        from importlib.metadata import version
        return tuple(int(x) for x in version("graphifyy").split(".")[:3])
    except Exception:
        return None


def sanitized_env() -> dict[str, str]:
    env = {}
    for k, v in os.environ.items():
        if k.startswith(CREDENTIAL_PREFIXES) or CREDENTIAL_SUFFIX_RE.search(k):
            continue
        env[k] = v
    return env


def first_key(obj: dict, keys: tuple[str, ...]):
    for k in keys:
        if k in obj and obj[k] not in (None, ""):
            return obj[k]
    return None


def coerce_line(value) -> int:
    if isinstance(value, str):
        m = re.match(r"^L?(\d+)", value.strip())
        value = m.group(1) if m else None
    try:
        n = int(value)
        return n if n > 0 else 1
    except (TypeError, ValueError):
        return 1


def node_kind(node: dict) -> str | None:
    """Resolve a graphifyy node to a contract kind, or None (skip, counted).

    Real graphifyy schema (verified on graphifyy==0.9.43 output): code symbols are
    flagged with `_callable` (function/method) / `_callable_class` (class); plain
    file_type=="code" nodes are file/module nodes; `type` appears only on special
    nodes (e.g. "package"). file_type=="rationale" nodes are docstring-derived
    prose, not code symbols — skipped here (candidate KG-description feed later).
    """
    file_type = str(node.get("file_type", "")).lower()
    if file_type and file_type != "code":
        return None
    explicit = str(first_key(node, KIND_KEYS) or "").lower()
    if explicit in KIND_MAP:
        return KIND_MAP[explicit]
    if node.get("_callable"):
        return "handler"
    if node.get("_callable_class"):
        return "module"
    if file_type == "code":
        return "module"
    return None


def rel_path(raw, repo_path: Path) -> str | None:
    if not raw or not isinstance(raw, str):
        return None
    p = raw.replace("\\", "/")
    root = str(repo_path.resolve()).replace("\\", "/").rstrip("/") + "/"
    if p.startswith(root):
        p = p[len(root):]
    return p.lstrip("/") or None


def confidence_of(obj: dict) -> str:
    return str(obj.get("confidence", "EXTRACTED")).upper()


def map_nodes(nodes: list, repo_path: Path, engine: str, counters: dict) -> tuple[list[dict], list[dict]]:
    """Map graph nodes to contract records. Returns (records, needs_verification)."""
    records, sidecar = [], []
    node_index = {}
    for node in nodes:
        if not isinstance(node, dict):
            counters["nodes_unparseable"] += 1
            continue
        node_id = node.get("id")
        name = first_key(node, NAME_KEYS)
        path = rel_path(first_key(node, PATH_KEYS), repo_path)
        if node_id is not None:
            node_index[node_id] = {"name": name, "path": path,
                                   "line": coerce_line(first_key(node, LINE_KEYS))}
        kind = node_kind(node)
        if kind is None:
            skipped = (str(node.get("file_type") or first_key(node, KIND_KEYS) or "<missing>")).lower()
            counters.setdefault("skipped_kinds", {}).setdefault(skipped, 0)
            counters["skipped_kinds"][skipped] += 1
            continue
        if not path or not name:
            counters["nodes_missing_fields"] += 1
            continue
        record = {"path": path, "line": coerce_line(first_key(node, LINE_KEYS)),
                  "kind": kind, "identifier": str(name),
                  "engine": engine, "confidence": confidence_of(node)}
        conf = record["confidence"]
        if conf == "EXTRACTED":
            records.append(record)
        elif conf == "INFERRED":
            sidecar.append(record)
            counters["inferred_to_sidecar"] += 1
        else:
            counters["ambiguous_dropped"] += 1
    counters["node_index"] = node_index
    return records, sidecar


def map_edges(edges: list, counters: dict, engine: str,
              repo_path: Path | None = None) -> tuple[list[dict], list[dict]]:
    """Map dependency edges to contract records. Returns (records, needs_verification)."""
    records, sidecar = [], []
    repo_path = repo_path or Path(".")
    node_index = counters.get("node_index", {})
    for edge in edges:
        if not isinstance(edge, dict):
            counters["edges_unparseable"] += 1
            continue
        etype = str(edge.get("relation") or first_key(edge, KIND_KEYS) or "").lower()
        if etype not in DEPENDENCY_EDGE_TYPES:
            counters["edges_non_dependency"] += 1
            continue
        src = node_index.get(edge.get("source")) or {}
        dst = node_index.get(edge.get("target")) or {}
        # graphifyy edges carry their own provenance — prefer it over node lookup
        path = rel_path(first_key(edge, PATH_KEYS), repo_path) or src.get("path")
        line = coerce_line(first_key(edge, LINE_KEYS) or src.get("line", 1))
        src_name = src.get("name") or edge.get("source")
        dst_name = dst.get("name") or edge.get("target")
        if not path or not src_name or not dst_name:
            counters["edges_unresolvable"] += 1
            continue
        record = {"path": path, "line": line, "kind": "dependency",
                  "identifier": f"{src_name} -> {dst_name}",
                  "engine": engine, "confidence": confidence_of(edge)}
        conf = record["confidence"]
        if conf == "EXTRACTED":
            records.append(record)
        elif conf == "INFERRED":
            sidecar.append(record)
            counters["inferred_to_sidecar"] += 1
        else:
            counters["ambiguous_dropped"] += 1
    return records, sidecar


def find_graph_json(out_dir: Path) -> Path | None:
    direct = out_dir / "graph.json"
    if direct.is_file():
        return direct
    hits = sorted(out_dir.rglob("graph.json"))
    return hits[0] if hits else None


def run_engine(repo_path: Path, out_dir: Path) -> bool:
    """Run the engine's code-only pass, then relocate its native graphify-out/
    directory under Generated/graphify/ so nothing lands in the repo root."""
    cmd = shlex.split(os.environ.get("GRAPHIFY_CMD", f"{sys.executable} -m graphify"))
    subcommand = os.environ.get("GRAPHIFY_SUBCOMMAND", "update")
    extra = shlex.split(os.environ.get("GRAPHIFY_ARGS", "--no-cluster"))
    timeout = int(os.environ.get("GRAPHIFY_TIMEOUT", "900"))
    argv = cmd + [subcommand, str(repo_path)] + extra
    log(f"engine invocation (sanitized env, no credentials): {' '.join(argv)}")
    try:
        result = subprocess.run(argv, env=sanitized_env(), capture_output=True,
                                text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        log(f"ENGINE TIMEOUT after {timeout}s — no records emitted")
        return False
    except FileNotFoundError:
        log(f"ENGINE COMMAND NOT FOUND: {argv[0]} — no records emitted")
        return False
    if result.returncode != 0:
        tail = (result.stderr or "").strip().splitlines()[-5:]
        log(f"engine exited {result.returncode}; stderr tail: {' | '.join(tail)}")
    native_out = repo_path / "graphify-out"
    if native_out.is_dir():
        target = out_dir / "graphify-out"
        if target.is_dir():
            shutil.rmtree(target)
        shutil.move(str(native_out), str(target))
        log(f"engine output relocated: {native_out} -> {target}")
    return True


def main() -> int:
    if not flag_enabled():
        log("GRAPHIFY_ADAPTER flag is not set — adapter disabled, skipping cleanly "
            "(bash/python extractors remain the engines of record)")
        return 0

    if len(sys.argv) < 2:
        log("usage: extract_graphify.py <repo_path> — no repo path given, skipping")
        return 0
    repo_path = Path(sys.argv[1]).resolve()
    if not repo_path.is_dir():
        log(f"repo path does not exist: {repo_path} — skipping")
        return 0

    ver = engine_version()
    if ver is None:
        log(f"graphifyy is not installed — skipping cleanly. To enable: {PIN_HINT}")
        return 0
    if ver < MIN_VERSION:
        log(f"graphifyy {'.'.join(map(str, ver))} < required "
            f"{'.'.join(map(str, MIN_VERSION))} (older builds ignore base-URL "
            f"overrides) — skipping. Upgrade: {PIN_HINT}")
        return 0
    engine = f"graphifyy=={'.'.join(map(str, ver))}"

    out_dir = repo_path / "Generated" / "graphify"
    out_dir.mkdir(parents=True, exist_ok=True)

    if not run_engine(repo_path, out_dir):
        return 0

    graph_file = find_graph_json(out_dir)
    if graph_file is None:
        log(f"no graph.json produced under {out_dir} — no records emitted")
        return 0

    try:
        graph = json.loads(graph_file.read_text())
    except (json.JSONDecodeError, OSError) as exc:
        log(f"graph.json unreadable ({exc}) — no records emitted")
        return 0

    nodes = graph.get("nodes") or []
    edges = graph.get("edges") or graph.get("links") or []
    if not isinstance(nodes, list):
        log(f"UNRECOGNIZED SCHEMA: top-level keys {sorted(graph)[:12]} — no records emitted")
        return 0

    counters = {"nodes_unparseable": 0, "nodes_missing_fields": 0,
                "inferred_to_sidecar": 0, "ambiguous_dropped": 0,
                "edges_unparseable": 0, "edges_non_dependency": 0,
                "edges_unresolvable": 0}
    node_records, node_sidecar = map_nodes(nodes, repo_path, engine, counters)
    edge_records, edge_sidecar = map_edges(edges, counters, engine, repo_path)
    counters.pop("node_index", None)

    for record in node_records + edge_records:
        print(json.dumps(record))

    sidecar = node_sidecar + edge_sidecar
    if sidecar:
        sidecar_file = out_dir / "NEEDS_VERIFICATION.jsonl"
        with sidecar_file.open("w") as fh:
            for record in sidecar:
                fh.write(json.dumps(record) + "\n")
        log(f"INFERRED records quarantined to {sidecar_file} ({len(sidecar)}) — "
            f"verify before promoting to the index")

    by_kind: dict[str, int] = {}
    for record in node_records + edge_records:
        by_kind[record["kind"]] = by_kind.get(record["kind"], 0) + 1
    log(f"engine={engine} nodes_in={len(nodes)} edges_in={len(edges)} "
        f"emitted={sum(by_kind.values())} by_kind={by_kind} "
        f"sidecar={len(sidecar)} counters={counters}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
