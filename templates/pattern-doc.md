---
description: "Template for a pattern doc in Agentic-Repo/Knowledge/patterns/. Captures a reusable design pattern with the problem it solves, the solution shape, when to apply, when to skip, and battle-tested-in evidence."
template_version: 0
status: pre-battle-tested
---

# {PATTERN_NAME}

> **This is a template.** Replace `{PATTERN_NAME}`, the placeholders, and write the actual pattern content. Strip inline `<!-- WHY -->` annotations before publishing.

## TL;DR (one paragraph)

{ONE_PARAGRAPH_SUMMARY — what this pattern solves and what shape the solution takes. A reader should know whether to keep reading after this paragraph.}

## Problem

{Describe the failure mode this pattern fixes. Use a concrete scenario, not abstract phrasing. Cite the trigger event that motivated documenting this pattern (e.g., "After running 10+ parallel sessions, I noticed...").}

## Solution

{Describe the pattern shape. If there's code or configuration involved, show the minimal form. If the pattern is conceptual (architectural choice, naming convention, workflow rule), describe its key decisions and rationale.}

### Key components

1. {Component 1} — what it does, why it's necessary
2. {Component 2} — what it does, why it's necessary
3. {Component 3} — etc.

### Counter-patterns (what NOT to do)

- {Common mistake 1 — why people reach for it, why it fails}
- {Common mistake 2}
- {Adjacent pattern that gets confused for this one — distinguish them}

## When to apply this pattern

- {Trigger condition 1}
- {Trigger condition 2}
- {Trigger condition 3}

## When to SKIP this pattern

<!-- WHY: Most pattern docs only describe when to use. Patterns that get
     applied indiscriminately erode trust. Equal time on when NOT to apply. -->

- {Anti-trigger 1 — context where this pattern is overkill or wrong}
- {Anti-trigger 2}
- {Adjacent context that this pattern doesn't fit}

## Battle-tested in

<!-- TODO when instantiating: replace with 1-3 real projects where this pattern has been applied. Use generic descriptors only ("an enterprise data platform," "a personal career repo") — no employer or client identifiers. Until first use, leave as `(not yet battle-tested)`. -->

(not yet battle-tested)

## References

**Original work this pattern draws from (cite Rany if applicable):**
- {Article/repo URL with date}
- {Other URL}

**Industry prior art that converged on similar patterns:**
- {External reference 1 with URL}
- {External reference 2 with URL}

---

## Why this template exists (delete from your published pattern doc)

Pattern docs are how reusable design knowledge gets propagated forward. Without a consistent shape:
- Readers can't quickly assess whether a pattern fits their problem
- "When to skip" gets dropped, leading to over-application
- Battle-tested-in evidence gets dropped, making patterns feel theoretical
- References get dropped, hiding the prior-art trail

This template enforces all four. Treat the structure as load-bearing — don't omit a section because "it doesn't apply." If a section truly doesn't apply, write `(N/A — see [reason])` so future readers know it was considered.

References for the template itself:
- The Agentic Repos framework: https://github.com/ranyelhousieny/Agentic-Repo
- LinkedIn (Rany ElHousieny): https://linkedin.com/in/rany-ai/
