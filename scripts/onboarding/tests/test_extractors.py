"""
tests/test_extractors.py — Integration tests for scripts/onboarding extractors.

Each test uses a minimal fixture repo and validates that extractor output:
  1. Is valid JSON-lines (each line parses).
  2. Every record has path (non-empty), line (int > 0), kind (non-empty),
     identifier (non-empty).
  3. Expected kinds / values appear for the fixture.
  4. stderr is empty on happy-path runs.
  5. Edge cases: empty repos, SyntaxError Python, malformed JSON, .env files,
     Pydantic BaseSettings, application.properties, merge failure paths.

NOTE: the extractors all exit 0 — returncode==0 is a necessary but not
sufficient assertion. All substantive correctness checks are shape-based
(record contents) rather than exit-code-based.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parent.parent
FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"


# ─── helpers ────────────────────────────────────────────────────────────────

def run_bash(script: str, repo_path: Path) -> tuple[list[dict], str]:
    """Run a bash extractor. Returns (records, stderr)."""
    result = subprocess.run(
        ["bash", str(SCRIPTS_DIR / script), str(repo_path)],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, f"Script exited non-zero: {result.stderr}"
    records = []
    for line in result.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        records.append(json.loads(line))   # raises json.JSONDecodeError on bad JSON
    return records, result.stderr


def run_python(script: str, repo_path: Path) -> tuple[list[dict], str]:
    """Run a Python extractor. Returns (records, stderr)."""
    result = subprocess.run(
        [sys.executable, str(SCRIPTS_DIR / script), str(repo_path)],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, f"Script exited non-zero: {result.stderr}"
    records = []
    for line in result.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        records.append(json.loads(line))
    return records, result.stderr


def assert_valid_records(records: list[dict]) -> None:
    """Shape assertion: every record must satisfy the code-symbol contract."""
    for rec in records:
        assert "path" in rec and rec["path"], f"Missing path in {rec}"
        assert "line" in rec, f"Missing line in {rec}"
        assert isinstance(rec["line"], int) and rec["line"] > 0, f"Bad line in {rec}"
        assert "kind" in rec and rec["kind"], f"Missing kind in {rec}"
        assert "identifier" in rec and rec["identifier"], f"Missing identifier in {rec}"


# ─── Spring Boot fixture ─────────────────────────────────────────────────────

@pytest.fixture()
def spring_boot_repo(tmp_path: Path) -> Path:
    src = tmp_path / "src" / "main" / "java" / "com" / "example"
    src.mkdir(parents=True)
    (tmp_path / "pom.xml").write_text(
        "<project><groupId>com.example</groupId><artifactId>demo</artifactId></project>"
    )
    (src / "DemoApplication.java").write_text(textwrap.dedent("""\
        package com.example;
        import org.springframework.boot.autoconfigure.SpringBootApplication;

        @SpringBootApplication
        public class DemoApplication {
            public static void main(String[] args) {}
        }
    """))
    (src / "UserController.java").write_text(textwrap.dedent("""\
        package com.example;
        import org.springframework.web.bind.annotation.*;

        @RestController
        @RequestMapping("/api/users")
        public class UserController {
            @GetMapping("/")
            public String list() { return "[]"; }

            @PostMapping("/")
            public String create() { return "{}"; }
        }
    """))
    (src / "AppConfig.java").write_text(textwrap.dedent("""\
        package com.example;
        import org.springframework.beans.factory.annotation.Value;

        public class AppConfig {
            @Value("${app.secret}")
            private String secret;
        }
    """))
    # application.properties so we can verify property parsing
    resources = tmp_path / "src" / "main" / "resources"
    resources.mkdir(parents=True)
    (resources / "application.properties").write_text(textwrap.dedent("""\
        server.port=8080
        spring.datasource.url=jdbc:postgresql://localhost/mydb
        # comment line should be ignored
        app.feature-flag=true
    """))
    return tmp_path


def test_spring_boot_valid_records(spring_boot_repo: Path) -> None:
    records, _ = run_bash("extract_spring_boot.sh", spring_boot_repo)
    assert records, "No records emitted"
    assert_valid_records(records)


def test_spring_boot_happy_path_clean_stderr(spring_boot_repo: Path) -> None:
    _, stderr = run_bash("extract_spring_boot.sh", spring_boot_repo)
    assert stderr == "", f"Unexpected stderr on happy path: {stderr!r}"


def test_spring_boot_has_entry_point(spring_boot_repo: Path) -> None:
    records, _ = run_bash("extract_spring_boot.sh", spring_boot_repo)
    assert any(r["kind"] == "entry_point" for r in records)


def test_spring_boot_has_endpoints(spring_boot_repo: Path) -> None:
    records, _ = run_bash("extract_spring_boot.sh", spring_boot_repo)
    endpoints = [r for r in records if r["kind"] == "endpoint"]
    assert any("GET" in r["identifier"] for r in endpoints), "No GET endpoint found"
    assert any("POST" in r["identifier"] for r in endpoints), "No POST endpoint found"


def test_spring_boot_no_request_mapping_phantom_endpoints(spring_boot_repo: Path) -> None:
    """Class-level @RequestMapping must NOT produce endpoint rows (phantom inventory)."""
    records, _ = run_bash("extract_spring_boot.sh", spring_boot_repo)
    endpoints = [r for r in records if r["kind"] == "endpoint"]
    # The fixture has @RequestMapping("/api/users") at class level — it must not
    # appear as an 'ANY /api/users' endpoint row.
    assert not any(
        r["identifier"].startswith("ANY ") for r in endpoints
    ), "Class-level @RequestMapping produced a phantom endpoint row"


def test_spring_boot_request_mapping_emitted_as_config(spring_boot_repo: Path) -> None:
    """Class-level @RequestMapping IS captured as a config base-path record."""
    records, _ = run_bash("extract_spring_boot.sh", spring_boot_repo)
    configs = [r for r in records if r["kind"] == "config"]
    assert any(
        "RequestMapping" in r["identifier"] and "/api/users" in r["identifier"]
        for r in configs
    ), "Class-level @RequestMapping not captured as a config record"


def test_spring_boot_has_config(spring_boot_repo: Path) -> None:
    records, _ = run_bash("extract_spring_boot.sh", spring_boot_repo)
    configs = [r for r in records if r["kind"] == "config"]
    assert configs, "No config entries found"


def test_spring_boot_application_properties_parsed(spring_boot_repo: Path) -> None:
    """application.properties keys must appear as config entries."""
    records, _ = run_bash("extract_spring_boot.sh", spring_boot_repo)
    config_ids = [r["identifier"] for r in records if r["kind"] == "config"]
    assert any("server.port" in c for c in config_ids), \
        "server.port not found in config entries"
    # Comments must be excluded
    assert not any("#" in c for c in config_ids), "Commented line appeared in config"


def test_spring_boot_empty_repo(tmp_path: Path) -> None:
    """An empty directory must produce zero records, not crash."""
    records, stderr = run_bash("extract_spring_boot.sh", tmp_path)
    assert records == [], "Expected zero records for empty repo"
    assert stderr == "", f"Unexpected stderr for empty repo: {stderr!r}"


def test_spring_boot_special_chars_in_path(tmp_path: Path) -> None:
    """Route paths with quotes and backslashes must produce valid JSON."""
    src = tmp_path / "src" / "main" / "java"
    src.mkdir(parents=True)
    (src / "Tricky.java").write_text(textwrap.dedent('''\
        @GetMapping("/path/with-\\"quotes\\"")
        public String tricky() {}
    '''))
    records, _ = run_bash("extract_spring_boot.sh", tmp_path)
    # All records must parse (json.loads already ran in run_bash)
    assert_valid_records(records)


# ─── FastAPI fixture ──────────────────────────────────────────────────────────

@pytest.fixture()
def fastapi_repo(tmp_path: Path) -> Path:
    app_dir = tmp_path / "app"
    app_dir.mkdir()
    (app_dir / "__init__.py").write_text("")
    (app_dir / "main.py").write_text(textwrap.dedent("""\
        import os
        from fastapi import FastAPI

        app = FastAPI()

        @app.get("/health")
        async def health():
            return {"status": "ok"}

        @app.post("/users")
        async def create_user():
            db_url = os.getenv("DATABASE_URL")
            return {}
    """))
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    (tests_dir / "test_main.py").write_text(textwrap.dedent("""\
        def test_health():
            assert True
    """))
    return tmp_path


@pytest.fixture()
def fastapi_repo_with_settings(tmp_path: Path) -> Path:
    """FastAPI repo with Pydantic BaseSettings."""
    app_dir = tmp_path / "app"
    app_dir.mkdir()
    (app_dir / "__init__.py").write_text("")
    (app_dir / "config.py").write_text(textwrap.dedent("""\
        from pydantic import BaseSettings

        class Settings(BaseSettings):
            database_url: str
            secret_key: str
            debug: bool = False
    """))
    (app_dir / "main.py").write_text(textwrap.dedent("""\
        from fastapi import FastAPI
        app = FastAPI()

        @app.get("/ping")
        def ping():
            return "pong"
    """))
    return tmp_path


@pytest.fixture()
def fastapi_repo_with_syntax_error(tmp_path: Path) -> Path:
    """FastAPI repo where one .py file has a SyntaxError (tests regex fallback)."""
    app_dir = tmp_path / "app"
    app_dir.mkdir()
    (app_dir / "__init__.py").write_text("")
    (app_dir / "broken.py").write_text(textwrap.dedent("""\
        # This file is intentionally broken
        def foo(
        # missing closing paren
        @app.get("/broken")
        def handler():
            return {}
    """))
    (app_dir / "good.py").write_text(textwrap.dedent("""\
        import os
        from fastapi import FastAPI
        app = FastAPI()

        @app.get("/ok")
        def ok():
            return os.getenv("APP_KEY")
    """))
    return tmp_path


@pytest.fixture()
def fastapi_repo_with_verb_decorators(tmp_path: Path) -> Path:
    """Repo mixing real routes with non-route decorators that share an HTTP verb name.

    `routes.py` imports its `router`, so the binding is invisible in-file — the only
    thing separating its real PATCH route from `tests/test_things.py`'s `@mock.patch`
    is the shape of the argument.
    """
    app_dir = tmp_path / "app"
    app_dir.mkdir()
    (app_dir / "__init__.py").write_text("")
    (app_dir / "routes.py").write_text(textwrap.dedent("""\
        from .deps import router

        @router.patch("/things/{thing_id}")
        async def update_thing(thing_id: str):
            return {}

        @router.get("")
        async def list_things():
            return []
    """))
    (app_dir / "dynamic_routes.py").write_text(textwrap.dedent("""\
        from .deps import router
        from .settings import API_PREFIX, EXTERNAL_BASE

        @router.get(f"/{API_PREFIX}/items")
        async def list_items():
            return []

        @router.post(f"{EXTERNAL_BASE}/callbacks")
        async def register_callback():
            return {}
    """))
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    (tests_dir / "test_things.py").write_text(textwrap.dedent("""\
        from unittest import mock
        from unittest.mock import patch

        @mock.patch("app.routes.update_thing")
        @mock.patch.object(mock, "sentinel")
        @patch("app.deps.router")
        def test_update(mock_router, mock_sentinel, mock_update):
            assert True

        @responses.get("https://api.example.com/v1/things")
        @session.delete("things/1")
        def test_outbound():
            assert True
    """))
    return tmp_path


@pytest.fixture()
def fastapi_repo_with_app_factory(tmp_path: Path) -> Path:
    """`app = create_app()` — the application-factory idiom, alongside an imported `mock`.

    Neither decorator argument is a literal, so both rest entirely on the receiver signal.
    """
    app_dir = tmp_path / "app"
    app_dir.mkdir()
    (app_dir / "__init__.py").write_text("")
    (app_dir / "wsgi.py").write_text(textwrap.dedent("""\
        from unittest import mock

        from .factory import create_app
        from .settings import HEALTH_PATH, PATCH_TARGET

        app = create_app()

        @app.get(HEALTH_PATH)
        def health():
            return {}

        @mock.patch(PATCH_TARGET)
        def not_a_route():
            pass
    """))
    return tmp_path


@pytest.fixture()
def fastapi_repo_verb_decorators_unparseable(tmp_path: Path) -> Path:
    """Same collision, in a file that only the regex fallback ever sees."""
    app_dir = tmp_path / "app"
    app_dir.mkdir()
    (app_dir / "__init__.py").write_text("")
    (app_dir / "broken.py").write_text(textwrap.dedent("""\
        def foo(
        # missing closing paren

        @mock.patch("app.routes.update_thing")
        def test_update(mock_update):
            pass

        @graphs_router.patch("/graphs/{graph_id}")
        def update_graph(graph_id):
            pass
    """))
    return tmp_path


def test_fastapi_valid_records(fastapi_repo: Path) -> None:
    records, _ = run_python("extract_fastapi.py", fastapi_repo)
    assert records, "No records emitted"
    assert_valid_records(records)


def test_fastapi_happy_path_clean_stderr(fastapi_repo: Path) -> None:
    _, stderr = run_python("extract_fastapi.py", fastapi_repo)
    assert stderr == "", f"Unexpected stderr on happy path: {stderr!r}"


def test_fastapi_has_entry_point(fastapi_repo: Path) -> None:
    records, _ = run_python("extract_fastapi.py", fastapi_repo)
    assert any(r["kind"] == "entry_point" for r in records)


def test_fastapi_has_endpoints(fastapi_repo: Path) -> None:
    records, _ = run_python("extract_fastapi.py", fastapi_repo)
    endpoints = [r for r in records if r["kind"] == "endpoint"]
    assert any("/health" in r["identifier"] for r in endpoints)
    assert any("POST" in r["identifier"] for r in endpoints)


def test_fastapi_has_config(fastapi_repo: Path) -> None:
    records, _ = run_python("extract_fastapi.py", fastapi_repo)
    configs = [r for r in records if r["kind"] == "config"]
    assert any("DATABASE_URL" in r["identifier"] for r in configs)


def test_fastapi_has_test_location(fastapi_repo: Path) -> None:
    records, _ = run_python("extract_fastapi.py", fastapi_repo)
    assert any(r["kind"] == "test_location" for r in records)


def test_fastapi_pydantic_settings(fastapi_repo_with_settings: Path) -> None:
    """Pydantic BaseSettings fields must be emitted as config entries."""
    records, _ = run_python("extract_fastapi.py", fastapi_repo_with_settings)
    config_ids = [r["identifier"] for r in records if r["kind"] == "config"]
    assert any("database_url" in c for c in config_ids), \
        "Pydantic BaseSettings.database_url not found in config entries"
    assert any("secret_key" in c for c in config_ids), \
        "Pydantic BaseSettings.secret_key not found in config entries"


def test_fastapi_regex_fallback_on_syntax_error(fastapi_repo_with_syntax_error: Path) -> None:
    """Extractor must not crash on a SyntaxError file; good.py entries must still appear."""
    records, _ = run_python("extract_fastapi.py", fastapi_repo_with_syntax_error)
    assert_valid_records(records)
    # good.py endpoint must be present
    endpoint_ids = [r["identifier"] for r in records if r["kind"] == "endpoint"]
    assert any("/ok" in e for e in endpoint_ids), \
        "good.py endpoint missing after SyntaxError fallback"


@pytest.fixture()
def fastapi_repo_with_blueprint_unparseable(tmp_path: Path) -> Path:
    """A Flask `Blueprint()` factory call in a file only the regex fallback ever sees.

    The regex fallback's factory pattern is interpolated from `ROUTE_FACTORIES`
    (`FastAPI`, `Flask`, `APIRouter`, `Blueprint`), not a hardcoded copy — the copy it
    replaced was `r'(FastAPI|Flask|APIRouter)\\(\\)'` and never learned `Blueprint` when
    `ROUTE_FACTORIES` gained it (extract_fastapi.py "Both the verb list and the factory
    list are interpolated..." docstring). `ast.parse` also reads `ROUTE_FACTORIES`
    directly, so a well-formed file hides that drift; only a SyntaxError file, which
    routes through `extract_file_regex` alone, can observe it.
    """
    app_dir = tmp_path / "app"
    app_dir.mkdir()
    (app_dir / "__init__.py").write_text("")
    (app_dir / "broken_blueprint.py").write_text(textwrap.dedent("""\
        def foo(
        # missing closing paren

        bp = Blueprint()

        @bp.get("/widgets")
        def list_widgets():
            return []
    """))
    return tmp_path


def test_fastapi_regex_fallback_recognizes_blueprint_factory(
        fastapi_repo_with_blueprint_unparseable: Path) -> None:
    """Regression pin for the `ROUTE_FACTORIES`-derived regex fallback pattern.

    Reverting extract_fastapi.py's factory regex to the old hardcoded
    `r'(FastAPI|Flask|APIRouter)\\(\\)'` leaves every other test in this suite green —
    `Blueprint` is the only observable difference, and only through this SyntaxError
    fixture, which is why the gap existed unpinned.
    """
    records, _ = run_python("extract_fastapi.py", fastapi_repo_with_blueprint_unparseable)
    entry_points = [r["identifier"] for r in records if r["kind"] == "entry_point"]
    assert "Blueprint()" in entry_points, \
        f"Blueprint() entry_point missing from regex fallback: {entry_points}"


def test_fastapi_mock_patch_is_not_an_endpoint(
        fastapi_repo_with_verb_decorators: Path) -> None:
    """`@mock.patch("dotted.path")` must not be indexed as an HTTP PATCH route.

    Matching the verb without the receiver made a real FastAPI monorepo report 110
    PATCH endpoints against 2 genuine ones — 108 of them mock decorators in tests/.
    """
    records, _ = run_python("extract_fastapi.py", fastapi_repo_with_verb_decorators)
    endpoints = [r for r in records if r["kind"] == "endpoint"]
    assert not any("test_things.py" in r["path"] for r in endpoints), \
        f"Non-route decorator indexed as an endpoint: {endpoints}"
    assert not any(target in r["identifier"] for r in endpoints
                   for target in ("app.routes", "https://", "things/1")), \
        f"Mock / HTTP-client target indexed as an endpoint: {endpoints}"


def test_fastapi_route_on_imported_router_survives(
        fastapi_repo_with_verb_decorators: Path) -> None:
    """Recall guard: a real route whose router is imported has no in-file binding."""
    records, _ = run_python("extract_fastapi.py", fastapi_repo_with_verb_decorators)
    endpoint_ids = [r["identifier"] for r in records if r["kind"] == "endpoint"]
    assert "PATCH /things/{thing_id}" in endpoint_ids, \
        f"Genuine PATCH route on an imported router was dropped: {endpoint_ids}"


def test_fastapi_empty_decorator_path_is_dropped(
        fastapi_repo_with_verb_decorators: Path) -> None:
    """`@router.get("")` must produce no row — the identifier would be the bare `"GET "`.

    The prefix that makes such a route addressable lives on the `APIRouter()` call, not on
    the decorator, so the row would carry no path at all. Only the PATCH decorator on
    `routes.py:3` survives that file.
    """
    records, _ = run_python("extract_fastapi.py", fastapi_repo_with_verb_decorators)
    endpoints = [r for r in records if r["kind"] == "endpoint"]
    assert not any(r["identifier"].strip() in ("GET", "") for r in endpoints), \
        f"Pathless route decorator produced a malformed identifier: {endpoints}"
    routes_lines = sorted(r["line"] for r in endpoints
                          if Path(r["path"]).name == "routes.py")
    assert routes_lines == [3], \
        f'Expected only the PATCH route from routes.py:3, got lines {routes_lines}'


def test_fastapi_fstring_route_path_survives(
        fastapi_repo_with_verb_decorators: Path) -> None:
    """An f-string route path is an `ast.JoinedStr`; its leading "/" still proves the shape.

    Measured: `@self.router.post(f"/collections/{...}")` is the only route across five real
    Python services whose receiver no in-file binding resolves, and reading the shape off
    `ast.Constant` alone dropped it. The interpolated segments cannot be rendered, so the
    row reads "(dynamic)" — the same identifier the pre-gate extractor emitted for it.
    """
    records, _ = run_python("extract_fastapi.py", fastapi_repo_with_verb_decorators)
    dynamic = [(r["line"], r["identifier"]) for r in records
               if r["kind"] == "endpoint" and Path(r["path"]).name == "dynamic_routes.py"]
    assert dynamic == [(4, "GET (dynamic)")], \
        f'f-string route path mishandled (an f-string opening with an interpolation ' \
        f'exposes no "/" and must stay dropped): {dynamic}'


def test_fastapi_app_factory_route_survives(
        fastapi_repo_with_app_factory: Path) -> None:
    """`app = create_app()` binds a route object in-file; `from unittest import mock` does not.

    Both decorators take a computed argument, so the receiver is the only signal left.
    Restricting it to a literal `FastAPI()`/`APIRouter()` call dropped the genuine route.
    """
    records, _ = run_python("extract_fastapi.py", fastapi_repo_with_app_factory)
    endpoint_ids = [r["identifier"] for r in records if r["kind"] == "endpoint"]
    assert endpoint_ids == ["GET (dynamic)"], \
        f"Application-factory route lost, or @mock.patch admitted: {endpoint_ids}"
    assert not [r for r in records if r["kind"] == "entry_point"], \
        "Widening the route-object signal must not make every call binding an entry point"


def test_fastapi_regex_fallback_rejects_mock_patch(
        fastapi_repo_verb_decorators_unparseable: Path) -> None:
    """The fallback gates on path shape, so it widens the receiver without re-opening
    the false positive the AST path just closed."""
    records, _ = run_python(
        "extract_fastapi.py", fastapi_repo_verb_decorators_unparseable)
    assert_valid_records(records)
    endpoint_ids = [r["identifier"] for r in records if r["kind"] == "endpoint"]
    assert "PATCH /graphs/{graph_id}" in endpoint_ids, \
        f"Route on a non-'app'/'router' receiver was dropped: {endpoint_ids}"
    assert not any("update_thing" in e for e in endpoint_ids), \
        f"mock.patch target indexed as an endpoint: {endpoint_ids}"


def test_fastapi_empty_repo(tmp_path: Path) -> None:
    records, stderr = run_python("extract_fastapi.py", tmp_path)
    assert records == [], "Expected zero records for empty repo"
    assert stderr == "", f"Unexpected stderr for empty repo: {stderr!r}"


# ─── Express fixture ──────────────────────────────────────────────────────────

@pytest.fixture()
def express_repo(tmp_path: Path) -> Path:
    src = tmp_path / "src"
    src.mkdir()
    routes = src / "routes"
    routes.mkdir()
    (tmp_path / "package.json").write_text('{"name":"my-service","version":"1.0.0"}')
    (src / "app.ts").write_text(textwrap.dedent("""\
        import express from 'express';
        const app = express();
        export default app;
    """))
    (routes / "users.ts").write_text(textwrap.dedent("""\
        import { Router } from 'express';
        const router = Router();

        router.get('/users', (req, res) => res.json([]));
        router.post('/users', (req, res) => res.json({}));

        const PORT = process.env.PORT;
        export default router;
    """))
    (src / "users.spec.ts").write_text(textwrap.dedent("""\
        describe('users', () => {
            it('returns list', () => {});
        });
    """))
    return tmp_path


@pytest.fixture()
def express_repo_with_dotenv(tmp_path: Path) -> Path:
    """Express repo with a .env file."""
    src = tmp_path / "src"
    src.mkdir()
    (tmp_path / "package.json").write_text('{"name":"env-service","version":"1.0.0"}')
    (src / "index.ts").write_text("const app = require('express')();\n")
    # .env with an embedded = in the value (the Token Truncation Bug)
    (tmp_path / ".env").write_text(textwrap.dedent("""\
        DATABASE_URL=postgres://user:p%40ss=word@host/db
        SECRET_KEY=abc=def=ghi
        PORT=3000
        # comment should be ignored
    """))
    return tmp_path


def test_express_valid_records(express_repo: Path) -> None:
    records, _ = run_bash("extract_express.sh", express_repo)
    assert records, "No records emitted"
    assert_valid_records(records)


def test_express_happy_path_clean_stderr(express_repo: Path) -> None:
    _, stderr = run_bash("extract_express.sh", express_repo)
    assert stderr == "", f"Unexpected stderr on happy path: {stderr!r}"


def test_express_has_endpoints(express_repo: Path) -> None:
    records, _ = run_bash("extract_express.sh", express_repo)
    endpoints = [r for r in records if r["kind"] == "endpoint"]
    assert endpoints, "No endpoint records"


def test_express_has_config(express_repo: Path) -> None:
    records, _ = run_bash("extract_express.sh", express_repo)
    configs = [r for r in records if r["kind"] == "config"]
    assert any("PORT" in r["identifier"] for r in configs)


def test_express_has_test_location(express_repo: Path) -> None:
    records, _ = run_bash("extract_express.sh", express_repo)
    assert any(r["kind"] == "test_location" for r in records)


def test_express_dotenv_keys_extracted(express_repo_with_dotenv: Path) -> None:
    """.env keys must appear as config entries; comment lines must be excluded."""
    records, _ = run_bash("extract_express.sh", express_repo_with_dotenv)
    config_ids = [r["identifier"] for r in records if r["kind"] == "config"]
    assert any("DATABASE_URL" in c for c in config_ids), \
        "DATABASE_URL not found in .env config entries"
    assert any("SECRET_KEY" in c for c in config_ids), \
        "SECRET_KEY not found in .env config entries"
    assert any("PORT" in c for c in config_ids), \
        "PORT not found in .env config entries"
    assert not any("#" in c for c in config_ids), \
        "Comment line appeared in config entries"


def test_express_dotenv_keys_are_keys_only(express_repo_with_dotenv: Path) -> None:
    """Rule 11: key extraction must not include the value or the embedded = signs."""
    records, _ = run_bash("extract_express.sh", express_repo_with_dotenv)
    for rec in records:
        if rec["kind"] == "config" and rec["identifier"] in ("DATABASE_URL", "SECRET_KEY"):
            # The identifier should be the key name only, not include the value
            assert "=" not in rec["identifier"], \
                f"Value leaked into config identifier: {rec['identifier']!r}"


def test_express_empty_repo(tmp_path: Path) -> None:
    records, stderr = run_bash("extract_express.sh", tmp_path)
    assert records == [], "Expected zero records for empty repo"
    assert stderr == "", f"Unexpected stderr for empty repo: {stderr!r}"


def test_express_malformed_package_json(tmp_path: Path) -> None:
    """Malformed package.json must not crash the extractor."""
    src = tmp_path / "src"
    src.mkdir()
    (src / "app.ts").write_text("const app = require('express')();\n")
    (tmp_path / "package.json").write_text("{this is not valid json}")
    records, _ = run_bash("extract_express.sh", tmp_path)
    # Should still produce records from the .ts file; must not crash
    assert_valid_records(records)


# ─── Terraform fixture ────────────────────────────────────────────────────────

@pytest.fixture()
def terraform_repo(tmp_path: Path) -> Path:
    (tmp_path / "main.tf").write_text(textwrap.dedent("""\
        terraform {
          required_providers {
            aws = { source = "hashicorp/aws" }
          }
        }

        provider "aws" {
          region = var.region
        }

        variable "region" {
          default = "us-east-1"
        }

        module "vpc" {
          source = "./modules/vpc"
        }

        output "vpc_id" {
          value = module.vpc.id
        }
    """))
    return tmp_path


def test_terraform_valid_records(terraform_repo: Path) -> None:
    records, _ = run_bash("extract_terraform.sh", terraform_repo)
    assert records, "No records emitted"
    assert_valid_records(records)


def test_terraform_happy_path_clean_stderr(terraform_repo: Path) -> None:
    _, stderr = run_bash("extract_terraform.sh", terraform_repo)
    assert stderr == "", f"Unexpected stderr on happy path: {stderr!r}"


def test_terraform_has_module(terraform_repo: Path) -> None:
    records, _ = run_bash("extract_terraform.sh", terraform_repo)
    assert any(r["kind"] == "module" for r in records)


def test_terraform_has_config(terraform_repo: Path) -> None:
    records, _ = run_bash("extract_terraform.sh", terraform_repo)
    assert any(r["kind"] == "config" for r in records)


def test_terraform_has_integration(terraform_repo: Path) -> None:
    records, _ = run_bash("extract_terraform.sh", terraform_repo)
    assert any(r["kind"] == "integration" for r in records)


def test_terraform_empty_repo(tmp_path: Path) -> None:
    records, stderr = run_bash("extract_terraform.sh", tmp_path)
    assert records == [], "Expected zero records for empty repo"
    assert stderr == "", f"Unexpected stderr for empty repo: {stderr!r}"


def test_terraform_special_chars_in_identifier(tmp_path: Path) -> None:
    """Terraform resource names with special chars must produce valid JSON."""
    (tmp_path / "main.tf").write_text(textwrap.dedent("""\
        variable "db-connection_string%test" {
          description = "A tricky var name"
        }
    """))
    records, _ = run_bash("extract_terraform.sh", tmp_path)
    assert_valid_records(records)


# ─── merge_sme_contacts ───────────────────────────────────────────────────────

@pytest.fixture()
def git_repo(tmp_path: Path) -> Path:
    """Minimal git repo with one commit."""
    subprocess.run(["git", "init", str(tmp_path)], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(tmp_path), "config", "user.email", "test@example.com"],
                   check=True, capture_output=True)
    subprocess.run(["git", "-C", str(tmp_path), "config", "user.name", "Test User"],
                   check=True, capture_output=True)
    src = tmp_path / "src"
    src.mkdir()
    (src / "app.py").write_text("# hello\n")
    subprocess.run(["git", "-C", str(tmp_path), "add", "."], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(tmp_path), "commit", "-m", "init"],
                   check=True, capture_output=True)
    return tmp_path


def test_merge_sme_dry_run(git_repo: Path) -> None:
    result = subprocess.run(
        [sys.executable, str(SCRIPTS_DIR / "merge_sme_contacts.py"),
         "--repo-path", str(git_repo), "--dry-run"],
        capture_output=True, text=True,
    )
    assert result.returncode == 0
    assert "BEGIN AUTO" in result.stdout
    assert "END AUTO" in result.stdout


def test_merge_sme_dry_run_no_file_written(git_repo: Path) -> None:
    """--dry-run must not write anything to Knowledge/SME_CONTACTS.md."""
    output = git_repo / "Knowledge" / "SME_CONTACTS.md"
    subprocess.run(
        [sys.executable, str(SCRIPTS_DIR / "merge_sme_contacts.py"),
         "--repo-path", str(git_repo), "--dry-run"],
        capture_output=True, text=True, check=True,
    )
    assert not output.exists(), "--dry-run must not write to disk"


def test_merge_sme_creates_file(git_repo: Path, tmp_path: Path) -> None:
    output = tmp_path / "SME_CONTACTS.md"
    result = subprocess.run(
        [sys.executable, str(SCRIPTS_DIR / "merge_sme_contacts.py"),
         "--repo-path", str(git_repo), "--output", str(output)],
        capture_output=True, text=True,
    )
    assert result.returncode == 0
    assert output.exists()
    content = output.read_text()
    assert "BEGIN AUTO" in content
    assert "END AUTO" in content


def test_merge_sme_preserves_hand_rows(git_repo: Path, tmp_path: Path) -> None:
    output = tmp_path / "SME_CONTACTS.md"
    # First run
    subprocess.run(
        [sys.executable, str(SCRIPTS_DIR / "merge_sme_contacts.py"),
         "--repo-path", str(git_repo), "--output", str(output)],
        capture_output=True, text=True, check=True,
    )
    # Add a hand-authored row OUTSIDE the auto block (prepend before auto)
    content = output.read_text()
    content = "| Alice | Lead | auth | alice@example.com |\n\n" + content
    output.write_text(content)

    # Second run — hand row must survive
    subprocess.run(
        [sys.executable, str(SCRIPTS_DIR / "merge_sme_contacts.py"),
         "--repo-path", str(git_repo), "--output", str(output)],
        capture_output=True, text=True, check=True,
    )
    final = output.read_text()
    assert "alice@example.com" in final, "Hand-authored row was overwritten!"


def test_merge_sme_non_git_repo_exits_zero(tmp_path: Path) -> None:
    """merge_sme_contacts.py must exit 0 even for a non-git directory."""
    result = subprocess.run(
        [sys.executable, str(SCRIPTS_DIR / "merge_sme_contacts.py"),
         "--repo-path", str(tmp_path), "--dry-run"],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, \
        f"Must exit 0 for non-git repo, got {result.returncode}: {result.stderr}"


def test_merge_sme_output_is_valid_markdown(git_repo: Path, tmp_path: Path) -> None:
    """The generated file must contain the standard structural markers."""
    output = tmp_path / "SME_CONTACTS.md"
    subprocess.run(
        [sys.executable, str(SCRIPTS_DIR / "merge_sme_contacts.py"),
         "--repo-path", str(git_repo), "--output", str(output)],
        capture_output=True, text=True, check=True,
    )
    content = output.read_text()
    assert "<!-- BEGIN AUTO -->" in content
    assert "<!-- END AUTO -->" in content
    # Auto block must appear exactly once (structural markers only)
    assert content.count("<!-- BEGIN AUTO -->") == 1, \
        f"Expected 1 BEGIN AUTO marker, got {content.count('<!-- BEGIN AUTO -->')}"
    assert content.count("<!-- END AUTO -->") == 1
    # Auto block order: BEGIN before END
    assert content.index("<!-- BEGIN AUTO -->") < content.index("<!-- END AUTO -->")


# ─── T1 schema: ownership v2 + bot filtering ─────────────────────────────────

def assert_valid_ownership_records(records: list[dict]) -> None:
    """Shape assertion: every record must satisfy the T1 ownership schema."""
    required_fields = {
        "area", "original_architect", "current_maintainer",
        "codeowners_entry", "catalog_info_owner", "agreement",
        "derivation_date", "top_committers", "last_touched_date", "commit_count",
    }
    for rec in records:
        missing = required_fields - set(rec.keys())
        assert not missing, f"T1 schema fields missing in record {rec}: {missing}"
        assert rec["agreement"] in ("AGREE", "CONFLICTING", "SINGLE_SOURCE"), \
            f"Invalid agreement value in {rec}"
        # derivation_date must look like YYYY-MM-DD
        import re
        assert re.match(r"\d{4}-\d{2}-\d{2}", rec.get("derivation_date", "")), \
            f"derivation_date missing or malformed in {rec}"
        assert isinstance(rec["top_committers"], list), \
            f"top_committers must be a list in {rec}"
        assert isinstance(rec["commit_count"], int), \
            f"commit_count must be an int in {rec}"


def run_bash_ownership(repo_path: Path) -> tuple[list[dict], str]:
    """Run extract_git_ownership.sh and return (records, stderr)."""
    result = subprocess.run(
        ["bash", str(SCRIPTS_DIR / "extract_git_ownership.sh"), str(repo_path)],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, f"Script exited non-zero: {result.stderr}"
    records = []
    for line in result.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        records.append(json.loads(line))
    return records, result.stderr


@pytest.fixture()
def git_repo_with_human(tmp_path: Path) -> Path:
    """Git repo with one human committer and one bot committer."""
    subprocess.run(["git", "init", str(tmp_path)], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(tmp_path), "config", "user.email", "human@example.com"],
                   check=True, capture_output=True)
    subprocess.run(["git", "-C", str(tmp_path), "config", "user.name", "Human Dev"],
                   check=True, capture_output=True)
    src = tmp_path / "src"
    src.mkdir()
    (src / "app.py").write_text("# human work\n")
    subprocess.run(["git", "-C", str(tmp_path), "add", "."], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(tmp_path), "commit", "-m", "human commit"],
                   check=True, capture_output=True)
    return tmp_path


@pytest.fixture()
def git_repo_with_bot_only(tmp_path: Path) -> Path:
    """Git repo where only a bot has committed (all commits should be filtered)."""
    subprocess.run(["git", "init", str(tmp_path)], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(tmp_path), "config", "user.email", "renovate[bot]@noreply.github.com"],
                   check=True, capture_output=True)
    subprocess.run(["git", "-C", str(tmp_path), "config", "user.name", "renovate[bot]"],
                   check=True, capture_output=True)
    src = tmp_path / "src"
    src.mkdir()
    (src / "app.py").write_text("# bot work\n")
    subprocess.run(["git", "-C", str(tmp_path), "add", "."], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(tmp_path), "commit", "-m", "bot commit"],
                   check=True, capture_output=True)
    return tmp_path


def test_ownership_t1_schema(git_repo_with_human: Path) -> None:
    """extract_git_ownership.sh must emit records satisfying the T1 schema."""
    records, _ = run_bash_ownership(git_repo_with_human)
    assert records, "No records emitted for a valid git repo"
    assert_valid_ownership_records(records)


def test_ownership_t1_human_commit_present(git_repo_with_human: Path) -> None:
    """Human committer must appear in original_architect or current_maintainer."""
    records, _ = run_bash_ownership(git_repo_with_human)
    src_record = next((r for r in records if r["area"] == "src"), None)
    assert src_record is not None, "Expected a record for 'src' area"
    assert "Human Dev" in (src_record.get("original_architect") or "") or \
           "Human Dev" in (src_record.get("current_maintainer") or ""), \
        f"Human Dev not found in T1 fields: {src_record}"


def test_ownership_bot_filtered_from_top_committers(git_repo_with_bot_only: Path) -> None:
    """Bot-only repo must produce no records (all filtered, fail-closed)."""
    records, _ = run_bash_ownership(git_repo_with_bot_only)
    # Bot-only areas are silently dropped (fail-closed)
    for rec in records:
        committers_str = str(rec.get("top_committers", []))
        assert "renovate" not in committers_str.lower(), \
            f"Bot committer leaked into top_committers: {rec}"
        if rec.get("original_architect"):
            assert "renovate" not in rec["original_architect"].lower(), \
                f"Bot committer leaked into original_architect: {rec}"
        if rec.get("current_maintainer"):
            assert "renovate" not in rec["current_maintainer"].lower(), \
                f"Bot committer leaked into current_maintainer: {rec}"


def test_ownership_agreement_single_source_no_codeowners(git_repo_with_human: Path) -> None:
    """Without CODEOWNERS or catalog-info, agreement must be SINGLE_SOURCE."""
    records, _ = run_bash_ownership(git_repo_with_human)
    for rec in records:
        assert rec["agreement"] == "SINGLE_SOURCE", \
            f"Expected SINGLE_SOURCE when no external sources present: {rec}"


def test_ownership_derivation_date_present(git_repo_with_human: Path) -> None:
    """Every record must carry a derivation_date."""
    import re as _re
    records, _ = run_bash_ownership(git_repo_with_human)
    for rec in records:
        assert _re.match(r"\d{4}-\d{2}-\d{2}", rec.get("derivation_date", "")), \
            f"derivation_date missing or malformed: {rec}"


def test_merge_sme_t1_schema_in_output(git_repo: Path, tmp_path: Path) -> None:
    """merge_sme_contacts.py output must contain T1 schema column headers."""
    output = tmp_path / "SME_CONTACTS.md"
    subprocess.run(
        [sys.executable, str(SCRIPTS_DIR / "merge_sme_contacts.py"),
         "--repo-path", str(git_repo), "--output", str(output)],
        capture_output=True, text=True, check=True,
    )
    content = output.read_text()
    assert "Original Architect" in content, "T1 column 'Original Architect' missing"
    assert "Current Maintainer" in content, "T1 column 'Current Maintainer' missing"
    assert "Agreement" in content, "T1 column 'Agreement' missing"
    assert "Derivation Date" in content, "T1 column 'Derivation Date' missing"
    assert "CODEOWNERS" in content, "T1 column 'CODEOWNERS' missing"


def test_merge_sme_committer_names_with_special_chars(tmp_path: Path) -> None:
    """Committer names with quotes/backslashes must produce valid JSON from the ownership script."""
    subprocess.run(["git", "init", str(tmp_path)], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(tmp_path), "config", "user.email", 'tricky"user@example.com'],
                   check=True, capture_output=True)
    subprocess.run(["git", "-C", str(tmp_path), "config", "user.name", 'O\'Brien, "James"'],
                   check=True, capture_output=True)
    src = tmp_path / "src"
    src.mkdir()
    (src / "a.py").write_text("x = 1\n")
    subprocess.run(["git", "-C", str(tmp_path), "add", "."], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(tmp_path), "commit", "-m", "init"],
                   check=True, capture_output=True)

    result = subprocess.run(
        ["bash", str(SCRIPTS_DIR / "extract_git_ownership.sh"), str(tmp_path)],
        capture_output=True, text=True,
    )
    assert result.returncode == 0
    for line in result.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        # Must parse as valid JSON — not crash on special chars in committer name
        rec = json.loads(line)
        assert "area" in rec
        assert "top_committers" in rec
        assert isinstance(rec["top_committers"], list)


# ─── B16: repos with no src/ directory ───────────────────────────────────────

@pytest.fixture()
def express_repo_no_src(tmp_path: Path) -> Path:
    """Express repo with TypeScript files at root — no src/ dir (mr-tracker shape)."""
    (tmp_path / "package.json").write_text('{"name":"mr-tracker","version":"1.0.0"}')
    (tmp_path / "app.ts").write_text(textwrap.dedent("""\
        import express from 'express';
        const app = express();
        app.get('/health', (req, res) => res.json({status: 'ok'}));
        const PORT = process.env.PORT;
        export default app;
    """))
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    (tests_dir / "app.spec.ts").write_text("describe('app', () => { it('works', () => {}); });\n")
    return tmp_path


def test_b16_express_no_src_emits_records(express_repo_no_src: Path) -> None:
    """B16: Express extractor must emit records even when no src/ directory exists."""
    records, _ = run_bash("extract_express.sh", express_repo_no_src)
    assert records, "B16: Express extractor must emit records for a repo without src/"
    assert_valid_records(records)


def test_b16_express_no_src_finds_entry_point(express_repo_no_src: Path) -> None:
    """B16: express() at repo root must be found as an entry_point."""
    records, _ = run_bash("extract_express.sh", express_repo_no_src)
    assert any(r["kind"] == "entry_point" for r in records), \
        "B16: express() entry point at root not found"


def test_b16_express_no_src_finds_endpoint(express_repo_no_src: Path) -> None:
    """B16: app.get('/health') at repo root must be found as an endpoint."""
    records, _ = run_bash("extract_express.sh", express_repo_no_src)
    endpoints = [r for r in records if r["kind"] == "endpoint"]
    assert endpoints, "B16: No endpoints found in no-src/ Express repo"


# ─── B17: git ownership keyed by lowercased email ────────────────────────────

@pytest.fixture()
def git_repo_alias_committers(tmp_path: Path) -> Path:
    """Git repo with two display names for the same email (B17 alias case)."""
    subprocess.run(["git", "init", str(tmp_path)], check=True, capture_output=True)
    src = tmp_path / "src"
    src.mkdir()

    # First commit: display name "alice" (1 commit)
    subprocess.run(["git", "-C", str(tmp_path), "config", "user.email", "alice@example.com"],
                   check=True, capture_output=True)
    subprocess.run(["git", "-C", str(tmp_path), "config", "user.name", "alice"],
                   check=True, capture_output=True)
    (src / "a.py").write_text("x = 1\n")
    subprocess.run(["git", "-C", str(tmp_path), "add", "."], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(tmp_path), "commit", "-m", "init"],
                   check=True, capture_output=True)

    # Three more commits: display name "Alice Smith" (3 commits, same email)
    subprocess.run(["git", "-C", str(tmp_path), "config", "user.name", "Alice Smith"],
                   check=True, capture_output=True)
    for i in range(3):
        (src / f"b{i}.py").write_text(f"y = {i}\n")
        subprocess.run(["git", "-C", str(tmp_path), "add", "."], check=True, capture_output=True)
        subprocess.run(["git", "-C", str(tmp_path), "commit", "-m", f"commit {i}"],
                       check=True, capture_output=True)
    return tmp_path


def test_b17_email_dedup_commit_count(git_repo_alias_committers: Path) -> None:
    """B17: Two display names on same email → commit_count=4, not split."""
    records, _ = run_bash_ownership(git_repo_alias_committers)
    src_record = next((r for r in records if r["area"] == "src"), None)
    assert src_record is not None, "Expected a record for 'src' area"
    assert src_record["commit_count"] == 4, \
        f"B17: Expected commit_count=4 (email-deduped), got {src_record['commit_count']}"


def test_b17_top_committers_uses_most_frequent_display_name(git_repo_alias_committers: Path) -> None:
    """B17: The canonical name must be the most-frequent one (Alice Smith, 3 commits)."""
    records, _ = run_bash_ownership(git_repo_alias_committers)
    src_record = next((r for r in records if r["area"] == "src"), None)
    assert src_record is not None
    top = src_record.get("top_committers", [])
    assert top, "B17: top_committers must not be empty"
    assert "Alice Smith" in top[0], \
        f"B17: Expected 'Alice Smith' as top committer (3 commits), got {top[0]!r}"


# ─── symbol citations must land on the declaration, not a nearby mention ─────

GRAPHIFY_ADAPTER = SCRIPTS_DIR / "extract_graphify.py"


def graph_node(label: str, path: str, line: int) -> dict:
    """A graphifyy code-symbol node — `_callable` is how the engine flags a declaration."""
    return {"id": f"{path}#{line}#{label}", "label": label, "file_type": "code",
            "_callable": True, "source_file": path, "source_location": f"L{line}"}


def plain_node(label: str, path: str, line: int) -> dict:
    """A graphifyy node with NO `_callable` flag — the per-file nodes and, in languages
    with no parser here, enum constants and shell functions all arrive in this shape."""
    return {"id": f"{path}#{line}#{label}", "label": label, "file_type": "code",
            "source_file": path, "source_location": f"L{line}"}


def run_graphify(repo_path: Path, nodes: list[dict]) -> tuple[list[dict], list[dict]]:
    """Drive the Graphify adapter over `nodes` via a stub engine.

    Returns (index records from stdout, NEEDS_VERIFICATION.jsonl records). GRAPHIFY_CMD is
    double-gated on GRAPHIFY_ALLOW_CMD_OVERRIDE=1 because an env var that picks the binary
    is a code-execution surface, so the stub opts in exactly as an operator would; the whole
    GRAPHIFY_ namespace is dropped first so a knob exported in the developer's shell cannot
    change the outcome.
    """
    stub = repo_path.parent / "stub_engine.py"
    stub.write_text(
        "import pathlib, sys\n"
        "out = pathlib.Path(sys.argv[2]) / 'graphify-out'\n"
        "out.mkdir(parents=True, exist_ok=True)\n"
        f"(out / 'graph.json').write_text({json.dumps({'nodes': nodes})!r})\n"
    )
    env = {k: v for k, v in os.environ.items() if not k.startswith("GRAPHIFY_")}
    env.update({"GRAPHIFY_ADAPTER": "1",
                "GRAPHIFY_CMD": f"{sys.executable} {stub}",
                "GRAPHIFY_ALLOW_CMD_OVERRIDE": "1"})
    result = subprocess.run([sys.executable, str(GRAPHIFY_ADAPTER), str(repo_path)],
                            capture_output=True, text=True, env=env)
    assert result.returncode == 0, f"Adapter exited non-zero: {result.stderr}"
    records = [json.loads(line) for line in result.stdout.splitlines() if line.strip()]
    quarantine = repo_path / "Generated" / "graphify" / "NEEDS_VERIFICATION.jsonl"
    sidecar = ([json.loads(line) for line in quarantine.read_text().splitlines()
                if line.strip()] if quarantine.is_file() else [])
    return records, sidecar


@pytest.fixture()
def graphify_symbol_repo(tmp_path: Path) -> Path:
    """Declarations whose own line a name search cannot find.

    `store.py` is the sample-monorepo shape: `_` is a word character, so a word-boundary
    search for `campaign` matches neither `load_campaign_template` nor its own `def` line,
    while the NEXT function's docstring — four lines inside the ten-line snap window —
    says "campaign template" in prose. `routes.py` puts the name behind a decorator and
    `dispatch.py` gives one name to two classes. `s3_async.py` is the file-node shape:
    `s3` and `py` are too short for the gate's tokenizer, so `async` is the only word of
    the FILENAME a scan can look for, and line 1 does not contain it.
    """
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    (pkg / "store.py").write_text(textwrap.dedent("""\
        async def load_campaign_template(tenant_id: str):
            return None


        async def _load_acme_campaign_template(
            campaign_template_id: str,
        ) -> None:
            '''Load a single campaign template by campaign_template_id.'''
            return None
    """))
    (pkg / "routes.py").write_text(textwrap.dedent("""\
        import functools


        @functools.cache
        def resolve_settings():
            '''Resolve the settings mapping.'''
            return {}
    """))
    (pkg / "s3_async.py").write_text(textwrap.dedent("""\
        import asyncio

        TIMEOUT = 30


        async def _upload_file_async(key: str) -> None:
            await asyncio.sleep(TIMEOUT)
    """))
    (pkg / "dispatch.py").write_text(textwrap.dedent("""\
        class AlphaHandler:
            def dispatch(self, payload):
                return payload


        SEPARATOR = "-"


        class BetaHandler:
            def dispatch(self, payload):
                return payload
    """))
    src = tmp_path / "src"
    src.mkdir()
    (src / "Main.java").write_text(
        "package x;\nclass Main {\n  @Override\n  public void run() {\n  }\n}\n")
    return tmp_path


def test_graphify_symbol_cited_at_its_own_def_line(graphify_symbol_repo: Path) -> None:
    """Both symbols must be cited at their own `def`, not at the second one's docstring.

    The forward token scan walked past two correct engine citations onto the one line that
    spells "campaign template" with a space. On the sample-monorepo conversion 1,341 of
    2,069 handler rows cited something other than the declaration, 45 of them a line
    outside the named symbol altogether, and 16 locations were each published as the
    definition of two different symbols — all stamped VERIFIED.
    """
    records, _ = run_graphify(graphify_symbol_repo, [
        graph_node("load_campaign_template()", "pkg/store.py", 1),
        graph_node("_load_acme_campaign_template()", "pkg/store.py", 5),
    ])
    assert_valid_records(records)
    cited = {r["identifier"]: r["line"] for r in records}
    assert cited == {"load_campaign_template()": 1, "_load_acme_campaign_template()": 5}, \
        f"Symbols cited away from their own def lines: {cited}"


def test_graphify_decorated_symbol_cites_the_naming_line(graphify_symbol_repo: Path) -> None:
    """An engine citation of the decorator resolves to the `def`, which is the line the
    T3 gate scores and the only line that names the symbol."""
    records, _ = run_graphify(
        graphify_symbol_repo, [graph_node("resolve_settings()", "pkg/routes.py", 4)])
    assert [r["line"] for r in records] == [5], \
        f"Decorated def not resolved to its naming line: {records}"


def test_graphify_same_named_methods_keep_distinct_definitions(
        graphify_symbol_repo: Path) -> None:
    """Two classes, one method name: each record cites its own class's `def`."""
    records, _ = run_graphify(graphify_symbol_repo, [
        graph_node("dispatch()", "pkg/dispatch.py", 2),
        graph_node("dispatch()", "pkg/dispatch.py", 10),
    ])
    assert sorted(r["line"] for r in records) == [2, 10], \
        f"Same-named methods collapsed onto one definition: {records}"


def test_graphify_ambiguous_symbol_goes_to_the_sidecar(graphify_symbol_repo: Path) -> None:
    """A citation equidistant from two declarations of the same name is quarantined.

    Choosing one arbitrarily is what published 16 path:line locations as the definition of
    two symbols each, so the tie the nearest-candidate rule cannot break is not published.
    """
    records, sidecar = run_graphify(
        graphify_symbol_repo, [graph_node("dispatch()", "pkg/dispatch.py", 6)])
    assert records == [], f"Ambiguous symbol entered the index: {records}"
    assert [(r["identifier"], r["line"]) for r in sidecar] == [("dispatch()", 6)], \
        f"Ambiguous symbol missing from the sidecar at the engine's line: {sidecar}"


def test_graphify_symbol_absent_from_the_source_never_enters_the_index(
        graphify_symbol_repo: Path) -> None:
    """A name no declaration in the file answers to cannot be resolved, so it is
    quarantined rather than cited at whatever line happens to mention it."""
    records, sidecar = run_graphify(
        graphify_symbol_repo, [graph_node("ghost_handler()", "pkg/store.py", 1)])
    assert records == [], f"Unresolvable symbol entered the index: {records}"
    assert [r["identifier"] for r in sidecar] == ["ghost_handler()"], \
        f"Unresolvable symbol missing from the sidecar: {sidecar}"


def test_graphify_file_node_never_becomes_a_declaration(
        graphify_symbol_repo: Path) -> None:
    """A per-file node is dropped, so it can never be published as a symbol's definition.

    This is the sample-monorepo instance: the file node labelled `s3_async.py` has one
    gate-surviving word from its own filename, `async`; line 1 (`import asyncio`) does
    not match `\\basync\\b`, so the scan walked forward onto the `async def` below and
    published that line as the definition of BOTH the module and the handler. Four of the
    22 duplicated path:line locations on that conversion survived the declaration fix, and
    all four are this shape. Nor does it belong in the sidecar: no human review can turn
    "this file is named s3_async.py" into a declaration citation.
    """
    records, sidecar = run_graphify(graphify_symbol_repo, [
        plain_node("s3_async.py", "pkg/s3_async.py", 1),
        graph_node("_upload_file_async()", "pkg/s3_async.py", 6),
    ])
    assert [(r["identifier"], r["line"]) for r in records] == \
        [("_upload_file_async()", 6)], f"File node reached the index: {records}"
    assert sidecar == [], f"File node quarantined instead of dropped: {sidecar}"


def test_graphify_named_python_non_declaration_still_uses_the_token_scan(
        graphify_symbol_repo: Path) -> None:
    """Only the file node is dropped, not every non-declaration node in a Python file.

    A module-level constant is named by a line even though `ast`'s def/class walk does
    not collect it, so the bounded forward scan stays its rule: cited one line early, it
    resolves to `TIMEOUT = 30` rather than being dropped or quarantined.
    """
    records, sidecar = run_graphify(
        graphify_symbol_repo, [plain_node("TIMEOUT", "pkg/s3_async.py", 2)])
    assert [(r["kind"], r["line"]) for r in records] == [("module", 3)], \
        f"Named non-declaration node not resolved by the token scan: {records}"
    assert sidecar == []


def test_graphify_annotated_java_still_snaps_forward(graphify_symbol_repo: Path) -> None:
    """The token scan remains the rule for a language no parser here can read: an
    `@Override` citation still snaps to the declaration below it."""
    records, _ = run_graphify(
        graphify_symbol_repo, [graph_node(".run()", "src/Main.java", 3)])
    assert [r["line"] for r in records] == [4], \
        f"Annotated-Java snap regressed: {records}"
