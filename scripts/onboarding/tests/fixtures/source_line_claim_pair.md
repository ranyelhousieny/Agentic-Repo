# source_line_claim_pair.md
#
# Regression fixture for verify_citations.sh SOURCE-line claim derivation.
#
# Structure: two sections with identical shape (bullets + a standalone **SOURCE:**
# line), one carrying a wrong citation and one carrying a right citation. This is
# what proves the resolver derives the claim from the preceding prose block rather
# than from the citation line itself — if it read the citation line, both sections
# would score the same.
#
# Wrong citation (Section 1):
#   Claim: catalogue search index / ISBN lookup / cursor pagination
#   Cites: source_line_claim_pair_source.md lines 1-30 (reading-room scheduling prose)
#   Expected: FLAGGED — lines 1-30 contain no catalogue or search content
#
# Right citation (Section 2):
#   Claim: catalogue search index / stemming / cursor pagination
#   Cites: source_line_claim_pair_source.md lines 31-60 (catalogue search prose)
#   Expected: PASSES — the cited lines are about exactly that
#
# Exit behaviour: verify_citations.sh MUST exit non-zero (one fails, one passes),
# and the outcome must be a 1/1 split, not all-pass or all-fail.

## Catalogue Service Reuse Assessment

The following sections assess which subsystems can be reused for the new service.

---

### Section 1: Search Subsystem Reuse

The existing catalogue search components can be adopted with minor changes:

- Current state of the search tier and its rebuild cadence
- Existing operational familiarity with the query path

**Recommendation:** REUSE the catalogue search index and its query parser

- Adopt the inverted index over title and author fields
- Keep ISBN lookup bypassing the search index for primary-key hits
- Apply the same cursor pagination for catalogue search results

**SOURCE:** source_line_claim_pair_source.md:1-30

---

### Section 2: Query Handling Reuse

The query normalisation path carries over unchanged:

- Existing stemming behaviour already matches the target requirements
- Cursor-based paging is already implemented in the query parser

**Recommendation:** REUSE catalogue search stemming and cursor pagination

- Stem query terms before matching against the inverted index
- Use cursor pagination for catalogue search results rather than an offset
- Fall back to a title prefix scan when the stemmed query returns nothing

**SOURCE:** source_line_claim_pair_source.md:31-60
