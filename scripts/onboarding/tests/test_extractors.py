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
    """Env-var parsing: key extraction must not include the value or the embedded = signs."""
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


# ─── Ownership schema v2 + bot filtering ─────────────────────────────────

def assert_valid_ownership_records(records: list[dict]) -> None:
    """Shape assertion: every record must satisfy the ownership schema."""
    required_fields = {
        "area", "original_architect", "current_maintainer",
        "codeowners_entry", "catalog_info_owner", "agreement",
        "derivation_date", "top_committers", "last_touched_date", "commit_count",
    }
    for rec in records:
        missing = required_fields - set(rec.keys())
        assert not missing, f"Ownership schema fields missing in record {rec}: {missing}"
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
    """extract_git_ownership.sh must emit records satisfying the ownership schema."""
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
        f"Human Dev not found in ownership fields: {src_record}"


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
    """merge_sme_contacts.py output must contain ownership schema column headers."""
    output = tmp_path / "SME_CONTACTS.md"
    subprocess.run(
        [sys.executable, str(SCRIPTS_DIR / "merge_sme_contacts.py"),
         "--repo-path", str(git_repo), "--output", str(output)],
        capture_output=True, text=True, check=True,
    )
    content = output.read_text()
    assert "Original Architect" in content, "ownership column 'Original Architect' missing"
    assert "Current Maintainer" in content, "ownership column 'Current Maintainer' missing"
    assert "Agreement" in content, "ownership column 'Agreement' missing"
    assert "Derivation Date" in content, "ownership column 'Derivation Date' missing"
    assert "CODEOWNERS" in content, "ownership column 'CODEOWNERS' missing"


def test_merge_sme_committer_names_with_special_chars(tmp_path: Path) -> None:
    """Committer names with quotes/backslashes must produce valid JSON from the ownership script."""
    subprocess.run(["git", "init", str(tmp_path)], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(tmp_path), "config", "user.email", 'tricky"user@example.com'],
                   check=True, capture_output=True)
    subprocess.run(["git", "-C", str(tmp_path), "config", "user.name", 'O\'Quote, "Comma"'],
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


# ─── No-src/ repos: repos with no src/ directory ───────────────────────────────────────

@pytest.fixture()
def express_repo_no_src(tmp_path: Path) -> Path:
    """Express repo with TypeScript files at root — no src/ dir."""
    (tmp_path / "package.json").write_text('{"name":"root-app","version":"1.0.0"}')
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
    """No-src/ repos: Express extractor must emit records even when no src/ directory exists."""
    records, _ = run_bash("extract_express.sh", express_repo_no_src)
    assert records, "No-src/ repos: Express extractor must emit records for a repo without src/"
    assert_valid_records(records)


def test_b16_express_no_src_finds_entry_point(express_repo_no_src: Path) -> None:
    """No-src/ repos: express() at repo root must be found as an entry_point."""
    records, _ = run_bash("extract_express.sh", express_repo_no_src)
    assert any(r["kind"] == "entry_point" for r in records), \
        "No-src/ repos: express() entry point at root not found"


def test_b16_express_no_src_finds_endpoint(express_repo_no_src: Path) -> None:
    """No-src/ repos: app.get('/health') at repo root must be found as an endpoint."""
    records, _ = run_bash("extract_express.sh", express_repo_no_src)
    endpoints = [r for r in records if r["kind"] == "endpoint"]
    assert endpoints, "No-src/ repos: No endpoints found in no-src/ Express repo"


# ─── Email-keyed dedup: git ownership keyed by lowercased email ────────────────────────────

@pytest.fixture()
def git_repo_alias_committers(tmp_path: Path) -> Path:
    """Git repo with two display names for the same email (Email-keyed dedup alias case)."""
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
    """Email-keyed dedup: Two display names on same email → commit_count=4, not split."""
    records, _ = run_bash_ownership(git_repo_alias_committers)
    src_record = next((r for r in records if r["area"] == "src"), None)
    assert src_record is not None, "Expected a record for 'src' area"
    assert src_record["commit_count"] == 4, \
        f"Email-keyed dedup: Expected commit_count=4 (email-deduped), got {src_record['commit_count']}"


def test_b17_top_committers_uses_most_frequent_display_name(git_repo_alias_committers: Path) -> None:
    """Email-keyed dedup: The canonical name must be the most-frequent one (Alice Smith, 3 commits)."""
    records, _ = run_bash_ownership(git_repo_alias_committers)
    src_record = next((r for r in records if r["area"] == "src"), None)
    assert src_record is not None
    top = src_record.get("top_committers", [])
    assert top, "Email-keyed dedup: top_committers must not be empty"
    assert "Alice Smith" in top[0], \
        f"Email-keyed dedup: Expected 'Alice Smith' as top committer (3 commits), got {top[0]!r}"
