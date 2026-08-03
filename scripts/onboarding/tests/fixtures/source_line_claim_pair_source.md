## Part A: Reading Room Scheduling Options (lines 1-30)

This section covers scheduling policy choices for the physical reading room.

### Option A: Fixed Daily Slots

Pros: Predictable staffing, simple signage.
Cons: Poor utilisation on quiet mornings.
Timeline: 3 weeks.
Effort: Low.

### Option B: Rolling Reservations

Pros: Higher seat utilisation, fewer walk-away visitors.
Cons: Requires a booking desk and a cancellation policy.
Timeline: 8 weeks.
Effort: High.

### Option C: Blended Schedule

Combines fixed morning slots with afternoon rolling reservations.
Pros: Gradual rollout, keeps walk-ins possible.
Cons: Staff rota complexity.
Timeline: 5 weeks.
Effort: Medium.

Every consideration above relates to room scheduling and staffing rotas only.
No other subsystem is discussed in this part of the document.
Lines 1-30 end here.

## Part B: Catalogue Search and Indexing (lines 31-60)

The catalogue search subsystem builds an inverted index over title and author fields.

Search queries are normalised, stemmed, and matched against the inverted index.
Pagination for catalogue search results uses a cursor rather than an offset:
  catalogue/search_index.py
  catalogue/query_parser.py

ISBN lookup bypasses the search index entirely and hits the primary key directly.
Result ranking uses a title-match boost with an author-match fallback.
Index rebuilds run nightly over the whole catalogue.

The catalogue search index configuration:
  - Stems query terms with a Porter stemmer before matching the inverted index
  - Caches the most frequent search queries with a one-hour expiry
  - Falls back to a title prefix scan when the stemmed query returns nothing

### Pagination Behaviour

Each catalogue search response exposes NEXT_CURSOR, RESULT_COUNT and INDEX_VERSION.
