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
        emit(rel(repo_root, init_py), 1, "module", pkg_dir.name)

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
    for test_file in repo_root.rglob("test_*.py"):
        parts = test_file.parts
        if any(p in parts for p in (".git", "venv", ".venv", "__pycache__")):
            continue
        emit(rel(repo_root, test_file), 1, "test_location", test_file.stem)
    for test_file in repo_root.rglob("*_test.py"):
        parts = test_file.parts
        if any(p in parts for p in (".git", "venv", ".venv", "__pycache__")):
            continue
        emit(rel(repo_root, test_file), 1, "test_location", test_file.stem)


if __name__ == "__main__":
    main()
