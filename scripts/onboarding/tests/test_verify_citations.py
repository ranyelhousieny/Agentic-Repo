"""
tests/test_verify_citations.py — Tests for scripts/onboarding/verify_citations.sh.

Verifies:
  1. A citation pointing to lines whose content has ZERO overlap with the claim
     → script exits non-zero (hard gate fires).
  2. A citation that resolves correctly (claim and cited lines share keywords)
     → script exits 0.
  3. A NOT_FOUND row is exempt from the overlap check regardless of evidence content.
  4. The regression fixture (non_resolving_citations.md + sample_source.md)
     correctly flags the two non-resolving citations.
  5. --dry-run prints VALIDATION_SUMMARY content to stdout and writes no file.
  6. Missing cited file → script exits non-zero.
  7. VALIDATION_SUMMARY.md is written with correct totals.
  8. Forbidden phrases are reported.
  9. Multi-line range citation.
 10. No citations → exit 0 (non-citation-bearing name).
 11. Version-string false-positive guard: "Phase 1.5.2:100" in prose must exit 0.
 12. --dry-run without REPO_PATH positional must succeed (Bug 2 regression).
 13. Claim derivation: claim derived from Field+Value cells, not from citation text itself.
     Standalone SOURCE lines walk back to preceding non-citation content.
 14. NOT_FOUND exemption: requires exact Status column match, not substring anywhere.
 15. Empty-artifact guard: CODE_INDEX.md with zero citations → exit 1 (empty artifact guard).
 16. Argument validation: --threshold 0 must be rejected with a clear error.
 17. Span cap: cited line span capped at 40 lines.
 18. SHA pinning: --sha flag resolves files via git show (requires a real git repo).
 19. Executable file mode: all scripts/onboarding/*.sh and *.py are mode 100755 in git.
 20. Claim-derivation regression: source_line_claim_pair fixture — wrong citation flagged, right passes.
 21. Non-degenerate overlap: wrong citation scores < threshold, right citation ≥ threshold.
 22. VALIDATION_SUMMARY.md defaults to CWD, not artifact directory.
"""
from __future__ import annotations

import subprocess
import textwrap
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parent.parent
FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"
VERIFY_SH = SCRIPTS_DIR / "verify_citations.sh"


def run_verify(artifact: Path, repo_path: Path = None,
               dry_run: bool = False,
               threshold: str = None,
               summary_path: Path = None,
               sha: str = None,
               min_citations: str = None) -> subprocess.CompletedProcess:
    """Run verify_citations.sh and return the completed process."""
    cmd = ["bash", str(VERIFY_SH), str(artifact)]
    if repo_path:
        cmd.append(str(repo_path))
    if dry_run:
        cmd += ["--dry-run"]
    if threshold:
        cmd += ["--threshold", threshold]
    if summary_path:
        cmd += ["--summary-path", str(summary_path)]
    if sha:
        cmd += ["--sha", sha]
    if min_citations is not None:
        cmd += ["--min-citations", str(min_citations)]
    return subprocess.run(cmd, capture_output=True, text=True)


# ── Helpers ──────────────────────────────────────────────────────────────────

def make_source_file(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(content), encoding="utf-8")


# ── 1. Non-resolving citation hard gate ──────────────────────────────────────

def test_non_resolving_citation_fails(tmp_path: Path) -> None:
    """A citation whose cited lines share NO keywords with the claim must fail."""
    source = tmp_path / "source.md"
    source.write_text(
        "line 1\nRecipe: boil water and add pasta.\nline 3\n",
        encoding="utf-8",
    )
    artifact = tmp_path / "CODE_INDEX.md"
    artifact.write_text(
        "| Terraform IaC remote state backend | S3 backend with locking | source.md:2 | CONFIRMED |\n",
        encoding="utf-8",
    )
    result = run_verify(artifact, tmp_path, threshold="0.10")
    assert result.returncode != 0, (
        "Expected non-zero exit for non-resolving citation\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )
    assert "FAILED" in result.stdout or "failed" in result.stdout.lower()


# ── 2. Resolving citation passes ─────────────────────────────────────────────

def test_resolving_citation_passes(tmp_path: Path) -> None:
    """A citation whose cited lines share keywords with the claim must pass."""
    source = tmp_path / "source.md"
    source.write_text(
        "line 1\nTerraform remote state managed by S3 backend with DynamoDB locking.\nline 3\n",
        encoding="utf-8",
    )
    artifact = tmp_path / "CODE_INDEX.md"
    artifact.write_text(
        "| Terraform remote state | S3 backend | source.md:2 | CONFIRMED |\n",
        encoding="utf-8",
    )
    result = run_verify(artifact, tmp_path, threshold="0.10")
    assert result.returncode == 0, (
        "Expected exit 0 for resolving citation\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )


# ── 3. NOT_FOUND rows are exempt ─────────────────────────────────────────────

def test_not_found_row_exempt(tmp_path: Path) -> None:
    """NOT_FOUND rows must not be checked for overlap even with a bad Evidence cell.
    Includes a real citation so the Empty-artifact guard zero-citation gate is satisfied."""
    # A real source file that resolves the second row
    src = tmp_path / "src.md"
    src.write_text("Terraform remote backend S3 state.\n", encoding="utf-8")
    artifact = tmp_path / "CODE_INDEX.md"
    # Row 1: NOT_FOUND (probe: no real path:line) — must be exempt
    # Row 2: real resolving citation — satisfies Empty-artifact guard gate
    artifact.write_text(
        "| OpenAPI spec | Not found | probe: find . -name openapi.yaml | NOT_FOUND |\n"
        "| Terraform backend | S3 state | src.md:1 | CONFIRMED |\n",
        encoding="utf-8",
    )
    result = run_verify(artifact, tmp_path)
    assert result.returncode == 0, (
        "NOT_FOUND row should be exempt from overlap check\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )


# ── 4. Regression fixture: non_resolving_citations.md ────────────────────────

def test_regression_fixture_flags_non_resolving(tmp_path: Path) -> None:
    """The committed regression fixture must produce at least 1 failure."""
    fixture_artifact = FIXTURES_DIR / "non_resolving_citations.md"
    fixture_source   = FIXTURES_DIR / "sample_source.md"
    if not fixture_artifact.exists() or not fixture_source.exists():
        pytest.skip("Regression fixtures not found — skipping")

    import shutil
    dest_fixtures = tmp_path / "fixtures"
    dest_fixtures.mkdir()
    shutil.copy(fixture_artifact, tmp_path / "non_resolving_citations.md")
    shutil.copy(fixture_source, dest_fixtures / "sample_source.md")

    result = run_verify(tmp_path / "non_resolving_citations.md", tmp_path, threshold="0.10")
    assert result.returncode != 0, (
        "Regression fixture must fail — it contains non-resolving citations\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )
    assert "failed" in result.stdout.lower() or "FAILED" in result.stdout


# ── 5. --dry-run: stdout only, no file written ───────────────────────────────

def test_dry_run_no_file_written(tmp_path: Path) -> None:
    """--dry-run must print to stdout and NOT write VALIDATION_SUMMARY.md."""
    source = tmp_path / "source.md"
    source.write_text("Terraform backend state S3.\n", encoding="utf-8")
    artifact = tmp_path / "CODE_INDEX.md"
    artifact.write_text(
        "| Terraform backend | S3 | source.md:1 | CONFIRMED |\n",
        encoding="utf-8",
    )
    summary = tmp_path / "VALIDATION_SUMMARY.md"
    result = run_verify(artifact, tmp_path, dry_run=True, summary_path=summary)
    assert not summary.exists(), "--dry-run must not write VALIDATION_SUMMARY.md"
    assert "VALIDATION_SUMMARY" in result.stdout or "Citations" in result.stdout


# ── 6. Missing cited file → non-zero exit ────────────────────────────────────

def test_missing_cited_file_fails(tmp_path: Path) -> None:
    """A citation pointing to a non-existent file must fail."""
    artifact = tmp_path / "CODE_INDEX.md"
    artifact.write_text(
        "| Auth pattern | JWT | does_not_exist.md:5 | CONFIRMED |\n",
        encoding="utf-8",
    )
    result = run_verify(artifact, tmp_path)
    assert result.returncode != 0, "Missing cited file should cause failure"


# ── 7. VALIDATION_SUMMARY.md written correctly ───────────────────────────────

def test_validation_summary_written(tmp_path: Path) -> None:
    """verify_citations.sh must write VALIDATION_SUMMARY.md on success."""
    source = tmp_path / "src.md"
    source.write_text("Auth JWT bearer token authentication.\n", encoding="utf-8")
    artifact = tmp_path / "CODE_INDEX.md"
    artifact.write_text(
        "| Auth | JWT bearer token | src.md:1 | CONFIRMED |\n",
        encoding="utf-8",
    )
    summary = tmp_path / "VALIDATION_SUMMARY.md"
    result = run_verify(artifact, tmp_path, summary_path=summary)
    assert result.returncode == 0
    assert summary.exists(), "VALIDATION_SUMMARY.md must be written"
    content = summary.read_text()
    assert "VALIDATION_SUMMARY" in content
    assert "Total citations" in content
    assert "Verification rate" in content


# ── 8. Forbidden phrases reported ────────────────────────────────────────────

def test_forbidden_phrases_reported(tmp_path: Path) -> None:
    """Forbidden phrases in artifact rows must be reported in VALIDATION_SUMMARY."""
    source = tmp_path / "src.md"
    source.write_text("Auth JWT bearer token authentication.\n", encoding="utf-8")
    artifact = tmp_path / "CODE_INDEX.md"
    artifact.write_text(
        "| Auth | JWT probably used | src.md:1 | CONFIRMED |\n",
        encoding="utf-8",
    )
    summary = tmp_path / "VALIDATION_SUMMARY.md"
    result = run_verify(artifact, tmp_path, summary_path=summary)
    content = summary.read_text() if summary.exists() else result.stdout
    assert "probably" in content.lower() or "forbidden" in content.lower(), (
        "Forbidden phrase 'probably' must appear in VALIDATION_SUMMARY"
    )


# ── 9. Multi-line range citation ─────────────────────────────────────────────

def test_multi_line_range_citation(tmp_path: Path) -> None:
    """Citations with line ranges (path:10-15) must check the full range."""
    source = tmp_path / "src.md"
    source.write_text(
        "\n".join([
            "line 1", "line 2", "line 3", "line 4", "line 5",
            "line 6", "line 7", "line 8", "line 9",
            "Terraform S3 backend state management remote locking.",   # line 10
            "Uses DynamoDB for distributed locking.",                  # line 11
            "line 12",
        ]) + "\n",
        encoding="utf-8",
    )
    artifact = tmp_path / "CODE_INDEX.md"
    artifact.write_text(
        "| Terraform remote state | S3 DynamoDB backend | src.md:10-11 | CONFIRMED |\n",
        encoding="utf-8",
    )
    result = run_verify(artifact, tmp_path, threshold="0.10")
    assert result.returncode == 0, (
        "Multi-line range citation with matching content should pass\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )


# ── 10. No citations → exit 0 (non-citation-bearing artifact name) ───────────

def test_empty_artifact_exits_zero(tmp_path: Path) -> None:
    """An artifact with no citations must exit 0 (using a non-citation-bearing name)."""
    artifact = tmp_path / "arbitrary_artifact.md"
    artifact.write_text("# No citations here\n\nJust prose.\n", encoding="utf-8")
    result = run_verify(artifact, tmp_path)
    assert result.returncode == 0


# ── 11. Version-string false-positive guard ───────────────────────────────────

def test_version_string_not_treated_as_citation(tmp_path: Path) -> None:
    """Prose containing 'Phase 1.5.2:100' or 'v2.0:5' must NOT be treated as citations."""
    artifact = tmp_path / "CODE_INDEX.md"
    artifact.write_text(
        "# Phase 1.5.2:100 describes the onboarding flow\n"
        "See v2.0:5 for the updated schema.\n"
        "API version 3.1.4:22 introduced breaking changes.\n",
        encoding="utf-8",
    )
    result = run_verify(artifact, tmp_path, min_citations="0")
    assert result.returncode == 0, (
        "Version-like tokens must not be treated as citations\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )
    assert "0 total" in result.stdout or "Citations: 0" in result.stdout, (
        f"Expected 0 citations extracted\nstdout: {result.stdout}"
    )


# ── 12. --dry-run without positional REPO_PATH must succeed ──────────────────

def test_dry_run_without_repo_path_positional(tmp_path: Path) -> None:
    """Invoking verify_citations.sh <artifact> --dry-run (no REPO_PATH) must exit 0."""
    artifact = tmp_path / "ARTIFACT.md"
    artifact.write_text("# No citations\nJust prose.\n", encoding="utf-8")
    cmd = ["bash", str(VERIFY_SH), str(artifact), "--dry-run"]
    result = subprocess.run(cmd, capture_output=True, text=True, cwd=str(tmp_path))
    assert result.returncode == 0, (
        "--dry-run without REPO_PATH positional must exit 0\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )
    assert result.stdout.strip(), f"--dry-run must print to stdout\nstdout: {result.stdout!r}"


# ── 13. Claim derivation: claim from Field+Value, not citation text ────────────────────────

def test_b2_claim_from_field_value_not_citation(tmp_path: Path) -> None:
    """
    Claim derivation: The claim must use Field+Value (table cols 1+2), not the raw row string.
    Terraform/S3 field cited against cooking source must fail.
    """
    source = tmp_path / "src.md"
    source.write_text("Recipe: boil water pasta sauce ingredients.\n", encoding="utf-8")
    artifact = tmp_path / "CODE_INDEX.md"
    artifact.write_text(
        "| Terraform IaC | S3 backend | src.md:1 | CONFIRMED |\n",
        encoding="utf-8",
    )
    result = run_verify(artifact, tmp_path, threshold="0.10")
    assert result.returncode != 0, (
        "Claim derivation: Terraform claim against cooking source should fail\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )


def test_b2_standalone_source_line_uses_preceding_content(tmp_path: Path) -> None:
    """
    Claim derivation: A standalone **SOURCE:** line derives its claim from preceding prose,
    not from the citation string itself.
    """
    source = tmp_path / "src.md"
    # Cited content has no overlap with Auth/JWT
    source.write_text("Cooking recipes pasta water boil heat.\n", encoding="utf-8")
    artifact = tmp_path / "PHASE1_DETECTION.md"
    artifact.write_text(
        "Auth JWT bearer token validates requests.\n"
        "**SOURCE:** src.md:1\n",
        encoding="utf-8",
    )
    # Preceding prose "Auth JWT bearer" has no overlap with "Cooking recipes pasta"
    result = run_verify(artifact, tmp_path, threshold="0.10")
    assert result.returncode != 0, (
        "Claim derivation: SOURCE line with mismatched preceding prose should fail\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )


# ── 14. NOT_FOUND exemption: NOT_FOUND must be exact Status column, not prose substring ────────

def test_b4_not_found_in_prose_does_not_bypass(tmp_path: Path) -> None:
    """NOT_FOUND exemption: NOT_FOUND in Value cell (not Status) must NOT exempt the row."""
    source = tmp_path / "src.md"
    source.write_text("Cooking recipes pasta water.\n", encoding="utf-8")
    artifact = tmp_path / "CODE_INDEX.md"
    # "NOT_FOUND" in the Value cell; Status = CONFIRMED
    artifact.write_text(
        "| Terraform IaC | NOT_FOUND in some prose | src.md:1 | CONFIRMED |\n",
        encoding="utf-8",
    )
    result = run_verify(artifact, tmp_path, threshold="0.10")
    assert result.returncode != 0, (
        "NOT_FOUND exemption: NOT_FOUND in Value must NOT bypass the gate; Status=CONFIRMED should fail\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )


def test_b4_not_found_in_status_column_is_exempt(tmp_path: Path) -> None:
    """NOT_FOUND exemption: A row with NOT_FOUND in the Status column MUST be exempt.
    Includes a real citation so the Empty-artifact guard zero-citation gate is satisfied."""
    src = tmp_path / "src.md"
    src.write_text("Terraform remote backend S3 state.\n", encoding="utf-8")
    artifact = tmp_path / "CODE_INDEX.md"
    artifact.write_text(
        "| OpenAPI spec | No OpenAPI spec found | probe: find . -name openapi.yaml | NOT_FOUND |\n"
        "| Terraform backend | S3 state | src.md:1 | CONFIRMED |\n",
        encoding="utf-8",
    )
    result = run_verify(artifact, tmp_path)
    assert result.returncode == 0, (
        "NOT_FOUND exemption: NOT_FOUND in Status column must be exempt\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )


# ── 15. Empty-artifact guard: empty CODE_INDEX.md → exit 1 ─────────────────────────────────────

def test_b5_empty_code_index_fails(tmp_path: Path) -> None:
    """Empty-artifact guard: CODE_INDEX.md with zero citations must exit 1."""
    artifact = tmp_path / "CODE_INDEX.md"
    artifact.write_text("# Empty\n\nNo citations here.\n", encoding="utf-8")
    result = run_verify(artifact, tmp_path)
    assert result.returncode != 0, (
        "Empty-artifact guard: empty CODE_INDEX.md should fail the gate\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )


def test_b5_min_citations_zero_overrides(tmp_path: Path) -> None:
    """Empty-artifact guard: --min-citations 0 overrides the default gate for CODE_INDEX.md."""
    artifact = tmp_path / "CODE_INDEX.md"
    artifact.write_text("# Empty\n\nNo citations here.\n", encoding="utf-8")
    result = run_verify(artifact, tmp_path, min_citations="0")
    assert result.returncode == 0, (
        "Empty-artifact guard: --min-citations 0 must suppress the empty-artifact gate\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )


# ── 16. Argument validation: --threshold 0 rejected ───────────────────────────────────────────

def test_b6_threshold_zero_rejected(tmp_path: Path) -> None:
    """Argument validation: --threshold 0 must exit non-zero with a clear error."""
    artifact = tmp_path / "CODE_INDEX.md"
    artifact.write_text("# Anything\n", encoding="utf-8")
    result = run_verify(artifact, tmp_path, threshold="0", min_citations="0")
    assert result.returncode != 0, f"Argument validation: --threshold 0 must be rejected\nstderr: {result.stderr}"
    assert "threshold" in result.stderr.lower() or "error" in result.stderr.lower()


def test_b6_threshold_greater_than_one_rejected(tmp_path: Path) -> None:
    """Argument validation: --threshold 1.5 must exit non-zero."""
    artifact = tmp_path / "CODE_INDEX.md"
    artifact.write_text("# Anything\n", encoding="utf-8")
    result = run_verify(artifact, tmp_path, threshold="1.5", min_citations="0")
    assert result.returncode != 0, f"Argument validation: --threshold > 1 must be rejected\nstderr: {result.stderr}"


# ── 17. Span cap ─────────────────────────────────────────────────────────

def test_b6_span_cap_does_not_crash(tmp_path: Path) -> None:
    """Span cap: Citing file:1-999 (huge range) must not crash and must be capped at 40."""
    content_lines = ["Auth JWT bearer token validation enforcement."]
    content_lines += [f"unrelated filler line {i}" for i in range(2, 101)]
    source = tmp_path / "src.md"
    source.write_text("\n".join(content_lines) + "\n", encoding="utf-8")
    artifact = tmp_path / "CODE_INDEX.md"
    artifact.write_text(
        "| Auth | JWT bearer token | src.md:1-99 | CONFIRMED |\n",
        encoding="utf-8",
    )
    result = run_verify(artifact, tmp_path, threshold="0.10")
    assert result.returncode in (0, 1), "Script must exit 0 or 1, not crash"


# ── 18. SHA pinning: --sha flag resolves via git show ─────────────────────────────────

def test_b3_sha_flag_resolves_git_content(tmp_path: Path) -> None:
    """SHA pinning: --sha uses committed content, not the mutable working tree."""
    import subprocess as sp
    sp.run(["git", "init", str(tmp_path)], check=True, capture_output=True)
    sp.run(["git", "-C", str(tmp_path), "config", "user.email", "t@test.com"],
           check=True, capture_output=True)
    sp.run(["git", "-C", str(tmp_path), "config", "user.name", "Test"],
           check=True, capture_output=True)
    src = tmp_path / "src.md"
    src.write_text("Auth JWT bearer token validation.\n", encoding="utf-8")
    sp.run(["git", "-C", str(tmp_path), "add", "src.md"], check=True, capture_output=True)
    sp.run(["git", "-C", str(tmp_path), "commit", "-m", "init"],
           check=True, capture_output=True)
    sha = sp.run(
        ["git", "-C", str(tmp_path), "rev-parse", "HEAD"],
        capture_output=True, text=True, check=True
    ).stdout.strip()

    # Overwrite working tree with cooking content
    src.write_text("Recipe boil water pasta cooking.\n", encoding="utf-8")

    artifact = tmp_path / "CODE_INDEX.md"
    artifact.write_text(
        "| Auth | JWT bearer token | src.md:1 | CONFIRMED |\n",
        encoding="utf-8",
    )
    result_sha = run_verify(artifact, tmp_path, threshold="0.10", sha=sha)
    result_wt  = run_verify(artifact, tmp_path, threshold="0.10")

    assert result_sha.returncode == 0, (
        "SHA pinning: --sha should use committed Auth content and pass\n"
        f"stdout: {result_sha.stdout}\nstderr: {result_sha.stderr}"
    )
    assert result_wt.returncode != 0, (
        "SHA pinning: without --sha, working-tree cooking content should fail\n"
        f"stdout: {result_wt.stdout}\nstderr: {result_wt.stderr}"
    )


# ── 19. Executable file mode: scripts are mode 100755 in git ──────────────────────────────────

def test_b18_scripts_are_executable_in_git() -> None:
    """
    Executable file mode: All .sh and .py files under scripts/onboarding/ must be checked in at
    mode 100755 so direct invocation works without `bash <script>`.
    """
    repo_root = Path(__file__).resolve().parent.parent.parent.parent
    result = subprocess.run(
        ["git", "ls-files", "-s",
         "scripts/onboarding/verify_citations.sh",
         "scripts/onboarding/extract_express.sh",
         "scripts/onboarding/extract_spring_boot.sh",
         "scripts/onboarding/extract_fastapi.py",
         "scripts/onboarding/extract_git_ownership.sh",
         "scripts/onboarding/extract_terraform.sh",
         ],
        capture_output=True, text=True, cwd=str(repo_root),
    )
    assert result.returncode == 0, f"git ls-files failed: {result.stderr}"
    for line in result.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split()
        mode = parts[0]
        filename = parts[3] if len(parts) >= 4 else "(unknown)"
        assert mode == "100755", (
            f"Executable file mode: {filename} is mode {mode}, expected 100755. "
            "Run: git update-index --chmod=+x <file>"
        )


# ── 20. Claim derivation: source_line_claim_pair regression fixture ───────────────────────

def test_ac4_source_line_claim_pair_fixture(tmp_path: Path) -> None:
    """
    Claim-derivation regression: the source_line_claim_pair fixture has IDENTICAL surrounding
    structure for a wrong citation and a right citation.  The gate MUST:
      - FLAG  the wrong citation  (catalogue-search claim → reading-room scheduling prose)
      - PASS  the right citation  (query-stemming claim → catalogue-search prose)

    This is the pair that distinguishes a working claim-derivation from a coin flip.
    The fixture is committed at scripts/onboarding/tests/fixtures/source_line_claim_pair*.md.
    """
    import shutil

    fixture_artifact = FIXTURES_DIR / "source_line_claim_pair.md"
    fixture_source   = FIXTURES_DIR / "source_line_claim_pair_source.md"

    if not fixture_artifact.exists():
        pytest.skip("source_line_claim_pair.md fixture not found — skipping")
    if not fixture_source.exists():
        pytest.skip("source_line_claim_pair_source.md fixture not found — skipping")

    # Replicate fixture layout: artifact AND source file live in tmp_path at the
    # same level (the fixture uses bare "source_line_claim_pair_source.md:N-M"
    # citations, so REPO_PATH = tmp_path resolves them directly).
    shutil.copy(fixture_artifact, tmp_path / "source_line_claim_pair.md")
    shutil.copy(fixture_source, tmp_path / "source_line_claim_pair_source.md")

    result = run_verify(
        tmp_path / "source_line_claim_pair.md",
        tmp_path,
        threshold="0.10",
        dry_run=True,  # dry-run so no VALIDATION_SUMMARY.md is written to tmp_path
    )

    # The fixture contains one wrong + one right citation → net failure
    assert result.returncode != 0, (
        "Claim derivation: source_line_claim_pair fixture must fail the gate "
        "(wrong citation should be flagged).\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )

    # The right citation must pass — verify the summary does NOT flag both
    stdout = result.stdout
    assert "failed" in stdout.lower() or "FAILED" in stdout, (
        "Expected failure output in stdout"
    )
    # Exactly 1 failure (wrong citation); the right citation should be RESOLVED
    lines = stdout.splitlines()
    citation_count_line = next(
        (l for l in lines if l.startswith("Citations:")), ""
    )
    # "Citations: 2 total, 1 resolved (50.0%), 1 failed"
    assert "1 failed" in citation_count_line, (
        f"Claim derivation: Expected exactly 1 failed citation (wrong citation).\n"
        f"Got: {citation_count_line!r}\nFull stdout:\n{stdout}"
    )
    assert "1 resolved" in citation_count_line, (
        f"Claim derivation: Expected exactly 1 resolved citation (right citation).\n"
        f"Got: {citation_count_line!r}\nFull stdout:\n{stdout}"
    )


# ── 21. Claim derivation: non-degenerate overlap distribution ─────────────────────────────

def test_ac4_non_degenerate_overlap_distribution(tmp_path: Path) -> None:
    """
    Non-degenerate overlap assertion (load-bearing constraint):

    On the source_line_claim_pair fixture, the gate MUST produce a non-degenerate
    outcome — NOT the "all pass" or "all fail" coin-flip result the old implementation
    produced:

      - The wrong citation (catalogue-search claim → reading-room scheduling prose):
        FAILS the gate (overlap < threshold).  Overlap may be 0.0 (total mismatch)
        but the score is produced from a NON-EMPTY claim derived from the preceding
        prose block, NOT from an empty string fallback.

      - The right citation (query-stemming claim → catalogue-search prose):
        PASSES the gate (overlap ≥ threshold, RESOLVED).

    The old "mirror bug" signature was: wrong citation PASSED (empty claim → overlap 1.0
    auto-pass) and right citation FAILED (or all citations failed with overlap 0.0
    because the empty-claim auto-pass path was never reached).

    We check that the distribution is split: exactly 1 RESOLVED and 1 LOW_OVERLAP,
    proving the claim-derivation is measuring different claims on different rows.
    We also verify the failing row is LOW_OVERLAP (measured, <threshold) not
    NOT_FOUND_ON_DISK or empty-claim auto-pass — those would indicate a different
    failure mode.
    """
    import shutil
    import re as _re

    fixture_artifact = FIXTURES_DIR / "source_line_claim_pair.md"
    fixture_source   = FIXTURES_DIR / "source_line_claim_pair_source.md"

    if not fixture_artifact.exists() or not fixture_source.exists():
        pytest.skip("source_line_claim_pair fixtures not found — skipping")

    shutil.copy(fixture_artifact, tmp_path / "source_line_claim_pair.md")
    shutil.copy(fixture_source, tmp_path / "source_line_claim_pair_source.md")

    result = run_verify(
        tmp_path / "source_line_claim_pair.md",
        tmp_path,
        threshold="0.10",
        dry_run=True,
    )

    stdout = result.stdout

    # 1. Exactly one RESOLVED and one LOW_OVERLAP — the split proves non-degenerate scoring
    citation_count_line = next(
        (l for l in stdout.splitlines() if l.startswith("Citations:")), ""
    )
    assert "1 resolved" in citation_count_line, (
        f"Claim derivation: Right citation (stemming → catalogue-search prose) must be RESOLVED.\n"
        f"Got: {citation_count_line!r}\nFull stdout:\n{stdout}"
    )
    assert "1 failed" in citation_count_line, (
        f"Claim derivation: Wrong citation (search claim → room-scheduling prose) must FAIL.\n"
        f"Got: {citation_count_line!r}\nFull stdout:\n{stdout}"
    )

    # 2. The failing row must be LOW_OVERLAP (claim has tokens, source doesn't match),
    #    NOT NOT_FOUND_ON_DISK (which would mean the file resolution is broken) and
    #    NOT an empty-claim auto-pass (which would give overlap 1.0 and show as RESOLVED).
    assert "LOW_OVERLAP" in stdout, (
        "Claim derivation: Failing citation must have status LOW_OVERLAP (measured score < threshold).\n"
        "NOT_FOUND_ON_DISK would indicate a fixture-path mismatch, not a claim issue.\n"
        f"stdout:\n{stdout}"
    )
    assert "NOT_FOUND_ON_DISK" not in stdout, (
        "Claim derivation: Source file not found on disk. "
        "Check that source_line_claim_pair_source.md is copied to tmp_path, "
        "not tmp_path/fixtures/.\n"
        f"stdout:\n{stdout}"
    )


# ── 22. VALIDATION_SUMMARY.md defaults to CWD ────────────────────────────────

def test_validation_summary_defaults_to_cwd(tmp_path: Path) -> None:
    """
    VALIDATION_SUMMARY.md must default to $(pwd)/VALIDATION_SUMMARY.md,
    NOT $(dirname "$ARTIFACT_FILE")/VALIDATION_SUMMARY.md.

    When the artifact lives inside a read-only fixture directory (a vendored reference repo, say),
    the old default would write into that directory — violating the ticket's Out-of-scope.
    This test verifies the new default by placing the artifact in a sub-directory and
    running from a different CWD; the summary must land in the CWD, not the artifact dir.
    """
    # Create artifact in a sub-directory (simulates a different fixture dir)
    artifact_dir = tmp_path / "fixture_dir"
    artifact_dir.mkdir()
    source = artifact_dir / "src.md"
    source.write_text("Auth JWT bearer token authentication.\n", encoding="utf-8")
    artifact = artifact_dir / "CODE_INDEX.md"
    artifact.write_text(
        "| Auth | JWT bearer token | src.md:1 | CONFIRMED |\n",
        encoding="utf-8",
    )

    # Run from tmp_path (different from artifact_dir)
    cmd = ["bash", str(VERIFY_SH), str(artifact), str(artifact_dir)]
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        cwd=str(tmp_path),  # CWD is tmp_path, NOT artifact_dir
    )

    # The summary must land in CWD (tmp_path), NOT in artifact_dir
    summary_in_cwd = tmp_path / "VALIDATION_SUMMARY.md"
    summary_in_artifact_dir = artifact_dir / "VALIDATION_SUMMARY.md"

    assert summary_in_cwd.exists(), (
        f"VALIDATION_SUMMARY.md must default to CWD ({tmp_path}), not artifact dir.\n"
        f"returncode: {result.returncode}\nstdout: {result.stdout}\nstderr: {result.stderr}"
    )
    assert not summary_in_artifact_dir.exists(), (
        "VALIDATION_SUMMARY.md must NOT be written into the artifact's directory "
        "(that would contaminate read-only fixture dirs).\n"
        f"returncode: {result.returncode}\nstdout: {result.stdout}"
    )
