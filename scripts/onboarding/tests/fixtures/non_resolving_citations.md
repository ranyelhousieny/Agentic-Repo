# Non-Resolving Citations Regression Fixture
#
# Committed regression fixture for verify_citations.sh.
# Running the resolver against this file MUST flag the non-resolving citations.
#
# The failure modes modelled here:
#
#   - A citation whose line range is in-bounds but whose content has ZERO
#     keyword overlap with the claim (the cited lines are about something else
#     entirely). This is the common real-world shape: the range is valid, so a
#     path-existence check passes, and only a content check catches it.
#
#   - A row whose Status column is NOT_FOUND, which must be exempt from the
#     overlap check rather than flagged.
#
# Exit behaviour: verify_citations.sh must exit non-zero when run against this
# file (the regression test asserts exit code != 0).
#
# ────────────────────────────────────────────────────────────────────────────
# Format: standard generated-artifact rows.
# The Evidence cell must match ^[^\s]+:\d+(-\d+)?$ unless Status is NOT_FOUND.
# ────────────────────────────────────────────────────────────────────────────

| Field | Value | Evidence | Status |
|-------|-------|----------|--------|
| Search index rebuild | Inverted index rebuilt nightly across the catalogue | fixtures/sample_source.md:11-16 | CONFIRMED |
| Cursor pagination | Catalogue results paged by cursor rather than offset | fixtures/sample_source.md:18-22 | CONFIRMED |
| Auth pattern | OAuth2 JWT bearer token validation | fixtures/sample_source.md:24-26 | CONFIRMED |
| OpenAPI spec | No OpenAPI spec found | probe: find . -name openapi.yaml | NOT_FOUND |
