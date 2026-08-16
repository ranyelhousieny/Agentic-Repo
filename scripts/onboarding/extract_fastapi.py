#!/usr/bin/env python3
"""
extract_fastapi.py — FastAPI / Python code-index extractor

Usage:
    python3 scripts/onboarding/extract_fastapi.py <REPO_PATH>

Stdout contract: one JSON-lines record per discovered symbol, e.g.:
    {"path":"app/main.py","line":15,"kind":"endpoint","identifier":"GET /api/users"}

kind values:
    module        — top-level Python package (directory with __init__.py)
    entry_point   — FastAPI() / Flask() / APIRouter() / Blueprint() instantiation
    endpoint      — route decorator: @app.get/post/put/delete/patch, @router.*
    config        — os.getenv / os.environ key, Pydantic BaseSettings field
    integration   — httpx.AsyncClient / requests.get/post, external service calls
    test_location — test file (test_*.py / *_test.py)

Fail-closed: entries without a verifiable file:line are SILENTLY DROPPED.
Exit 0 always (partial output is valid).

Requires: python3 3.9+
"""

from __future__ import annotations

import ast
import json
import os
import re
import sys
from pathlib import Path
from typing import Optional

def emit(path: str, line: int, kind: str, identifier: str) -> None:
    """Print one JSON-lines record; drop silently if any field is invalid.

    Fail-closed contract:
    - path must be a non-empty string
    - line must be an int > 0  (str(0)=="0" is truthy — checked explicitly)
    - kind and identifier must be non-empty strings
    """
    if not (path and isinstance(line, int) and line > 0 and kind and identifier):
        return
    print(json.dumps({"path": path, "line": line, "kind": kind,
                      "identifier": identifier}))

def rel(repo_root: Path, p: Path) -> str:
    try:
        return str(p.relative_to(repo_root))
    except ValueError:
        return str(p)

# ── AST-based extraction ──────────────────────────────────────────────────────

ROUTE_METHODS = {"get", "post", "put", "delete", "patch", "head", "options"}
ROUTE_FACTORIES = {"FastAPI", "Flask", "APIRouter", "Blueprint"}


def called_factory(value: Optional[ast.expr]) -> str:
    """Name of the route-object factory `value` calls, or "" if it calls none."""
    if not isinstance(value, ast.Call):
        return ""
    func = value.func
    if isinstance(func, ast.Name):
        name = func.id
    elif isinstance(func, ast.Attribute):
        name = func.attr
    else:
        return ""
    return name if name in ROUTE_FACTORIES else ""


def collect_route_objects(tree: ast.Module) -> set[str]:
    """Names this module binds to the result of a call — its candidate route objects.

    Requiring a literal `FastAPI()` / `Flask()` / `APIRouter()` / `Blueprint()` call
    recognises the object only where it is constructed inline, so the application-factory
    idiom Flask documents (`app = create_app()`) binds a route object in-file and still
    resolves to nothing. Any call binding counts instead, because the false positives this
    signal exists to reject decorate an IMPORTED name — all 108 measured on a real FastAPI
    monorepo were `@mock.patch` against `from unittest import mock` — and an import is not
    a call binding. Measured cost of the wider rule: 0 added rows across five real Python
    services. Resolving what `create_app` returns is the call-graph step this deliberately
    does not take; the name is only ever a fallback signal (below).

    A positive signal only, never a veto: a router module that does
    `from .main import fastapi_app` binds nothing locally yet still declares real
    routes (measured on a real FastAPI monorepo: `@fastapi_app.get("/raise-exception")`
    in a tests/ file whose `fastapi_app` comes from another package).
    """
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call):
            names.update(t.id for t in node.targets if isinstance(t, ast.Name))
        elif isinstance(node, ast.AnnAssign) and isinstance(node.value, ast.Call):
            if isinstance(node.target, ast.Name):
                names.add(node.target.id)
    return names


def literal_path_prefix(arg: Optional[ast.expr]) -> Optional[str]:
    """The literal text a decorator argument is known to begin with, else None.

    An f-string route path is an `ast.JoinedStr`, so its leading "/" sits in `values[0]`
    rather than on the node itself — visible proof of shape that reading only `ast.Constant`
    throws away. Measured: `@self.router.post(f"/collections/{...}")` is the one route in
    five real Python services whose receiver no in-file binding can resolve, and skipping
    the shape test on `JoinedStr` dropped it. An f-string that opens with an interpolation
    (`f"{BASE}/callbacks"`) exposes no such text and returns None, so it falls to the
    receiver signal like any other computed argument.
    """
    if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
        return arg.value
    if isinstance(arg, ast.JoinedStr) and arg.values:
        head = arg.values[0]
        if isinstance(head, ast.Constant) and isinstance(head.value, str):
            return head.value
    return None


def looks_like_route_path(value: str) -> bool:
    """Whether a decorator argument's literal text is shaped like a mountable route path.

    Both frameworks enforce the shape at runtime — Starlette's `Route.__init__` asserts
    `path.startswith("/")`, Werkzeug's `Rule` rejects a rule without a leading slash — so
    a literal that is not "/"-rooted cannot be a route whatever it decorates. That is what
    separates `@router.patch("/workflows/{workflow_id}")` from
    `@mock.patch("campaign_ws.deploy_templates._deploy_template")`, and unlike receiver
    resolution it still holds when the route object was imported from another module.
    A `requests.post("https://…")` / `httpx.get("https://…")` target fails it too.

    The empty path a prefixed APIRouter accepts for its own root fails on purpose: the
    prefix lives on the `APIRouter()` call, not on the decorator, so the row would carry
    no path at all (measured on a real FastAPI monorepo: all 5 such decorators sit one
    line from a `("/")` twin on the same handler, which is indexed instead).
    """
    return value.startswith("/")


def route_from_decorator(decorator: ast.expr,
                         route_objects: set[str]) -> Optional[tuple[str, str]]:
    """(METHOD, path) for a genuine route decorator, else None.

    Accepting any `@<anything>.get/post/put/delete/patch/head/options(...)` treats the
    HTTP verb as a property of the attribute name when it is really a property of the
    receiver. Measured cost on a real FastAPI monorepo: 110 of 254 endpoint rows carried
    PATCH against 2 genuine PATCH routes, because 108 `@mock.patch("dotted.python.path")`
    decorators in tests/ parse identically — a 55x overstatement of the PATCH surface.

    A path with literal text carries its own proof and is judged on shape alone; only its
    full-literal form can be reported, an interpolated one reads "(dynamic)". A path with
    no literal text carries none, so it falls back to the other signal: the receiver being
    a name this module binds. That fallback needs `func.value` to be an `ast.Name`, which
    rules out `@self.router.get(...)` — resolving that would mean finding the enclosing
    class's `self.router = APIRouter()`, and it buys nothing measurable: a decorator on
    `self` can only run inside a method body, and the sole instance across five real Python
    services writes its path literally, so the shape test admits it whatever the receiver.
    """
    if not isinstance(decorator, ast.Call):
        return None
    func = decorator.func
    if not isinstance(func, ast.Attribute) or func.attr not in ROUTE_METHODS:
        return None

    arg: Optional[ast.expr] = decorator.args[0] if decorator.args else next(
        (kw.value for kw in decorator.keywords if kw.arg in ("path", "rule")), None)
    prefix = literal_path_prefix(arg)
    if prefix is not None:
        if not looks_like_route_path(prefix):
            return None
        return func.attr.upper(), prefix if isinstance(arg, ast.Constant) else "(dynamic)"
    if not (isinstance(func.value, ast.Name) and func.value.id in route_objects):
        return None
    return func.attr.upper(), "(dynamic)" if arg is not None else "(unmapped)"


def extract_file(repo_root: Path, filepath: Path) -> None:
    rel_path = rel(repo_root, filepath)
    source = ""  # initialize before try so it's always bound for the fallback
    try:
        source = filepath.read_text(encoding="utf-8", errors="replace")
        tree = ast.parse(source, filename=str(filepath))
    except (SyntaxError, OSError):
        # Fall back to regex extraction for unparseable files
        extract_file_regex(repo_root, filepath, source)
        return

    lines = source.splitlines()
    route_objects = collect_route_objects(tree)

    for node in ast.walk(tree):
        # ── entry points ──────────────────────────────────────────────────
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    func_name = called_factory(node.value)
                    if func_name:
                        emit(rel_path, node.lineno, "entry_point",
                             f"{target.id} = {func_name}()")

        # ── route decorators ──────────────────────────────────────────────
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for decorator in node.decorator_list:
                route = route_from_decorator(decorator, route_objects)
                if route:
                    emit(rel_path, decorator.lineno, "endpoint",
                         f"{route[0]} {route[1]}")

        # ── config: os.getenv / os.environ ────────────────────────────────
        if isinstance(node, ast.Call):
            func = node.func
            # os.getenv("KEY") or os.environ.get("KEY")
            if isinstance(func, ast.Attribute):
                if (hasattr(func, "value") and isinstance(func.value, ast.Name) and
                        func.value.id == "os" and func.attr == "getenv"):
                    if node.args and isinstance(node.args[0], ast.Constant):
                        # Use .value (Python 3.8+); .s is deprecated in 3.12
                        key_val = node.args[0].value
                        if isinstance(key_val, str):
                            emit(rel_path, node.lineno, "config",
                                 f"os.getenv(\"{key_val}\")")

        # ── integration: httpx / requests ─────────────────────────────────
        if isinstance(node, (ast.Assign, ast.Expr, ast.AnnAssign)):
            line_no = node.lineno
            line_txt = lines[line_no - 1] if line_no <= len(lines) else ""
            for client in ("httpx", "requests", "aiohttp"):
                if client in line_txt:
                    # Grab the method call hint
                    m = re.search(r"(httpx|requests|aiohttp)\.[A-Za-z_]+", line_txt)
                    if m:
                        emit(rel_path, line_no, "integration", m.group(0))


def extract_file_regex(repo_root: Path, filepath: Path, source: str = "") -> None:
    """Regex fallback for files that fail AST parsing.

    The route pattern gates on path shape rather than on a two-name receiver allowlist
    (`app|router`), which silently dropped every other route object a real FastAPI
    monorepo uses — `graphs_router`, `executions_router`, `runs_router`, `fastapi_app`
    carry 28 of its genuine routes. Shape is the gate the AST path also applies, so a
    `@mock.patch("dotted.python.path")` line cannot slip through the wider receiver;
    a non-path match formats to "" and `emit` drops it under the fail-closed contract.

    Both the verb list and the factory list are interpolated from the module constants:
    a hardcoded copy is a list that drifts, and this one already had — it never learned
    `Blueprint` when `ROUTE_FACTORIES` gained it.
    """
    if not source:
        try:
            source = filepath.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return
    rel_path = rel(repo_root, filepath)
    verbs = "|".join(sorted(ROUTE_METHODS))
    factories = "|".join(sorted(ROUTE_FACTORIES))
    for lineno, line in enumerate(source.splitlines(), start=1):
        for pat, kind, fmt in [
            (rf'^\s*@[A-Za-z_][A-Za-z0-9_.]*\.({verbs})\("([^"]*)"',
             "endpoint",
             lambda m: (f"{m.group(1).upper()} {m.group(2)}"
                        if looks_like_route_path(m.group(2)) else "")),
            (r'os\.getenv\("([^"]+)"', "config",
             lambda m: f'os.getenv("{m.group(1)}")'),
            (rf'({factories})\(\)', "entry_point",
             lambda m: m.group(0)),
            (r'(httpx|requests|aiohttp)\.\w+', "integration",
             lambda m: m.group(0)),
        ]:
            m = re.search(pat, line)
            if m:
                emit(rel_path, lineno, kind, fmt(m))


# ── Pydantic BaseSettings (config) ───────────────────────────────────────────

def extract_pydantic_settings(repo_root: Path, filepath: Path) -> None:
    rel_path = rel(repo_root, filepath)
    try:
        source = filepath.read_text(encoding="utf-8", errors="replace")
        tree = ast.parse(source)
    except (SyntaxError, OSError):
        return

    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            # Check if class inherits from BaseSettings
            bases = [
                (b.id if isinstance(b, ast.Name) else
                 b.attr if isinstance(b, ast.Attribute) else "")
                for b in node.bases
            ]
            if "BaseSettings" in bases:
                for item in node.body:
                    if isinstance(item, ast.AnnAssign):
                        if isinstance(item.target, ast.Name):
                            emit(rel_path, item.lineno, "config",
                                 f"{node.name}.{item.target.id}")


def first_line_matching(path: Path, patterns: list, fallback_token: str = "") -> int:
    """1-based line number of the first line matching any pattern, else the first
    line containing fallback_token as a word, else 0 (= no verifiable line).

    Exists because the T3 citation gate requires token overlap between a record's
    identifier and the EXACT cited line. A blanket `:1` cites a shebang, an import,
    or nothing at all (95 of this repo's `__init__.py` files are EMPTY) — measured
    on a real FastAPI service: 344 of 2,858 index records failed the gate purely
    on unverifiable `:1` citations from this extractor.

    The fallback searches for the token's snake_case WORDS, not the whole token:
    the gate tokenizer does not split camelCase, so a `class TestDocsClient:` line
    can never verify the identifier `test_docs_client` — but the import line
    `from ...docs_client import ...` shares the words and verifies (measured: 27
    class-only test files failed on exactly this before the word-level fallback).
    """
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return 0
    for i, text in enumerate(lines, 1):
        if any(re.match(p, text) for p in patterns):
            return i
    if fallback_token:
        words = [w for w in re.split(r"[^a-zA-Z0-9]+", fallback_token)
                 if len(w) >= 3 and w.lower() not in ("test", "tests")]
        if not words:
            words = [fallback_token]
        word_res = [re.compile(r"\b" + re.escape(w) + r"\b") for w in words]
        for i, text in enumerate(lines, 1):
            if any(wr.search(text) for wr in word_res):
                return i
    return 0


# ── main ─────────────────────────────────────────────────────────────────────

def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: extract_fastapi.py <REPO_PATH>", file=sys.stderr)
        sys.exit(1)
    repo_root = Path(sys.argv[1]).resolve()

    # ── modules (packages with __init__.py) ──────────────────────────────
    for init_py in repo_root.rglob("__init__.py"):
        # Skip venv, .git, __pycache__
        parts = init_py.parts
        if any(p in parts for p in (".git", "venv", ".venv", "__pycache__",
                                     "node_modules", ".tox", "dist", "build")):
            continue
        pkg_dir = init_py.parent
        # A package record must cite a line its name can be verified against.
        # Empty __init__.py (the common case) has no such line — the package
        # structure is already navigable via the per-file records and the
        # dependency graph, so an unverifiable row would only fail the gate.
        line = first_line_matching(init_py, [], fallback_token=pkg_dir.name)
        if line:
            emit(rel(repo_root, init_py), line, "module", pkg_dir.name)

    # ── Python source files ───────────────────────────────────────────────
    for py_file in repo_root.rglob("*.py"):
        parts = py_file.parts
        if any(p in parts for p in (".git", "venv", ".venv", "__pycache__",
                                     "node_modules", ".tox", "dist", "build")):
            continue
        # Route Pydantic settings classes through dedicated extractor
        try:
            src = py_file.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if "BaseSettings" in src:
            extract_pydantic_settings(repo_root, py_file)
        # General extraction
        extract_file(repo_root, py_file)

    # ── test locations ────────────────────────────────────────────────────
    # Cite the first test definition (its `def test_...` / `class Test...` text
    # shares the "test" token with the identifier), falling back to any line
    # carrying the file's stem; a bare `:1` cites an import or a shebang and
    # fails the gate for a file that genuinely exists.
    seen_tests = set()
    for pattern in ("test_*.py", "*_test.py"):
        for test_file in repo_root.rglob(pattern):
            parts = test_file.parts
            if any(p in parts for p in (".git", "venv", ".venv", "__pycache__")):
                continue
            if test_file in seen_tests:
                continue
            seen_tests.add(test_file)
            # `def test_...` lines share snake tokens with the identifier; a
            # `class TestX:` line is camelCase and can never verify a snake
            # identifier under the gate tokenizer, so it is NOT a pattern here —
            # class-only files resolve through the word-level fallback instead
            # (their import lines carry the snake words).
            line = first_line_matching(
                test_file,
                [r"\s*def test_", r"\s*async def test_"],
                fallback_token=test_file.stem,
            )
            # No verifiable line (empty file, or camelCase-only content that the
            # gate tokenizer cannot match to a snake identifier) -> no row: a
            # guaranteed-failing citation helps nobody, and the file stays
            # discoverable through the document index.
            if line:
                emit(rel(repo_root, test_file), line, "test_location", test_file.stem)


if __name__ == "__main__":
    main()
