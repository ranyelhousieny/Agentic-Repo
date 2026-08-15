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
    GRAPHIFY_PYTHON             interpreter that RUNS the engine (default: this adapter's
                                own sys.executable). The engine needs Python >= 3.10 while
                                the adapter itself must stay 3.9-compatible, and the
                                Phase 1.5 hook invokes the adapter as bare "python3" — on a
                                stock macOS box that is 3.9.6. This knob is what makes the
                                floor satisfiable without handing out the code-execution
                                surface GRAPHIFY_CMD is: it names an INTERPRETER, and the
                                module run inside it is still hard-coded to "-m graphify".
    GRAPHIFY_SUBCOMMAND         engine subcommand. Default "update" — the code-only, no-LLM
                                re-extraction path per the engine's own help. Changing it
                                reaches the engine's LLM paths, so it is honoured ONLY when
                                GRAPHIFY_ALLOW_LLM_PATH=1 is also set (see guarantee 1).
    GRAPHIFY_ARGS               extra CLI args. Default "--no-cluster"; same gate as
                                GRAPHIFY_SUBCOMMAND, since dropping --no-cluster is itself
                                a way back onto the clustering/LLM path.
    GRAPHIFY_ALLOW_LLM_PATH     set to "1" to allow GRAPHIFY_SUBCOMMAND / GRAPHIFY_ARGS to
                                take effect. Deliberately a DIFFERENT gate from
                                GRAPHIFY_ALLOW_CMD_OVERRIDE: every stub-engine test needs
                                the command gate, and sharing one variable would hand the
                                larger power to every test seam.
    GRAPHIFY_TIMEOUT            engine timeout seconds (default 900)

Safety guarantees:
  1. CODE-ONLY INVOCATION — this is the egress guarantee, so it is GATED rather than
     merely defaulted. Only the engine's "update" subcommand with --no-cluster is
     invoked; the LLM-dependent paths (extract, community labeling) are not. Because the
     guarantee rests on those two values, GRAPHIFY_SUBCOMMAND and GRAPHIFY_ARGS are
     ignored unless GRAPHIFY_ALLOW_LLM_PATH=1 is explicitly set — an ungated env var that
     picks the subcommand would put the whole posture one variable away from false, while
     the invocation log still claimed the code-only path. When the gate IS set, the run is
     logged as OVERRIDDEN and the code-only claim is withdrawn in the log line itself.
     Additionally, and as DEFENCE IN DEPTH rather than the
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
  4. NO STALE REPUBLISHING. EVERY artifact this adapter derives is removed before the
     engine runs — the engine-native graphify-out/ tree AND the CODE_GRAPH.jsonl /
     NEEDS_VERIFICATION.jsonl / CODE_INDEX_RECORDS.jsonl files it writes — so a run that
     fails, or that legitimately produces zero edges or zero INFERRED records, cannot
     leave the previous run's file on disk looking like current output. Clearing the
     engine tree alone is not enough: those files are written conditionally, so "no
     records of this kind this run" would otherwise preserve last run's. That matters
     most for NEEDS_VERIFICATION.jsonl, which is the list an operator is told to check
     before promoting anything.
  5. Requires graphifyy >= MIN_VERSION when using the packaged engine. The floor is a
     known-good baseline for the graph schema this adapter maps; it is NOT about base-URL
     overrides, since guarantee 1 strips every *_BASE_URL variable anyway. The engine also
     requires Python >= 3.10, so the floor is checked against GRAPHIFY_PYTHON — the
     interpreter that will actually RUN the engine — not against the one running this
     adapter. Phase 1.5 invokes the adapter as bare "python3" (3.9.6 on stock macOS), so
     checking the adapter's own interpreter would make the feature unreachable through the
     only path that invokes it. When no 3.10+ interpreter can be found the adapter names
     the ones it tried and skips cleanly (the adapter itself stays 3.9-compatible per the
     directory convention).
  6. Always exits 0 (Phase 1.5 convention); all diagnostics go to stderr. Malformed
     values for the env knobs above are reported and skipped, never raised — and so are
     filesystem failures: an unwritable target repo makes the adapter skip, not crash.

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
            "(any Python >= 3.10 interpreter; if it is not the one running this adapter, "
            "point GRAPHIFY_PYTHON at it)")

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


def default_engine_cmd() -> str:
    """The packaged-engine command: `<engine interpreter> -m graphify`.

    Only the INTERPRETER is operator-selectable (GRAPHIFY_PYTHON); the module is fixed, so
    this is not a code-execution surface the way GRAPHIFY_CMD is.
    """
    return f"{engine_python()} -m graphify"


def cmd_override_honoured() -> bool:
    """Single shared predicate for "the operator named their own engine".

    main() and run_engine() previously asked this question two different ways, and they
    disagreed: GRAPHIFY_CMD="" (or set to exactly the default string) plus the allow gate
    made main() skip the version floor and stamp provenance graphifyy==unknown, while
    run_engine fell back to the REAL packaged engine. One predicate, one answer.
    """
    raw = os.environ.get("GRAPHIFY_CMD")
    if not raw or raw == default_engine_cmd():
        return False
    return os.environ.get("GRAPHIFY_ALLOW_CMD_OVERRIDE") == "1"


def llm_path_unlocked() -> bool:
    """True when the operator has explicitly accepted leaving the code-only path."""
    return os.environ.get("GRAPHIFY_ALLOW_LLM_PATH") == "1"


_ENGINE_PYTHON_CACHE: Dict[str, str] = {}


def engine_python() -> str:
    """Interpreter that will RUN the engine.

    Defaults to this adapter's own interpreter, which is correct when the operator invoked
    the adapter with a modern python3. It is NOT correct under the Phase 1.5 hook, which
    calls bare `python3` — 3.9.6 on a stock macOS box, below the engine's 3.10 floor. So
    an explicit GRAPHIFY_PYTHON wins, and otherwise we fall back to probing for a 3.10+
    interpreter on PATH before giving up.

    Memoized on the GRAPHIFY_PYTHON value: the probe spawns up to one subprocess per
    candidate, and this is called from several places per run.
    """
    explicit = (os.environ.get("GRAPHIFY_PYTHON") or "").strip()
    if explicit:
        return explicit
    if sys.version_info >= ENGINE_PY_FLOOR:
        return sys.executable
    if "probed" not in _ENGINE_PYTHON_CACHE:
        _ENGINE_PYTHON_CACHE["probed"] = find_modern_python() or sys.executable
    return _ENGINE_PYTHON_CACHE["probed"]


def python_version_of(executable: str) -> Optional[Tuple[int, ...]]:
    """(major, minor) of `executable`, or None if it cannot be run or parsed."""
    if executable == sys.executable:
        return (sys.version_info[0], sys.version_info[1])
    try:
        proc = subprocess.run(
            [executable, "-c",
             "import sys; print('%d.%d' % sys.version_info[:2])"],
            capture_output=True, text=True, timeout=15,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        return None
    try:
        return tuple(int(x) for x in proc.stdout.strip().split(".")[:2])
    except (TypeError, ValueError):
        return None


# Probed in order when the adapter is running under an interpreter older than the engine
# floor. Newest first so the engine gets the best available interpreter.
PYTHON_CANDIDATES = ("python3.13", "python3.12", "python3.11", "python3.10", "python3")


def find_modern_python() -> Optional[str]:
    """First interpreter on PATH at or above the engine's Python floor."""
    for name in PYTHON_CANDIDATES:
        resolved = shutil.which(name)
        if not resolved:
            continue
        version = python_version_of(resolved)
        if version and version >= ENGINE_PY_FLOOR:
            return resolved
    return None


def engine_version(executable: Optional[str] = None) -> Optional[Tuple[int, ...]]:
    """Return the installed graphifyy version, or None if it is not installed.

    Looked up in the interpreter that will RUN the engine, not necessarily this one -- the
    adapter may be running under 3.9 while the engine runs under GRAPHIFY_PYTHON, and
    "installed" is a property of that interpreter's environment.

    Raises nothing. A version string we cannot parse is reported distinctly from a missing
    package, so the operator is not sent to a pip install that would change nothing.
    """
    executable = executable or engine_python()
    if executable == sys.executable:
        try:
            from importlib.metadata import version
            raw = version("graphifyy")
        except Exception:
            return None
    else:
        try:
            proc = subprocess.run(
                [executable, "-c",
                 "from importlib.metadata import version; print(version('graphifyy'))"],
                capture_output=True, text=True, timeout=30,
            )
        except (OSError, subprocess.SubprocessError):
            return None
        if proc.returncode != 0:
            return None
        raw = proc.stdout.strip()
        if not raw:
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

    The default is deliberately the trusting one -- dropping everything the moment the field
    was absent would make the adapter useless. But an absent field is exactly the case we
    know least about, so count BOTH the absent and the present cases: the ratio is what
    carries the signal. main() reports 100%-absent as the expected baseline and reserves a
    WARNING for a partial split, which is the only shape that actually indicates drift.

    Counting is opt-in via `counters` and is applied to NODES only. graphifyy edges carry no
    confidence key by design -- that is precisely why weakest_confidence() exists -- so
    folding them in made the count exceed the node set and fire at 1,803-of-3,159 magnitude
    on a clean run.
    """
    if counters is not None:
        key = "confidence_present" if "confidence" in obj else "confidence_absent"
        counters[key] = counters.get(key, 0) + 1
    return str(obj.get("confidence", "EXTRACTED")).upper()


def clean_identifier(name) -> str:
    """Human-facing symbol label: at most ONE leading dot removed.

    graphifyy labels methods with a single leading dot (`.main()`). `lstrip(".")` removed
    EVERY leading dot, which is wrong wherever they are significant -- a Python relative
    import `..utils` became `utils`, a different module. So exactly one is removed.

    Returns "" when what is left carries no name at all (a label of nothing but dots and
    whitespace), so callers can drop the record instead of emitting a blank identifier or
    a meaningless one like "..". The raw-label emptiness guards in map_nodes/map_edges run
    BEFORE this, which is how "..." used to slip through and emit "" / " -> ".
    """
    text = str(name).strip()
    if text.startswith("."):
        text = text[1:]
    text = text.strip()
    if not text.strip(". \t"):
        return ""
    return text


# The conversion pipeline itself creates files inside the target repo (Generated/,
# Knowledge/, .claude/, CLAUDE.md, ...) BEFORE Phase 1.5 runs, and the engine walks
# the filesystem without regard for .gitignore — so on every conversion (and every
# re-run) it indexes the framework's own artifacts as if they were the team's code.
# Measured on a real conversion re-run: 261 unverifiable module records were the
# framework's own generated files. Exclude them: they are the knowledge layer
# ABOUT the code, not the code.
FRAMEWORK_ARTIFACT_RE = re.compile(
    r"(^|/)(Generated|Knowledge|\.claude|\.windsurf)(/|$)"
    r"|(^|/)(CLAUDE|AGENTS|START_HERE|START_HERE\.agentic)\.md$"
    r"|(^|/)prompts/templates/AI Agents(/|$)"
    r"|(^|/)BINDING\.yml$"
)


def is_framework_artifact(path: str) -> bool:
    return bool(FRAMEWORK_ARTIFACT_RE.search(path))


_SNAP_WINDOW = 10

# Mirror of verify_citations.sh tokenize()/stem(): the T3 gate scores overlap on
# stems >= 3 chars that are not stopwords. An identifier none of whose words
# survive that filter (`US`, `EU`, `with()`, `from()`) can NEVER pass the gate no
# matter how correct its citation is — so those records are quarantined to the
# sidecar rather than left in the index as guaranteed gate failures.
_GATE_STOP = {"the", "a", "an", "in", "of", "to", "and", "or", "is", "are", "was",
              "with", "for", "on", "at", "by", "from", "this", "that", "it", "its",
              "not", "no", "be", "has", "have", "do", "all", "as", "into", "via"}


def _gate_stem(word: str) -> str:
    w = word.lower()
    for suffix in ("tion", "tions", "ings", "ing", "tion", "ed", "ly", "er", "est", "s"):
        if w.endswith(suffix) and len(w) - len(suffix) >= 3:
            w = w[:-len(suffix)]
            break
    return w


def gate_surviving_words(identifier: str) -> list:
    """The identifier's words that survive the T3 gate's tokenizer (original
    casing kept for the line search; presence of the raw word on a line implies
    a stem match, since the gate stems both sides identically)."""
    out = []
    for w in re.findall(r"[a-zA-Z][a-zA-Z0-9]*", identifier):
        s = _gate_stem(w)
        if len(s) >= 3 and s not in _GATE_STOP:
            out.append(w)
    return out


def snap_line_to_identifier(repo_path: Path, path: str, line: int, identifier: str,
                            counters: dict, cache: dict) -> int:
    """Align the engine's citation with the framework's exact-line overlap contract.

    graphifyy cites a declaration's START line, which for annotated Java/Kotlin
    symbols is the annotation (`@Override`, `@GET`, `@Value`), not the line that
    names the symbol. The T3 verifier (verify_citations.sh) requires stemmed-token
    overlap on the exact cited line, so an annotation-line citation fails the gate
    for a symbol that genuinely exists at that declaration — measured on a real
    431-file JAX-RS service: 1,751 of 1,774 gate failures were this mismatch.

    Snap FORWARD only, to the nearest line within the declaration header that
    contains the identifier's bare name as a whole word. Forward-only because the
    engine cites the header's first line; scanning backward risks landing on an
    unrelated earlier mention.

    Returns the (possibly snapped) line, or -1 when the identifier cannot be
    located within the window — the caller routes that record to the
    needs-verification sidecar: a symbol whose name cannot be found at or near
    its own citation is the definition of "needs verification before promoting",
    and leaving it in the index guarantees a citation-gate failure. An EMPTY file
    is the same verdict — it was read successfully and no line exists that could
    verify the identifier (measured: 48 engine records for empty `__init__.py`
    files sat in the index as guaranteed gate failures under the earlier
    keep-unjudged rule). An UNREADABLE file (OSError) keeps the engine's line
    unjudged: the adapter only rules on content it actually read — absence is the
    gate's jurisdiction, not this function's.

    Punctuated engine labels (`billing-ws-pom`, `.Builder()`) are judged by
    their LONGEST gate-surviving word — the first version exempted them entirely,
    which leaked exactly the unverifiable synthesized file-node labels back into
    the index (measured: the last 40 gate failures were all this class). An
    identifier with NO gate-surviving words (`US`, `with()`) is unverifiable by
    construction under the gate's tokenizer and goes straight to the sidecar.
    """
    tokens = gate_surviving_words(identifier)
    if not tokens:
        counters["gate_unverifiable_identifier"] = \
            counters.get("gate_unverifiable_identifier", 0) + 1
        return -1
    token = max(tokens, key=len)
    lines = cache.get(path)
    if lines is None:
        try:
            lines = (repo_path / path).read_text(encoding="utf-8",
                                                 errors="replace").splitlines()
        except OSError:
            lines = False  # sentinel: unreadable, distinct from read-but-empty
        cache[path] = lines
    if lines is False or line < 1:
        return line
    if not lines:
        counters["unverifiable_file_to_sidecar"] = \
            counters.get("unverifiable_file_to_sidecar", 0) + 1
        return -1
    pattern = re.compile(r"\b" + re.escape(token) + r"\b")
    if line <= len(lines) and pattern.search(lines[line - 1]):
        return line
    for probe in range(line + 1, min(line + _SNAP_WINDOW, len(lines)) + 1):
        if pattern.search(lines[probe - 1]):
            counters["line_snapped"] = counters.get("line_snapped", 0) + 1
            return probe
    counters["line_snap_miss"] = counters.get("line_snap_miss", 0) + 1
    return -1


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
    snap_cache: dict = {}
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
        if is_framework_artifact(path):
            counters["framework_artifacts_excluded"] = \
                counters.get("framework_artifacts_excluded", 0) + 1
            continue
        # graphifyy labels methods with a leading dot (`.main()`); identifier is the
        # human-facing column in CODE_INDEX.md, so strip it at the mapping site.
        identifier = clean_identifier(name)
        if not identifier:
            # The emptiness guard above runs on the RAW label, so a label of nothing but
            # dots ("...") passed it and then stripped to "". Re-check after cleaning:
            # an empty identifier is exactly what that guard exists to keep out.
            counters["nodes_missing_fields"] += 1
            continue
        snapped = snap_line_to_identifier(repo_path, path, line, identifier,
                                          counters, snap_cache)
        if snapped == -1:
            # Identifier not locatable at/near its citation: quarantine with the
            # engine's original line so a human can judge it — never the index.
            sidecar.append({"path": path, "line": line, "kind": kind,
                            "identifier": identifier, "engine": engine,
                            "confidence": confidence_of(node, counters)})
            counters["snap_miss_to_sidecar"] = \
                counters.get("snap_miss_to_sidecar", 0) + 1
            continue
        record = {"path": path, "line": snapped,
                  "kind": kind, "identifier": identifier,
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
        if is_framework_artifact(path):
            counters["framework_artifacts_excluded"] = \
                counters.get("framework_artifacts_excluded", 0) + 1
            continue
        # The edge inherits the weakest confidence among itself and both endpoints.
        # counters=None: edges have no confidence key by design, so counting them as
        # "absent" would swamp the node-level drift signal main() reports.
        conf = weakest_confidence(confidence_of(edge, None),
                                  src.get("confidence", "EXTRACTED"),
                                  dst.get("confidence", "EXTRACTED"))
        src_label, dst_label = clean_identifier(src_name), clean_identifier(dst_name)
        if not src_label or not dst_label:
            # Same trap as map_nodes: the guard above ran on the raw labels, so a
            # dots-only endpoint would have produced the identifier " -> ".
            counters["edges_unresolvable"] += 1
            continue
        record = {"path": path, "line": line, "kind": "dependency",
                  "identifier": f"{src_label} -> {dst_label}",
                  "engine": engine, "confidence": conf}
        _route(record, records, sidecar, counters)
    return records, sidecar


def find_graph_json(out_dir: Path) -> Optional[Path]:
    direct = out_dir / "graph.json"
    if direct.is_file():
        return direct
    hits = sorted(out_dir.rglob("graph.json"))
    return hits[0] if hits else None


CODE_GRAPH_NAME = "CODE_GRAPH.jsonl"
SIDECAR_NAME = "NEEDS_VERIFICATION.jsonl"
PROVENANCE_NAME = "CODE_INDEX_RECORDS.jsonl"
# Everything the adapter derives, cleared before every run. Keep in sync with the writes
# in main(); .gitignore is deliberately NOT here (it is ours and must survive).
DERIVED_ARTIFACTS = ("graphify-out", "graph.json",
                     CODE_GRAPH_NAME, SIDECAR_NAME, PROVENANCE_NAME)


def clear_engine_output(out_dir: Path) -> None:
    """Remove any previous run's engine output AND every artifact we derive from it.

    Without this, an engine run that fails and writes nothing leaves the last run's
    graph.json in place; find_graph_json() then picks it up and the adapter re-emits stale
    symbols stamped with the CURRENT engine version, which nothing downstream can detect.

    Clearing only the engine's own output is one layer short, because the derived JSONL
    files are written CONDITIONALLY (`if edge_records:` / `if sidecar:`). A run that fails,
    or that honestly produces zero dependency edges or zero INFERRED records, would leave
    the previous run's file sitting there stamped with the previous run's engine version --
    indistinguishable from fresh output. NEEDS_VERIFICATION.jsonl is the list an operator is
    told to verify before promoting records, so a stale one is actively misleading.
    """
    for name in DERIVED_ARTIFACTS:
        stale = out_dir / name
        try:
            if stale.is_dir():
                shutil.rmtree(stale, ignore_errors=True)
            elif stale.exists():
                stale.unlink()
        except OSError as exc:
            log(f"WARNING: could not remove stale {stale} ({exc}) — it may contain a "
                f"previous run's records; treat its contents as unverified")


def run_engine(repo_path: Path, out_dir: Path) -> bool:
    """Run the engine's code-only pass, then relocate its native graphify-out/
    directory under Generated/graphify/ so nothing lands in the repo root.

    Returns False on ANY failure -- a non-zero exit included -- so the caller emits nothing
    rather than falling through to whatever happens to be on disk.
    """
    default_cmd = default_engine_cmd()
    if cmd_override_honoured():
        raw_cmd = os.environ["GRAPHIFY_CMD"]
        log(f"WARNING: non-default engine command honoured "
            f"(GRAPHIFY_ALLOW_CMD_OVERRIDE=1): {raw_cmd}")
    else:
        raw_cmd = None
        if os.environ.get("GRAPHIFY_CMD"):
            log("GRAPHIFY_CMD is set but GRAPHIFY_ALLOW_CMD_OVERRIDE=1 is not (or the "
                "value equals the default) — ignoring the override and using the default "
                "engine command (an env var that picks the binary is a code-execution "
                "surface)")

    # The code-only invocation IS the egress guarantee, so these two are gated rather than
    # merely defaulted. Ungated, `GRAPHIFY_SUBCOMMAND=extract` reached the engine's LLM
    # path while the log line below still announced the code-only path.
    subcommand, extra_raw = "update", "--no-cluster"
    llm_path = False
    requested = {k: os.environ[k] for k in ("GRAPHIFY_SUBCOMMAND", "GRAPHIFY_ARGS")
                 if os.environ.get(k) is not None}
    if requested:
        if llm_path_unlocked():
            subcommand = os.environ.get("GRAPHIFY_SUBCOMMAND", subcommand)
            extra_raw = os.environ.get("GRAPHIFY_ARGS", extra_raw)
            llm_path = True
            log(f"WARNING: code-only invocation OVERRIDDEN "
                f"(GRAPHIFY_ALLOW_LLM_PATH=1): {requested} — the no-LLM egress guarantee "
                f"in this adapter's docstring DOES NOT APPLY to this run")
        else:
            log(f"ignoring {sorted(requested)} — GRAPHIFY_ALLOW_LLM_PATH=1 is not set. "
                f"The code-only invocation (update --no-cluster) is the egress guarantee, "
                f"so leaving it requires an explicit opt-in")
    try:
        cmd = shlex.split(raw_cmd or default_cmd)
        extra = shlex.split(extra_raw)
    except ValueError as exc:
        log(f"GRAPHIFY_CMD/GRAPHIFY_ARGS is not parseable as a shell command ({exc}) — "
            f"skipping cleanly, no records emitted")
        return False
    raw_timeout = os.environ.get("GRAPHIFY_TIMEOUT", "900")
    try:
        timeout = int(raw_timeout)
    except (TypeError, ValueError):
        log(f"GRAPHIFY_TIMEOUT={raw_timeout!r} is not an integer number of seconds — "
            f"skipping cleanly, no records emitted")
        return False
    if timeout <= 0:
        log(f"GRAPHIFY_TIMEOUT={raw_timeout!r} is not a positive number of seconds — "
            f"skipping cleanly, no records emitted")
        return False

    argv = cmd + [subcommand, str(repo_path)] + extra
    path_label = "OVERRIDDEN path — NOT the code-only guarantee" if llm_path else "code-only path"
    log(f"engine invocation ({path_label}, credential-stripped env, timeout {timeout}s): "
        f"{' '.join(argv)}")
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


def write_jsonl(path: Path, records: List[dict], description: str) -> None:
    """Write records as JSON-lines, or leave no file at all when there are none.

    clear_engine_output() has already removed any previous copy, so "no records" correctly
    means "no file" rather than "last run's file". A write failure is reported and skipped:
    guarantee 6 says an unwritable target repo makes the adapter skip, not crash.
    """
    if not records:
        return
    try:
        with path.open("w") as fh:
            for record in records:
                fh.write(json.dumps(record) + "\n")
    except OSError as exc:
        log(f"WARNING: could not write {path} ({exc}) — {description} was NOT persisted")
        return
    log(f"{path}: {description}")


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
    # of whatever graphifyy happens to be installed says nothing about it. Honoured requires
    # the double gate (GRAPHIFY_ALLOW_CMD_OVERRIDE=1) — a CMD set without the gate is ignored
    # by run_engine, so the packaged preflight still applies. cmd_override_honoured() is the
    # SAME predicate run_engine uses; asking the question two ways let GRAPHIFY_CMD="" skip
    # the floor here while the real packaged engine ran there.
    # GRAPHIFY_SKIP_PREFLIGHT=1 is the equivalent test seam without a custom command.
    custom_cmd = cmd_override_honoured()
    if custom_cmd or os.environ.get("GRAPHIFY_SKIP_PREFLIGHT") == "1":
        engine = os.environ.get("GRAPHIFY_ENGINE_ID", "graphifyy==unknown")
        reason = ("GRAPHIFY_CMD override honoured" if custom_cmd
                  else "GRAPHIFY_SKIP_PREFLIGHT=1 (test seam)")
        log(f"packaged version floor skipped — {reason}; provenance stamped as {engine}")
    else:
        # The engine needs Python >= 3.10. Check the interpreter that will actually RUN it
        # (GRAPHIFY_PYTHON, else a probed 3.10+ interpreter, else ours) — NOT this one.
        # Phase 1.5 invokes the adapter as bare `python3`, which is 3.9.6 on a stock macOS
        # box, so checking sys.version_info here made the feature unreachable through the
        # only path that invokes it.
        interpreter = engine_python()
        interpreter_version = python_version_of(interpreter)
        running = f"{sys.version_info[0]}.{sys.version_info[1]}"
        found = ("unusable" if interpreter_version is None
                 else f"{interpreter_version[0]}.{interpreter_version[1]}")
        if interpreter_version is None or interpreter_version < ENGINE_PY_FLOOR:
            log(f"graphifyy requires Python >= "
                f"{ENGINE_PY_FLOOR[0]}.{ENGINE_PY_FLOOR[1]}; no suitable interpreter was "
                f"found (this adapter runs under {running}; best candidate "
                f"{interpreter} is {found}; probed {', '.join(PYTHON_CANDIDATES)}) — "
                f"skipping cleanly. Point GRAPHIFY_PYTHON at a 3.10+ interpreter that has "
                f"the engine, or install it: {PIN_HINT}")
            return 0
        if interpreter != sys.executable:
            log(f"engine will run under {interpreter} ({found}), not this adapter's "
                f"interpreter ({sys.executable} = {running})")
        ver = engine_version(interpreter)
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
    try:
        out_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        # Guarantee 6: an unwritable target repo makes the adapter skip, not crash. The
        # Phase 1.5 hook ends in `|| true`, so a traceback here would be swallowed into a
        # log file and the conversion would silently lose the adapter with no diagnosis.
        log(f"cannot create {out_dir} ({exc}) — skipping cleanly, no records emitted")
        return 0
    ensure_output_ignored(out_dir)
    # Cleared HERE, not inside run_engine: every early return in run_engine (unparseable
    # command, bad timeout, engine failure) must also start from a blank slate, otherwise
    # the previous run's derived JSONL files survive looking current.
    clear_engine_output(out_dir)

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

    # Check the container BEFORE calling .get on it: a graph.json whose top level is a
    # JSON array (or a string, or a number) raised AttributeError here and exited 1,
    # which breaks the always-exit-0 convention guarantee 6 promises.
    if not isinstance(graph, dict):
        log(f"UNRECOGNIZED SCHEMA: graph.json top level is {type(graph).__name__}, "
            f"expected an object — no records emitted")
        return 0

    nodes = graph.get("nodes") or []
    edges = graph.get("edges") or graph.get("links") or []
    if not isinstance(nodes, list):
        log(f"UNRECOGNIZED SCHEMA: top-level keys {sorted(graph)[:12]} — no records emitted")
        return 0
    if not isinstance(edges, list):
        log(f"UNRECOGNIZED SCHEMA: `edges` is {type(edges).__name__}, expected a list — "
            f"mapping nodes only")
        edges = []

    counters = {"nodes_unparseable": 0, "nodes_missing_fields": 0,
                "inferred_to_sidecar": 0, "ambiguous_dropped": 0,
                "edges_unparseable": 0, "edges_non_dependency": 0,
                "edges_unresolvable": 0, "confidence_absent": 0,
                "confidence_present": 0, "vendor_excluded": 0}
    node_records, node_sidecar = map_nodes(nodes, repo_path, engine, counters)
    edge_records, edge_sidecar = map_edges(edges, counters, engine, repo_path)
    counters.pop("node_index", None)

    # Absent confidence is only a DRIFT signal when it is PARTIAL. On graphifyy==0.9.43
    # every node record lacks the field (measured: 100% absent on every repo tested), so
    # warning on a non-zero count meant warning on every clean run, at a count equal to the
    # whole node set -- telling the operator the schema had drifted from the very baseline
    # the README documents. Only edges are counted (nodes carry no field by design), and
    # only a partial count is a WARNING.
    absent = counters["confidence_absent"]
    mapped = absent + counters["confidence_present"]
    if absent and absent == mapped:
        log(f"confidence: all {absent} mapped node record(s) carried no `confidence` field "
            f"and defaulted to EXTRACTED. This is the expected baseline for {engine} — for "
            f"nodes the gate is a forward-compatible hook, not a filter.")
    elif absent:
        log(f"WARNING: {absent} of {mapped} mapped node record(s) carried no `confidence` "
            f"field and were treated as EXTRACTED, while {mapped - absent} did carry one. A "
            f"PARTIAL split is the actual schema-drift signal — {engine} is emitting the "
            f"field inconsistently and the gate is filtering only part of the output.")
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

    # Provenance would otherwise die at the Phase 1.5 boundary: the materialiser keeps only
    # the four contract fields, marks every row VERIFIED, and then rm -f's the extractor
    # file -- so nothing downstream records which CODE_INDEX.md rows came from a
    # third-party engine rather than our own extractors. Mirror the emitted records WITH
    # engine/confidence so that question stays answerable.
    write_jsonl(out_dir / PROVENANCE_NAME, node_records,
                f"provenance mirror of the {len(node_records)} stdout record(s) "
                f"(engine/confidence survive here; CODE_INDEX.md keeps only the "
                f"four contract fields)")

    write_jsonl(out_dir / CODE_GRAPH_NAME, edge_records,
                f"dependency edges ({len(edge_records)}) — kept out of CODE_INDEX.md to "
                f"protect the eager-load token budget")

    sidecar = node_sidecar + edge_sidecar
    write_jsonl(out_dir / SIDECAR_NAME, sidecar,
                f"INFERRED records quarantined ({len(sidecar)}) — verify before promoting "
                f"to the index")

    by_kind: Dict[str, int] = {}
    for record in node_records + edge_records:
        by_kind[record["kind"]] = by_kind.get(record["kind"], 0) + 1
    log(f"engine={engine} nodes_in={len(nodes)} edges_in={len(edges)} "
        f"stdout_records={len(node_records)} code_graph_records={len(edge_records)} "
        f"by_kind={by_kind} sidecar={len(sidecar)} counters={counters}")
    return 0


if __name__ == "__main__":
    # Last-resort net for guarantee 6. Every known failure mode above already returns 0,
    # but this adapter is optional by design: an unanticipated exception must degrade the
    # conversion to the bash/python extractors, never abort Phase 1.5 with a traceback the
    # hook's `|| true` would bury in a log file.
    try:
        sys.exit(main())
    except Exception as exc:  # noqa: BLE001 - deliberate catch-all, see above
        log(f"UNEXPECTED ERROR ({type(exc).__name__}: {exc}) — skipping cleanly, no "
            f"records emitted. The bash/python extractors remain the engines of record.")
        sys.exit(0)
