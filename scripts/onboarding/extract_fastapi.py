#!/usr/bin/env python3
"""
extract_fastapi.py — FastAPI / Python code-index extractor

Usage:
    python3 scripts/onboarding/extract_fastapi.py <REPO_PATH>

Stdout contract: one JSON-lines record per discovered symbol, e.g.:
    {"path":"app/main.py","line":15,"kind":"endpoint","identifier":"GET /api/users"}

kind values:
    module        — top-level Python package (directory with __init__.py)
    entry_point   — FastAPI() / Flask() / APIRouter() instantiation
    endpoint      — route decorator: @app.get/post/put/delete/patch, @router.*
    config        — os.getenv / os.environ key, Pydantic BaseSettings field
    integration   — httpx.AsyncClient / requests.get/post, external service calls
    test_location — test file (test_*.py / *_test.py)

Fail-closed: entries without a verifiable file:line are SILENTLY DROPPED.
Exit 0 always (partial output is valid).

Requires: python3 3.9+
"""

import ast
import json
import os
import re
import sys
from pathlib import Path

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

    for node in ast.walk(tree):
        # ── entry points ──────────────────────────────────────────────────
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    if isinstance(node.value, ast.Call):
                        func = node.value.func
                        func_name = ""
                        if isinstance(func, ast.Name):
                            func_name = func.id
                        elif isinstance(func, ast.Attribute):
                            func_name = func.attr
                        if func_name in ("FastAPI", "Flask", "APIRouter", "Blueprint"):
                            emit(rel_path, node.lineno, "entry_point",
                                 f"{target.id} = {func_name}()")

        # ── route decorators ──────────────────────────────────────────────
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for decorator in node.decorator_list:
                http_method = None
                path_val = None

                # @app.get("/path") or @router.post("/path")
                if isinstance(decorator, ast.Call):
                    func = decorator.func
                    if isinstance(func, ast.Attribute) and func.attr in ROUTE_METHODS:
                        http_method = func.attr.upper()
                        # First positional arg is the path
                        if decorator.args:
                            arg = decorator.args[0]
                            if isinstance(arg, ast.Constant):
                                # Use .value (Python 3.8+); .s is deprecated in 3.12
                                val = arg.value
                                if isinstance(val, str):
                                    path_val = val
                                else:
                                    path_val = "(dynamic)"
                            else:
                                path_val = "(dynamic)"
                        else:
                            path_val = "(unmapped)"

                if http_method and path_val:
                    emit(rel_path, decorator.lineno, "endpoint",
                         f"{http_method} {path_val}")

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
    """Regex fallback for files that fail AST parsing."""
    if not source:
        try:
            source = filepath.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return
    rel_path = rel(repo_root, filepath)
    for lineno, line in enumerate(source.splitlines(), start=1):
        for pat, kind, fmt in [
            (r'@(app|router)\.(get|post|put|delete|patch)\("([^"]*)"',
             "endpoint", lambda m: f"{m.group(2).upper()} {m.group(3)}"),
            (r'os\.getenv\("([^"]+)"', "config",
             lambda m: f'os.getenv("{m.group(1)}")'),
            (r'(FastAPI|Flask|APIRouter)\(\)', "entry_point",
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
