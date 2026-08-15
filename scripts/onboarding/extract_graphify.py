#!/usr/bin/env python3
# Requires: python3 3.9+
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

Gated on the engine being installed. graphifyy is a pip package nobody has by default,
so installing it is the opt-in; when it is absent the adapter skips cleanly with a
one-line install hint. This adapter is a tenant behind the extraction contract, not a
load-bearing dependency. Controls:

    GRAPHIFY_ADAPTER            kill switch. Only an explicit affirmative ("1", "true",
                                "yes", "on") enables; ANY other value — including
                                "disabled", "none" or a typo — disables. Unset means
                                enabled, so the switch fails CLOSED on a mistake.
    GRAPHIFY_CMD                override engine command (default: adapter's own
                                interpreter, "-m graphify"). Honoured ONLY when
                                GRAPHIFY_ALLOW_CMD_OVERRIDE=1 is also set — an env var
                                that selects an arbitrary binary is a code-execution
                                surface, so the override is double-gated and logged
                                loudly. When honoured, the operator has named their own
                                engine: the packaged version floor is skipped and
                                provenance is stamped from GRAPHIFY_ENGINE_ID.
    GRAPHIFY_ALLOW_CMD_OVERRIDE set to "1" to allow GRAPHIFY_CMD to take effect
    GRAPHIFY_ENGINE_ID          provenance stamp to use when GRAPHIFY_CMD is honoured
                                (default "graphifyy==unknown")
    GRAPHIFY_SKIP_PREFLIGHT     set to "1" to bypass the installed-package version
                                lookup (test seam; logged loudly)
    GRAPHIFY_SUBCOMMAND         engine subcommand (default "update" — the code-only,
                                no-LLM re-extraction path per the engine's own help)
    GRAPHIFY_ARGS               extra CLI args (default "--no-cluster")
    GRAPHIFY_TIMEOUT            engine timeout seconds (default 900)

Safety guarantees:
  1. CODE-ONLY INVOCATION — this is the egress guarantee. Only the engine's "update"
     subcommand with --no-cluster is ever invoked; the LLM-dependent paths (extract,
     community labeling) are not. Additionally, and as DEFENCE IN DEPTH rather than the
     guarantee itself, the subprocess env is SANITIZED on a best-effort basis: provider
     prefixes, credential-shaped suffixes (*_API_KEY, *_BASE_URL, *_TOKEN, *_SECRET,
     *_PASSWORD, *_PASSWD, *_KEY, *_PAT, *_CREDENTIALS) and an exact denylist covering
     the ssh-agent socket (SSH_AUTH_SOCK — a live authentication channel, not just a
     secret), proxy redirectors (HTTP_PROXY/HTTPS_PROXY/ALL_PROXY, any case), NETRC and
     bare API_KEY are all stripped. Note the limit of that second layer: it removes
     env-based credentials and channels only. It does NOT reach credentials the engine
     could read from files under $HOME (~/.aws/credentials, ~/.netrc,
     ~/.config/gh/hosts.yml, git credential helpers), and it is not a network sandbox —
     so it is not on its own a proof that the engine cannot authenticate.
  2. Engine output stays in $REPO_PATH/Generated/graphify/. Nothing in the framework
     git-ignores that path, so the adapter writes Generated/graphify/.gitignore itself to
     keep engine output out of the target repo's history. Contract records go to stdout;
     INFERRED-confidence records go to the NEEDS_VERIFICATION.jsonl sidecar, never the
     index; AMBIGUOUS is dropped and counted. Honest scope: on graphifyy==0.9.43 output,
     NODE records carry no confidence field at all (measured: 100% absent on every repo
     tested), so in practice the gate filters edges; absent-confidence records default to
     EXTRACTED, are counted, and trip a loud WARNING — see confidence_of().
  3. FAIL-CLOSED CITATIONS. A node or edge whose line cannot be resolved is dropped and
     counted, never emitted with a fabricated line 1 (README.md "Fail-closed guarantee").
     VENDORED/GENERATED/MINIFIED paths (node_modules, dist, build, target, *.min.js,
     swagger-ui bundles, ...) are filtered before emission and counted as vendor_excluded:
     minified bundles have no meaningful lines to cite, and one-in-five records on a real
     service described Swagger's internals rather than the service before this filter.
  4. NO STALE REPUBLISHING. The engine output directory is cleared before each run and a
     non-zero engine exit emits nothing, so a failed run cannot re-emit the previous
     run's symbols.
  5. Requires graphifyy >= MIN_VERSION when using the packaged engine. The floor is a
     known-good baseline for the graph schema this adapter maps; it is NOT about base-URL
     overrides, since guarantee 1 strips every *_BASE_URL variable anyway. The engine
     also requires Python >= 3.10 and runs in THIS interpreter: under an older Python the
     adapter states the floor and skips cleanly instead of surfacing pip's version-skew
     noise (the adapter itself stays 3.9-compatible per the directory convention).
  6. Always exits 0 (Phase 1.5 convention); all diagnostics go to stderr. Malformed
     values for the env knobs above are reported and skipped, never raised.

Removal drill: set GRAPHIFY_ADAPTER=0 (or uninstall the engine) and the framework
degrades to the bash/python extractors with no other change. Artifacts derived from this
engine carry engine="graphifyy==<version>" for later re-derivation.
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
from typing import Dict, List, Optional, Tuple

MIN_VERSION = (0, 9, 24)
# The engine requires Python >= 3.10 (this adapter itself runs on 3.9). The hint names a
# concrete modern interpreter because `python3 -m pip install` on a stock macOS box is
# Python 3.9 and fails with 200 lines of version-skew noise that never states the floor.
ENGINE_PY_FLOOR = (3, 10)
PIN_HINT = ("python3.13 -m pip install 'graphifyy==0.9.43'  "
            "(any Python >= 3.10 interpreter; the engine runs in the SAME interpreter "
            "as this adapter)")

CREDENTIAL_PREFIXES = (
    "OPENAI_", "ANTHROPIC_", "GEMINI_", "GOOGLE_", "MOONSHOT_", "DEEPSEEK_",
    "AZURE_", "OLLAMA_", "AWS_", "GRAPHIFY_LLM", "KIMI_",
)
CREDENTIAL_SUFFIX_RE = re.compile(
    r"(_API_KEY|_BASE_URL|_TOKEN|_SECRET|_PASSWORD|_PASSWD|_KEY|_PAT|_CREDENTIALS)$",
    re.IGNORECASE)
# Exact-name denylist (compared case-insensitively). SSH_AUTH_SOCK is the sharp one:
# it is a live socket to the user's ssh-agent — an active authentication channel, not
# a readable secret. The proxy variables redirect outbound traffic to an unnamed host.
CREDENTIAL_EXACT = {
    "ssh_auth_sock", "http_proxy", "https_proxy", "all_proxy", "no_proxy",
    "netrc", "api_key", "curl_ca_bundle",
}

PATH_KEYS = ("source_file", "path", "file", "file_path", "filepath", "source", "rel_path")
# Edges get their own tuple WITHOUT "source": on an edge object `source` is the source
# node id, not a file path. With string node ids the generic tuple would emit the id as
# the record's path — a citation no file backs.
EDGE_PATH_KEYS = ("source_file", "path", "file", "file_path", "filepath", "rel_path")
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

# Vendored / generated / minified code is not the team's code and minified bundles have
# no meaningful lines to cite (independent test: 827 of 3,969 records — 20.8% — on one
# service came from three swagger-ui bundles, with symbols cited at a comment banner).
# Filtered BEFORE emission and counted as vendor_excluded so the number is visible.
VENDOR_RE = re.compile(
    r"(^|/)(node_modules|vendor|third_party|thirdparty|dist|build|target|out"
    r"|\.venv|venv|site-packages|__pycache__|\.gradle|\.m2|bower_components)(/|$)"
    r"|\.min\.(js|css)$|-bundle\.js$|\.bundle\.js$|(^|/)swagger-ui(/|$)",
    re.IGNORECASE,
)


def is_vendored(path: str) -> bool:
    """True for paths the target team did not write (vendored/generated/minified)."""
    return bool(VENDOR_RE.search(path))


def log(msg: str) -> None:
    print(f"[extract_graphify] {msg}", file=sys.stderr, flush=True)


AFFIRMATIVE = ("1", "true", "yes", "on")


def flag_enabled() -> bool:
    """Kill switch that fails CLOSED.

    Installing the engine is the opt-in, so an unset variable means enabled. But once the
    operator sets the variable at all, they are trying to control the adapter — and the
    only safe reading of a value we do not recognise is "stop". `GRAPHIFY_ADAPTER=disabled`
    is the most likely thing someone types, and treating it as enabled (the previous
    behaviour) silently ran a third-party engine over the target repo.
    """
    raw = os.environ.get("GRAPHIFY_ADAPTER")
    if raw is None:
        return True
    return raw.strip().lower() in AFFIRMATIVE


def engine_version() -> Optional[Tuple[int, ...]]:
    """Return the installed graphifyy version, or None if it is not installed.

    Raises nothing. A version string we cannot parse is reported distinctly from a missing
    package, so the operator is not sent to a pip install that would change nothing.
    """
    try:
        from importlib.metadata import version
        raw = version("graphifyy")
    except Exception:
        return None
    try:
        return tuple(int(x) for x in raw.split(".")[:3])
    except (TypeError, ValueError):
        log(f"graphifyy is installed but reports an unparseable version {raw!r} — "
            f"treating as too old to trust; skipping")
        return ()


def sanitized_env() -> Dict[str, str]:
    env = {}
    for k, v in os.environ.items():
        if (k.startswith(CREDENTIAL_PREFIXES) or CREDENTIAL_SUFFIX_RE.search(k)
                or k.lower() in CREDENTIAL_EXACT):
            continue
        env[k] = v
    return env


def first_key(obj: dict, keys: Tuple[str, ...]):
    for k in keys:
        if k in obj and obj[k] not in (None, ""):
            return obj[k]
    return None


def coerce_line(value) -> Optional[int]:
    """Parse a line number, or return None when the value does not carry one.

    Returns None rather than 1 on failure. Defaulting to 1 passes the `line > 0` check the
    contract uses to mean "citable", so an unlocatable symbol would be emitted pointing at
    the wrong line instead of being dropped -- see the fail-closed guarantee in
    scripts/onboarding/README.md and its implementation in extract_fastapi.py.
    """
    if isinstance(value, str):
        # Accept "42", "L42", "42:7"; also "src/api.py:42" and "src/api.py#L42", which is
        # the shape a key literally named `source_location` tends to carry.
        text = value.strip()
        m = re.match(r"^L?(\d+)", text) or re.search(r"[:#]L?(\d+)\s*(?::\d+)?$", text)
        value = m.group(1) if m else None
    try:
        n = int(value)
    except (TypeError, ValueError):
        return None
    return n if n > 0 else None


def resolve_line(obj: dict) -> Optional[int]:
    """First value across LINE_KEYS that actually yields a line number.

    Deliberately not `coerce_line(first_key(obj, LINE_KEYS))`: `first_key` short-circuits on
    the first present key, so a `source_location` the parser cannot read would permanently
    mask a perfectly good `line` / `lineno` sitting on the same node.
    """
    for key in LINE_KEYS:
        if key not in obj:
            continue
        line = coerce_line(obj[key])
        if line is not None:
            return line
    return None


def node_kind(node: dict) -> Optional[str]:
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


def rel_path(raw, repo_path: Path) -> Optional[str]:
    if not raw or not isinstance(raw, str):
        return None
    p = raw.replace("\\", "/")
    root = str(repo_path.resolve()).replace("\\", "/").rstrip("/") + "/"
    if p.startswith(root):
        p = p[len(root):]
    return p.lstrip("/") or None


def confidence_of(obj: dict, counters: Optional[dict] = None) -> str:
    """Confidence label for a node/edge, defaulting to EXTRACTED when absent.

    The default is deliberately the trusting one -- the engine emits this field today and
    dropping everything the moment it stopped would make the adapter useless. But an absent
    field is exactly the case we know least about, so count it; main() turns a non-zero
    count into a loud WARNING rather than letting schema drift pass silently.
    """
    if "confidence" not in obj and counters is not None:
        counters["confidence_absent"] = counters.get("confidence_absent", 0) + 1
    return str(obj.get("confidence", "EXTRACTED")).upper()


def _file_and_line(obj: dict, repo_path: Path, counters: dict, missing_counter: str):
    """Resolve (path, line) or return None after counting a fail-closed drop."""
    path = rel_path(first_key(obj, PATH_KEYS), repo_path)
    line = resolve_line(obj)
    if not path or line is None:
        counters[missing_counter] = counters.get(missing_counter, 0) + 1
        return None
    return path, line


def _route(record: dict, records: list, sidecar: list, counters: dict) -> None:
    """Send a record to the index, the sidecar, or the floor, by confidence."""
    conf = record["confidence"]
    if conf == "EXTRACTED":
        records.append(record)
    elif conf == "INFERRED":
        sidecar.append(record)
        counters["inferred_to_sidecar"] += 1
    else:
        counters["ambiguous_dropped"] += 1


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
            # counters=None: confidence_of is already counted once per mapped record;
            # the index copy must not double-count absent-confidence.
            node_index[node_id] = {"name": name, "path": path, "line": resolve_line(node),
                                   "confidence": confidence_of(node, None)}
        kind = node_kind(node)
        if kind is None:
            skipped = (str(node.get("file_type") or first_key(node, KIND_KEYS) or "<missing>")).lower()
            counters.setdefault("skipped_kinds", {}).setdefault(skipped, 0)
            counters["skipped_kinds"][skipped] += 1
            continue
        if not name:
            counters["nodes_missing_fields"] += 1
            continue
        located = _file_and_line(node, repo_path, counters, "nodes_missing_fields")
        if located is None:
            continue
        path, line = located
        if is_vendored(path):
            counters["vendor_excluded"] = counters.get("vendor_excluded", 0) + 1
            continue
        # graphifyy labels methods with a leading dot (`.main()`); identifier is the
        # human-facing column in CODE_INDEX.md, so strip it at the mapping site.
        record = {"path": path, "line": line,
                  "kind": kind, "identifier": str(name).lstrip("."),
                  "engine": engine, "confidence": confidence_of(node, counters)}
        _route(record, records, sidecar, counters)
    counters["node_index"] = node_index
    return records, sidecar


_CONFIDENCE_RANK = {"EXTRACTED": 0, "INFERRED": 1}  # anything else ranks weakest (2)


def weakest_confidence(*labels: str) -> str:
    """The least-trustworthy label wins. An edge is only as good as its endpoints:
    emitting `a -> b` as EXTRACTED while `b` itself sat quarantined as INFERRED would
    put an assertion about an unverified symbol into the index through the side door.
    """
    return max(labels, key=lambda l: _CONFIDENCE_RANK.get(l, 2))


def map_edges(edges: list, counters: dict, engine: str,
              repo_path: Optional[Path] = None) -> tuple[list[dict], list[dict]]:
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
        # graphifyy edges carry their own provenance — prefer it over node lookup.
        # EDGE_PATH_KEYS, not PATH_KEYS: an edge's `source` is a node id, never a path.
        path = rel_path(first_key(edge, EDGE_PATH_KEYS), repo_path) or src.get("path")
        # Fail closed: fall back to the source node's line, but never to a literal 1.
        line = resolve_line(edge)
        if line is None:
            line = src.get("line")
        src_name = src.get("name") or edge.get("source")
        dst_name = dst.get("name") or edge.get("target")
        if not path or line is None or not src_name or not dst_name:
            counters["edges_unresolvable"] += 1
            continue
        if is_vendored(path):
            counters["vendor_excluded"] = counters.get("vendor_excluded", 0) + 1
            continue
        # The edge inherits the weakest confidence among itself and both endpoints.
        conf = weakest_confidence(confidence_of(edge, counters),
                                  src.get("confidence", "EXTRACTED"),
                                  dst.get("confidence", "EXTRACTED"))
        record = {"path": path, "line": line, "kind": "dependency",
                  "identifier": f"{str(src_name).lstrip('.')} -> {str(dst_name).lstrip('.')}",
                  "engine": engine, "confidence": conf}
        _route(record, records, sidecar, counters)
    return records, sidecar


def find_graph_json(out_dir: Path) -> Optional[Path]:
    direct = out_dir / "graph.json"
    if direct.is_file():
        return direct
    hits = sorted(out_dir.rglob("graph.json"))
    return hits[0] if hits else None


def clear_engine_output(out_dir: Path) -> None:
    """Remove any previous run's engine output.

    Without this, an engine run that fails and writes nothing leaves the last run's
    graph.json in place; find_graph_json() then picks it up and the adapter re-emits stale
    symbols stamped with the CURRENT engine version, which nothing downstream can detect.
    """
    for stale in (out_dir / "graphify-out", out_dir / "graph.json"):
        if stale.is_dir():
            shutil.rmtree(stale, ignore_errors=True)
        elif stale.exists():
            stale.unlink(missing_ok=True)


def run_engine(repo_path: Path, out_dir: Path) -> bool:
    """Run the engine's code-only pass, then relocate its native graphify-out/
    directory under Generated/graphify/ so nothing lands in the repo root.

    Returns False on ANY failure -- a non-zero exit included -- so the caller emits nothing
    rather than falling through to whatever happens to be on disk.
    """
    default_cmd = f"{sys.executable} -m graphify"
    raw_cmd = os.environ.get("GRAPHIFY_CMD")
    if raw_cmd and raw_cmd != default_cmd:
        if os.environ.get("GRAPHIFY_ALLOW_CMD_OVERRIDE") == "1":
            log(f"WARNING: non-default engine command honoured "
                f"(GRAPHIFY_ALLOW_CMD_OVERRIDE=1): {raw_cmd}")
        else:
            log("GRAPHIFY_CMD is set but GRAPHIFY_ALLOW_CMD_OVERRIDE=1 is not — "
                "ignoring the override and using the default engine command "
                "(an env var that picks the binary is a code-execution surface)")
            raw_cmd = None
    try:
        cmd = shlex.split(raw_cmd or default_cmd)
        extra = shlex.split(os.environ.get("GRAPHIFY_ARGS", "--no-cluster"))
    except ValueError as exc:
        log(f"GRAPHIFY_CMD/GRAPHIFY_ARGS is not parseable as a shell command ({exc}) — "
            f"skipping cleanly, no records emitted")
        return False
    subcommand = os.environ.get("GRAPHIFY_SUBCOMMAND", "update")
    raw_timeout = os.environ.get("GRAPHIFY_TIMEOUT", "900")
    try:
        timeout = int(raw_timeout)
    except (TypeError, ValueError):
        log(f"GRAPHIFY_TIMEOUT={raw_timeout!r} is not an integer number of seconds — "
            f"skipping cleanly, no records emitted")
        return False

    clear_engine_output(out_dir)
    argv = cmd + [subcommand, str(repo_path)] + extra
    log(f"engine invocation (code-only path, credential-stripped env): {' '.join(argv)}")
    try:
        result = subprocess.run(argv, env=sanitized_env(), capture_output=True,
                                text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        log(f"ENGINE TIMEOUT after {timeout}s — no records emitted")
        return False
    except (FileNotFoundError, PermissionError, OSError) as exc:
        log(f"ENGINE COMMAND NOT RUNNABLE: {argv[0]} ({exc}) — no records emitted")
        return False
    if result.returncode != 0:
        tail = (result.stderr or "").strip().splitlines()[-5:]
        log(f"ENGINE FAILED (exit {result.returncode}) — no records emitted; "
            f"stderr tail: {' | '.join(tail)}")
        return False
    native_out = repo_path / "graphify-out"
    if native_out.is_dir():
        target = out_dir / "graphify-out"
        if target.is_dir():
            shutil.rmtree(target)
        shutil.move(str(native_out), str(target))
        log(f"engine output relocated: {native_out} -> {target}")
    return True


def ensure_output_ignored(out_dir: Path) -> None:
    """Keep engine output out of the TARGET repo's history.

    Nothing in this framework git-ignores Generated/graphify/ -- the framework .gitignore
    only covers Generated/session_logs/*.private.md and Generated/Repos/*_PROFILE.md, and
    the rest of Generated/ is committed on purpose. The adapter also writes into a repo
    whose .gitignore we do not own, so it drops a self-scoped one here instead of relying
    on the target repo having a rule we never asked it to add.
    """
    marker = out_dir / ".gitignore"
    body = ("# Machine-local Graphify engine output — never committed.\n"
            "# Written by scripts/onboarding/extract_graphify.py.\n"
            "*\n")
    try:
        if not marker.is_file() or marker.read_text() != body:
            marker.write_text(body)
    except OSError as exc:
        log(f"WARNING: could not write {marker} ({exc}) — engine output under {out_dir} "
            f"is NOT git-ignored; do not commit it")


def main() -> int:
    if not flag_enabled():
        log(f"GRAPHIFY_ADAPTER={os.environ.get('GRAPHIFY_ADAPTER')!r} is not an explicit "
            "affirmative — adapter disabled, skipping cleanly "
            "(bash/python extractors remain the engines of record)")
        return 0

    if len(sys.argv) < 2:
        log("usage: extract_graphify.py <repo_path> — no repo path given, skipping")
        return 0
    repo_path = Path(sys.argv[1]).resolve()
    if not repo_path.is_dir():
        log(f"repo path does not exist: {repo_path} — skipping")
        return 0

    # An HONOURED GRAPHIFY_CMD means the operator named their own engine, so the version
    # of whatever graphifyy happens to be installed in THIS interpreter says nothing about
    # it. Honoured requires the double gate (GRAPHIFY_ALLOW_CMD_OVERRIDE=1) — a CMD set
    # without the gate is ignored by run_engine, so the packaged preflight still applies.
    # GRAPHIFY_SKIP_PREFLIGHT=1 is the equivalent test seam without a custom command.
    custom_cmd = ("GRAPHIFY_CMD" in os.environ
                  and os.environ.get("GRAPHIFY_ALLOW_CMD_OVERRIDE") == "1")
    if custom_cmd or os.environ.get("GRAPHIFY_SKIP_PREFLIGHT") == "1":
        engine = os.environ.get("GRAPHIFY_ENGINE_ID", "graphifyy==unknown")
        reason = ("GRAPHIFY_CMD override honoured" if custom_cmd
                  else "GRAPHIFY_SKIP_PREFLIGHT=1 (test seam)")
        log(f"packaged version floor skipped — {reason}; provenance stamped as {engine}")
    else:
        # The engine needs Python >= 3.10 and runs in THIS interpreter (sys.executable).
        # On a stock macOS box `python3` is 3.9.6 and the pip failure it produces never
        # states the floor — so state it here and skip cleanly, before the version check.
        if sys.version_info < ENGINE_PY_FLOOR:
            log(f"graphifyy requires Python >= 3.10; this adapter is running under "
                f"{sys.version_info[0]}.{sys.version_info[1]} ({sys.executable}) "
                f"and invokes the engine in its own interpreter. Re-run Phase 1.5 under "
                f"a 3.10+ interpreter, or install the engine into one: {PIN_HINT}")
            return 0
        ver = engine_version()
        if ver is None:
            log(f"graphifyy is not installed — skipping cleanly. To enable: {PIN_HINT}")
            return 0
        if ver < MIN_VERSION:
            log(f"graphifyy {'.'.join(map(str, ver)) or 'unparseable'} < required "
                f"{'.'.join(map(str, MIN_VERSION))} (known-good baseline for the graph "
                f"schema this adapter maps) — skipping. Upgrade: {PIN_HINT}")
            return 0
        engine = f"graphifyy=={'.'.join(map(str, ver))}"

    out_dir = repo_path / "Generated" / "graphify"
    out_dir.mkdir(parents=True, exist_ok=True)
    ensure_output_ignored(out_dir)

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
                "edges_unresolvable": 0, "confidence_absent": 0,
                "vendor_excluded": 0}
    node_records, node_sidecar = map_nodes(nodes, repo_path, engine, counters)
    edge_records, edge_sidecar = map_edges(edges, counters, engine, repo_path)
    counters.pop("node_index", None)

    if counters["confidence_absent"]:
        log(f"WARNING: {counters['confidence_absent']} record(s) carried no `confidence` "
            f"field and were treated as EXTRACTED. The confidence gate assumes {engine} "
            f"emits that field — if this count is large the engine's schema has drifted "
            f"and the gate is no longer filtering anything.")
    dropped = counters["nodes_missing_fields"] + counters["edges_unresolvable"]
    if dropped:
        log(f"fail-closed: {dropped} record(s) dropped for want of a resolvable "
            f"path:line citation (never emitted at a fabricated line 1)")
    if counters["vendor_excluded"]:
        log(f"vendor_excluded={counters['vendor_excluded']} record(s) from vendored/"
            f"generated/minified paths filtered before emission (not the team's code)")

    # Symbol records go to stdout (Phase 1.5 merges them into Knowledge/CODE_INDEX.md,
    # which is eager-loaded at session start). Dependency edges do NOT: at real-repo
    # scale they are the bulk of the output (1,803 of 3,159 records on the largest test
    # repo) and would blow the activation token budget. They land in CODE_GRAPH.jsonl
    # under the machine-local tier instead, for agents that want the graph on demand.
    for record in node_records:
        print(json.dumps(record))

    if edge_records:
        graph_out = out_dir / "CODE_GRAPH.jsonl"
        with graph_out.open("w") as fh:
            for record in edge_records:
                fh.write(json.dumps(record) + "\n")
        log(f"dependency edges written to {graph_out} ({len(edge_records)}) — "
            f"kept out of CODE_INDEX.md to protect the eager-load token budget")

    sidecar = node_sidecar + edge_sidecar
    if sidecar:
        sidecar_file = out_dir / "NEEDS_VERIFICATION.jsonl"
        with sidecar_file.open("w") as fh:
            for record in sidecar:
                fh.write(json.dumps(record) + "\n")
        log(f"INFERRED records quarantined to {sidecar_file} ({len(sidecar)}) — "
            f"verify before promoting to the index")

    by_kind: Dict[str, int] = {}
    for record in node_records + edge_records:
        by_kind[record["kind"]] = by_kind.get(record["kind"], 0) + 1
    log(f"engine={engine} nodes_in={len(nodes)} edges_in={len(edges)} "
        f"stdout_records={len(node_records)} code_graph_records={len(edge_records)} "
        f"by_kind={by_kind} sidecar={len(sidecar)} counters={counters}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
