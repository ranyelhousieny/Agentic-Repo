# Non-Resolving Citations Regression Fixture
#
# This file is the committed regression fixture for verify_citations.sh (T3).
# Running the resolver against this file MUST flag the two named citations as
# non-resolving. These citations are modelled on the real defects documented
# in human_input T3 (framework spec):
#
#   - A citation whose line range is in-bounds but whose content has ZERO
#     keyword overlap with the claim sentence.
#   - A citation whose provenance is inverted (claim says "documentation only"
#     but the cited document says "code-verified").
#
# Exit behaviour: verify_citations.sh must exit non-zero when run against
# this file (the regression test asserts exit code != 0).
#
# ────────────────────────────────────────────────────────────────────────────
# Format: standard generated-artifact rows used by T2.
# The Evidence cell must match ^[^\s]+:\d+(-\d+)?$ unless Status is NOT_FOUND.
# ────────────────────────────────────────────────────────────────────────────

| Field | Value | Evidence | Status |
|-------|-------|----------|--------|
| Terraform IaC state management | Uses remote S3 backend with state locking | fixtures/sample_source.md:10-15 | CONFIRMED |
| API versioning | Backward-compatible versioning enforced via semver | fixtures/sample_source.md:20-25 | CONFIRMED |
| Auth pattern | OAuth2 JWT bearer token | fixtures/sample_source.md:5 | CONFIRMED |
| OpenAPI spec | No OpenAPI spec found | probe: find . -name openapi.yaml | NOT_FOUND |
